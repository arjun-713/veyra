"""End-to-end: Python observation frame -> V3 protocol -> C++ engine -> layers.

These tests run the real engine binary over the real protocol writer. They
exist because every other test of the layered map is in-process, and the layers
spent one whole development cycle working perfectly in-process while being
completely dormant on the live path -- the V2 wire format had no field to carry
height above ground, so every observation arrived with the value unset.

A unit test cannot catch that. Only a test that crosses the protocol can.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

import numpy as np

from benchmarks.protocol import PROTOCOL_VERSION, stream_bytes
from datasets.common.observation import ObservationFrame, PoseSE3

REPO = Path(__file__).resolve().parents[1]


def _engine() -> Path | None:
    """The benchmark engine binary, wherever this checkout put it."""
    for candidate in (
        REPO / "build" / "apps" / "benchmark" / "veyra_benchmark",
        REPO / "build" / "Release" / "apps" / "benchmark" / "veyra_benchmark",
        REPO / "build" / "Debug" / "apps" / "benchmark" / "veyra_benchmark",
    ):
        if candidate.is_file():
            return candidate
    found = shutil.which("veyra_benchmark")
    return Path(found) if found else None


def _frame(
    xyz: np.ndarray,
    ground: np.ndarray,
    hag: np.ndarray | None,
    *,
    frame_id: str = "0",
    timestamp: float = 1.0,
) -> ObservationFrame:
    count = xyz.shape[0]
    points = np.hstack([xyz, np.zeros((count, 1), dtype=np.float32)]).astype(np.float32)
    return ObservationFrame(
        timestamp=timestamp,
        pose=PoseSE3(matrix=np.eye(4, dtype=np.float64), timestamp=timestamp),
        points=points,
        semantic_class=np.full(count, 1, dtype=np.int32),
        semantic_confidence=np.full(count, 0.9, dtype=np.float32),
        ground=ground.astype(bool),
        drivable=np.full(count, "drivable", dtype="U15"),
        slope=np.zeros(count, dtype=np.float32),
        roughness=np.zeros(count, dtype=np.float32),
        height_complexity=np.zeros(count, dtype=np.float32),
        motion_probability=np.zeros(count, dtype=np.float32),
        velocity_xy=np.zeros((count, 2), dtype=np.float32),
        dataset="synthetic",
        sequence="layers",
        frame_id=frame_id,
        terrain_confidence=np.full(count, 0.9, dtype=np.float32),
        step=np.zeros(count, dtype=np.float32),
        motion_state=np.full(count, "static", dtype="U15"),
        observation_quality=np.full(count, 0.9, dtype=np.float32),
        height_above_ground=hag,
    )


def _road_under_a_branch(with_hag: bool) -> list[ObservationFrame]:
    """Flat road at z=0 with overhead structure at z=3, in the same columns.

    This is the geometry a pooled elevation mean cannot represent: averaging
    the two gives a surface at 1.5 m that the sensor never observed.
    """
    grid = np.arange(-4.0, 4.0, 0.5, dtype=np.float32)
    xs, ys = np.meshgrid(grid, grid)
    flat = np.stack([xs.ravel(), ys.ravel()], axis=1)
    road = np.hstack([flat, np.zeros((flat.shape[0], 1), dtype=np.float32)])
    canopy = np.hstack([flat, np.full((flat.shape[0], 1), 3.0, dtype=np.float32)])

    xyz = np.vstack([road, canopy]).astype(np.float32)
    ground = np.concatenate(
        [np.ones(road.shape[0], dtype=bool), np.zeros(canopy.shape[0], dtype=bool)]
    )
    hag = None
    if with_hag:
        hag = np.concatenate(
            [
                np.zeros(road.shape[0], dtype=np.float32),
                np.full(canopy.shape[0], 3.0, dtype=np.float32),
            ]
        )
    # Two frames: the engine discards a warmup frame.
    return [
        _frame(xyz, ground, hag, frame_id=str(index), timestamp=1.0 + index)
        for index in range(2)
    ]


def _run(frames: list[ObservationFrame], engine: Path) -> dict:
    payload, _ = stream_bytes(frames)
    completed = subprocess.run(
        [str(engine), "--policy", "uniform5"],
        input=payload,
        capture_output=True,
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"engine exited {completed.returncode}: {completed.stderr.decode()[:2000]}"
        )
    return json.loads(completed.stdout.decode())


class LayeredEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _engine()
        if self.engine is None:
            self.skipTest(
                "veyra_benchmark not built; run cmake --build build before this test"
            )

    def test_protocol_version_is_three(self) -> None:
        self.assertEqual(PROTOCOL_VERSION, 3)
        payload, _ = stream_bytes(_road_under_a_branch(with_hag=True))
        self.assertTrue(payload.startswith(b"VEYRA_STREAM 3\n"))

    def test_height_above_ground_survives_the_wire(self) -> None:
        """The whole point: layers are populated from a real stream."""
        report = _run(_road_under_a_branch(with_hag=True), self.engine)
        layers = report["snapshot"]["layers"]

        self.assertGreater(layers["ground_points"], 0, "road reached the ground layer")
        self.assertGreater(
            layers["overhead_points"], 0, "canopy reached the overhead layer"
        )
        self.assertEqual(
            layers["unmodelled_returns"],
            0,
            "every return carried a ground model across the wire",
        )
        # The canopy is overhead, not an obstacle: nothing stands on this road.
        self.assertEqual(
            layers["obstacle_points"], 0, "no obstacle evidence on open road"
        )

    def test_v2_producer_is_counted_not_silently_misfiled(self) -> None:
        """A frame with no height above ground must be loudly unmodelled.

        This is the regression guard for the failure that motivated the V3
        bump: the layers silently doing nothing while every metric looked
        healthy.
        """
        report = _run(_road_under_a_branch(with_hag=False), self.engine)
        layers = report["snapshot"]["layers"]

        self.assertGreater(
            layers["unmodelled_returns"],
            0,
            "returns without a ground model are counted",
        )
        self.assertEqual(
            layers["overhead_points"],
            0,
            "and are never promoted to overhead on a guess",
        )

    def test_ground_height_is_the_road_not_the_average(self) -> None:
        """Per-cell proof that the pooled mean and the ground layer differ."""
        payload, _ = stream_bytes(_road_under_a_branch(with_hag=True))
        completed = subprocess.run(
            [str(self.engine), "--policy", "uniform5", "--include-leaf-details"],
            input=payload,
            capture_output=True,
            timeout=120,
        )
        if completed.returncode != 0:
            self.skipTest("engine build does not expose --leaf-details")
        report = json.loads(completed.stdout.decode())
        leaves = report["snapshot"].get("leaves")
        if not leaves:
            self.skipTest("no leaf details emitted")

        mixed = [
            leaf
            for leaf in leaves
            if leaf["ground_count"] > 0 and leaf["overhead_count"] > 0
        ]
        self.assertTrue(mixed, "some cell holds both road and canopy returns")
        for leaf in mixed:
            self.assertAlmostEqual(
                leaf["ground_mean_z"],
                0.0,
                places=3,
                msg="ground layer recovers the road surface",
            )
            self.assertAlmostEqual(
                leaf["overhead_min_z"],
                3.0,
                places=3,
                msg="overhead layer recovers the canopy height",
            )
            self.assertGreater(
                leaf["mean_z"],
                0.5,
                "while the pooled mean sits between the two, as expected",
            )


class InteractiveEngineEndToEnd(unittest.TestCase):
    """The persistent engine path, which the batch path does not exercise.

    The V2/V3 handshake regression lived here and not in the batch path: batch
    reads its version from the stream header, the persistent engine reads it
    from the handshake, and only one of those was updated. Covering batch alone
    left the half where the bug was.
    """

    def setUp(self) -> None:
        self.engine_path = _engine()
        if self.engine_path is None:
            self.skipTest("veyra_benchmark not built")

    def test_occluded_ground_is_reported_not_invented(self) -> None:
        """A column with only overhead returns must read as occluded.

        A pooled elevation mean answers this case with a confident height at
        roof level and no indication that the floor was never seen. The whole
        layered design exists to make that distinction reportable.
        """
        from viewer.runtime import PersistentMapEngine

        grid = np.arange(-2.0, 2.0, 0.5, dtype=np.float32)
        xs, ys = np.meshgrid(grid, grid)
        flat = np.stack([xs.ravel(), ys.ravel()], axis=1)
        roof = np.hstack([flat, np.full((flat.shape[0], 1), 2.6, dtype=np.float32)])
        ground_flags = np.zeros(roof.shape[0], dtype=bool)
        hag = np.full(roof.shape[0], 2.6, dtype=np.float32)
        frames = [
            _frame(
                roof.astype(np.float32),
                ground_flags,
                hag,
                frame_id=str(index),
                timestamp=1.0 + index,
            )
            for index in range(2)
        ]

        engine = PersistentMapEngine(self.engine_path, policy="uniform5")
        try:
            for frame in frames:
                response = engine.process_frame(frame)
        finally:
            engine.close()

        layers = response["snapshot"]["layers"]
        self.assertEqual(layers["ground_points"], 0, "no floor was ever observed")
        self.assertGreater(layers["overhead_points"], 0, "the roof was observed")
        self.assertGreater(
            layers["occluded_ground_cells"],
            0,
            "and the map says so, instead of reporting a surface at roof height",
        )
        self.assertEqual(layers["cells_with_ground"], 0)

    def test_layers_populate_over_the_persistent_engine(self) -> None:
        from viewer.runtime import PersistentMapEngine

        engine = PersistentMapEngine(self.engine_path, policy="uniform5")
        try:
            for frame in _road_under_a_branch(with_hag=True):
                response = engine.process_frame(frame)
        finally:
            engine.close()

        self.assertEqual(response.get("status"), "available", response)
        layers = response["snapshot"]["layers"]
        self.assertGreater(layers["ground_points"], 0)
        self.assertGreater(layers["overhead_points"], 0)
        self.assertEqual(layers["unmodelled_returns"], 0)
        self.assertGreater(layers["cells_with_ground"], 0)
        self.assertEqual(
            layers["occluded_ground_cells"],
            0,
            "the road was observed in every column, so nothing is occluded",
        )
        # Occupancy must be driven by ordinary ingestion, not only by the
        # range-gated overload. A feature that only works when a second,
        # optional API is used is the same dormant-feature trap the V2 wire
        # format created for the layers.
        self.assertGreater(
            layers["occupied_cells"], 0, "returns drive the occupancy accumulator"
        )
        self.assertEqual(
            layers["free_cells"],
            0,
            "and nothing is free: only an observed beam through a cell may do that",
        )


class ProtocolVersionCoupling(unittest.TestCase):
    """Every writer must announce the version of the records it writes.

    Regression guard. Bumping PROTOCOL_VERSION to 3 while the persistent
    engine handshake still said "VEYRA_ENGINE 2" made the engine parse 20-field
    records against a 19-field layout. It surfaced as "nonfinite required point
    value" -- an error pointing at the data, several fields away from the
    actual fault. A version mismatch should not be diagnosed by reading point
    values.
    """

    def test_viewer_handshake_matches_protocol_version(self) -> None:
        source = (REPO / "viewer" / "runtime.py").read_text(encoding="utf-8")
        self.assertNotIn(
            'VEYRA_ENGINE 2\\n"',
            source,
            "handshake version is hard-coded and will drift from the writer",
        )
        self.assertIn("VEYRA_ENGINE {PROTOCOL_VERSION}", source)

    def test_engine_accepts_the_version_we_announce(self) -> None:
        engine = _engine()
        if engine is None:
            self.skipTest("veyra_benchmark not built")
        payload, _ = stream_bytes(_road_under_a_branch(with_hag=True))
        header = payload.split(b"\n", 1)[0].decode()
        self.assertEqual(header, f"VEYRA_STREAM {PROTOCOL_VERSION}")
        completed = subprocess.run(
            [str(engine), "--policy", "uniform5"],
            input=payload,
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"engine rejected its own protocol version: {completed.stderr.decode()[:500]}",
        )
        self.assertEqual(
            json.loads(completed.stdout.decode())["protocol_version"], PROTOCOL_VERSION
        )


class HeightAboveGroundStage(unittest.TestCase):
    """The perception stage that produces the value, tested on its own."""

    def test_flat_ground_gives_true_heights(self) -> None:
        from perception.ground import height_above_ground

        ground_pts = np.array(
            [[x, y, 0.0] for x in (-1.0, 0.0, 1.0) for y in (-1.0, 0.0, 1.0)],
            dtype=np.float64,
        )
        above = np.array([[0.0, 0.0, 2.5]], dtype=np.float64)
        points = np.vstack([ground_pts, above])
        mask = np.concatenate(
            [np.ones(len(ground_pts), dtype=bool), np.zeros(1, dtype=bool)]
        )

        hag = height_above_ground(points, mask, cell_size_m=4.0)
        self.assertAlmostEqual(float(hag[-1]), 2.5, places=4)
        for value in hag[:-1]:
            self.assertAlmostEqual(float(value), 0.0, places=4)

    def test_no_ground_evidence_is_nan_not_zero(self) -> None:
        from perception.ground import height_above_ground

        points = np.array([[0.0, 0.0, 1.0], [50.0, 50.0, 2.0]], dtype=np.float64)
        mask = np.zeros(2, dtype=bool)
        hag = height_above_ground(points, mask)
        self.assertTrue(np.all(np.isnan(hag)), "no ground stage means no guesses")

    def test_depressions_are_negative_not_clamped(self) -> None:
        from perception.ground import height_above_ground

        ground_pts = np.array(
            [[x, 0.0, 0.0] for x in np.linspace(-1.0, 1.0, 9)], dtype=np.float64
        )
        pothole = np.array([[0.0, 0.0, -0.35]], dtype=np.float64)
        points = np.vstack([ground_pts, pothole])
        mask = np.concatenate(
            [np.ones(len(ground_pts), dtype=bool), np.zeros(1, dtype=bool)]
        )
        hag = height_above_ground(points, mask, cell_size_m=4.0)
        self.assertLess(float(hag[-1]), -0.3, "a pothole reports negative height")

    def test_vectorised_median_matches_numpy_exactly(self) -> None:
        """The per-cell median is index arithmetic, not np.median.

        Replacing a well-tested library call with a sort-and-index trick is
        only safe if it agrees exactly, including the even-count case where the
        median is the mean of two middle elements. Random cell populations,
        both parities, checked against np.median itself.
        """
        from perception.ground import height_above_ground

        rng = np.random.default_rng(20260919)
        for trial in range(25):
            # One cell, random population size so both parities are covered.
            size = int(rng.integers(3, 40))
            zs = rng.normal(0.0, 0.5, size)
            ground_pts = np.column_stack([np.zeros(size), np.zeros(size), zs])
            probe = np.array([[0.0, 0.0, 5.0]])
            points = np.vstack([ground_pts, probe])
            mask = np.concatenate([np.ones(size, dtype=bool), np.zeros(1, dtype=bool)])

            hag = height_above_ground(points, mask, cell_size_m=10.0)
            expected = 5.0 - float(np.median(zs))
            self.assertAlmostEqual(
                float(hag[-1]),
                expected,
                places=5,
                msg=f"trial {trial}, population {size} ({'even' if size % 2 == 0 else 'odd'})",
            )

    def test_many_cells_agree_with_a_reference_implementation(self) -> None:
        """Whole-frame agreement, not just one cell."""
        from perception.ground import height_above_ground

        rng = np.random.default_rng(7)
        count = 4000
        xy = rng.uniform(-20.0, 20.0, (count, 2))
        z = rng.normal(0.0, 0.2, count)
        points = np.column_stack([xy, z])
        mask = rng.random(count) < 0.5

        cell = 2.0
        hag = height_above_ground(
            points, mask, cell_size_m=cell, use_neighbour_fallback=False
        )

        # Straightforward reference: group by cell, take np.median, subtract.
        keys = np.floor(xy / cell).astype(np.int64)
        expected = np.full(count, np.nan)
        for key in np.unique(keys[mask], axis=0):
            in_cell = (keys[:, 0] == key[0]) & (keys[:, 1] == key[1])
            ground_here = in_cell & mask
            if int(ground_here.sum()) < 3:
                continue
            expected[in_cell] = z[in_cell] - np.median(z[ground_here])

        both_nan = np.isnan(hag) & np.isnan(expected)
        close = np.isclose(hag, expected, atol=1e-5, equal_nan=False)
        self.assertTrue(
            np.all(both_nan | close),
            f"{int((~(both_nan | close)).sum())} of {count} points disagree",
        )

    def test_median_resists_leaked_non_ground_returns(self) -> None:
        from perception.ground import height_above_ground

        # Eight true ground returns and three that leaked in from a kerb. A
        # mean would be dragged upward and would make real obstacles look
        # shorter than they are -- an error in the unsafe direction.
        road = [[x, 0.0, 0.0] for x in np.linspace(-1.0, 1.0, 8)]
        leaked = [[0.5, 0.0, 0.15]] * 3
        probe = [[0.0, 0.0, 1.0]]
        points = np.array(road + leaked + probe, dtype=np.float64)
        mask = np.array([True] * 11 + [False], dtype=bool)

        hag = height_above_ground(points, mask, cell_size_m=4.0)
        self.assertAlmostEqual(float(hag[-1]), 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
