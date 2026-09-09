import tempfile
import unittest
from pathlib import Path

import numpy as np

from viewer import server


class ViewerAdapterIntegrationTests(unittest.TestCase):
    def test_semanticposs_frame_payload_uses_common_adapter_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dataset" / "sequences" / "00"
            (root / "velodyne").mkdir(parents=True)
            (root / "labels").mkdir()
            points = np.array(
                [[1.0, 0.0, 0.5, 0.2], [3.0, 0.0, 0.7, 0.4], [120.0, 0.0, 0.9, 0.6]],
                dtype=np.float32,
            )
            points.tofile(root / "velodyne" / "000000.bin")
            np.array([7, 22, 13], dtype=np.uint32).tofile(
                root / "labels" / "000000.label"
            )
            (root.parent.parent / "timestamps").mkdir()
            (root.parent.parent / "timestamps" / "00.txt").write_text("12.5\n")
            (root.parent.parent / "poses").mkdir()
            (root.parent.parent / "poses" / "00.txt").write_text(
                "1 0 0 10 0 1 0 0 0 0 1 0\n"
            )
            (root.parent.parent / "calib").mkdir()
            (root.parent.parent / "calib" / "00.txt").write_text(
                "Tr: 1 0 0 0 0 1 0 0 0 0 1 0\n"
            )

            old_repo, old_cfg = server.REPO, server.CFG
            try:
                server.REPO = Path(tmp)
                server.CFG = {
                    "semanticposs": {
                        "root": "dataset",
                        "sequences": ["00"],
                        "scan_dir": "velodyne",
                        "label_dir": "labels",
                        "min_range_m": 0,
                        "max_range_m": 100,
                    }
                }
                server.datasets_payload.cache_clear()
                payload = server.frame_payload("semanticposs", "00", 0, 100)
            finally:
                server.REPO, server.CFG = old_repo, old_cfg
                server.datasets_payload.cache_clear()

            self.assertEqual(payload["source"], "SemanticPOSSDataset")
            self.assertEqual(payload["timestamp"], 12.5)
            self.assertTrue(payload["pose"]["available"])
            self.assertTrue(payload["cropped"])
            self.assertEqual(payload["n_points"], 2)
            self.assertEqual(payload["labels"], [7, 22])
            self.assertEqual(payload["semantic_labels"], [0, 0])
            self.assertEqual(payload["points"][0], [11.0, 0.0, 0.5])

    def test_static_mount_serves_assets_from_both_root_styles(self):
        self.assertTrue((server.STATIC / "app.js").is_file())
        self.assertTrue((server.STATIC / "styles.css").is_file())


if __name__ == "__main__":
    unittest.main()
