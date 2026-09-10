"""SemanticPOSS KITTI-layout adapter and deterministic replay."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path

import numpy as np

from datasets.common.adapter import DatasetFrameRef
from datasets.common.observation import FrameProvenance, ObservationFrame, PoseSE3
from datasets.common.taxonomy import SEMANTIC_POSS_LABELS, map_dataset_labels

FrameRef = DatasetFrameRef


class SemanticPOSSDataset:
    """Read SemanticPOSS from the repository-relative KITTI-style layout."""

    dataset_name = "semanticposs"
    default_label_mapping = SEMANTIC_POSS_LABELS
    timestamp_filenames = ("timestamps.txt",)

    def __init__(
        self,
        root: str | Path,
        *,
        sequences: list[str] | None = None,
        scan_dir: str = "velodyne",
        label_dir: str = "labels",
    ) -> None:
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"SemanticPOSS root does not exist: {self.root}")
        self._sequences = (
            [str(sequence) for sequence in sequences] if sequences else None
        )
        self.scan_dir = scan_dir
        self.label_dir = label_dir

    def list_sequences(self) -> list[str]:
        if self._sequences is not None:
            return list(self._sequences)
        sequence_root = self.root / "sequences"
        base = sequence_root if sequence_root.is_dir() else self.root
        return sorted(
            path.name
            for path in base.iterdir()
            if path.is_dir() and path.name.isdigit()
        )

    def _sequence_root(self, sequence: str) -> Path:
        nested = self.root / "sequences" / str(sequence)
        direct = self.root / str(sequence)
        return nested if nested.is_dir() else direct

    def list_frames(self, sequence: str) -> list[FrameRef]:
        sequence = str(sequence)
        scan_root = self._sequence_root(sequence) / self.scan_dir
        if not scan_root.is_dir():
            raise FileNotFoundError(f"scan directory does not exist: {scan_root}")
        scans = sorted(
            scan_root.glob("*.bin"), key=lambda path: self._frame_sort_key(path.stem)
        )
        label_root = self._sequence_root(sequence) / self.label_dir
        return [
            FrameRef(
                sequence=sequence,
                frame_id=scan.stem,
                scan_path=scan,
                label_path=(label_root / f"{scan.stem}.label")
                if (label_root / f"{scan.stem}.label").is_file()
                else None,
            )
            for scan in scans
        ]

    @staticmethod
    def _frame_sort_key(frame_id: str) -> tuple[int, int | str]:
        try:
            return (0, int(frame_id))
        except ValueError:
            return (1, frame_id)

    def load_frame(
        self,
        sequence: str,
        frame_id: str,
        *,
        label_mapping: Mapping[int, int] | None = None,
        max_range_m: float | None = None,
        min_range_m: float = 0.0,
    ) -> ObservationFrame:
        refs = {ref.frame_id: ref for ref in self.list_frames(sequence)}
        ref = refs.get(str(frame_id))
        if ref is None:
            raise FileNotFoundError(f"frame {sequence}/{frame_id} does not exist")
        if ref.label_path is None:
            raise FileNotFoundError(f"label file is missing for {sequence}/{frame_id}")

        raw_points = np.fromfile(ref.scan_path, dtype=np.float32)
        if raw_points.size % 4:
            raise ValueError(
                f"scan does not contain complete XYZ/intensity records: {ref.scan_path}"
            )
        points = raw_points.reshape((-1, 4))
        if not np.all(np.isfinite(points)):
            raise ValueError(f"scan contains non-finite XYZI values: {ref.scan_path}")
        raw_labels = np.fromfile(ref.label_path, dtype=np.uint32)
        if raw_labels.shape[0] != points.shape[0]:
            raise ValueError(
                f"scan/label length mismatch for {sequence}/{frame_id}: "
                f"{points.shape[0]} != {raw_labels.shape[0]}"
            )
        timestamp, timestamp_source = self._timestamp(sequence, frame_id)
        pose, pose_source, calibration_source = self._world_pose(
            sequence, frame_id, timestamp
        )
        semantic_class = map_dataset_labels(
            raw_labels & 0xFFFF,
            self.default_label_mapping if label_mapping is None else label_mapping,
        )
        raw_semantic_class = (raw_labels & 0xFFFF).astype(np.int32, copy=False)
        confidence = np.ones(points.shape[0], dtype=np.float32)

        # Crop in the sensor frame. A valid world translation must not make a
        # near return disappear merely because the robot moved away from odom.
        mask = self._range_mask(points, min_range_m, max_range_m)
        world_points = self._transform_points(points[mask], pose.matrix)
        semantic_class = semantic_class[mask]
        raw_semantic_class = raw_semantic_class[mask]
        confidence = confidence[mask]
        count = world_points.shape[0]
        return ObservationFrame(
            timestamp=timestamp,
            pose=pose,
            points=world_points,
            semantic_class=semantic_class,
            semantic_confidence=confidence,
            ground=np.zeros(count, dtype=bool),
            drivable=np.full(count, "unknown", dtype="U16"),
            slope=np.full(count, np.nan, dtype=np.float32),
            roughness=np.full(count, np.nan, dtype=np.float32),
            height_complexity=np.full(count, np.nan, dtype=np.float32),
            motion_probability=np.zeros(count, dtype=np.float32),
            velocity_xy=np.zeros((count, 2), dtype=np.float32),
            raw_semantic_class=raw_semantic_class,
            dataset=self.dataset_name,
            sequence=str(sequence),
            frame_id=str(frame_id),
            provenance=FrameProvenance(
                coordinate_frame=(
                    "world"
                    if pose_source == "dataset"
                    else "calibrated_lidar"
                    if calibration_source == "dataset"
                    else "lidar"
                ),
                timestamp_source=timestamp_source,
                pose_source=pose_source,
                calibration_source=calibration_source,
            ),
        )

    def replay(
        self,
        sequence: str,
        *,
        start: int = 0,
        end: int | None = None,
        stride: int = 1,
        label_mapping: Mapping[int, int] | None = None,
        max_range_m: float | None = None,
        min_range_m: float = 0.0,
    ) -> Iterator[ObservationFrame]:
        if start < 0 or stride <= 0:
            raise ValueError("start must be non-negative and stride must be positive")
        refs = self.list_frames(sequence)
        stop = len(refs) if end is None else min(end, len(refs))
        if stop < start:
            raise ValueError("end must be greater than or equal to start")
        for ref in refs[start:stop:stride]:
            yield self.load_frame(
                sequence,
                ref.frame_id,
                label_mapping=label_mapping,
                max_range_m=max_range_m,
                min_range_m=min_range_m,
            )

    def _timestamp(self, sequence: str, frame_id: str) -> tuple[float | None, str]:
        candidates = tuple(
            path
            for name in self.timestamp_filenames
            for path in (
                self.root / "timestamps" / f"{sequence}.txt",
                self._sequence_root(sequence) / name,
            )
        )
        frame_index = next(
            (
                index
                for index, ref in enumerate(self.list_frames(sequence))
                if ref.frame_id == str(frame_id)
            ),
            None,
        )
        if frame_index is None:
            return None, "absent"
        for path in candidates:
            if path.is_file():
                values = [
                    line.strip()
                    for line in path.read_text().splitlines()
                    if line.strip()
                ]
                if frame_index >= len(values):
                    raise ValueError(
                        f"timestamp file has no value for {sequence}/{frame_id}"
                    )
                try:
                    return float(values[frame_index].split()[0]), "dataset"
                except ValueError as error:
                    raise ValueError(
                        f"invalid timestamp at {path}:{frame_index + 1}"
                    ) from error
        return None, "absent"

    def _world_pose(
        self, sequence: str, frame_id: str, timestamp: float | None
    ) -> tuple[PoseSE3, str, str]:
        pose_path = next(
            (
                path
                for path in (
                    self.root / "poses" / f"{sequence}.txt",
                    self._sequence_root(sequence) / "poses.txt",
                )
                if path.is_file()
            ),
            None,
        )
        pose, has_pose = self._matrix_for_frame(
            pose_path, sequence, frame_id, timestamp
        )
        calibration_path = next(
            (
                path
                for path in (
                    self.root / "calib" / f"{sequence}.txt",
                    self._sequence_root(sequence) / "calib.txt",
                )
                if path.is_file()
            ),
            None,
        )
        calibration, has_calibration = self._calibration_matrix(calibration_path)
        return (
            PoseSE3(pose.matrix @ calibration, timestamp=timestamp),
            "dataset" if has_pose else "identity_absent",
            "dataset" if has_calibration else "identity_absent",
        )

    def _matrix_for_frame(
        self,
        path: Path | None,
        sequence: str,
        frame_id: str,
        timestamp: float | None,
    ) -> tuple[PoseSE3, bool]:
        if path is None:
            return PoseSE3.identity(timestamp), False
        frame_index = next(
            index
            for index, ref in enumerate(self.list_frames(sequence))
            if ref.frame_id == str(frame_id)
        )
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        if frame_index >= len(lines):
            raise ValueError(f"pose file has no value for {sequence}/{frame_id}")
        try:
            values = [
                float(value) for value in lines[frame_index].replace(",", " ").split()
            ]
        except ValueError as error:
            raise ValueError(f"invalid pose at {path}:{frame_index + 1}") from error
        if len(values) != 12:
            raise ValueError(f"pose must contain 12 values: {path}:{frame_index + 1}")
        matrix = np.eye(4, dtype=np.float64)
        matrix[:3] = np.asarray(values, dtype=np.float64).reshape(3, 4)
        return PoseSE3(matrix, timestamp=timestamp), True

    @staticmethod
    def _calibration_matrix(path: Path | None) -> tuple[np.ndarray, bool]:
        if path is None:
            return np.eye(4, dtype=np.float64), False
        for line in path.read_text().splitlines():
            if line.startswith(("Tr:", "Tr_velo_to_cam:")):
                try:
                    values = [float(value) for value in line.split(":", 1)[1].split()]
                except ValueError as error:
                    raise ValueError(
                        f"invalid calibration transform: {path}"
                    ) from error
                if len(values) != 12:
                    raise ValueError(
                        f"calibration transform must contain 12 values: {path}"
                    )
                matrix = np.eye(4, dtype=np.float64)
                matrix[:3] = np.asarray(values).reshape(3, 4)
                return matrix, True
        raise ValueError(f"calibration transform not found: {path}")

    @staticmethod
    def _transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        homogeneous = np.concatenate(
            [points[:, :3].astype(np.float64), np.ones((points.shape[0], 1))], axis=1
        )
        transformed = (matrix @ homogeneous.T).T[:, :3]
        return np.column_stack([transformed, points[:, 3]]).astype(np.float32)

    @staticmethod
    def _range_mask(
        points: np.ndarray, minimum: float, maximum: float | None
    ) -> np.ndarray:
        if minimum < 0 or not np.isfinite(minimum):
            raise ValueError("min_range_m must be finite and non-negative")
        distances = np.linalg.norm(points[:, :2], axis=1)
        mask = distances >= minimum
        if maximum is not None:
            if maximum < minimum or maximum < 0:
                raise ValueError("max_range_m must be non-negative and >= min_range_m")
            mask &= distances <= maximum
        return mask


__all__ = ["FrameRef", "SemanticPOSSDataset"]
