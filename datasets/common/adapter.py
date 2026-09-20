"""Protocol shared by dataset-specific adapters and replay consumers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from .observation import ObservationFrame


@dataclass(frozen=True)
class DatasetFrameRef:
    sequence: str
    frame_id: str
    scan_path: Path
    label_path: Path | None


def reject_orphan_label_files(
    scan_root: Path,
    label_root: Path,
    *,
    scan_suffix: str = ".bin",
    label_suffix: str = ".label",
    require_labels: bool = False,
) -> None:
    """Reject labels that cannot be paired by their frame stem.

    A scan directory is the source of replay identity. An extra label is
    nevertheless an integrity error: silently ignoring it makes a partial or
    incorrectly rooted checkout look valid.
    """
    if not label_root.is_dir():
        return
    scan_ids = {path.stem for path in scan_root.glob(f"*{scan_suffix}")}
    label_ids = {path.stem for path in label_root.glob(f"*{label_suffix}")}
    if require_labels:
        missing = sorted(scan_ids - label_ids)
        if missing:
            raise FileNotFoundError(
                f"label file is missing for frame(s) in {scan_root}: "
                f"{', '.join(missing[:5])}"
            )
    orphaned = sorted(
        path.name
        for path in label_root.glob(f"*{label_suffix}")
        if path.stem not in scan_ids
    )
    if orphaned:
        raise ValueError(
            f"label has no matching scan in {scan_root}: {', '.join(orphaned[:5])}"
        )


def require_complete_binary_records(path: Path, record_size: int, kind: str) -> None:
    """Fail before ``numpy.fromfile`` can silently discard a byte tail."""
    if path.stat().st_size % record_size:
        record_name = "uint32 label" if kind == "label" else kind
        raise ValueError(
            f"{kind} does not contain complete {record_name} records: {path}"
        )


def require_finite_metadata_value(value: float, path: Path, row: int, kind: str) -> float:
    """Reject NaN/Inf metadata at the file boundary with its source row."""
    if not np.isfinite(value):
        raise ValueError(f"invalid {kind} at {path}:{row}: value must be finite")
    return value


class DatasetAdapter(Protocol):
    def list_sequences(self) -> list[str]: ...

    def list_frames(self, sequence: str) -> list[DatasetFrameRef]: ...

    def load_frame(
        self, sequence: str, frame_id: str, **options: object
    ) -> ObservationFrame: ...

    def replay(
        self, sequence: str, **options: object
    ) -> Iterator[ObservationFrame]: ...


__all__ = [
    "DatasetAdapter",
    "DatasetFrameRef",
    "reject_orphan_label_files",
    "require_complete_binary_records",
    "require_finite_metadata_value",
]
