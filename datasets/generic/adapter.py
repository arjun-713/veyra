"""Strict, dataset-neutral replay from an explicit JSON manifest.

The manifest is an interchange contract, not an autodetector. Dataset-specific
conversion (taxonomy, pose direction, timestamps and intensity semantics) must
be declared by the producer before data enters Veyra.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path

import numpy as np

from datasets.common.adapter import DatasetFrameRef
from datasets.common.observation import FrameProvenance, ObservationFrame, PoseSE3


class ManifestDataset:
    """Load XYZI frames described by a versioned, explicit manifest."""

    def __init__(
        self, root: str | Path, manifest: str | Path = "manifest.json"
    ) -> None:
        self.root = Path(root).resolve()
        manifest_path = Path(manifest)
        if not manifest_path.is_absolute():
            manifest_path = self.root / manifest_path
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError("manifest schema_version must be 1")
        if not isinstance(data.get("dataset"), str) or not data["dataset"]:
            raise ValueError("manifest dataset must be a non-empty string")
        point_schema = data.get("point_schema")
        if not isinstance(point_schema, dict) or point_schema.get("format") != "xyzi":
            raise ValueError("manifest point_schema.format must be xyzi")
        if point_schema.get("coordinate_frame") != "sensor":
            raise ValueError("manifest point_schema.coordinate_frame must be sensor")
        if not isinstance(point_schema.get("intensity_semantics"), str):
            raise ValueError("manifest must declare intensity_semantics")
        taxonomy = data.get("taxonomy")
        if not isinstance(taxonomy, dict) or not isinstance(
            taxonomy.get("version"), str
        ):
            raise ValueError("manifest must declare taxonomy.version")
        mapping = taxonomy.get("mapping")
        if not isinstance(mapping, dict):
            raise ValueError("manifest taxonomy.mapping must be an object")
        self._mapping = self._parse_mapping(mapping)
        frames = data.get("frames")
        if not isinstance(frames, list) or not frames:
            raise ValueError("manifest frames must be a non-empty list")
        self.dataset_name = data["dataset"]
        self.taxonomy_version = taxonomy["version"]
        self._frames: dict[tuple[str, str], dict[str, object]] = {}
        for item in frames:
            if not isinstance(item, dict):
                raise ValueError("manifest frame entries must be objects")
            sequence, frame_id = item.get("sequence"), item.get("frame_id")
            if (
                not isinstance(sequence, str)
                or not sequence
                or not isinstance(frame_id, str)
                or not frame_id
            ):
                raise ValueError("each frame needs non-empty sequence and frame_id")
            key = (sequence, frame_id)
            if key in self._frames:
                raise ValueError(f"duplicate manifest frame: {sequence}/{frame_id}")
            point_spec = item.get("points")
            if not isinstance(point_spec, dict) or point_spec.get("format") not in {
                "xyzi_f32_bin",
                "xyzi_f32_npy",
            }:
                raise ValueError("points format must be xyzi_f32_bin or xyzi_f32_npy")
            self._safe_path(point_spec.get("path"))
            label_spec = item.get("labels")
            if label_spec is not None:
                if not isinstance(label_spec, dict) or label_spec.get("format") not in {
                    "uint32_label",
                    "integer_npy",
                }:
                    raise ValueError("labels format is unsupported")
                self._safe_path(label_spec.get("path"))
            self._validate_optional_metadata(item)
            self._frames[key] = item
        self._by_sequence = {
            sequence: sorted(
                (item for (seq, _), item in self._frames.items() if seq == sequence),
                key=lambda item: self._frame_key(str(item["frame_id"])),
            )
            for sequence in sorted({seq for seq, _ in self._frames})
        }

    @staticmethod
    def _parse_mapping(mapping: Mapping[object, object]) -> dict[int, int]:
        parsed: dict[int, int] = {}
        for raw, target in mapping.items():
            try:
                raw_i, target_i = int(raw), int(target)
            except (TypeError, ValueError) as exc:
                raise ValueError("taxonomy mapping IDs must be integers") from exc
            if raw_i < 0 or target_i < 0 or target_i > 19:
                raise ValueError(
                    "taxonomy IDs must be non-negative and target IDs <= 19"
                )
            if str(raw_i) != str(raw) and not isinstance(raw, int):
                raise ValueError("taxonomy mapping raw IDs must be integer strings")
            parsed[raw_i] = target_i
        return parsed

    def _safe_path(self, value: object) -> Path:
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            raise ValueError("manifest data paths must be relative")
        path = (self.root / value).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("manifest data path escapes dataset root")
        return path

    @staticmethod
    def _frame_key(frame_id: str) -> tuple[int, int | str]:
        try:
            return (0, int(frame_id))
        except ValueError:
            return (1, frame_id)

    @staticmethod
    def _validate_optional_metadata(item: Mapping[str, object]) -> None:
        if "timestamp_s" in item:
            timestamp = item["timestamp_s"]
            if (
                isinstance(timestamp, bool)
                or not isinstance(timestamp, (int, float))
                or not np.isfinite(timestamp)
            ):
                raise ValueError("timestamp_s must be finite seconds")
        if "pose_sensor_to_world" in item:
            matrix = np.asarray(item["pose_sensor_to_world"], dtype=np.float64)
            PoseSE3(matrix)

    def list_sequences(self) -> list[str]:
        return list(self._by_sequence)

    def list_frames(self, sequence: str) -> list[DatasetFrameRef]:
        return [
            DatasetFrameRef(
                sequence=sequence,
                frame_id=str(item["frame_id"]),
                scan_path=self._safe_path(item["points"]["path"]),
                label_path=(
                    self._safe_path(item["labels"]["path"])
                    if item.get("labels")
                    else None
                ),
            )
            for item in self._by_sequence.get(str(sequence), [])
        ]

    def _read_points(self, spec: Mapping[str, object]) -> np.ndarray:
        path = self._safe_path(spec["path"])
        if spec["format"] == "xyzi_f32_bin":
            raw = np.fromfile(path, dtype="<f4")
            if raw.size == 0 or raw.size % 4:
                raise ValueError("binary XYZI file is not divisible into four floats")
            points = raw.reshape(-1, 4)
        else:
            points = np.load(path, allow_pickle=False)
            if points.dtype != np.float32:
                points = points.astype(np.float32)
        if points.ndim != 2 or points.shape[1] != 4 or not np.isfinite(points).all():
            raise ValueError("points must be finite XYZI with shape (N, 4)")
        return np.asarray(points, dtype=np.float32)

    def _read_labels(self, spec: Mapping[str, object], count: int) -> np.ndarray:
        path = self._safe_path(spec["path"])
        labels = (
            np.fromfile(path, dtype="<u4")
            if spec["format"] == "uint32_label"
            else np.load(path, allow_pickle=False)
        )
        labels = np.asarray(labels).reshape(-1)
        if (
            labels.shape != (count,)
            or labels.dtype.kind not in "iu"
            or np.any(labels < 0)
        ):
            raise ValueError("labels must contain one non-negative integer per point")
        # SemanticKITTI-style uint32 labels pack instance bits above the low
        # 16-bit semantic ID. The manifest's uint32_label format explicitly
        # declares that convention; integer_npy is already semantic-only.
        if spec["format"] == "uint32_label":
            labels = labels.astype(np.uint64, copy=False) & np.uint64(0xFFFF)
        return labels.astype(np.int64, copy=False)

    def load_frame(
        self,
        sequence: str,
        frame_id: str,
        *,
        max_range_m: float | None = None,
        min_range_m: float = 0.0,
    ) -> ObservationFrame:
        item = self._frames.get((str(sequence), str(frame_id)))
        if item is None:
            raise KeyError(f"unknown manifest frame: {sequence}/{frame_id}")
        if max_range_m is not None and (
            not np.isfinite(max_range_m) or max_range_m < 0
        ):
            raise ValueError("max_range_m must be finite and non-negative")
        if (
            not np.isfinite(min_range_m)
            or min_range_m < 0
            or (max_range_m is not None and min_range_m > max_range_m)
        ):
            raise ValueError("invalid range bounds")
        points = self._read_points(item["points"])
        labels = np.zeros(len(points), dtype=np.int64)
        if item.get("labels") is not None:
            labels = self._read_labels(item["labels"], len(points))
        keep = np.linalg.norm(points[:, :3], axis=1) >= min_range_m
        if max_range_m is not None:
            keep &= np.linalg.norm(points[:, :3], axis=1) <= max_range_m
        points, labels = points[keep], labels[keep]
        raw_labels = labels.astype(np.int32, copy=False)
        classes = np.asarray(
            [self._mapping.get(int(label), 0) for label in labels], dtype=np.int32
        )
        confidence = (classes != 0).astype(np.float32)
        timestamp = item.get("timestamp_s")
        if "pose_sensor_to_world" in item:
            pose = PoseSE3(
                np.asarray(item["pose_sensor_to_world"], dtype=np.float64),
                timestamp=timestamp,
            )
            points = points.copy()
            points[:, :3] = points[:, :3] @ pose.matrix[:3, :3].T + pose.matrix[:3, 3]
            provenance = FrameProvenance(
                coordinate_frame="world",
                timestamp_source="dataset" if timestamp is not None else "absent",
                pose_source="dataset",
                calibration_source="identity_absent",
            )
        else:
            pose = PoseSE3.identity(timestamp)
            provenance = FrameProvenance(
                coordinate_frame="lidar",
                timestamp_source="dataset" if timestamp is not None else "absent",
                pose_source="identity_absent",
                calibration_source="identity_absent",
            )
        unknown = np.full(len(points), "unknown")
        nan = np.full(len(points), np.nan, dtype=np.float32)
        return ObservationFrame(
            timestamp=timestamp,
            pose=pose,
            points=points,
            semantic_class=classes,
            semantic_confidence=confidence,
            ground=np.zeros(len(points), bool),
            drivable=unknown,
            slope=nan,
            roughness=nan,
            height_complexity=nan,
            motion_probability=np.zeros(len(points), np.float32),
            velocity_xy=np.zeros((len(points), 2), np.float32),
            dataset=self.dataset_name,
            sequence=str(sequence),
            frame_id=str(frame_id),
            raw_semantic_class=raw_labels,
            provenance=provenance,
        )

    def replay(
        self,
        sequence: str,
        *,
        start: int = 0,
        end: int | None = None,
        stride: int = 1,
        **options: object,
    ) -> Iterator[ObservationFrame]:
        items = self._by_sequence.get(str(sequence), [])
        if start < 0 or stride <= 0 or end is not None and end < start:
            raise ValueError("invalid replay bounds")
        for item in items[start:end:stride]:
            yield self.load_frame(str(sequence), str(item["frame_id"]), **options)
