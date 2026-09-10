"""RELLIS-3D KITTI-style scans and SemanticKITTI-compatible labels."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, Mapping
from pathlib import Path

import numpy as np

from datasets.common.adapter import DatasetFrameRef
from datasets.common.observation import FrameProvenance, ObservationFrame, PoseSE3
from datasets.common.taxonomy import RELLIS_LABELS, map_dataset_labels

FrameRef = DatasetFrameRef


class Rellis3DDataset:
    """Read the original local RELLIS-3D repository layout.

    The adapter intentionally receives the already-resolved local dataset root;
    it never downloads, discovers, or writes dataset assets. A RELLIS sequence
    contains ``.bin`` scans in ``vel_cloud_node_kitti_bin`` and labels in
    ``vel_cloud_node_semantickitti_label_id``.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        sequences: list[str] | None = None,
        scan_dir: str = "vel_cloud_node_kitti_bin",
        label_dir: str = "vel_cloud_node_semantickitti_label_id",
        max_cached_sequences: int = 8,
        metadata_root: str | Path | None = None,
    ) -> None:
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"RELLIS-3D root does not exist: {self.root}")
        self._sequences = (
            [str(sequence) for sequence in sequences] if sequences else None
        )
        self.scan_dir = scan_dir
        self.label_dir = label_dir
        self.metadata_root = Path(metadata_root) if metadata_root is not None else self.root
        if max_cached_sequences <= 0:
            raise ValueError("max_cached_sequences must be positive")
        self.max_cached_sequences = max_cached_sequences
        self._sequence_cache: OrderedDict[str, list[FrameRef]] = OrderedDict()
        self._metadata_cache: OrderedDict[str, dict[str, object]] = OrderedDict()

    def list_sequences(self) -> list[str]:
        if self._sequences is not None:
            return list(self._sequences)
        return sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_dir() and path.name.isdigit()
        )

    def _sequence_root(self, sequence: str) -> Path:
        return self.root / str(sequence)

    def list_frames(self, sequence: str) -> list[FrameRef]:
        sequence = str(sequence)
        cached = self._sequence_cache.get(sequence)
        if cached is not None:
            self._sequence_cache.move_to_end(sequence)
            return cached
        scan_root = self._sequence_root(sequence) / self.scan_dir
        if not scan_root.is_dir():
            raise FileNotFoundError(f"scan directory does not exist: {scan_root}")
        label_root = self._sequence_root(sequence) / self.label_dir
        scans = sorted(
            scan_root.glob("*.bin"), key=lambda path: self._frame_sort_key(path.stem)
        )
        refs = [
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
        self._sequence_cache[sequence] = refs
        self._sequence_cache.move_to_end(sequence)
        self._trim_caches()
        return refs

    def _trim_caches(self) -> None:
        while len(self._sequence_cache) > self.max_cached_sequences:
            sequence, _ = self._sequence_cache.popitem(last=False)
            self._metadata_cache.pop(sequence, None)

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
            raise FileNotFoundError(
                f"label file is missing for {sequence}/{frame_id} in {self.label_dir}"
            )

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
            RELLIS_LABELS if label_mapping is None else label_mapping,
        )
        raw_semantic_class = (raw_labels & 0xFFFF).astype(np.int32, copy=False)
        confidence = np.where(semantic_class == 0, 0.0, 1.0).astype(np.float32)

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
            dataset="rellis3d",
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
        path = self._metadata_path(sequence, "timestamps", "timestamps.txt")
        if path is None:
            return None, "absent"
        index = self._frame_index(sequence, frame_id)
        lines = self._cached_lines(self._metadata(sequence), path)
        self._require_metadata_alignment(sequence, path, lines, "timestamp")
        if index >= len(lines):
            raise ValueError(f"timestamp file has no value for {sequence}/{frame_id}")
        try:
            return float(lines[index].split()[0]), "dataset"
        except ValueError as error:
            raise ValueError(f"invalid timestamp at {path}:{index + 1}") from error

    def _world_pose(
        self, sequence: str, frame_id: str, timestamp: float | None
    ) -> tuple[PoseSE3, str, str]:
        pose_path = self._metadata_path(sequence, "poses", "poses.txt")
        pose, has_pose = self._matrix_for_frame(
            pose_path, sequence, frame_id, timestamp
        )
        calibration_path = self._metadata_path(sequence, "calib", "calib.txt")
        _, has_calibration = self._calibration_matrix(
            calibration_path, self._metadata(sequence)
        )
        # RELLIS documents this calibration as Velodyne-versus-camera for
        # projection. It is not documented as a LiDAR-to-world transform, so
        # validate and record it without composing it into the world pose.
        return (
            PoseSE3(pose.matrix, timestamp=timestamp),
            "dataset" if has_pose else "identity_absent",
            "dataset" if has_calibration else "identity_absent",
        )

    def _metadata_path(
        self, sequence: str, root_name: str, sequence_name: str
    ) -> Path | None:
        candidates = (
            self.metadata_root / root_name / f"{sequence}.txt",
            self.metadata_root / str(sequence) / sequence_name,
            self.metadata_root / sequence_name,
        )
        return next((path for path in candidates if path.is_file()), None)

    def _frame_index(self, sequence: str, frame_id: str) -> int:
        for index, ref in enumerate(self.list_frames(sequence)):
            if ref.frame_id == str(frame_id):
                return index
        raise FileNotFoundError(f"frame {sequence}/{frame_id} does not exist")

    def _matrix_for_frame(
        self,
        path: Path | None,
        sequence: str,
        frame_id: str,
        timestamp: float | None,
    ) -> tuple[PoseSE3, bool]:
        if path is None:
            return PoseSE3.identity(timestamp), False
        index = self._frame_index(sequence, frame_id)
        lines = self._cached_lines(self._metadata(sequence), path)
        self._require_metadata_alignment(sequence, path, lines, "pose")
        if index >= len(lines):
            raise ValueError(f"pose file has no value for {sequence}/{frame_id}")
        try:
            values = [float(value) for value in lines[index].replace(",", " ").split()]
        except ValueError as error:
            raise ValueError(f"invalid pose at {path}:{index + 1}") from error
        if len(values) != 12:
            raise ValueError(f"pose must contain 12 values: {path}:{index + 1}")
        matrix = np.eye(4, dtype=np.float64)
        matrix[:3] = np.asarray(values, dtype=np.float64).reshape(3, 4)
        return PoseSE3(matrix, timestamp=timestamp), True

    @staticmethod
    def _calibration_matrix(
        path: Path | None, metadata: dict[str, object]
    ) -> tuple[np.ndarray, bool]:
        if path is None:
            return np.eye(4, dtype=np.float64), False
        lines = Rellis3DDataset._cached_lines(metadata, path)
        for line in lines:
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
                matrix[:3] = np.asarray(values, dtype=np.float64).reshape(3, 4)
                try:
                    PoseSE3(matrix)
                except ValueError as error:
                    raise ValueError(
                        f"calibration transform is not a rigid SE(3) matrix: {path}"
                    ) from error
                return matrix, True
        raise ValueError(f"calibration transform not found: {path}")

    def _metadata(self, sequence: str) -> dict[str, object]:
        sequence = str(sequence)
        metadata = self._metadata_cache.get(sequence)
        if metadata is None:
            metadata = {}
            self._metadata_cache[sequence] = metadata
            self._metadata_cache.move_to_end(sequence)
            self._trim_caches()
        return metadata

    def _require_metadata_alignment(
        self, sequence: str, path: Path, lines: list[str], kind: str
    ) -> None:
        frame_count = len(self.list_frames(sequence))
        if len(lines) != frame_count:
            raise ValueError(
                f"{kind} metadata cannot be aligned by frame order for {sequence}: "
                f"{path} has {len(lines)} rows for {frame_count} scans"
            )

    @staticmethod
    def _nonempty_lines(path: Path) -> list[str]:
        return [line.strip() for line in path.read_text().splitlines() if line.strip()]

    @classmethod
    def _cached_lines(cls, metadata: dict[str, object], path: Path) -> list[str]:
        key = str(path)
        if key not in metadata:
            metadata[key] = cls._nonempty_lines(path)
        return metadata[key]  # type: ignore[return-value]

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
        if maximum is not None and (maximum < minimum or maximum < 0):
            raise ValueError("max_range_m must be non-negative and >= min_range_m")
        distances = np.linalg.norm(points[:, :2], axis=1)
        mask = distances >= minimum
        if maximum is not None:
            mask &= distances <= maximum
        return mask


__all__ = ["FrameRef", "Rellis3DDataset"]
