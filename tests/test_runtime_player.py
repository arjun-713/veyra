"""Runtime player regression suite."""

import http.client
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from datasets.rellis.adapter import Rellis3DDataset
from viewer import server
from viewer.runtime import RuntimeSession

# Runtime player


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
        self.assertEqual(
            payload["pose"]["provenance"],
            {
                "coordinate_frame": "world",
                "timestamp_source": "dataset",
                "pose_source": "dataset",
                "calibration_source": "identity_absent",
            },
        )

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


# Viewer adapter integration


class ViewerAdapterIntegrationTests(unittest.TestCase):
    def test_runtime_session_payload_uses_configured_pipeline_instead_of_defaults(self):
        from viewer.runtime import RuntimeSession

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Rellis-3D"
            scans = root / "00000" / "vel_cloud_node_kitti_bin"
            labels = root / "00000" / "vel_cloud_node_semantickitti_label_id"
            scans.mkdir(parents=True)
            labels.mkdir()
            np.array([[1.0, 0.0, 0.5, 0.2]], dtype=np.float32).tofile(
                scans / "000000.bin"
            )
            np.array([7], dtype=np.uint32).tofile(labels / "000000.label")

            old_runtime = server.RUNTIME
            try:
                server.RUNTIME = RuntimeSession.from_dataset_settings(
                    dataset="rellis3d",
                    dataset_root=root,
                    sequences=["00000"],
                    pipeline_config={
                        "semantic": {"mode": "ground_truth"},
                        "ground": {"enabled": False},
                        "terrain": {"enabled": False},
                        "temporal": {"enabled": False},
                    },
                )
                payload = server.frame_payload("rellis3d", "00000", 0, 100)
                status = server.runtime_status_payload()
            finally:
                server.RUNTIME = old_runtime

            self.assertEqual(payload["source"], "Rellis3DDataset")
            self.assertEqual(payload["pipeline_status"]["semantic"], "ground_truth")
            self.assertEqual(payload["pipeline_status"]["ground"], "disabled")
            self.assertEqual(payload["semantic_confidence"], [0.0])
            self.assertIn("total", payload["perception_timings_ms"])
            self.assertEqual(status["state"], "configured")
            self.assertEqual(status["dataset"], "rellis3d")

    def test_repo_rellis_configuration_enforces_the_100_m_map_envelope(self):
        self.assertEqual(float(server.CFG["rellis3d"]["max_range_m"]), 100.0)

    def test_rellis_frame_payload_uses_common_adapter_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Rellis-3D" / "00000"
            (root / "vel_cloud_node_kitti_bin").mkdir(parents=True)
            (root / "vel_cloud_node_semantickitti_label_id").mkdir()
            np.array(
                [[1.0, 0.0, 0.5, 0.2], [120.0, 0.0, 0.7, 0.4]], dtype=np.float32
            ).tofile(root / "vel_cloud_node_kitti_bin" / "000000.bin")
            np.array([7, 22], dtype=np.uint32).tofile(
                root / "vel_cloud_node_semantickitti_label_id" / "000000.label"
            )

            old_repo, old_cfg = server.REPO, server.CFG
            try:
                server.REPO = Path(tmp)
                server.CFG = {
                    "rellis3d": {
                        "root": "Rellis-3D",
                        "sequences": ["00000"],
                        "scan_dir": "vel_cloud_node_kitti_bin",
                        "label_dir": "vel_cloud_node_semantickitti_label_id",
                        "max_range_m": 100,
                    }
                }
                payload = server.frame_payload("rellis3d", "00000", 0, 100)
            finally:
                server.REPO, server.CFG = old_repo, old_cfg

            self.assertEqual(payload["source"], "Rellis3DDataset")
            self.assertTrue(payload["cropped"])
            self.assertEqual(payload["n_points"], 1)
            self.assertEqual(payload["labels"], [7])

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
            self.assertEqual(payload["labels"], [7, 22])
            self.assertEqual(payload["semantic_labels"], [1, 12])
            self.assertEqual(payload["points"][0], [11.0, 0.0, 0.5])

    def test_static_mount_serves_assets_from_both_root_styles(self):
        self.assertTrue((server.STATIC / "app.js").is_file())
        self.assertTrue((server.STATIC / "styles.css").is_file())


# Viewer runtime http


def _write_http_frame(root: Path, frame_id: str, x: float) -> None:
    scans = root / "00000" / "vel_cloud_node_kitti_bin"
    labels = root / "00000" / "vel_cloud_node_semantickitti_label_id"
    scans.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    np.asarray([[x, 0.0, 0.0, 0.2]], dtype=np.float32).tofile(scans / f"{frame_id}.bin")
    np.asarray([7], dtype=np.uint32).tofile(labels / f"{frame_id}.label")


class ViewerRuntimeHttpTests(unittest.TestCase):
    def test_local_http_runtime_exposes_frame_status_and_reset(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_http_frame(root, "000000", 1.0)
            _write_http_frame(root, "000001", 2.0)
            previous = server.RUNTIME
            listener = None
            thread = None
            try:
                server.RUNTIME = RuntimeSession.from_dataset_settings(
                    dataset="rellis3d",
                    dataset_root=root,
                    sequences=["00000"],
                    pipeline_config={"semantic": {"mode": "ground_truth"}},
                )
                listener = server.http.server.ThreadingHTTPServer(
                    ("127.0.0.1", 0), server.Handler
                )
                thread = threading.Thread(target=listener.serve_forever, daemon=True)
                thread.start()
                port = listener.server_address[1]

                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                connection.request("GET", "/api/runtime/status")
                status_response = connection.getresponse()
                status = json.loads(status_response.read())
                connection.request(
                    "GET", "/api/frame?dataset=rellis3d&seq=00000&index=1&budget=1000"
                )
                frame_response = connection.getresponse()
                frame = json.loads(frame_response.read())
                connection.request("POST", "/api/runtime/reset?budget=1000")
                reset_response = connection.getresponse()
                reset = json.loads(reset_response.read())
                connection.close()
            finally:
                if listener is not None:
                    listener.shutdown()
                    listener.server_close()
                if thread is not None:
                    thread.join(timeout=3)
                server.RUNTIME = previous

            self.assertEqual(status_response.status, 200)
            self.assertEqual(status["state"], "configured")
            self.assertEqual(frame_response.status, 200)
            self.assertEqual(frame["id"], "000001")
            self.assertEqual(reset_response.status, 200)
            self.assertEqual(reset["index"], 0)

    def test_map_cells_endpoint_reports_unavailable_without_map_runtime(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_http_frame(root, "000000", 1.0)
            previous = server.RUNTIME
            listener = None
            thread = None
            try:
                server.RUNTIME = RuntimeSession.from_dataset_settings(
                    dataset="rellis3d",
                    dataset_root=root,
                    sequences=["00000"],
                    pipeline_config={"semantic": {"mode": "ground_truth"}},
                )
                listener = server.http.server.ThreadingHTTPServer(
                    ("127.0.0.1", 0), server.Handler
                )
                thread = threading.Thread(target=listener.serve_forever, daemon=True)
                thread.start()
                port = listener.server_address[1]

                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                connection.request("GET", "/api/map_cells?budget=1000")
                cells_response = connection.getresponse()
                cells = json.loads(cells_response.read())
                connection.request("GET", "/api/map_cells?budget=nope")
                bad_response = connection.getresponse()
                bad_response.read()
                connection.close()
            finally:
                if listener is not None:
                    listener.shutdown()
                    listener.server_close()
                if thread is not None:
                    thread.join(timeout=3)
                server.RUNTIME = previous

            self.assertEqual(cells_response.status, 200)
            self.assertEqual(cells["status"], "unavailable")
            self.assertIn("reason", cells)
            self.assertEqual(bad_response.status, 400)


class ViewerBindAddressTests(unittest.TestCase):
    def test_host_defaults_to_loopback(self):
        args = server.build_arg_parser().parse_args([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)

    def test_host_option_allows_all_interfaces_for_containers(self):
        args = server.build_arg_parser().parse_args(
            ["--host", "0.0.0.0", "--port", "9000"]
        )
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9000)

    def test_main_binds_parsed_host_and_port(self):
        captured = {}

        class FakeServer:
            def __init__(self, address, handler):
                captured["address"] = address
                captured["handler"] = handler

            def serve_forever(self):
                raise KeyboardInterrupt

        with mock.patch.object(server.http.server, "ThreadingHTTPServer", FakeServer):
            with mock.patch("builtins.print"):
                server.main([])
                self.assertEqual(captured["address"], ("127.0.0.1", 8765))
                server.main(["--host", "0.0.0.0", "--port", "8765"])
                self.assertEqual(captured["address"], ("0.0.0.0", 8765))
        self.assertIs(captured["handler"], server.Handler)

    def test_repo_root_resolves_from_outside_the_checkout(self):
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(
                server.find_repo_root(Path(raw).resolve()),
                Path(server.__file__).resolve().parent.parent,
            )


# Player cli


class PlayerCliTests(unittest.TestCase):
    def test_player_requires_a_viewer_runtime_config(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as raw:
            player = Path(raw) / "veyra_player"
            subprocess.run(
                [
                    "c++",
                    "-std=c++20",
                    str(repo / "apps/player/main.cpp"),
                    "-o",
                    str(player),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            result = subprocess.run(
                [str(player)],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--runtime-config", result.stderr)


if __name__ == "__main__":
    unittest.main()
