"""Height of each return above the locally fitted ground surface.

This is the value that lets the map sort returns into its ground, obstacle and
overhead layers. It is computed here, in perception, and not in the map,
because the map cannot compute it without circularity: assigning a return to a
layer needs a ground height, and the ground height is the mean of the returns
assigned to the ground layer. Perception already has a ground segmentation, so
it is the only place the loop can be broken.

The estimator is deliberately plain. A coarse XY lattice, the median elevation
of the ground-labelled returns in each cell, and a one-ring fallback for cells
that have none of their own. Anything more elaborate -- plane fitting, RANSAC,
interpolation across the lattice -- extrapolates ground into places the sensor
did not observe it, and the whole point of the layered map is to stop doing
that. Where there is no nearby ground evidence the answer is NaN, which the map
counts as "ground model unavailable" rather than silently treating as level.
"""

from __future__ import annotations


import numpy as np

__all__ = ["height_above_ground"]


def height_above_ground(
    points: np.ndarray,
    ground_mask: np.ndarray,
    *,
    cell_size_m: float = 2.0,
    min_ground_points: int = 3,
    use_neighbour_fallback: bool = True,
) -> np.ndarray:
    """Return height above local ground, in metres, one value per point.

    ``points`` is (N, 3+) in a consistent frame; only columns 0..2 are read.
    ``ground_mask`` is a length-N boolean selecting ground-labelled returns.

    NaN where no ground evidence is available nearby. Negative values are
    depressions and are returned as-is: a pothole is a hazard, and clamping it
    to zero would hide it.
    """
    array = np.asarray(points, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] < 3:
        raise ValueError("points must have shape (N, 3+)")
    mask = np.asarray(ground_mask, dtype=bool).reshape(-1)
    if mask.shape[0] != array.shape[0]:
        raise ValueError("ground_mask must have one entry per point")
    if not np.isfinite(cell_size_m) or cell_size_m <= 0.0:
        raise ValueError("cell_size_m must be finite and positive")
    if min_ground_points < 1:
        raise ValueError("min_ground_points must be at least 1")

    count = array.shape[0]
    result = np.full(count, np.nan, dtype=np.float32)
    if count == 0:
        return result

    finite = (
        np.isfinite(array[:, 0]) & np.isfinite(array[:, 1]) & np.isfinite(array[:, 2])
    )
    if not finite.any():
        return result

    ix = np.floor(np.where(finite, array[:, 0], 0.0) / cell_size_m).astype(np.int64)
    iy = np.floor(np.where(finite, array[:, 1], 0.0) / cell_size_m).astype(np.int64)

    ground = mask & finite
    if not ground.any():
        # A frame with no ground segmentation at all. Every return is honestly
        # unmodelled; the map will count them rather than guess.
        return result

    # Median, not mean: a few returns that leaked through the ground
    # segmentation from a kerb or a car sill would drag a mean upward, and the
    # resulting ground height would make real obstacles look shorter than they
    # are -- an error in the unsafe direction.
    #
    # Cells are addressed by a single packed int64 rather than an (ix, iy)
    # tuple so every lookup below is a vectorised searchsorted instead of a
    # per-point dict probe. The dict version cost 75 ms for 120k points --
    # most of a frame budget for one helper -- because it ran a Python loop
    # over every return.
    codes = _pack(ix, iy)
    ground_codes = codes[ground]
    ground_z = array[ground, 2]

    # Per-cell medians without a per-cell call. Sorting by (cell, z) makes each
    # cell's elevations contiguous and ordered, so every median is two index
    # lookups: the middle element for odd counts, the mean of the two middle
    # elements for even. Calling np.median once per cell instead cost 58% of
    # this function's runtime -- 2500 Python-level calls per frame, each with
    # its own dispatch and NaN check, to do arithmetic that indexing already
    # answers. The same sort also yields the distinct cells and their counts,
    # so no separate np.unique sort is needed.
    order = np.lexsort((ground_z, ground_codes))
    sorted_codes = ground_codes[order]
    sorted_z = ground_z[order]
    new_cell = np.empty(sorted_codes.shape[0], dtype=bool)
    new_cell[0] = True
    np.not_equal(sorted_codes[1:], sorted_codes[:-1], out=new_cell[1:])
    starts = np.flatnonzero(new_cell)
    unique_codes = sorted_codes[starts]
    counts = np.diff(starts, append=sorted_codes.shape[0]).astype(np.int64)
    lower = starts + (counts - 1) // 2
    upper = starts + counts // 2
    medians = 0.5 * (sorted_z[lower] + sorted_z[upper])

    # Cells with too little evidence do not get to define a ground height.
    credible = counts >= min_ground_points
    if not credible.any():
        return result
    cell_codes = unique_codes[credible]
    cell_heights = medians[credible]

    ground_height = _lookup(codes, cell_codes, cell_heights)
    heights = array[:, 2] - ground_height
    if use_neighbour_fallback:
        missing = np.isnan(heights)
        if missing.any():
            # One ring only. Borrowing a ground height from an adjacent cell is
            # a modest, bounded assumption; reaching further would be inventing
            # terrain, which is the failure this whole design exists to avoid.
            #
            # The median of whichever neighbours exist, matching the per-cell
            # estimator, so a cell beside a kerb does not inherit the kerb.
            #
            # The borrowed height depends only on the cell, so it is computed
            # once per distinct missing cell (~1.6k) rather than once per
            # missing return (~30k on a 97k-point PandaSet scan) and then
            # broadcast back.
            missing_codes = codes[missing]
            missing_cells, inverse = np.unique(missing_codes, return_inverse=True)
            # First return of each distinct cell, found without the stable
            # sort that np.unique(return_index=True) would add.
            first = np.full(missing_cells.shape[0], missing_codes.shape[0])
            np.minimum.at(first, inverse, np.arange(missing_codes.shape[0]))
            neighbours = np.full((missing_cells.shape[0], 8), np.nan, dtype=np.float64)
            missing_ix = ix[missing][first]
            missing_iy = iy[missing][first]
            column = 0
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    neighbours[:, column] = _lookup(
                        _pack(missing_ix + dx, missing_iy + dy),
                        cell_codes,
                        cell_heights,
                    )
                    column += 1
            borrowed = _nanmedian_rows(neighbours)[inverse]
            heights[missing] = array[missing, 2] - borrowed

    heights[~finite] = np.nan
    return heights.astype(np.float32)


def _nanmedian_rows(values: np.ndarray) -> np.ndarray:
    """Row-wise median ignoring NaN; NaN for a row with no finite value.

    Bit-identical to ``np.nanmedian(values, axis=1)`` -- the same sort and the
    same ``(low + high) / 2`` of the two middle finite values -- without its
    masked-array path, which also issued one ``RuntimeWarning`` per all-NaN
    row (thousands per frame, each a Python-level call). An all-NaN row means
    no neighbour had ground either; NaN is the legitimate answer.
    """
    ordered = np.sort(values, axis=1)  # NaN sorts after every finite value.
    finite = np.count_nonzero(~np.isnan(values), axis=1)
    upper = finite // 2
    lower = np.where(finite % 2 == 1, upper, upper - 1)
    rows = np.arange(values.shape[0])
    low = ordered[rows, np.maximum(lower, 0)]
    high = ordered[rows, upper]
    medians = (low + high) / 2.0
    medians[finite == 0] = np.nan
    return medians


def _pack(ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
    """Pack two cell indices into one int64 key.

    Bit-packing rather than hashing: the mapping is exact and order-preserving
    enough for searchsorted, so no collision can silently merge two cells.
    """
    return (ix.astype(np.int64) << np.int64(32)) | (
        iy.astype(np.int64) & np.int64(0xFFFFFFFF)
    )


def _lookup(
    codes: np.ndarray, cell_codes: np.ndarray, cell_heights: np.ndarray
) -> np.ndarray:
    """Height above ground for each code, NaN where the cell has no estimate."""
    if cell_codes.size == 0:
        return np.full(codes.shape[0], np.nan, dtype=np.float64)
    position = np.searchsorted(cell_codes, codes)
    clamped = np.clip(position, 0, cell_codes.shape[0] - 1)
    found = cell_codes[clamped] == codes
    return np.where(found, cell_heights[clamped], np.nan)
