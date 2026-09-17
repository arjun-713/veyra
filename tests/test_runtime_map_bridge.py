import atexit
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from datasets.common.observation import ObservationFrame, PoseSE3
from viewer.runtime import BenchmarkMapRunner

# Configure/build bounds are generous upper bounds (many times the measured
# ~30-60 s single-target build), never a substitute for the engine-level
# response bounds: a stuck toolchain must fail the gate, not stall it.
_CONFIGURE_TIMEOUT_S = 300
_BUILD_TIMEOUT_S = 600

_shared_binary: Path | None = None


def _benchmark_binary() -> Path:
    """Resolve one veyra_benchmark binary for the whole test session.

    Resolution order: ``$VEYRA_BENCHMARK_BINARY`` (also set by CTest, see
    tests/CMakeLists.txt), the in-repo build tree, otherwise a single
    configure+build cached in a session temp dir. Previously every test
    reconfigured and rebuilt from scratch, which dominated gate wall-clock
    (~30-60 s per test) and read as a stall at python_unittest.
    """
    global _shared_binary
    if _shared_binary is not None:
        return _shared_binary
    override = os.environ.get("VEYRA_BENCHMARK_BINARY", "").strip()
    if override:
        binary = Path(override)
        if not binary.is_file():
            raise AssertionError(
                f"VEYRA_BENCHMARK_BINARY does not exist: {binary}"
            )
        _shared_binary = binary
        return binary
    repo = Path(__file__).resolve().parents[1]
    candidate = repo / "build/apps/benchmark/veyra_benchmark"
    if candidate.is_file():
        _shared_binary = candidate
        return candidate
    directory = Path(tempfile.mkdtemp(prefix="veyra-bridge-build-"))
    atexit.register(lambda: shutil.rmtree(str(directory), ignore_errors=True))
    try:
        subprocess.run(
            ["cmake", "-S", str(repo), "-B", str(directory), "-DBUILD_TESTING=OFF"],
            check=True,
            capture_output=True,
            text=True,
            timeout=_CONFIGURE_TIMEOUT_S,
        )
        subprocess.run(
            [
                "cmake",
                "--build",
                str(directory),
                "--target",
                "veyra_benchmark",
                "-j2",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=_BUILD_TIMEOUT_S,
        )
    except Exception:
        shutil.rmtree(str(directory), ignore_errors=True)
        raise
    binary = directory / "apps" / "benchmark" / "veyra_benchmark"
    if not binary.is_file():
        raise AssertionError(f"benchmark build did not produce {binary}")
    _shared_binary = binary
    return binary


class RuntimeMapBridgeTests(unittest.TestCase):
    def test_persistent_engine_accumulates_resets_and_exposes_all_real_policies(self):
        from viewer.runtime import PersistentMapEngine

        binary = _benchmark_binary()
        first = _frame(1.0, 1.0)
        second = _frame(2.0, 2.0)

        for policy in ("uniform5", "uniform40", "distance_lod", "utility_lod"):
            engine = PersistentMapEngine(binary, policy=policy)
            try:
                one = engine.process_frame(first)
                two = engine.process_frame(second)
                status = engine.status()
                reset = engine.reset()
                after_reset = engine.process_frame(second)
            finally:
                engine.close()

            self.assertEqual(one["status"], "available", one)
            self.assertEqual(two["snapshot"]["point_count"], 2)
            self.assertEqual(after_reset["snapshot"]["point_count"], 1)
            self.assertEqual(status["policy"], policy)
            self.assertEqual(status["snapshot"]["point_count"], 2)
            self.assertEqual(
                status["snapshot"]["memory"]["allocated_bytes"],
                status["metrics"]["allocated_map_bytes"],
            )
            self.assertEqual(reset["status"], "available")
            self.assertIsNotNone(two["metrics"]["allocated_map_bytes"])

    def test_persistent_engine_keeps_calibrated_crop_boundary_points(self):
        from viewer.runtime import PersistentMapEngine

        binary = _benchmark_binary()
        frame = _frame(1.0, 100.0005)
        engine = PersistentMapEngine(binary)
        try:
            report = engine.process_frame(frame)
        finally:
            engine.close()

        self.assertEqual(report["status"], "available")
        self.assertEqual(report["snapshot"]["point_count"], 1)

    def test_engine_map_cells_match_snapshot_topology(self):
        from viewer.runtime import PersistentMapEngine

        binary = _benchmark_binary()
        engine = PersistentMapEngine(binary)
        try:
            report = engine.process_frame(_grid_frame())
            cells = engine.map_cells(budget=10000)
            engine.reset()
            cleared = engine.map_cells(budget=10000)
        finally:
            engine.close()

        self.assertEqual(report["status"], "available")
        self.assertEqual(cells["status"], "available")
        self.assertEqual(cells["cell_count"], report["snapshot"]["active_leaf_count"])
        self.assertGreater(cells["cell_count"], 1)
        for cell in cells["cells"]:
            self.assertIn(cell["l"], (0, 1, 2, 3))
            for key in (
                "ix",
                "iy",
                "z",
                "c",
                "semantic_confidence",
                "ground_evidence",
                "terrain_confidence",
                "geometry_complexity",
                "m",
                "q",
                "drivable_evidence",
            ):
                self.assertIn(key, cell)
            self.assertEqual(cell["c"], 7)
            self.assertAlmostEqual(cell["semantic_confidence"], 1.0)
            self.assertAlmostEqual(cell["ground_evidence"], 0.9)
            self.assertAlmostEqual(cell["terrain_confidence"], 0.9)
            self.assertAlmostEqual(cell["geometry_complexity"], 0.03)
            self.assertAlmostEqual(cell["m"], 0.0)
            self.assertAlmostEqual(cell["q"], 0.9)
            self.assertAlmostEqual(cell["drivable_evidence"], 0.9)
        self.assertEqual(cleared["cell_count"], 0)

    def test_malformed_record_aborts_frame_with_single_response(self):
        """A corrupt record must not strand the bridge behind an error storm.

        Regression: one malformed P record used to emit one error line per
        remaining record while Python was still writing the frame, deadlocking
        both pipes. The engine must answer once, drain the rest of the frame
        silently, and stay usable for the next frame.
        """
        import concurrent.futures

        from benchmarks.protocol import frame_records
        from viewer.runtime import PersistentMapEngine

        binary = _benchmark_binary()
        frame = _many_points_frame(3000)
        records = frame_records(frame)
        poisoned = [records[0], "P garbage not-a-number\n"] + records[1:]
        engine = PersistentMapEngine(binary)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(engine._command, "".join(poisoned))
                try:
                    response = future.result(timeout=30)
                except concurrent.futures.TimeoutError:
                    self.fail("engine deadlocked on a malformed record")
            self.assertEqual(response.get("status"), "unavailable")
            recovered = engine.process_frame(_frame(9.0, 9.0))
            self.assertEqual(recovered["status"], "available")
            self.assertEqual(recovered["snapshot"]["point_count"], 1)
        finally:
            engine.close()

    def test_real_benchmark_v2_report_is_exposed_without_synthetic_metrics(self):
        binary = _benchmark_binary()
        frame = _frame(1.0, 1.0)
        report = BenchmarkMapRunner(binary).process(frame)

        self.assertEqual(report["status"], "available")
        self.assertEqual(report["source"], "veyra_persistent_engine")
        self.assertEqual(report["input_points"], 1)
        self.assertIn("levels", report["snapshot"])
        self.assertNotIn("leaves", report["snapshot"])
        self.assertIn("map_update_latency_ns", report["metrics"])
        self.assertIsNotNone(report["metrics"]["measured_rss_bytes"])
        self.assertTrue(report["input"]["pose_available"])
        self.assertTrue(report["input"]["enriched_fields_available"])
        for field in (
            "semantic_confidence",
            "slope",
            "roughness",
            "height_complexity",
            "terrain_confidence",
            "motion_probability",
            "observation_quality",
            "raw_semantic_class",
        ):
            self.assertIn(field, report["input"]["quality"])


def _grid_frame() -> ObservationFrame:
    """Nine points on a 3x3 metre grid so cells cannot coincide."""
    coords = [(x, y) for x in (0.0, 1.0, 2.0) for y in (0.0, 1.0, 2.0)]
    count = len(coords)
    points = np.array([[x, y, 0.2, 0.5] for x, y in coords], dtype=np.float32)
    return ObservationFrame(
        timestamp=3.0,
        pose=PoseSE3.identity(3.0),
        points=points,
        semantic_class=np.full(count, 7, dtype=np.int32),
        semantic_confidence=np.full(count, 1.0, dtype=np.float32),
        ground=np.full(count, True),
        drivable=np.full(count, "drivable"),
        slope=np.full(count, 0.01, dtype=np.float32),
        roughness=np.full(count, 0.02, dtype=np.float32),
        height_complexity=np.full(count, 0.03, dtype=np.float32),
        motion_probability=np.zeros(count, dtype=np.float32),
        velocity_xy=np.zeros((count, 2), dtype=np.float32),
        terrain_confidence=np.full(count, 0.9, dtype=np.float32),
        step=np.zeros(count, dtype=np.float32),
        motion_state=np.full(count, "static"),
        observation_quality=np.full(count, 0.9, dtype=np.float32),
        raw_semantic_class=np.full(count, 7, dtype=np.int32),
        dataset="fixture",
        sequence="00",
        frame_id="000003",
    )


def _many_points_frame(count: int) -> ObservationFrame:
    """A large valid frame whose records can follow one malformed record."""
    xs = np.linspace(0.5, 5.0, count, dtype=np.float32)
    points = np.column_stack(
        [
            xs,
            np.zeros(count, dtype=np.float32),
            np.full(count, 0.2, dtype=np.float32),
            np.full(count, 0.5, dtype=np.float32),
        ]
    )
    return ObservationFrame(
        timestamp=4.0,
        pose=PoseSE3.identity(4.0),
        points=points,
        semantic_class=np.full(count, 7, dtype=np.int32),
        semantic_confidence=np.full(count, 1.0, dtype=np.float32),
        ground=np.full(count, True),
        drivable=np.full(count, "drivable"),
        slope=np.full(count, 0.01, dtype=np.float32),
        roughness=np.full(count, 0.02, dtype=np.float32),
        height_complexity=np.full(count, 0.03, dtype=np.float32),
        motion_probability=np.zeros(count, dtype=np.float32),
        velocity_xy=np.zeros((count, 2), dtype=np.float32),
        terrain_confidence=np.full(count, 0.9, dtype=np.float32),
        step=np.zeros(count, dtype=np.float32),
        motion_state=np.full(count, "static"),
        observation_quality=np.full(count, 0.9, dtype=np.float32),
        raw_semantic_class=np.full(count, 7, dtype=np.int32),
        dataset="fixture",
        sequence="00",
        frame_id="000004",
    )


def _frame(timestamp: float, x: float) -> ObservationFrame:
    return ObservationFrame(
        timestamp=timestamp,
        pose=PoseSE3.identity(timestamp),
        points=np.array([[x, 0.0, 0.2, 0.5]], dtype=np.float32),
        semantic_class=np.array([7], dtype=np.int32),
        semantic_confidence=np.array([1.0], dtype=np.float32),
        ground=np.array([True]),
        drivable=np.array(["drivable"]),
        slope=np.array([0.01], dtype=np.float32),
        roughness=np.array([0.02], dtype=np.float32),
        height_complexity=np.array([0.03], dtype=np.float32),
        motion_probability=np.array([0.0], dtype=np.float32),
        velocity_xy=np.array([[0.0, 0.0]], dtype=np.float32),
        terrain_confidence=np.array([0.9], dtype=np.float32),
        step=np.array([0.0], dtype=np.float32),
        motion_state=np.array(["static"]),
        observation_quality=np.array([0.9], dtype=np.float32),
        raw_semantic_class=np.array([7], dtype=np.int32),
        dataset="fixture",
        sequence="00",
        frame_id=f"{round(timestamp):06d}",
    )


if __name__ == "__main__":
    unittest.main()
