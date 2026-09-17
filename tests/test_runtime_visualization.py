import unittest

import numpy as np

from runtime.visualization import pack_visualization


class RuntimeVisualizationTests(unittest.TestCase):
    def test_visualization_payload_preserves_enriched_perception_fields(self):
        frame = {
            "shown": 1,
            "points": np.array([[1, 2, 3]], dtype=np.float32),
            "intensity": np.array([0.4], dtype=np.float32),
            "semantic_labels": np.array([9], dtype=np.int32),
            "raw_semantic_labels": np.array([42], dtype=np.int32),
            "ground": np.array([True]),
            "drivable": np.array(["non_drivable"]),
            "semantic_confidence": np.array([0.8], dtype=np.float32),
            "slope": np.array([0.2], dtype=np.float32),
            "roughness": np.array([0.3], dtype=np.float32),
            "height_complexity": np.array([0.4], dtype=np.float32),
            "motion_probability": np.array([0.5], dtype=np.float32),
            "velocity_xy": np.array([[1.2, -0.7]], dtype=np.float32),
            "observation_quality": np.array([0.6], dtype=np.float32),
            "terrain_confidence": np.array([0.7], dtype=np.float32),
            "step": np.array([0.9], dtype=np.float32),
            "pipeline_status": {
                "semantic": "model",
                "ground": "available",
                "terrain": "available",
                "temporal": "available",
                "diagnostics": [],
            },
            "index": 0,
            "dataset": "fixture",
            "seq": "00",
            "id": "000000",
            "pose": {
                "available": True,
                "matrix": np.eye(4).reshape(-1).tolist(),
                "provenance": {
                    "coordinate_frame": "world",
                    "timestamp_source": "dataset",
                    "pose_source": "dataset",
                    "calibration_source": "dataset",
                },
            },
            "n_points": 1,
        }
        cells = {
            "status": "available",
            "cells": [
                {
                    "l": 1,
                    "ix": -2,
                    "iy": 3,
                    "z": 4.5,
                    "c": 9,
                    "m": 0.25,
                    "q": 0.8,
                    "drivable_evidence": -0.4,
                    "u": 0.7,
                }
            ],
        }

        metadata, payload = pack_visualization(frame, cells, 1)

        self.assertEqual(metadata["schema_version"], 2)
        self.assertEqual(metadata["points"], {"count": 1, "offset": 0, "stride": 68})
        self.assertEqual(metadata["provenance"]["timestamp_source"], "dataset")
        values = np.frombuffer(payload, dtype="<f4", count=17)
        np.testing.assert_allclose(
            values,
            [1, 2, 3, 0.4, 9, 42, 1, 2, 0.8, 0.2, 0.3, 0.4, 0.5, 1.2, -0.7, 0.6, 0.7],
        )
        mapped = np.frombuffer(payload, dtype="<f4", offset=17 * 4, count=9)
        np.testing.assert_allclose(
            mapped,
            [-0.15, 0.35, 4.5, 0.1, 9, 0.25, 0.8, -0.4, 0.7],
        )


if __name__ == "__main__":
    unittest.main()
