#!/usr/bin/env python3
"""Veyra dataset visualizer server — real files only, no mock data.

Reads KITTI-format .bin scans + uint32 .label files from the repo's own
data/raw/ layout (see configs/datasets.yaml) and serves decimated frames
as JSON to the static Three.js front-end in viewer/static/.

Run from the repo root:  python3 viewer/server.py [--port 8765]
Requires: numpy (pyyaml optional; a fallback parser covers datasets.yaml).
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import urllib.parse
from pathlib import Path

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise SystemExit("numpy is required (see requirements.txt)") from exc

try:
    import yaml  # type: ignore

    def _load_yaml(path: Path) -> dict:
        return yaml.safe_load(path.read_text())
except ImportError:  # minimal fallback for the known datasets.yaml shape
    def _load_yaml(path: Path) -> dict:
        cfg: dict = {}
        cur: dict | None = None
        for raw in path.read_text().splitlines():
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if not raw.startswith((" ", "\t")):
                cur = cfg.setdefault(line.rstrip(":").strip(), {})
            elif cur is not None:
                k, _, v = line.strip().partition(":")
                k, v = k.strip(), v.strip()
                if v.startswith("[") and v.endswith("]"):
                    cur[k] = [
                        s.strip().strip("'\"") for s in v[1:-1].split(",") if s.strip()
                    ]
                else:
                    cur[k] = v.strip("'\"")
        return cfg


def find_repo_root(start: Path) -> Path:
    for cand in [start, *start.parents]:
        if (cand / "configs" / "datasets.yaml").exists():
            return cand
    raise SystemExit("configs/datasets.yaml not found — run from the repo root.")


REPO = find_repo_root(Path.cwd().resolve())
CFG = _load_yaml(REPO / "configs" / "datasets.yaml")
STATIC = Path(__file__).resolve().parent / "static"


def _seq_dir(dataset: str, seq: str) -> Path:
    return REPO / CFG[dataset]["root"] / seq


def _scan_files(dataset: str, seq: str) -> list[Path]:
    d = _seq_dir(dataset, seq) / CFG[dataset]["scan_dir"]
    return sorted(d.glob("*.bin")) if d.is_dir() else []


def _label_for(dataset: str, seq: str, stem: str) -> Path | None:
    p = _seq_dir(dataset, seq) / CFG[dataset]["label_dir"] / (stem + ".label")
    return p if p.is_file() else None


@functools.lru_cache(maxsize=1)
def datasets_payload() -> dict:
    out: dict = {}
    for name, spec in CFG.items():
        seqs = []
        for seq in spec["sequences"]:
            scans = _scan_files(name, str(seq))
            stems = {p.stem for p in scans}
            paired = sum(
                1 for s in stems if _label_for(name, str(seq), s) is not None
            )
            seqs.append(
                {"id": str(seq), "scans": len(scans), "paired": paired}
            )
        out[name] = {"root": spec["root"], "sequences": seqs}
    return out


def frame_payload(dataset: str, seq: str, index: int, budget: int) -> dict:
    scans = _scan_files(dataset, seq)
    if not scans:
        raise KeyError("sequence not found")
    index = max(0, min(index, len(scans) - 1))
    scan = scans[index]
    pts = np.fromfile(scan, dtype=np.float32).reshape(-1, 4)
    n = int(pts.shape[0])
    stride = max(1, -(-n // max(1, budget)))  # ceil
    sub = pts[::stride]
    labels: list[int] | None = None
    hist: dict[str, int] = {}
    paired = False
    lab_path = _label_for(dataset, seq, scan.stem)
    if lab_path is not None:
        lab = np.fromfile(lab_path, dtype=np.uint32)
        if lab.shape[0] == n:
            paired = True
            cls = (lab & 0xFFFF).astype(np.int64)
            labels = cls[::stride].tolist()
            for k, c in zip(*np.unique(cls, return_counts=True)):
                hist[str(int(k))] = int(c)
    return {
        "dataset": dataset,
        "seq": seq,
        "index": index,
        "id": scan.stem,
        "n_points": n,
        "shown": int(sub.shape[0]),
        "stride": stride,
        "points": [[round(float(x), 3) for x in row[:3]] for row in sub.tolist()],
        "intensity": [round(float(v), 3) for v in sub[:, 3].tolist()],
        "labels": labels,
        "paired": paired,
        "hist": hist,
        "frames": len(scans),
    }


class Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "VeyraViewer/1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):  # quieter logs
        pass

    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.path = "/index.html"
            return super().do_GET()
        if parsed.path == "/api/datasets":
            return self._send_json(datasets_payload())
        if parsed.path.startswith("/static/"):
            # Static assets live in viewer/static/; strip the mount prefix so
            # /static/app.js resolves to viewer/static/app.js.
            self.path = parsed.path[len("/static"):] or "/"
            if parsed.query:
                self.path += "?" + parsed.query
            return super().do_GET()
        if parsed.path == "/api/frame":
            q = urllib.parse.parse_qs(parsed.query)
            try:
                ds = q["dataset"][0]
                seq = q["seq"][0]
                if ds not in CFG or str(seq) not in [
                    str(s) for s in CFG[ds]["sequences"]
                ]:
                    raise KeyError("unknown dataset/sequence")
                idx = int(q.get("index", ["0"])[0])
                budget = max(1000, min(int(q.get("budget", ["25000"])[0]), 100000))
            except (KeyError, ValueError, IndexError):
                return self._send_json({"error": "bad dataset, seq, or index"}, 400)
            try:
                return self._send_json(frame_payload(ds, seq, idx, budget))
            except KeyError:
                return self._send_json({"error": "sequence has no scans"}, 404)
        if parsed.path.startswith("/api/"):
            return self._send_json({"error": "unknown endpoint"}, 404)
        return super().do_GET()


def main() -> None:
    ap = argparse.ArgumentParser(description="Veyra LiDAR dataset visualizer")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    missing = [d for d in ("data/raw/rellis3d", "data/raw/semanticposs")
               if not (REPO / d).exists()]
    srv = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Veyra viewer  repo={REPO}  ->  http://{args.host}:{args.port}/")
    if missing:
        print(f"NOTE: missing local data (see datasets/README.md): {missing}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
