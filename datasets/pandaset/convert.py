"""Convert downloaded PandaSet sequences into a Veyra generic manifest.

PandaSet stores each sweep as a pickled pandas DataFrame of *world-frame*
points (columns ``x y z i t d``; ``d`` = 0 for the spinning Pandar64, 1 for
the forward PandarGT) plus one sensor-to-world pose per sweep. The generic
manifest contract takes sensor-frame XYZI and an explicit pose, so points are
moved back into the Pandar64 frame with the inverse of the published pose.

Only this one-time conversion needs pandas (to unpickle the source files);
replay through ``datasets.generic.ManifestDataset`` does not.

Default is the Pandar64 alone: the mapper's depth-image visibility clearing
assumes a single beam origin, and the PandarGT sits at a different mount.
``--sensors both`` adds PandarGT returns expressed in the Pandar64 frame,
which is denser for display but violates that single-origin assumption.

The published ``lidar/poses.json`` position is not the Pandar64 beam origin:
the road sits a steady ~0.27 m below it in every sequence checked. The beam
origin was *estimated* from ring sharpness (elevation angles of labelled
non-ground returns collapse onto the 64 discrete laser angles only when
measured from the true origin): 1.30 / 1.60 / 1.75 m above the published
position for sequences 021 / 011 / 039, pooled 1.55 m, i.e. ~1.8 m above the
road, consistent with a roof mount. The manifest records this as an estimated
calibration; ``--origin-offset`` overrides it.

    pip install pandas   # conversion only
    python -m datasets.pandaset.convert --source data/raw/pandaset/raw \
        --output data/raw/pandaset/veyra
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from datasets.common.taxonomy import DATASET_TAXONOMY_VERSIONS, PANDASET_LABELS

SENSORS = {"pandar64": (0,), "both": (0, 1)}
# Estimated beam-origin height above the published pose (see module docstring).
PANDAR64_ORIGIN_OFFSET_M = 1.55


def pose_matrix(pose: dict) -> np.ndarray:
    """PandaSet ``{position, heading}`` to a 4x4 sensor-to-world transform."""
    q = pose["heading"]
    w, x, y, z = (float(q[k]) for k in ("w", "x", "y", "z"))
    norm = np.sqrt(w * w + x * x + y * y + z * z)
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    matrix = np.eye(4)
    matrix[:3, :3] = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    p = pose["position"]
    matrix[:3, 3] = [float(p["x"]), float(p["y"]), float(p["z"])]
    return matrix


def world_to_sensor(
    points_world: np.ndarray, sensor_to_world: np.ndarray
) -> np.ndarray:
    rotation, translation = sensor_to_world[:3, :3], sensor_to_world[:3, 3]
    return (points_world - translation) @ rotation


def beam_origin_pose(published: np.ndarray, offset_m: float) -> np.ndarray:
    """Move the published sensor-to-world pose up its own z axis to the beam origin."""
    lift = np.eye(4)
    lift[2, 3] = offset_m
    return published @ lift


def convert_sequence(
    source: Path,
    output: Path,
    sequence: str,
    sensors: tuple[int, ...],
    origin_offset_m: float = PANDAR64_ORIGIN_OFFSET_M,
) -> list[dict]:
    import pandas as pd  # conversion-only dependency

    lidar = source / sequence / "lidar"
    semseg = source / sequence / "annotations" / "semseg"
    poses = json.loads((lidar / "poses.json").read_text())
    timestamps = json.loads((lidar / "timestamps.json").read_text())
    sweeps = sorted(
        lidar.glob("*.pkl.gz"), key=lambda path: int(path.name.split(".")[0])
    )
    if len(sweeps) != len(poses) or len(poses) != len(timestamps):
        raise ValueError(f"{sequence}: sweeps, poses and timestamps disagree")
    destination = output / sequence
    destination.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, sweep in enumerate(sweeps):
        frame_id = sweep.name.split(".")[0]
        df = pd.read_pickle(sweep)
        keep = df["d"].isin(sensors).to_numpy()
        sensor_to_world = beam_origin_pose(pose_matrix(poses[index]), origin_offset_m)
        xyz = world_to_sensor(
            df[["x", "y", "z"]].to_numpy(np.float64)[keep], sensor_to_world
        )
        xyzi = np.column_stack([xyz, df["i"].to_numpy(np.float64)[keep]]).astype(
            np.float32
        )
        points_path = destination / f"{frame_id}.xyzi.npy"
        np.save(points_path, xyzi)
        entry = {
            "sequence": sequence,
            "frame_id": frame_id,
            "points": {
                "format": "xyzi_f32_npy",
                "path": f"{sequence}/{points_path.name}",
            },
            "timestamp_s": float(timestamps[index]),
            "pose_sensor_to_world": sensor_to_world.tolist(),
        }
        label_file = semseg / sweep.name
        if label_file.is_file():
            labels = pd.read_pickle(label_file)["class"].to_numpy()
            if len(labels) != len(df):
                raise ValueError(
                    f"{sequence}/{frame_id}: labels do not align with points"
                )
            labels_path = destination / f"{frame_id}.labels.npy"
            np.save(labels_path, labels[keep].astype(np.int32))
            entry["labels"] = {
                "format": "integer_npy",
                "path": f"{sequence}/{labels_path.name}",
            }
        frames.append(entry)
    return frames


def convert(
    source: Path,
    output: Path,
    sequences: list[str],
    sensors: str,
    origin_offset_m: float = PANDAR64_ORIGIN_OFFSET_M,
) -> Path:
    if not sequences:
        sequences = sorted(
            p.name for p in source.iterdir() if (p / "lidar" / "poses.json").is_file()
        )
    if not sequences:
        raise SystemExit(f"no downloaded PandaSet sequences under {source}")
    frames = []
    for sequence in sequences:
        converted = convert_sequence(
            source, output, sequence, SENSORS[sensors], origin_offset_m
        )
        print(f"{sequence}: {len(converted)} frames", flush=True)
        frames.extend(converted)
    manifest = {
        "schema_version": 1,
        "dataset": "pandaset",
        "point_schema": {
            "format": "xyzi",
            "coordinate_frame": "sensor",
            "intensity_semantics": "pandar_reflectivity_0_255",
            "sensors": sensors,
            "sensor_origin": {
                "offset_above_published_pose_m": origin_offset_m,
                "source": "estimated_from_beam_ring_sharpness",
            },
        },
        "taxonomy": {
            "version": DATASET_TAXONOMY_VERSIONS["pandaset"],
            "mapping": {str(k): v for k, v in sorted(PANDASET_LABELS.items())},
        },
        "frames": frames,
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=1) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", type=Path, default=Path("data/raw/pandaset/raw"))
    parser.add_argument("--output", type=Path, default=Path("data/raw/pandaset/veyra"))
    parser.add_argument("--sequences", nargs="*", default=[])
    parser.add_argument("--sensors", choices=sorted(SENSORS), default="pandar64")
    parser.add_argument("--origin-offset", type=float, default=PANDAR64_ORIGIN_OFFSET_M)
    args = parser.parse_args(argv)
    try:
        import pandas  # noqa: F401
    except ImportError:
        parser.exit(2, "pandas is required for conversion only: pip install pandas\n")
    print(
        convert(
            args.source, args.output, args.sequences, args.sensors, args.origin_offset
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
