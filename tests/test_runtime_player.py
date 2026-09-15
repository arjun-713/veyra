import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.rellis.adapter import Rellis3DDataset


def _write_frame(root: Path, sequence: str, frame_id: str, offset: float) -> None:
    scan_dir = root / sequence / "vel_cloud_node_kitti_bin"
    label_dir = root / sequence / "vel_cloud_node_semantickitti_label_id"
    scan_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    np.asarray(
        [[offset, 0.0, 0.0, 0.25], [offset + 1.0, 0.0, 0.0, 0.75]],
        dtype=np.float32,
    ).tofile(scan_dir / f"{frame_id}.bin")
    np.asarray([10, 20], dtype=np.uint32).tofile(label_dir / f"{frame_id}.label")


def _write_generic_manifest(root: Path) -> None:
    points = np.asarray(
        [[1.0, 2.0, 0.5, 0.25], [2.0, 3.0, 0.6, 0.75]], dtype=np.float32
    )
    points.tofile(root / "scan.bin")
    np.asarray([10, 20], dtype=np.uint32).tofile(root / "labels.label")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset": "generic-fixture",
                "point_schema": {
                    "format": "xyzi",
                    "coordinate_frame": "sensor",
                    "intensity_semantics": "normalized",
                },
                "taxonomy": {"version": "fixture-v1", "mapping": {"10": 9}},
                "frames": [
                    {
                        "sequence": "demo",
                        "frame_id": "000000",
                        "timestamp_s": 12.5,
                        "pose_sensor_to_world": [
                            [1, 0, 0, 4],
                            [0, 1, 0, 5],
                            [0, 0, 1, 6],
                            [0, 0, 0, 1],
                        ],
                        "points": {"path": "scan.bin", "format": "xyzi_f32_bin"},
                        "labels": {"path": "labels.label", "format": "uint32_label"},
                    }
                ],
            }
        )
    )


class RuntimePlayerTests(unittest.TestCase):
    def _runtime(self, root: Path):
        from viewer.runtime import RuntimeSession

        adapter = Rellis3DDataset(root, sequences=["00000", "00001"])
        return RuntimeSession.from_adapter(
            adapter,
            dataset="rellis3d",
            sequence="00000",
            pipeline_config={
                "semantic": {"mode": "ground_truth"},
                "ground": {"enabled": False},
                "terrain": {"enabled": False},
                "temporal": {"enabled": True},
            },
        )

    def test_config_rejects_unknown_dataset_before_starting_runtime(self):
        from viewer.runtime import RuntimeConfigurationError, load_runtime_config

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "runtime.json"
            path.write_text(json.dumps({"dataset": "not-a-dataset", "sequence": "00"}))

            with self.assertRaisesRegex(RuntimeConfigurationError, "dataset"):
                load_runtime_config(path)

    def test_missing_dataset_root_is_reported_without_a_fallback_frame(self):
        from viewer.runtime import DatasetUnavailableError, RuntimeSession

        with self.assertRaisesRegex(DatasetUnavailableError, "does not exist"):
            RuntimeSession.from_dataset_settings(
                dataset="rellis3d",
                dataset_root=Path("/definitely/not/a/dataset"),
                sequences=["00000"],
                pipeline_config={"semantic": {"mode": "ground_truth"}},
            )

    def test_settings_session_supports_generic_manifest_and_preserves_provenance(self):
        from viewer.runtime import RuntimeSession

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_generic_manifest(root)
            runtime = RuntimeSession.from_dataset_settings(
                dataset="generic",
                dataset_root=root,
                sequences=["demo"],
                pipeline_config={
                    "semantic": {"mode": "ground_truth"},
                    "ground": {"enabled": False},
                    "terrain": {"enabled": False},
                    "temporal": {"enabled": False},
                },
            )
            try:
                payload = runtime.frame_payload(0, budget=1000)
            finally:
                runtime.close()

        self.assertEqual(payload["source"], "ManifestDataset")
        self.assertEqual(payload["timestamp"], 12.5)
        self.assertEqual(payload["pose"]["available"], True)
        self.assertEqual(payload["pose"]["provenance"], {
            "coordinate_frame": "world",
            "timestamp_source": "dataset",
            "pose_source": "dataset",
            "calibration_source": "identity_absent",
        })

    def test_controls_replay_real_adapter_frames_and_reset_temporal_state(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_frame(root, "00000", "000000", 1.0)
            _write_frame(root, "00000", "000001", 2.0)
            _write_frame(root, "00001", "000000", 10.0)
            _write_frame(root, "00001", "000001", 11.0)
            for sequence in ("00000", "00001"):
                (root / sequence / "timestamps.txt").write_text("0.0\n0.1\n")
            poses = root / "poses"
            poses.mkdir()
            for sequence in ("00000", "00001"):
                (poses / f"{sequence}.txt").write_text(
                    "1 0 0 0 0 1 0 0 0 0 1 0\n1 0 0 0 0 1 0 0 0 0 1 0\n"
                )

            runtime = self._runtime(root)
            first = runtime.frame_payload(0, budget=1_000)
            second = runtime.next(budget=1_000)
            previous = runtime.previous(budget=1_000)
            reset = runtime.reset(budget=1_000)
            switched = runtime.select_sequence("00001", budget=1_000)

            self.assertEqual(first["id"], "000000")
            self.assertEqual(second["id"], "000001")
            self.assertEqual(previous["id"], "000000")
            self.assertEqual(reset["index"], 0)
            self.assertEqual(switched["seq"], "00001")
            self.assertEqual(switched["index"], 0)
            self.assertEqual(switched["pipeline_status"]["temporal"], "available")
            self.assertTrue(switched["pose"]["available"])
            self.assertEqual(switched["n_points"], 2)
            self.assertEqual(switched["map"]["status"], "unavailable")

    def test_empty_frame_stays_empty_and_never_receives_synthetic_evidence(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_frame(root, "00000", "000000", 1.0)
            _write_frame(root, "00001", "000000", 2.0)
            runtime = self._runtime(root)
            runtime.min_range_m = 500.0

            frame = runtime.frame_payload(0, budget=1_000)

            self.assertEqual(frame["n_points"], 0)
            self.assertEqual(frame["points"], [])
            self.assertEqual(frame["ground"], [])
            self.assertEqual(frame["map"]["status"], "unavailable")

    def test_timestamp_without_dataset_pose_is_not_presented_as_world_coordinates(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_frame(root, "00000", "000000", 1.0)
            _write_frame(root, "00001", "000000", 2.0)
            (root / "00000" / "timestamps.txt").write_text("0.0\n")
            runtime = self._runtime(root)

            frame = runtime.frame_payload(0, budget=1_000)

            self.assertEqual(frame["timestamp"], 0.0)
            self.assertFalse(frame["pose"]["available"])

    def test_repeating_current_frame_reuses_processed_output(self):
        class CountingMapRunner:
            def __init__(self):
                self.calls = 0

            def process_frame(self, frame):
                del frame
                self.calls += 1
                return {"status": "available", "visit": self.calls}

            def reset(self):
                return {"status": "available"}

            def status(self):
                return {"status": "available"}

            def close(self):
                return None

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_frame(root, "00000", "000000", 1.0)
            _write_frame(root, "00001", "000000", 2.0)
            runner = CountingMapRunner()
            runtime = self._runtime(root)
            runtime.map_runner = runner

            first = runtime.frame_payload(0, budget=1_000)
            repeated = runtime.frame_payload(0, budget=1_000)

            self.assertEqual(first["map"]["visit"], 1)
            self.assertEqual(repeated["map"]["visit"], 1)
            self.assertEqual(runner.calls, 1)

    def test_missing_configured_ground_backend_is_visible_in_pipeline_diagnostics(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_frame(root, "00000", "000000", 1.0)
            _write_frame(root, "00001", "000000", 2.0)
            adapter = Rellis3DDataset(root, sequences=["00000", "00001"])
            from viewer.runtime import RuntimeSession

            runtime = RuntimeSession.from_adapter(
                adapter,
                dataset="rellis3d",
                sequence="00000",
                pipeline_config={
                    "semantic": {"mode": "ground_truth"},
                    "ground": {
                        "enabled": True,
                        "module_names": ["veyra_missing_patchworkpp_backend"],
                    },
                    "terrain": {"enabled": True},
                    "temporal": {"enabled": False},
                },
            )

            frame = runtime.frame_payload(0, budget=1_000)

            self.assertEqual(frame["pipeline_status"]["ground"], "unavailable")
            self.assertEqual(frame["pipeline_status"]["terrain"], "unavailable")
            self.assertIn(
                "veyra_missing_patchworkpp_backend",
                " ".join(frame["pipeline_status"]["diagnostics"]),
            )

    def test_long_playback_keeps_frame_fields_aligned(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(24):
                _write_frame(root, "00000", f"{index:06d}", float(index))
            _write_frame(root, "00001", "000000", 2.0)
            (root / "00000" / "timestamps.txt").write_text(
                "\n".join(str(index / 10) for index in range(24)) + "\n"
            )

            runtime = self._runtime(root)
            frames = [runtime.frame_payload(index, budget=1_000) for index in range(24)]

            self.assertEqual([frame["index"] for frame in frames], list(range(24)))
            for frame in frames:
                shown = frame["shown"]
                self.assertEqual(len(frame["points"]), shown)
                self.assertEqual(len(frame["semantic_labels"]), shown)
                self.assertEqual(len(frame["ground"]), shown)
                self.assertEqual(len(frame["drivable"]), shown)
                self.assertEqual(len(frame["motion_probability"]), shown)


if __name__ == "__main__":
    unittest.main()
