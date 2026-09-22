"""Veyra dataset visualizer server — real files only, no mock data.

Reads KITTI-format .bin scans + uint32 .label files from the repo's own
data/raw/ layout (see configs/datasets.yaml) and serves decimated frames
as JSON to the static Three.js front-end in viewer/static/.

Run from the repo root:  python3 viewer/server.py [--port 8765] [--host 127.0.0.1]
Requires: numpy (pyyaml optional; a fallback parser covers datasets.yaml).
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import sys
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if TYPE_CHECKING:
    from datasets.rellis import Rellis3DDataset
    from datasets.semanticposs import SemanticPOSSDataset

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
    # Prefer the working directory, then this file's checkout, so the viewer
    # also starts when launched from outside the repo (e.g. a container WORKDIR).
    here = Path(__file__).resolve().parent.parent
    for cand in [start, *start.parents, here]:
        if (cand / "configs" / "datasets.yaml").exists():
            return cand
    raise SystemExit("configs/datasets.yaml not found — run from the repo root.")


REPO = find_repo_root(Path.cwd().resolve())
CFG = _load_yaml(REPO / "configs" / "datasets.yaml")
STATIC = Path(__file__).resolve().parent / "static"
RUNTIME = None


def _seq_dir(dataset: str, seq: str) -> Path:
    return REPO / CFG[dataset]["root"] / seq


def _scan_files(dataset: str, seq: str) -> list[Path]:
    d = _seq_dir(dataset, seq) / CFG[dataset]["scan_dir"]
    return sorted(d.glob("*.bin")) if d.is_dir() else []


def _label_for(dataset: str, seq: str, stem: str) -> Path | None:
    p = _seq_dir(dataset, seq) / CFG[dataset]["label_dir"] / (stem + ".label")
    return p if p.is_file() else None


def _semanticposs_adapter() -> SemanticPOSSDataset:
    from datasets.semanticposs import SemanticPOSSDataset

    spec = CFG["semanticposs"]
    return SemanticPOSSDataset(
        REPO / spec["root"],
        sequences=[str(value) for value in spec["sequences"]],
        scan_dir=spec.get("scan_dir", "velodyne"),
        label_dir=spec.get("label_dir", "labels"),
    )


def _rellis_adapter() -> Rellis3DDataset:
    from datasets.rellis import Rellis3DDataset

    spec = CFG["rellis3d"]
    return Rellis3DDataset(
        REPO / spec["root"],
        sequences=[str(value) for value in spec["sequences"]],
        scan_dir=spec.get("scan_dir", "vel_cloud_node_kitti_bin"),
        label_dir=spec.get("label_dir", "vel_cloud_node_semantickitti_label_id"),
    )


@functools.lru_cache(maxsize=1)
def datasets_payload() -> dict:
    out: dict = {}
    for name, spec in CFG.items():
        seqs = []
        adapter = None
        if name == "semanticposs":
            try:
                adapter = _semanticposs_adapter()
            except FileNotFoundError:
                adapter = None
        for seq in spec["sequences"]:
            if adapter is not None:
                try:
                    refs = adapter.list_frames(str(seq))
                except FileNotFoundError:
                    refs = []
                scans_count = len(refs)
                paired = sum(ref.label_path is not None for ref in refs)
            else:
                scans = _scan_files(name, str(seq))
                stems = {p.stem for p in scans}
                scans_count = len(scans)
                paired = sum(
                    1 for s in stems if _label_for(name, str(seq), s) is not None
                )
            seqs.append({"id": str(seq), "scans": scans_count, "paired": paired})
        out[name] = {
            "root": spec["root"],
            "sequences": seqs,
            "source": "SemanticPOSSDataset" if adapter is not None else "raw files",
        }
    return out


def frame_payload(dataset: str, seq: str, index: int, budget: int) -> dict:
    if RUNTIME is not None:
        if dataset != RUNTIME.dataset:
            raise KeyError(
                f"runtime is configured for {RUNTIME.dataset}, not {dataset}"
            )
        if str(seq) != RUNTIME.sequence:
            return RUNTIME.select_sequence(str(seq), budget=budget)
        return RUNTIME.frame_payload(index, budget=budget)
    if dataset == "semanticposs":
        return _semanticposs_frame_payload(seq, index, budget)
    if dataset == "rellis3d":
        try:
            return _rellis_frame_payload(seq, index, budget)
        except FileNotFoundError:
            # Preserve scan-only visualization for incomplete local exports.
            pass
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
        "source": "raw files",
        "timestamp": None,
        "pose": {"available": False, "matrix": None},
        "cropped": False,
        "ground": [False] * int(sub.shape[0]),
        "drivable": ["unknown"] * int(sub.shape[0]),
        "slope": [None] * int(sub.shape[0]),
        "roughness": [None] * int(sub.shape[0]),
        "height_complexity": [None] * int(sub.shape[0]),
        "motion_probability": [0.0] * int(sub.shape[0]),
        "velocity_xy": [[0.0, 0.0]] * int(sub.shape[0]),
        "motion_state": ["unknown"] * int(sub.shape[0]),
        "pipeline_status": {
            "semantic": "ground_truth" if paired else "unavailable",
            "ground": "unavailable",
            "terrain": "unavailable",
            "temporal": "unavailable",
        },
    }


def _semanticposs_frame_payload(seq: str, index: int, budget: int) -> dict:
    try:
        adapter = _semanticposs_adapter()
        refs = adapter.list_frames(seq)
    except FileNotFoundError as exc:
        raise KeyError("sequence not found") from exc
    if not refs:
        raise KeyError("sequence not found")
    index = max(0, min(index, len(refs) - 1))
    ref = refs[index]
    spec = CFG["semanticposs"]
    observation = adapter.load_frame(
        seq,
        ref.frame_id,
        min_range_m=float(spec.get("min_range_m", 0.0)),
        max_range_m=float(spec.get("max_range_m", 100.0)),
    )
    n = int(observation.points.shape[0])
    stride = max(1, -(-n // max(1, budget)))
    sub = observation.points[::stride]
    raw_labels = np.fromfile(ref.label_path, dtype=np.uint32) & 0xFFFF
    raw_points = np.fromfile(ref.scan_path, dtype=np.float32).reshape((-1, 4))
    world_points = adapter._transform_points(raw_points, observation.pose.matrix)
    raw_labels = raw_labels[
        adapter._range_mask(
            world_points,
            float(spec.get("min_range_m", 0.0)),
            float(spec.get("max_range_m", 100.0)),
        )
    ]
    # Keep raw dataset IDs for the visual legend while exposing the mapped
    # common-taxonomy IDs alongside them for downstream consumers.
    classes = raw_labels[: observation.points.shape[0]][::stride].tolist()
    hist: dict[str, int] = {}
    for key, count in zip(*np.unique(raw_labels[:n], return_counts=True)):
        hist[str(int(key))] = int(count)
    matrix = observation.pose.matrix.tolist()
    return {
        "dataset": "semanticposs",
        "seq": seq,
        "index": index,
        "id": ref.frame_id,
        "n_points": n,
        "raw_points": int(raw_points.shape[0]),
        "shown": int(sub.shape[0]),
        "stride": stride,
        "points": [[round(float(x), 3) for x in row[:3]] for row in sub.tolist()],
        "intensity": [round(float(v), 3) for v in sub[:, 3].tolist()],
        "labels": classes,
        "semantic_labels": observation.semantic_class[::stride].tolist(),
        "paired": True,
        "hist": hist,
        "frames": len(refs),
        "source": "SemanticPOSSDataset",
        "timestamp": observation.timestamp,
        "pose": {"available": True, "matrix": matrix},
        "cropped": n != int(raw_points.shape[0]),
        "range_m": float(spec.get("max_range_m", 100.0)),
        "ground": observation.ground[::stride].tolist(),
        "drivable": observation.drivable[::stride].tolist(),
        "slope": _json_float_array(observation.slope[::stride]),
        "roughness": _json_float_array(observation.roughness[::stride]),
        "height_complexity": _json_float_array(observation.height_complexity[::stride]),
        "motion_probability": observation.motion_probability[::stride].tolist(),
        "velocity_xy": observation.velocity_xy[::stride].tolist(),
        "motion_state": observation.motion_state[::stride].tolist(),
        "pipeline_status": {
            "semantic": "ground_truth",
            "ground": "unavailable",
            "terrain": "unavailable",
            "temporal": "unavailable",
        },
    }


def _rellis_frame_payload(seq: str, index: int, budget: int) -> dict:
    adapter = _rellis_adapter()
    refs = adapter.list_frames(seq)
    if not refs:
        raise KeyError("sequence not found")
    index = max(0, min(index, len(refs) - 1))
    ref = refs[index]
    if ref.label_path is None:
        raise FileNotFoundError(f"label file is missing for {seq}/{ref.frame_id}")
    spec = CFG["rellis3d"]
    observation = adapter.load_frame(
        seq,
        ref.frame_id,
        min_range_m=float(spec.get("min_range_m", 0.0)),
        max_range_m=(
            float(spec["max_range_m"]) if spec.get("max_range_m") is not None else None
        ),
    )
    raw_points = np.fromfile(ref.scan_path, dtype=np.float32).reshape((-1, 4))
    raw_labels = np.fromfile(ref.label_path, dtype=np.uint32) & 0xFFFF
    world_points = adapter._transform_points(raw_points, observation.pose.matrix)
    raw_labels = raw_labels[
        adapter._range_mask(
            world_points,
            float(spec.get("min_range_m", 0.0)),
            float(spec["max_range_m"]) if spec.get("max_range_m") is not None else None,
        )
    ]
    n = int(observation.points.shape[0])
    stride = max(1, -(-n // max(1, budget)))
    hist = {
        str(int(key)): int(count)
        for key, count in zip(*np.unique(raw_labels, return_counts=True))
    }
    return {
        "dataset": "rellis3d",
        "seq": seq,
        "index": index,
        "id": ref.frame_id,
        "n_points": n,
        "raw_points": int(raw_points.shape[0]),
        "shown": int(observation.points[::stride].shape[0]),
        "stride": stride,
        "points": [
            [round(float(x), 3) for x in row[:3]]
            for row in observation.points[::stride].tolist()
        ],
        "intensity": [
            round(float(v), 3) for v in observation.points[::stride, 3].tolist()
        ],
        "labels": raw_labels[::stride].tolist(),
        "semantic_labels": observation.semantic_class[::stride].tolist(),
        "paired": True,
        "hist": hist,
        "frames": len(refs),
        "source": "Rellis3DDataset",
        "timestamp": observation.timestamp,
        "pose": {"available": False, "matrix": observation.pose.matrix.tolist()},
        "cropped": n != int(raw_points.shape[0]),
        "range_m": spec.get("max_range_m"),
        "ground": observation.ground[::stride].tolist(),
        "drivable": observation.drivable[::stride].tolist(),
        "slope": _json_float_array(observation.slope[::stride]),
        "roughness": _json_float_array(observation.roughness[::stride]),
        "height_complexity": _json_float_array(observation.height_complexity[::stride]),
        "motion_probability": observation.motion_probability[::stride].tolist(),
        "velocity_xy": observation.velocity_xy[::stride].tolist(),
        "motion_state": observation.motion_state[::stride].tolist(),
        "pipeline_status": {
            "semantic": "ground_truth",
            "ground": "unavailable",
            "terrain": "unavailable",
            "temporal": "unavailable",
        },
    }


def _json_float_array(values: np.ndarray) -> list[float | None]:
    """Serialize NaN feature values as null so unavailable data stays visible."""

    return [float(value) if np.isfinite(value) else None for value in values]


def runtime_status_payload() -> dict:
    if RUNTIME is None:
        return {"state": "not_configured", "map": "unavailable"}
    return RUNTIME.status()


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

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.path = "/index.html"
            return super().do_GET()
        if parsed.path == "/api/datasets":
            return self._send_json(datasets_payload())
        if parsed.path == "/api/runtime/status":
            return self._send_json(runtime_status_payload())
        if parsed.path == "/api/map_cells":
            if RUNTIME is None:
                return self._send_json({"error": "runtime is not configured"}, 409)
            query = urllib.parse.parse_qs(parsed.query)
            try:
                budget = max(1000, min(int(query.get("budget", ["20000"])[0]), 100000))
            except (ValueError, IndexError):
                return self._send_json({"error": "bad cell budget"}, 400)
            return self._send_json(RUNTIME.map_cells(budget=budget))
        if parsed.path.startswith("/static/"):
            # Static assets live in viewer/static/; strip the mount prefix so
            # /static/app.js resolves to viewer/static/app.js.
            self.path = parsed.path[len("/static") :] or "/"
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
            except FileNotFoundError as exc:
                return self._send_json({"error": str(exc)}, 422)
            except ValueError as exc:
                return self._send_json({"error": str(exc)}, 422)
        if parsed.path.startswith("/api/"):
            return self._send_json({"error": "unknown endpoint"}, 404)
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/runtime/reset":
            return self._send_json({"error": "unknown endpoint"}, 404)
        if RUNTIME is None:
            return self._send_json({"error": "runtime is not configured"}, 409)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            budget = max(1000, min(int(query.get("budget", ["25000"])[0]), 100000))
        except (ValueError, IndexError):
            return self._send_json({"error": "bad point budget"}, 400)
        try:
            return self._send_json(RUNTIME.reset(budget=budget))
        except (FileNotFoundError, ValueError) as error:
            return self._send_json({"error": str(error)}, 422)


DEFAULT_HOST = "127.0.0.1"


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Veyra LiDAR dataset visualizer")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="bind address; loopback by default, 0.0.0.0 to publish from a container",
    )
    ap.add_argument(
        "--runtime-config",
        type=Path,
        help="viewer-owned JSON selection and configured perception stages",
    )
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    global RUNTIME
    if args.runtime_config is not None:
        from viewer.runtime import build_runtime_session, load_runtime_config

        RUNTIME = build_runtime_session(
            load_runtime_config(args.runtime_config),
            dataset_settings=CFG,
            repo_root=REPO,
        )
    missing = [
        d
        for d in ("data/raw/rellis3d", "data/raw/semanticposs")
        if not (REPO / d).exists()
    ]
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
