"""Protocol shared by dataset-specific adapters and replay consumers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .observation import ObservationFrame


@dataclass(frozen=True)
class DatasetFrameRef:
    sequence: str
    frame_id: str
    scan_path: Path
    label_path: Path | None


class DatasetAdapter(Protocol):
    def list_sequences(self) -> list[str]: ...

    def list_frames(self, sequence: str) -> list[DatasetFrameRef]: ...

    def load_frame(
        self, sequence: str, frame_id: str, **options: object
    ) -> ObservationFrame: ...

    def replay(
        self, sequence: str, **options: object
    ) -> Iterator[ObservationFrame]: ...


__all__ = ["DatasetAdapter", "DatasetFrameRef"]
