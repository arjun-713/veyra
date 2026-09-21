"""SemanticKITTI adapter built on the shared KITTI replay contract."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from datasets.common.adapter import (
    reject_orphan_label_files,
    require_complete_binary_records,
    require_finite_metadata_value,
)
from datasets.common.taxonomy import SEMANTICKITTI_LABELS
from datasets.semanticposs.adapter import SemanticPOSSDataset


class SemanticKITTIDataset(SemanticPOSSDataset):
    """Read SemanticKITTI v1.1 ``sequences/<id>`` scans and metadata.

    The binary point, packed label, pose, calibration and replay rules are the
    same KITTI-style contract used by SemanticPOSS.  SemanticKITTI's published
    timestamp filename is ``times.txt``; ``timestamps.txt`` remains accepted
    for controlled local conversions, but no timestamp is generated when both
    are absent.
    """

    dataset_name = "semantickitti"
    default_label_mapping = SEMANTICKITTI_LABELS
    timestamp_filenames = ("times.txt", "timestamps.txt")
    convert_camera_pose_with_calibration = True

    def list_frames(self, sequence: str):
        was_cached = str(sequence) in self._sequence_cache
        refs = super().list_frames(sequence)
        if was_cached:
            # The base adapter deliberately freezes a discovered sequence;
            # retain that deterministic cache contract for the subclass check.
            return refs
        sequence_root = self._sequence_root(str(sequence))
        reject_orphan_label_files(
            sequence_root / self.scan_dir,
            sequence_root / self.label_dir,
            require_labels=self.require_labels,
        )
        return refs

    def load_frame(self, sequence: str, frame_id: str, **options: object):
        refs = {ref.frame_id: ref for ref in self.list_frames(sequence)}
        ref = refs.get(str(frame_id))
        if ref is not None and ref.label_path is not None:
            require_complete_binary_records(
                Path(ref.label_path), np.dtype(np.uint32).itemsize, "label"
            )
        return super().load_frame(sequence, frame_id, **options)

    def _timestamp(self, sequence: str, frame_id: str):
        value, source = super()._timestamp(sequence, frame_id)
        if value is not None:
            path = self._sequence_root(str(sequence)) / self.timestamp_filenames[0]
            if not path.is_file():
                path = self.root / "timestamps" / f"{sequence}.txt"
            value = require_finite_metadata_value(value, path, 1, "timestamp")
        return value, source


__all__ = ["SemanticKITTIDataset"]
