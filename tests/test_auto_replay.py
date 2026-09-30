"""Automatic smooth replay preparation and cache reuse."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.auto_replay import cache_path, prepare, ready_cache
from runtime.config import config_digest
from runtime.replay_cache import ReplayReader, ReplayWriter, build_header
from runtime.service import ProductRuntime


def make_config():
    return {
        "dataset": "semanticposs",
        "dataset_root": "/dataset",
        "sequence": "00",
        "map": {"policy": "distance_lod", "executable": "/backend/veyra_runtime"},
        "playback": {"fps": 30.0, "speed": 1.0, "full_sequence": True},
        "visualization": {"point_budget": 8, "cell_budget": 4},
        "pipeline": {"semantic": {"mode": "ground_truth"}},
    }


class AutoReplayTests(unittest.TestCase):
    def test_full_sequence_configuration_schedules_preparation_after_preview(self):
        config = make_config()
        runtime = ProductRuntime(Path.cwd())
        session = mock.Mock()
        session.status.return_value = {"frames": 488}
        with (
            mock.patch("runtime.service.validate_config", return_value=config),
            mock.patch.object(runtime, "_create_session", return_value=session),
        ):
            runtime._configure(config, prepare_replay=True)
        runtime._publish_status()
        self.assertEqual(runtime.status()["auto_replay"]["state"], "pending")
        self.assertEqual(runtime._auto_replay["state"], "pending")
        self.assertEqual(runtime._auto_replay_config, config)
        self.assertIsNone(runtime._auto_replay_thread)
        runtime.close()

    def test_ready_cache_requires_matching_configuration_and_frame_count(self):
        config = make_config()
        with tempfile.TemporaryDirectory() as directory:
            path = cache_path(config, 2, Path(directory))
            self.assertIsNone(ready_cache(path, config, 2))
            path.parent.mkdir(parents=True, exist_ok=True)
            header = build_header(
                dataset="semanticposs",
                sequence="00",
                start=0,
                count=2,
                policy="distance_lod",
                semantic_provider={"mode": "ground_truth"},
                point_budget=8,
                cell_budget=4,
                perception_config_digest="pipeline",
                config_digest=config_digest(config),
                repo=None,
            )
            writer = ReplayWriter(path, header, 2)
            for index in range(2):
                writer.add_frame(index, {"type": "visualization", "index": index}, b"frame")
            writer.close()
            self.assertEqual(ready_cache(path, config, 2), path)
            changed = make_config()
            changed["playback"]["fps"] = 60.0
            self.assertIsNone(ready_cache(path, changed, 2))
            self.assertIsNone(ready_cache(path, config, 3))

    def test_configured_runtime_reuses_ready_cache_without_mapping_again(self):
        config = make_config()
        runtime = ProductRuntime(Path.cwd())
        runtime.config = config
        runtime.session = mock.Mock()
        runtime.session.status.return_value = {"frames": 2}
        runtime._auto_replay_config = config
        with (
            mock.patch("runtime.auto_replay.cache_path", return_value=Path("/cache/ready.veyra-replay")),
            mock.patch("runtime.auto_replay.ready_cache", return_value=Path("/cache/ready.veyra-replay")),
            mock.patch("runtime.auto_replay.prepare") as prepare,
        ):
            runtime._prepare_auto_replay()
        self.assertEqual(runtime.status()["auto_replay"]["state"], "ready")
        self.assertEqual(runtime.status()["auto_replay"]["frames"], 2)
        prepare.assert_not_called()
        runtime.close()

    def test_new_cache_prepares_in_background_and_announces_ready(self):
        config = make_config()
        runtime = ProductRuntime(Path.cwd())
        runtime.config = config
        runtime.session = mock.Mock()
        runtime.session.status.return_value = {"frames": 2}
        runtime._auto_replay_config = config
        path = Path("/cache/new.veyra-replay")
        with (
            mock.patch("runtime.auto_replay.cache_path", return_value=path),
            mock.patch("runtime.auto_replay.ready_cache", return_value=None),
            mock.patch("runtime.auto_replay.prepare", return_value=path) as prepare,
        ):
            runtime._prepare_auto_replay()
            runtime._auto_replay_thread.join(timeout=2)
        self.assertEqual(runtime.status()["auto_replay"]["state"], "ready")
        self.assertEqual(runtime.status()["auto_replay"]["path"], str(path))
        prepare.assert_called_once()
        runtime.close()

    def test_preparation_records_each_real_frame_and_publishes_complete_cache(self):
        config = make_config()
        frame = {
            "map": {"status": "available", "snapshot": {"active_leaf_count": 1}},
            "pipeline_status": {"semantic": "ground_truth"},
            "perception_timings_ms": {"total": 1.0},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "complete.veyra-replay"
            with (
                mock.patch("runtime.service.ProductRuntime") as runtime_type,
                mock.patch("runtime.auto_replay.pack_visualization") as pack,
            ):
                builder = runtime_type.return_value
                builder._frame_count.return_value = 2
                builder.generation = 1
                builder.session.frame_payload.return_value = frame
                builder.session.map_cells_binary.return_value = {"status": "available"}
                pack.side_effect = [
                    ({"type": "visualization", "index": 0}, b"first"),
                    ({"type": "visualization", "index": 1}, b"second"),
                ]
                progress = []
                result = prepare(
                    config, Path.cwd(), 2, path,
                    lambda done, total: progress.append((done, total)),
                    lambda: False,
                )
                self.assertEqual(result, path)
                self.assertEqual(progress, [(1, 2), (2, 2)])
                self.assertEqual(builder.session.frame_payload.call_count, 2)
                builder.close.assert_called_once()
            with ReplayReader(path, verify=True) as reader:
                self.assertEqual(len(reader), 2)
                self.assertEqual(reader.read_frame(1)[1], b"second")
                self.assertTrue(reader.read_frame(0)[0]["recorded_telemetry"]["recorded_during_cache_build"])
            self.assertEqual(list(path.parent.glob("*.part")), [])

    def test_cancelled_preparation_removes_partial_cache(self):
        config = make_config()
        frame = {
            "map": {"status": "available", "snapshot": {}},
            "pipeline_status": {"semantic": "ground_truth"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cancelled.veyra-replay"
            done = []
            with (
                mock.patch("runtime.service.ProductRuntime") as runtime_type,
                mock.patch(
                    "runtime.auto_replay.pack_visualization",
                    return_value=({"type": "visualization", "index": 0}, b"frame"),
                ),
            ):
                builder = runtime_type.return_value
                builder._frame_count.return_value = 2
                builder.generation = 1
                builder.session.frame_payload.return_value = frame
                builder.session.map_cells_binary.return_value = {"status": "available"}
                with self.assertRaisesRegex(RuntimeError, "cancelled"):
                    prepare(
                        config, Path.cwd(), 2, path,
                        lambda current, total: done.append(current),
                        lambda: bool(done),
                    )
            self.assertEqual(done, [1])
            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()
