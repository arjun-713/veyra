"""SemanticKITTI adapter built on the shared KITTI replay contract."""

from __future__ import annotations

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


__all__ = ["SemanticKITTIDataset"]
