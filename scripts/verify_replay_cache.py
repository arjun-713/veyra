"""Verify a ``*.veyra-replay`` cache: schema, checksums, provenance, ordering."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from runtime.replay_cache import (
    ReplayError,
    ReplayReader,
    check_compatible,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify a Veyra replay cache.")
    parser.add_argument("path")
    parser.add_argument("--policy", default=None)
    parser.add_argument("--config-digest", default=None)
    parser.add_argument(
        "--verify-frames",
        action="store_true",
        help="Checksum every frame payload (slower).",
    )
    args = parser.parse_args(argv)
    try:
        with ReplayReader(args.path, verify=args.verify_frames) as reader:
            header = reader.header
            print(f"Path:     {args.path}")
            print(f"Schema:   replay v{header.get('replay_schema')}")
            print(f"Dataset:  {header.get('dataset')} / {header.get('sequence')}")
            print(
                f"Frames:   {len(reader)} "
                f"(indices {reader.frame_indices[0]}..{reader.frame_indices[-1]})"
            )
            print(f"Policy:   {header.get('policy')}")
            print(f"Provider: {header.get('semantic_provider')}")
            print(
                f"Budgets:  {header.get('point_budget')}pt/"
                f"{header.get('cell_budget')}cell"
            )
            print(
                f"Code:     {str(header.get('code_sha'))[:12]} "
                f"(dirty={header.get('working_tree_dirty')})"
            )
            print(f"Built:    {header.get('created_at')}")
            print(
                f"Disk:     {reader.disk_bytes() / 1e6:.1f} MB  "
                f"Avg:      {reader.avg_frame_bytes() / 1e3:.0f} KB/frame"
            )
            metadata, payload = reader.read_frame(0)
            print(
                f"Frame 0:  schema v{metadata.get('schema_version')} "
                f"points={metadata['points']['count']} "
                f"cells={metadata['cells']['count']} "
                f"payload={len(payload) / 1e3:.0f} KB"
            )
            mismatch = check_compatible(
                header, policy=args.policy, config_digest=args.config_digest
            )
            if mismatch:
                print(f"COMPAT:   MISMATCH — {mismatch}")
                return 2
            print("COMPAT:   OK")
    except ReplayError as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
