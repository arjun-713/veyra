"""Pack bounded sampled observations and map leaves into GPU-friendly float buffers."""

import numpy as np


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
    available = cells.get("status") == "available"
    binary = cells.get("cells_binary") if available else None
    rows = [] if binary is not None or not available else cells.get("cells", [])
    mapped = np.empty((len(rows), 9), dtype="<f4")
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
        )
    # The engine's binary rows already use this section's layout; forward them.
    cell_bytes = binary if binary is not None else mapped.tobytes()
    cell_count = len(cell_bytes) // 36
    status = frame["pipeline_status"]
    metadata = {
        "type": "visualization",
        # Version 2 adds enriched per-point evidence fields while preserving
        # the existing binary envelope and cell layout.
        "schema_version": 2,
        "generation": generation,
        "index": frame["index"],
        "dataset": frame["dataset"],
        "sequence": frame["seq"],
        "frame_id": frame["id"],
        "points": {"count": count, "offset": 0, "stride": 68},
        "cells": {"count": cell_count, "offset": points.nbytes, "stride": 36},
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
