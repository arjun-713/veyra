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
                    "zmin": 4.1,
                    "zmax": 4.9,
                    "zvar": 0.04,
                    "n": 42,
                    "c": 9,
                    "m": 0.25,
                    "q": 0.8,
                    "drivable_evidence": -0.4,
                    "u": 0.7,
                    "semantic_confidence": 0.9,
                    "ground_evidence": 0.6,
                    "terrain_confidence": 0.5,
                    "geometry_complexity": 0.3,
                    "physical_layers": [
                        1,
                        0,
                        0,
                        0,
                        0,
                        1,
                        0.3,
                        0.3,
                        0.3,
                        0,
                        1,
                        3,
                        3,
                        3,
                        0,
                    ],
                }
            ],
        }

        metadata, payload = pack_visualization(frame, cells, 1)

        self.assertEqual(metadata["schema_version"], 3)
        self.assertEqual(metadata["points"], {"count": 1, "offset": 0, "stride": 68})
        self.assertEqual(
            metadata["cells"], {"count": 1, "offset": 17 * 4, "stride": 68}
        )
        self.assertEqual(metadata["provenance"]["timestamp_source"], "dataset")
        values = np.frombuffer(payload, dtype="<f4", count=17)
        np.testing.assert_allclose(
            values,
            [1, 2, 3, 0.4, 9, 42, 1, 2, 0.8, 0.2, 0.3, 0.4, 0.5, 1.2, -0.7, 0.6, 0.7],
        )
        mapped = np.frombuffer(payload, dtype="<f4", offset=17 * 4, count=17)
        np.testing.assert_allclose(
            mapped,
            [
                -0.15,
                0.35,
                4.5,
                0.1,
                9,
                0.25,
                0.8,
                -0.4,
                0.7,
                0.9,
                0.6,
                0.5,
                0.3,
                42,
                4.1,
                4.9,
                0.04,
            ],
        )
        self.assertEqual(
            metadata.get("physical_layers"),
            {"version": 1, "count": 1, "offset": 136, "stride": 60},
        )
        layers = np.frombuffer(payload, dtype="<f4", offset=136)
        np.testing.assert_allclose(layers, cells["cells"][0]["physical_layers"])

    def test_visualization_cell_rows_use_nan_for_fields_an_older_engine_omits(self):
        frame = {
            "shown": 0,
            "points": np.empty((0, 3), dtype=np.float32),
            "intensity": np.empty(0, dtype=np.float32),
            "semantic_labels": np.empty(0, dtype=np.int32),
            "raw_semantic_labels": np.empty(0, dtype=np.int32),
            "ground": np.empty(0, dtype=bool),
            "drivable": np.empty(0, dtype="U12"),
            "semantic_confidence": np.empty(0, dtype=np.float32),
            "slope": np.empty(0, dtype=np.float32),
            "roughness": np.empty(0, dtype=np.float32),
            "height_complexity": np.empty(0, dtype=np.float32),
            "motion_probability": np.empty(0, dtype=np.float32),
            "velocity_xy": np.empty((0, 2), dtype=np.float32),
            "observation_quality": np.empty(0, dtype=np.float32),
            "terrain_confidence": np.empty(0, dtype=np.float32),
            "step": np.empty(0, dtype=np.float32),
            "pipeline_status": {
                "semantic": "ground_truth",
                "ground": "unavailable",
                "terrain": "unavailable",
                "temporal": "unavailable",
                "diagnostics": [],
            },
            "index": 0,
            "dataset": "fixture",
            "seq": "00",
            "id": "000000",
            "pose": {
                "available": False,
                "matrix": np.eye(4).reshape(-1).tolist(),
                "provenance": {
                    "coordinate_frame": "lidar",
                    "timestamp_source": "absent",
                    "pose_source": "absent",
                    "calibration_source": "absent",
                },
            },
            "n_points": 0,
        }
        cells = {
            "status": "available",
            "cells": [
                {
                    "l": 0,
                    "ix": 0,
                    "iy": 0,
                    "z": 1.0,
                    "c": 0,
                    "m": 0.0,
                    "q": 0.0,
                    "d": 0.0,
                    "u": 0.0,
                }
            ],
        }
        metadata, payload = pack_visualization(frame, cells, 1)
        self.assertEqual(metadata["schema_version"], 3)
        self.assertNotIn("physical_layers", metadata)
        mapped = np.frombuffer(payload, dtype="<f4", offset=0, count=17)
        # Legacy ``d`` alias is honored; absent evidence stays NaN (Unavailable).
        self.assertEqual(mapped[7], 0.0)
        for position in (9, 10, 11, 12, 13, 14, 15, 16):
            self.assertTrue(np.isnan(mapped[position]))


if __name__ == "__main__":
    unittest.main()
