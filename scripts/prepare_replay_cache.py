"""Prepare a precomputed visualization replay cache from a real dataset.

Real Veyra processing runs once per frame (perception + C++ mapper +
``pack_visualization``); the resulting visualization snapshots are stored in
a ``*.veyra-replay`` file under ``data/cache/replays/`` (git-ignored).
Smooth replay then serves those bytes with no neural inference, ground
segmentation, terrain processing or mapping per visible frame.

Example::

    python3 scripts/prepare_replay_cache.py \\
        --dataset semanticposs --sequence 00 --start 0 --count 488 \\
        --policy utility_lod --preset Quality

The preparation step may take a long time (it runs the full live pipeline);
that cost is paid once, before the demo, never during playback.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from runtime.config import PRESETS, config_digest, validate_config
from runtime.replay_cache import (
    ReplayWriter,
    build_header,
    default_cache_path,
    digest_mapping,
)
from runtime.service import ProductRuntime
from runtime.visualization import pack_visualization


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Build a *.veyra-replay cache from real Veyra processing."
    )
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--dataset", default="semanticposs")
    parser.add_argument(
        "--dataset-root",
        default=None,
        help="Explicit dataset root (defaults to configs/datasets.yaml).",
    )
    parser.add_argument("--sequence", default="00")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=488)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument(
        "--policy", default=None, help="Map policy (defaults to the preset policy)."
    )
    parser.add_argument(
        "--preset",
        default="Quality",
        choices=sorted(PRESETS),
        help="Visualization budgets come from this preset.",
    )
    parser.add_argument("--point-budget", type=int, default=None)
    parser.add_argument("--cell-budget", type=int, default=None)
    parser.add_argument("--semantic-mode", default="ground_truth")
    parser.add_argument("--perception-config", default=None)
    parser.add_argument(
        "--output",
        default=None,
        help="Explicit output path (defaults to data/cache/replays/).",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def resolve_dataset_root(repo: Path, dataset: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    import yaml

    with open(repo / "configs" / "datasets.yaml") as stream:
        settings = yaml.safe_load(stream)
    return str(repo / settings[dataset]["root"])


def main(argv=None) -> int:
    args = parse_args(argv)
    repo = Path(args.repo).resolve()
    root = resolve_dataset_root(repo, args.dataset, args.dataset_root)
    preset = PRESETS[args.preset]
    point_budget = args.point_budget or preset["visualization"]["point_budget"]
    cell_budget = args.cell_budget or preset["visualization"]["cell_budget"]
    policy = args.policy or preset["map"].get("policy", "distance_lod")

    perception_overrides: dict = {"semantic": {"mode": args.semantic_mode}}
    if args.perception_config:
        perception_overrides = json.loads(Path(args.perception_config).read_text())

    config = validate_config(
        {
            "dataset": args.dataset,
            "dataset_root": root,
            "sequence": args.sequence,
            "preset": args.preset,
            "pipeline": perception_overrides,
            "map": {"policy": policy},
            "playback": {"full_sequence": True},
            "visualization": {
                "point_budget": point_budget,
                "cell_budget": cell_budget,
            },
        },
        repo,
    )

    runtime = ProductRuntime(repo)
    try:
        runtime._configure(config)
    except Exception as error:  # noqa: BLE001 - CLI boundary reports build failure.
        print(f"failed to configure live session: {error}", file=sys.stderr)
        return 1
    total_frames = runtime.session.status()["frames"]
    indices = list(
        range(
            args.start,
            min(total_frames, args.start + args.count * args.stride),
            args.stride,
        )
    )
    if not indices:
        print("no frames selected", file=sys.stderr)
        return 1

    provider = {
        "mode": config["pipeline"]["semantic"].get("mode", "ground_truth"),
        "model": config["pipeline"]["semantic"].get("model"),
    }
    header = build_header(
        dataset=args.dataset,
        sequence=args.sequence,
        start=indices[0],
        count=len(indices),
        stride=args.stride,
        policy=config["map"]["policy"],
        semantic_provider=provider,
        point_budget=point_budget,
        cell_budget=cell_budget,
        perception_config_digest=digest_mapping(config["pipeline"]),
        config_digest=config_digest(config),
        repo=repo,
    )
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = repo / default_cache_path(
            dataset=args.dataset,
            sequence=args.sequence,
            start=indices[0],
            count=len(indices),
            policy=config["map"]["policy"],
            provider=provider["mode"],
            point_budget=point_budget,
            cell_budget=cell_budget,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not args.overwrite:
        print(f"cache exists (use --overwrite): {out_path}", file=sys.stderr)
        return 1

    writer = ReplayWriter(out_path, header, len(indices))
    started = time.monotonic()
    try:
        for position, target in enumerate(indices):
            frame = runtime.session.frame_payload(
                target, budget=point_budget, binary=True
            )
            if frame["map"].get("status") != "available":
                raise RuntimeError(
                    "mapper: " + frame["map"].get("reason", "map unavailable")
                )
            cells = runtime.session.map_cells_binary(budget=cell_budget)
            if cells.get("status") != "available":
                raise RuntimeError(
                    "mapper: " + cells.get("reason", "map visualization unavailable")
                )
            metadata, payload = pack_visualization(frame, cells, runtime.generation)
            # Display-ready recorded measurements for replay UI. Every value
            # was measured while building this cache and must be labeled
            # RECORDED at display time — never current live processing.
            # Rates the builder cannot measure honestly (processing FPS,
            # splits/s, merges/s) are omitted so replay shows N/A instead.
            map_payload = frame.get("map", {})
            snapshot = map_payload.get("snapshot", {})
            viewer_metrics = map_payload.get("metrics", {})
            latency_ns = viewer_metrics.get("map_update_latency_ns")
            # Viewer metrics carry a summary dict; p50 matches the live
            # "Map update" display semantics (labeled RECORDED at replay).
            if isinstance(latency_ns, dict):
                latency_ns = latency_ns.get("p50", latency_ns.get("mean"))
            recorded = {
                "recorded_during_cache_build": True,
                "perception_timings_ms": frame.get("perception_timings_ms", {}),
                "map_metrics": viewer_metrics,
                "active_cells": snapshot.get("active_leaf_count"),
                "cells_by_level": [
                    (snapshot.get("levels", {}) or {}).get(str(level))
                    for level in range(4)
                ],
                "map_update_ms": (
                    latency_ns / 1e6 if isinstance(latency_ns, (int, float)) else None
                ),
                "logical_bytes": viewer_metrics.get("logical_map_bytes"),
            }
            writer.add_frame(target, metadata, payload, telemetry=recorded)
            elapsed = time.monotonic() - started
            rate = (position + 1) / max(elapsed, 1e-6)
            remaining = (len(indices) - position - 1) / max(rate, 1e-6)
            print(
                f"Preparing smooth replay… {position + 1} / {len(indices)} "
                f"(frame {target}, ~{remaining:.0f}s remaining)",
                flush=True,
            )
    except Exception as error:  # noqa: BLE001 - CLI boundary reports build failure.
        print(f"cache build failed: {error}", file=sys.stderr)
        return 1
    finally:
        runtime.close()
    summary = writer.close()
    print(f"Replay ready: {summary['path']}")
    print(
        f"Frames: {summary['frames']}  "
        f"Disk: {summary['bytes'] / 1e6:.1f} MB  "
        f"Avg: {summary['avg_frame_bytes'] / 1e3:.0f} KB/frame"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
