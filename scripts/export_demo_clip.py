"""Offline demo capture fallback: real cached snapshots -> PNG frames -> MP4.

Renders each ``*.veyra-replay`` frame deterministically to image frames
(``frame_000001.ppm`` …) with numpy only, then encodes a 30 FPS H.264 clip
with ffmpeg. Every drawn point/cell comes from the real cached payloads —
no intermediate point clouds are fabricated. The camera view is fixed for
the whole clip (global bounds) unless ``--follow`` selects a discrete
ego-following window that steps only on real presented poses.

Example::

    python3 scripts/export_demo_clip.py --replay data/cache/replays/foo.veyra-replay \\
        --out demo/ --width 1920 --height 1080 --fps 30
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from runtime.replay_cache import ReplayReader

# Viewer semantic palette (approximate sRGB, class id -> RGB). Same ordering
# as apps/desktop/src/renderer/colors.ts; unknown stays grey.
PALETTE = np.array(
    [
        [89, 102, 115],
        [242, 77, 97],
        [245, 171, 36],
        [245, 171, 36],
        [242, 77, 97],
        [242, 77, 97],
        [163, 87, 237],
        [163, 87, 237],
        [163, 87, 237],
        [56, 140, 250],
        [112, 135, 207],
        [143, 169, 212],
        [184, 148, 110],
        [122, 138, 158],
        [163, 161, 181],
        [56, 179, 77],
        [122, 153, 79],
        [97, 173, 87],
        [245, 171, 36],
        [230, 184, 87],
    ],
    dtype=np.uint8,
)


def decode_points(payload: bytes, meta: dict) -> np.ndarray:
    """Return (N,17) float32 point rows from a cached payload."""
    section = meta["points"]
    count, offset, stride = section["count"], section["offset"], section["stride"]
    assert stride == 68, "unexpected point stride"
    raw = (
        np.frombuffer(payload, dtype="<f4", count=count * 17, offset=offset)
        .reshape(count, 17)
        .copy()
    )
    return raw


def decode_cells(payload: bytes, meta: dict) -> np.ndarray | None:
    section = meta["cells"]
    count, offset, stride = section["count"], section["offset"], section["stride"]
    floats = stride // 4
    if count == 0:
        return None
    return (
        np.frombuffer(payload, dtype="<f4", count=count * floats, offset=offset)
        .reshape(count, floats)
        .copy()
    )


def rasterize(
    points: np.ndarray,
    cells: np.ndarray | None,
    pose,
    *,
    width: int,
    height: int,
    bounds: tuple[float, float, float, float],
    layer: str = "semantic",
) -> np.ndarray:
    """Top-down projection. Points are real cached rows; nothing is invented."""
    xmin, xmax, ymin, ymax = bounds
    img = np.full((height, width, 3), 11, dtype=np.uint8)
    img[:, :] = (11, 18, 25)
    if cells is not None and len(cells):
        stride = cells.shape[1]
        cx, cy = cells[:, 0], cells[:, 1]
        size = cells[:, 3] if stride > 3 else np.full(len(cells), 0.4)
        px = ((cx - xmin) / max(xmax - xmin, 1e-6) * (width - 1)).astype(int)
        py = ((ymax - cy) / max(ymax - ymin, 1e-6) * (height - 1)).astype(int)
        half = np.maximum(
            1, (size / max(xmax - xmin, ymax - ymin, 1e-6) * width / 2).astype(int)
        )
        valid = (px >= 0) & (px < width) & (py >= 0) & (py < height)
        for x, y, h in zip(px[valid], py[valid], half[valid]):
            x0, x1 = max(0, x - h), min(width, x + h + 1)
            y0, y1 = max(0, y - h), min(height, y + h + 1)
            img[y0:y1, x0:x1] = (38, 74, 94)
    if len(points):
        x, y = points[:, 0], points[:, 1]
        px = ((x - xmin) / max(xmax - xmin, 1e-6) * (width - 1)).astype(int)
        py = ((ymax - y) / max(ymax - ymin, 1e-6) * (height - 1)).astype(int)
        valid = (px >= 0) & (px < width) & (py >= 0) & (py < height)
        if layer == "elevation":
            z = np.clip((points[valid, 2] + 3) / 8, 0, 1)
            col = (
                np.stack([51 + 191 * z, 204 - 89 * z, 242 - 179 * z]).astype(np.uint8).T
            )
        else:
            ids = np.clip(points[valid, 4].astype(int), 0, len(PALETTE) - 1)
            col = PALETTE[ids]
        img[py[valid], px[valid]] = col
    if pose is not None and len(pose) == 16:
        ex = int((pose[3] - xmin) / max(xmax - xmin, 1e-6) * (width - 1))
        ey = int((ymax - pose[7]) / max(ymax - ymin, 1e-6) * (height - 1))
        if 0 <= ex < width and 0 <= ey < height:
            y0, y1 = max(0, ey - 5), min(height, ey + 6)
            x0, x1 = max(0, ex - 5), min(width, ex + 6)
            img[y0:y1, x0:x1] = (255, 255, 255)
    return img


def write_ppm(path: Path, img: np.ndarray) -> None:
    height, width, _ = img.shape
    with open(path, "wb") as stream:
        stream.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
        stream.write(np.ascontiguousarray(img).tobytes())


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Export a replay cache to an MP4 demo clip."
    )
    parser.add_argument("--replay", required=True)
    parser.add_argument("--out", default="demo")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30, choices=(15, 30, 60))
    parser.add_argument(
        "--layer", default="semantic", choices=("semantic", "elevation")
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Ego-following window stepping on real poses.",
    )
    parser.add_argument("--window-m", type=float, default=120.0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--skip-encode", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out)
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    with ReplayReader(args.replay) as reader:
        total = len(reader)
        start = max(0, args.start)
        count = args.count or (total - start)
        positions = list(range(start, min(total, start + count)))
        if not positions:
            print("no frames selected", file=sys.stderr)
            return 1
        header = reader.header
        print(
            f"Exporting {len(positions)} cached frames "
            f"({header.get('dataset')}/{header.get('sequence')}, "
            f"policy {header.get('policy')})"
        )
        # Pass 1: global bounds (fixed camera for the whole clip).
        if args.follow:
            bounds = None
        else:
            gmin = np.full(2, np.inf)
            gmax = np.full(2, -np.inf)
            for position in positions:
                meta, payload = reader.read_frame(position)
                pts = decode_points(payload, meta)
                if len(pts):
                    gmin = np.minimum(gmin, pts[:, :2].min(axis=0))
                    gmax = np.maximum(gmax, pts[:, :2].max(axis=0))
            pad = 5.0
            bounds = (
                float(gmin[0] - pad),
                float(gmax[0] + pad),
                float(gmin[1] - pad),
                float(gmax[1] + pad),
            )
        # Pass 2: rasterize real snapshots only.
        for number, position in enumerate(positions):
            meta, payload = reader.read_frame(position)
            pts = decode_points(payload, meta)
            cls = decode_cells(payload, meta)
            if args.follow:
                pose = meta.get("pose")
                cx, cy = (pose[3], pose[7]) if pose and len(pose) == 16 else (0.0, 0.0)
                half = args.window_m / 2
                bounds = (cx - half, cx + half, cy - half, cy + half)
            assert bounds is not None
            img = rasterize(
                pts,
                cls,
                meta.get("pose"),
                width=args.width,
                height=args.height,
                bounds=bounds,
                layer=args.layer,
            )
            # Progress bar (burned-in presentation chrome, not sensor data).
            bar_w = int(args.width * (number + 1) / len(positions))
            img[-8:, :bar_w] = (51, 217, 242)
            write_ppm(frames_dir / f"frame_{number + 1:06d}.ppm", img)
            if (number + 1) % 30 == 0 or number + 1 == len(positions):
                print(f"Rendered {number + 1} / {len(positions)}", flush=True)
    clip = out_dir / f"veyra-demo-{args.fps}fps.mp4"
    if args.skip_encode:
        print(f"Frames in {frames_dir}; skipping ffmpeg encode.")
        return 0
    command = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(args.fps),
        "-i",
        str(frames_dir / "frame_%06d.ppm"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "18",
        "-movflags",
        "+faststart",
        "-metadata",
        "title=Veyra smooth replay (cached visualization)",
        str(clip),
    ]
    print("Encoding:", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stderr[-4000:], file=sys.stderr)
        return 1
    print(f"Demo clip ready: {clip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
