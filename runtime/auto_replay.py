"""Build and reuse display-ready replay snapshots for a configured session."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

from .config import config_digest
from .replay_cache import (
    ReplayReader,
    ReplayWriter,
    build_header,
    check_compatible,
    digest_mapping,
)
from .visualization import pack_visualization


def cache_directory() -> Path:
    """Keep generated data outside the installed, read-only app bundle."""
    configured = os.environ.get("VEYRA_REPLAY_CACHE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".cache" / "veyra" / "replays"


def cache_path(config: dict, frames: int, directory: Path | None = None) -> Path:
    key = config_digest(config)
    root = directory if directory is not None else cache_directory()
    return root / f"{config['dataset']}-{frames}-{key[:20]}.veyra-replay"


def ready_cache(path: Path, config: dict, frames: int) -> Path | None:
    try:
        with ReplayReader(path) as reader:
            header = reader.header
            if (
                len(reader) != frames
                or header.get("dataset") != config["dataset"]
                or header.get("sequence") != config["sequence"]
                or header.get("start") != 0
                or header.get("count") != frames
                or check_compatible(
                    header,
                    policy=config["map"]["policy"],
                    config_digest=config_digest(config),
                )
            ):
                return None
            return path
    except (OSError, ValueError):
        return None


def prepare(
    config: dict,
    repo: Path,
    frames: int,
    path: Path,
    progress: Callable[[int, int], None],
    cancelled: Callable[[], bool],
) -> Path:
    """Run the real mapper once per frame, then atomically publish its cache."""
    from .service import ProductRuntime

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}-{threading.get_ident()}.part")
    if temporary.exists():
        temporary.unlink()
    runtime = ProductRuntime(repo)
    writer = None
    try:
        runtime._configure(config)
        if runtime._frame_count() != frames:
            raise RuntimeError("dataset frame count changed during replay preparation")
        provider = {
            "mode": config["pipeline"]["semantic"].get("mode", "ground_truth"),
            "model": config["pipeline"]["semantic"].get("model"),
        }
        point_budget = config["visualization"]["point_budget"]
        cell_budget = config["visualization"]["cell_budget"]
        header = build_header(
            dataset=config["dataset"],
            sequence=config["sequence"],
            start=0,
            count=frames,
            policy=config["map"]["policy"],
            semantic_provider=provider,
            point_budget=point_budget,
            cell_budget=cell_budget,
            perception_config_digest=digest_mapping(config["pipeline"]),
            config_digest=config_digest(config),
            repo=repo,
        )
        writer = ReplayWriter(temporary, header, frames)
        for index in range(frames):
            if cancelled():
                raise RuntimeError("replay preparation cancelled")
            frame = runtime.session.frame_payload(index, budget=point_budget, binary=True)
            if frame["map"].get("status") != "available":
                raise RuntimeError("mapper: " + frame["map"].get("reason", "map unavailable"))
            if frame.get("pipeline_status", {}).get("semantic") == "unavailable":
                raise RuntimeError("semantic provider unavailable during replay preparation")
            cells = runtime.session.map_cells_binary(budget=cell_budget)
            if cells.get("status") != "available":
                raise RuntimeError("mapper: " + cells.get("reason", "map visualization unavailable"))
            metadata, payload = pack_visualization(frame, cells, runtime.generation)
            map_payload = frame.get("map", {})
            snapshot = map_payload.get("snapshot", {})
            metrics = map_payload.get("metrics", {})
            latency_ns = metrics.get("map_update_latency_ns")
            if isinstance(latency_ns, dict):
                latency_ns = latency_ns.get("p50", latency_ns.get("mean"))
            recorded = {
                "recorded_during_cache_build": True,
                "perception_timings_ms": frame.get("perception_timings_ms", {}),
                "map_metrics": metrics,
                "active_cells": snapshot.get("active_leaf_count"),
                "cells_by_level": [
                    (snapshot.get("levels", {}) or {}).get(str(level))
                    for level in range(4)
                ],
                "map_update_ms": latency_ns / 1e6 if isinstance(latency_ns, (int, float)) else None,
                "logical_bytes": metrics.get("logical_map_bytes"),
            }
            writer.add_frame(index, metadata, payload, telemetry=recorded)
            progress(index + 1, frames)
        writer.close()
        writer = None
        if cancelled():
            raise RuntimeError("replay preparation cancelled")
        temporary.replace(path)
        return path
    finally:
        if writer is not None:
            writer._stream.close()
        runtime.close()
        if temporary.exists():
            temporary.unlink()
