"""Pack bounded sampled observations and map leaves into GPU-friendly float buffers."""

import numpy as np


def pack_visualization(frame, cells, generation):
    count = int(frame["shown"])
    points = np.empty((count, 8), dtype="<f4")
    points[:, :3] = frame["points"]
    points[:, 3] = frame["intensity"]
    points[:, 4] = frame["semantic_labels"]
    points[:, 5] = frame["ground"]
    drivable = np.asarray(frame["drivable"])
    points[:, 6] = np.where(
        drivable == "drivable", 1, np.where(drivable == "non_drivable", 2, 0)
    )
    points[:, 7] = frame["motion_probability"]
    rows = cells.get("cells", []) if cells.get("status") == "available" else []
    mapped = np.empty((len(rows), 9), dtype="<f4")
    for index, cell in enumerate(rows):
        size = 0.05 * 2 ** cell["l"]
        mapped[index] = (
            (cell["ix"] + 0.5) * size,
            (cell["iy"] + 0.5) * size,
            cell["z"],
            size,
            cell["c"],
            cell["m"],
            cell["q"],
            cell["d"],
            cell["u"],
        )
    status = frame["pipeline_status"]
    metadata = {
        "type": "visualization",
        "schema_version": 1,
        "generation": generation,
        "index": frame["index"],
        "dataset": frame["dataset"],
        "sequence": frame["seq"],
        "frame_id": frame["id"],
        "points": {"count": count, "offset": 0, "stride": 32},
        "cells": {"count": len(rows), "offset": points.nbytes, "stride": 36},
        "pose": np.asarray(frame["pose"]["matrix"]).reshape(-1).tolist(),
        "pose_available": frame["pose"]["available"],
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
    return metadata, points.tobytes() + mapped.tobytes()
