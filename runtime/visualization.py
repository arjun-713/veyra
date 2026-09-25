"""Pack bounded sampled observations and map leaves into GPU-friendly float buffers."""

import numpy as np

# v3 display cell: 17 little-endian float32 per row (see pack_visualization).
CELL_FLOATS = 17
CELL_STRIDE = CELL_FLOATS * 4


def pack_visualization(frame, cells, generation):
    count = int(frame["shown"])
    # Point section: XYZ/I, mapped+raw semantic IDs, ground, drivable,
    # confidence, terrain evidence, motion, velocity, quality, terrain
    # confidence. This is bounded display data and is independent of map cells.
    points = np.empty((count, 17), dtype="<f4")
    points[:, :3] = frame["points"]
    points[:, 3] = frame["intensity"]
    points[:, 4] = frame["semantic_labels"]
    points[:, 5] = frame.get("raw_semantic_labels", frame["semantic_labels"])
    points[:, 6] = frame["ground"]
    drivable = np.asarray(frame["drivable"])
    points[:, 7] = np.where(
        drivable == "drivable", 1, np.where(drivable == "non_drivable", 2, 0)
    )
    points[:, 8] = frame["semantic_confidence"]
    points[:, 9] = np.nan_to_num(frame["slope"], nan=-1.0)
    points[:, 10] = np.nan_to_num(frame["roughness"], nan=-1.0)
    points[:, 11] = np.nan_to_num(frame["height_complexity"], nan=-1.0)
    points[:, 12] = frame["motion_probability"]
    points[:, 13:15] = np.asarray(frame["velocity_xy"])
    points[:, 15] = frame["observation_quality"]
    points[:, 16] = frame["terrain_confidence"]
    # Cell row layout (v3, 17 floats = 68-byte stride):
    # 0:x 1:y 2:z_mean 3:size 4:class 5:motion 6:quality 7:drivable_ev
    # 8:utility 9:sem_conf 10:ground_ev 11:terrain_conf 12:geom_complex
    # 13:count 14:zmin 15:zmax 16:zvar.
    # Anything the engine did not supply stays NaN so the UI renders
    # "Unavailable" instead of a fabricated zero. The engine's binary MB
    # rows use exactly this layout and are forwarded unparsed.
    available = cells.get("status") == "available"
    binary = cells.get("cells_binary") if available else None
    rows = [] if binary is not None or not available else cells.get("cells", [])
    mapped = np.empty((len(rows), CELL_FLOATS), dtype="<f4")
    for index, cell in enumerate(rows):
        size = 0.05 * 2 ** cell["l"]
        # The C++ map-cell schema names this field explicitly.  ``d`` was
        # emitted by the pre-evidence viewer contract; retain read support for
        # an older engine, but never turn a missing field into fabricated data.
        drivable_evidence = cell.get("drivable_evidence", cell.get("d"))
        if drivable_evidence is None:
            raise ValueError("map cell is missing drivable_evidence")
        mapped[index] = (
            (cell["ix"] + 0.5) * size,
            (cell["iy"] + 0.5) * size,
            cell["z"],
            size,
            cell["c"],
            cell["m"],
            cell["q"],
            drivable_evidence,
            cell["u"],
            cell.get("semantic_confidence", float("nan")),
            cell.get("ground_evidence", float("nan")),
            cell.get("terrain_confidence", float("nan")),
            cell.get("geometry_complexity", float("nan")),
            cell.get("n", float("nan")),
            cell.get("zmin", float("nan")),
            cell.get("zmax", float("nan")),
            cell.get("zvar", float("nan")),
        )
    # The engine's binary rows already use this section's layout; forward them.
    cell_bytes = binary if binary is not None else mapped.tobytes()
    cell_count = len(cell_bytes) // CELL_STRIDE
    status = frame["pipeline_status"]
    metadata = {
        "type": "visualization",
        # Version 3 extends the cell rows with the stored evidence the C++
        # leaf dump already emits (semantic confidence, ground/terrain
        # evidence, geometry complexity, point count, height min/max/var).
        # The point layout is unchanged. Older v2 frames (9-float cells)
        # remain decodable by the desktop viewer.
        "schema_version": 3,
        "generation": generation,
        "index": frame["index"],
        "dataset": frame["dataset"],
        "sequence": frame["seq"],
        "frame_id": frame["id"],
        "points": {"count": count, "offset": 0, "stride": 68},
        "cells": {"count": cell_count, "offset": points.nbytes, "stride": CELL_STRIDE},
        "pose": np.asarray(frame["pose"]["matrix"]).reshape(-1).tolist(),
        "pose_available": frame["pose"]["available"],
        "provenance": dict(frame["pose"].get("provenance", {})),
        "layers": {
            "semantic": status["semantic"],
            "ground": status["ground"],
            "terrain": status["terrain"],
            "motion": status["temporal"],
            "utility": "available",
        },
        "pipeline_status": status,
        "n_points": frame["n_points"],
        "total_leaves": cells.get("total_leaves", 0),
    }
    return metadata, points.tobytes() + cell_bytes
