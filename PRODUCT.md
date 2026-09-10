# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

delegated: Python (stdlib + numpy + pyyaml) local server + static Three.js front-end (vendored, pinned, no CDN), no build step. Chosen because AGENTS.md assigns plotting/evaluation tooling to Python, CI already pins Python, the team needs to read real multi-GB KITTI `.bin` files the browser cannot parse, and a zero-dependency front-end keeps every dev machine identical.

## Users

The three Veyra developers (Mallik — perception, Samay — mapping, Vinay — adaptive) on their local machines, while building dataset adapters and 2.5D map code. They open the visualizer to confirm a scan/label pair looks right before trusting it downstream.

## Product Purpose

Let a developer scrub through real RELLIS-3D and SemanticPOSS sequences in 3D — with semantic coloring and per-frame stats — so bad pairings, corrupt frames, and taxonomy mistakes surface in seconds instead of inside map-fusion debug sessions. Success is catching a dataset problem before it becomes a mapping bug.

## Positioning

The only viewer that reads this repo's own `configs/datasets.yaml` and `data/raw/` layout directly, serving the exact bytes the future adapters will consume — not re-exports, samples, or mock point clouds.

## Operating Context

Runs from the repo root (`python3 viewer/server.py`), serves repo-relative paths only, reads local-only `data/` that is never committed. Browser + server on the same machine; must work fully offline (vendored Three.js). Viz latency is kept separate from map-update latency per project architecture.

## Capabilities and Constraints

- Reads KITTI-format `.bin` (x, y, z, intensity float32) and uint32 `.label` (low 16 bits semantic class) for both datasets.
- Server decimates frames to a point budget before sending; browser renders, never parses raw files.
- SemanticPOSS taxonomy + palette transcribed from the dataset authors' `read_data.py` (`LABEL_DICT`, `SEM_COLOR`); RELLIS-3D classes colored by deterministic id palette until an authoritative mapping lands in `datasets/rellis/`.
- Day-one views: 3D orbit, semantic/elevation color toggle, dataset + sequence + frame scrubber with keyboard stepping, per-frame point count and class histogram.
- Undecided: range-image/tag views, ROS2 live mode, hosted sharing.
- Out of scope: map rendering, training, SLAM, planning (per project scope boundaries).

## Evidence on Hand

- Real data: `data/raw/rellis3d/Rellis-3D/{00000..00004}/` (13,532 scans + 13,532 labels), `data/raw/semanticposs/dataset/sequences/{00..05}/` (2,988 + 2,988). Present locally, never committed.
- Authoritative SemanticPOSS label names + colors: `data/raw/semanticposs/dataset/read_data.py` (local-only file; constants transcribed into viewer code as metadata).
- No product imagery, testimonials, or benchmarks exist; future work must not fabricate dataset statistics.

## Product Principles

1. Real files only — every pixel traces to a byte in `data/raw/`; no mock clouds, no invented histograms.
2. The repo is the config — paths and sequence lists come from `configs/datasets.yaml`, never absolute paths or copies.
3. Thin browser, Python does I/O — parsing and decimation live server-side where numpy exists.
4. Offline and identical everywhere — vendored assets, pinned versions, runnable from a clean checkout plus `data/`.
