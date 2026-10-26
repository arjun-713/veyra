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
            raise AssertionError(f"VEYRA_BENCHMARK_BINARY does not exist: {binary}")
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

    def _dense_patch_cells(self, *budgets):
        from viewer.runtime import PersistentMapEngine

        engine = PersistentMapEngine(_benchmark_binary(), policy="uniform5")
        try:
            engine.process_frame(_dense_patch_frame())
            return [engine.map_cells(budget=budget) for budget in budgets]
        finally:
            engine.close()

    def test_display_cells_under_budget_are_every_leaf_unfolded(self):
        (cells,) = self._dense_patch_cells(100000)
        self.assertEqual(cells["status"], "available")
        self.assertEqual(cells["selection"], "all")
        self.assertEqual(cells["cell_count"], cells["total_leaves"])
        self.assertTrue(all(cell["l"] == 0 for cell in cells["cells"]))

    def test_display_cells_over_budget_cover_the_whole_map_by_folding(self):
        full, folded = self._dense_patch_cells(100000, 1000)
        self.assertEqual(folded["status"], "available")
        self.assertEqual(folded["selection"], "folded")
        self.assertEqual(folded["total_leaves"], full["total_leaves"])
        self.assertLessEqual(folded["cell_count"], 1000)
        # A nearest-N disc would drop most of this 6 m patch; folding must
        # keep every mapped return and every mapped place.
        self.assertEqual(
            sum(cell["n"] for cell in folded["cells"]),
            sum(cell["n"] for cell in full["cells"]),
        )
        covered = {}
        for cell in folded["cells"]:
            self.assertIn(cell["l"], range(7))
            scale = 2 ** cell["l"]
            for ix in range(cell["ix"] * scale, (cell["ix"] + 1) * scale):
                for iy in range(cell["iy"] * scale, (cell["iy"] + 1) * scale):
                    self.assertNotIn((ix, iy), covered, "display tiles overlap")
                    covered[(ix, iy)] = cell["l"]
        for cell in full["cells"]:
            self.assertIn((cell["ix"], cell["iy"]), covered)
        # Folding is graded by range: native 5 cm near the vehicle, coarse
        # far away -- never a uniformly coarse or uniformly thinned map.
        radius = folded["native_radius_m"]
        self.assertGreater(radius, 0.0)

        def distance(cell):
            size = 0.05 * 2 ** cell["l"]
            return np.hypot((cell["ix"] + 0.5) * size, (cell["iy"] + 0.5) * size)

        nearest = min(folded["cells"], key=distance)
        farthest = max(folded["cells"], key=distance)
        self.assertEqual(nearest["l"], 0)
        self.assertEqual(farthest["l"], 3)
        self.assertTrue(
            all(cell["l"] == 0 for cell in folded["cells"] if distance(cell) < radius)
        )
        # Pooled height statistics survive the fold.
        self.assertAlmostEqual(
            min(cell["zmin"] for cell in folded["cells"]),
            min(cell["zmin"] for cell in full["cells"]),
            places=5,
        )

    def test_display_cells_over_budget_show_the_newest_whole_scans_natively(self):
        from viewer.runtime import PersistentMapEngine

        engine = PersistentMapEngine(_benchmark_binary(), policy="uniform5")
        try:
            engine.process_frame(_dense_patch_frame())
            newest = _dense_patch_frame(timestamp=4.0, offset_x=20.0)
            engine.process_frame(newest)
            full = engine.map_cells(budget=100000)
            recent = engine.map_cells(budget=4000)
            binary = engine.map_cells_binary(budget=4000)
        finally:
            engine.close()
        self.assertEqual(full["cell_count"], 7200)
        # The older scan no longer fits, the newest one does: it is sent
        # whole, at native 5 cm, never folded or cut to a disc.
        self.assertEqual(recent["selection"], "recent")
        self.assertEqual(recent["recent_scans"], 1)
        self.assertEqual(recent["cell_count"], 3600)
        self.assertTrue(all(cell["l"] == 0 for cell in recent["cells"]))
        self.assertTrue(all(cell["ix"] * 0.05 > 15.0 for cell in recent["cells"]))
        self.assertEqual(binary["selection"], "recent")
        self.assertEqual(binary["recent_scans"], 1)
        self.assertEqual(binary["cell_count"], 3600)

    def test_display_cells_fold_deterministically_and_match_binary_rows(self):
        from viewer.runtime import PersistentMapEngine

        engine = PersistentMapEngine(_benchmark_binary(), policy="uniform5")
        try:
            engine.process_frame(_dense_patch_frame())
            first = engine.map_cells(budget=700)
            second = engine.map_cells(budget=700)
            binary = engine.map_cells_binary(budget=700)
        finally:
            engine.close()
        self.assertEqual(first, second)
        self.assertEqual(binary["selection"], "folded")
        self.assertEqual(binary["cell_count"], first["cell_count"])
        self.assertAlmostEqual(
            binary["native_radius_m"], first["native_radius_m"], places=5
        )
        rows = np.frombuffer(binary["cells_binary"], "<f4").reshape(-1, 17)
        np.testing.assert_allclose(
            rows[:, 13], [cell["n"] for cell in first["cells"]], atol=0
        )

    def test_display_cells_beyond_the_coarsest_fold_keep_the_nearest_tiles(self):
        # The 6 m patch spans 2 x 2 display-only 3.2 m tiles (level 6).
        full, clipped = self._dense_patch_cells(100000, 2)
        self.assertEqual(clipped["selection"], "folded_nearest")
        self.assertEqual(clipped["cell_count"], 2)
        self.assertTrue(all(cell["l"] == 6 for cell in clipped["cells"]))
        self.assertLess(
            sum(cell["n"] for cell in clipped["cells"]),
            sum(cell["n"] for cell in full["cells"]),
        )

    def test_engine_map_cells_over_budget_still_cover_every_mapped_return(self):
        from viewer.runtime import PersistentMapEngine

        engine = PersistentMapEngine(_benchmark_binary())
        try:
            engine.process_frame(_grid_frame())
            cells = engine.map_cells(budget=3)
        finally:
            engine.close()

        self.assertEqual(cells["status"], "available")
        self.assertLessEqual(cells["cell_count"], 3)
        self.assertGreater(cells["total_leaves"], 3)
        # Folding, not a nearest-N disc: all nine returns of the 3 m grid
        # stay on screen, pooled into coarser display tiles.
        self.assertEqual(cells["selection"], "folded")
        self.assertEqual(sum(cell["n"] for cell in cells["cells"]), 9)

    def test_binary_map_cells_match_the_json_rows_they_replace(self):
        from runtime.visualization import pack_visualization
        from viewer.runtime import PersistentMapEngine

        engine = PersistentMapEngine(_benchmark_binary())
        try:
            engine.process_frame(_grid_frame())
            text = engine.map_cells(budget=4)
            binary = engine.map_cells_binary(budget=4)
        finally:
            engine.close()

        self.assertEqual(binary["status"], "available")
        self.assertEqual(binary["cell_count"], text["cell_count"])
        self.assertEqual(binary["total_leaves"], text["total_leaves"])
        frame = {
            "shown": 0,
            "points": np.empty((0, 3)),
            "intensity": [],
            "semantic_labels": [],
            "ground": [],
            "drivable": [],
            "semantic_confidence": [],
            "slope": [],
            "roughness": [],
            "height_complexity": [],
            "motion_probability": [],
            "velocity_xy": np.empty((0, 2)),
            "observation_quality": [],
            "terrain_confidence": [],
            "pipeline_status": {
                "semantic": "a",
                "ground": "a",
                "terrain": "a",
                "temporal": "a",
            },
            "index": 0,
            "dataset": "fixture",
            "seq": "00",
            "id": "0",
            "pose": {"matrix": np.eye(4), "available": False},
            "n_points": 0,
        }
        _, from_text = pack_visualization(frame, text, 1)
        _, from_binary = pack_visualization(frame, binary, 1)
        # JSON carries six decimals; the binary rows carry full float32.
        np.testing.assert_allclose(
            np.frombuffer(from_binary, "<f4"),
            np.frombuffer(from_text, "<f4"),
            atol=1e-6,
        )

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
            # Compared with an explicit tolerance rather than the default 7
            # places, so this asserts the emitted value and not the width of
            # the field behind it. A byte-wide fixed-point encoding was tried
            # for these and reverted (it froze the running averages); the
            # tolerance is what keeps this test about the contract.
            unsigned_quantum = 1.0 / 255.0
            signed_quantum = 1.0 / 127.0
            self.assertAlmostEqual(
                cell["semantic_confidence"], 1.0, delta=unsigned_quantum
            )
            self.assertAlmostEqual(cell["ground_evidence"], 0.9, delta=unsigned_quantum)
            self.assertAlmostEqual(
                cell["terrain_confidence"], 0.9, delta=unsigned_quantum
            )
            self.assertAlmostEqual(
                cell["geometry_complexity"], 0.03, delta=unsigned_quantum
            )
            self.assertAlmostEqual(cell["m"], 0.0, delta=unsigned_quantum)
            self.assertAlmostEqual(cell["q"], 0.9, delta=unsigned_quantum)
            self.assertAlmostEqual(cell["drivable_evidence"], 0.9, delta=signed_quantum)
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


def _dense_patch_frame(
    timestamp: float = 3.0, offset_x: float = 0.0
) -> ObservationFrame:
    """One return per 5 cm cell every 10 cm over a 6 m patch around the vehicle.

    3,600 level-0 leaves that fold to 15 x 15 = 225 level-3 tiles; the patch
    straddles the origin so negative indices exercise floor division.
    """
    axis = np.arange(-3.0, 3.0, 0.1) + 0.025
    xs, ys = np.meshgrid(axis, axis, indexing="ij")
    count = xs.size
    z = 0.2 + 0.01 * np.hypot(xs, ys).ravel()
    points = np.column_stack(
        [xs.ravel() + offset_x, ys.ravel(), z, np.full(count, 0.5)]
    ).astype(np.float32)
    return ObservationFrame(
        timestamp=timestamp,
        pose=PoseSE3.identity(timestamp),
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
        frame_id=f"{int(timestamp):06d}",
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
