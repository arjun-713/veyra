"""Train the native Pandora/SemanticPOSS per-point MLP.

Run from the repository root::

    python3 scripts/train_pandora_semantic.py --train-sequences 01 02 03 \
        --output data/cache/models/pandora-mlp/pandora_mlp_seed0.npz

Reads raw sensor-frame ``.bin``/``.label`` pairs directly so the i-th point
aligns with the i-th label. Labels fold into the native head space
(``perception.semantic.pandora.fold_to_native``): the 16 known SemanticPOSS
raw IDs pass through, raw 0 and every unmapped ID become unknown. Sequence
00 is never touched here; it is the held-out test sequence used by
``scripts/measure_pandora_native.py``. The last ``--calib-frames`` frames of
the last training sequence are reserved for temperature scaling, never for
gradient updates.

The checkpoint is a ``.npz`` archive (StandardScaler parameters, sklearn
MLP weights, class IDs, temperature, provenance JSON). It is written under
``data/cache/`` (git-ignored: weights are never committed); the metrics
artifact records its sha256 plus the full reproduction spec.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FALLBACK_ROOT = Path("/home/arjun/Captain/SIH/Lidar")
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if _FALLBACK_ROOT != _REPO_ROOT and str(_FALLBACK_ROOT) not in sys.path:
    sys.path.append(str(_FALLBACK_ROOT))
_REPOS = [_REPO_ROOT, _FALLBACK_ROOT]

import numpy as np

from perception.semantic.pandora import (
    FEATURE_NAMES,
    extract_features,
    fold_to_native,
    mlp_predict_proba,
)


def _resolve(root_arg: str) -> Path:
    root = Path(root_arg)
    if root.is_absolute():
        return root
    for repo in _REPOS:
        candidate = repo / root
        if candidate.is_dir():
            return candidate
    return _REPOS[0] / root


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPOS[0]), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def _scan_frames(root: Path, sequence: str) -> list[Path]:
    scans = sorted((root / "sequences" / sequence / "velodyne").glob("*.bin"))
    labels = root / "sequences" / sequence / "labels"
    frames = [s for s in scans if (labels / f"{s.stem}.label").is_file()]
    if not frames:
        raise FileNotFoundError(f"no labelled scans for sequence {sequence}")
    return frames


def _nll(proba: np.ndarray, targets: np.ndarray) -> float:
    eps = 1e-12
    return float(
        -np.log(np.clip(proba[np.arange(len(targets)), targets], eps, 1.0)).mean()
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="data/raw/semanticposs/dataset")
    parser.add_argument("--train-sequences", nargs="+", default=["01", "02", "03"])
    parser.add_argument("--calib-frames", type=int, default=20)
    parser.add_argument("--cap-per-class", type=int, default=20000)
    parser.add_argument("--hidden", nargs="+", type=int, default=[128, 64])
    parser.add_argument("--max-iter", type=int, default=150)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--output",
        default="data/cache/models/pandora-mlp/pandora_mlp_seed0.npz",
    )
    args = parser.parse_args()

    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler

    root = _resolve(args.root)
    rng = np.random.RandomState(args.seed)

    train_frames: list[Path] = []
    calib_frames: list[Path] = []
    for seq in args.train_sequences:
        frames = _scan_frames(root, seq)
        if seq == args.train_sequences[-1] and args.calib_frames > 0:
            calib_frames = frames[-args.calib_frames :]
            frames = frames[: -args.calib_frames]
        train_frames.extend(frames)
    calib_ids = {p.resolve() for p in calib_frames}
    print(
        f"train_frames={len(train_frames)} calib_frames={len(calib_frames)} "
        f"cap_per_class={args.cap_per_class} hidden={args.hidden} seed={args.seed}"
    )

    # Online per-class reservoir: never hold more than ~2x cap per class.
    buckets: dict[int, list[np.ndarray]] = {}
    counts: dict[int, int] = {}
    label_dir_of = lambda scan: scan.parent.parent / "labels" / f"{scan.stem}.label"
    for index, scan in enumerate(train_frames):
        if scan.resolve() in calib_ids:
            raise AssertionError("calibration frame leaked into training frames")
        points = np.fromfile(scan, dtype=np.float32).reshape(-1, 4)
        raw = (np.fromfile(label_dir_of(scan), dtype=np.uint32) & 0xFFFF).astype(
            np.int64
        )
        assert raw.shape[0] == points.shape[0]
        native = fold_to_native(raw)
        feats = extract_features(points)
        for cls in np.unique(native):
            sel = np.flatnonzero(native == cls)
            if sel.size > 4000:
                sel = rng.choice(sel, 4000, replace=False)
            block = np.column_stack([feats[sel], np.full(sel.size, cls)])
            buckets.setdefault(int(cls), []).append(block.astype(np.float32))
            counts[int(cls)] = counts.get(int(cls), 0) + int(sel.size)
            rows = sum(b.shape[0] for b in buckets[int(cls)])
            if rows > 2 * args.cap_per_class:
                merged = np.concatenate(buckets[int(cls)], axis=0)
                keep = rng.choice(merged.shape[0], args.cap_per_class, replace=False)
                buckets[int(cls)] = [merged[keep]]
        if (index + 1) % 200 == 0:
            total = sum(sum(b.shape[0] for b in v) for v in buckets.values())
            print(f"  streamed {index + 1}/{len(train_frames)} buffered={total}")

    parts = []
    for cls in sorted(buckets):
        merged = np.concatenate(buckets[cls], axis=0)
        if merged.shape[0] > args.cap_per_class:
            merged = merged[
                rng.choice(merged.shape[0], args.cap_per_class, replace=False)
            ]
        parts.append(merged)
    data = np.concatenate(parts, axis=0)
    order = rng.permutation(data.shape[0])
    data = data[order]
    X_all, y_all = data[:, : len(FEATURE_NAMES)], data[:, -1].astype(np.int32)
    print(f"train_samples={X_all.shape[0]} classes={sorted(np.unique(y_all).tolist())}")

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_all)
    clf = MLPClassifier(
        hidden_layer_sizes=tuple(args.hidden),
        activation="relu",
        solver="adam",
        alpha=1e-4,
        batch_size=1024,
        learning_rate_init=1e-3,
        max_iter=args.max_iter,
        shuffle=True,
        random_state=args.seed,
        tol=1e-4,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=10,
    )
    clf.fit(X_scaled, y_all)
    print(
        f"fitted n_iter={clf.n_iter_} loss={clf.loss_:.4f} "
        f"best_val={clf.best_validation_score_:.4f} classes={clf.classes_.tolist()}"
    )

    # Temperature scaling on held-out calibration frames (no gradient signal).
    cal_X, cal_y = [], []
    for scan in calib_frames:
        points = np.fromfile(scan, dtype=np.float32).reshape(-1, 4)
        raw = (np.fromfile(label_dir_of(scan), dtype=np.uint32) & 0xFFFF).astype(
            np.int64
        )
        cal_X.append(extract_features(points))
        cal_y.append(fold_to_native(raw))
    cal_X = np.concatenate(cal_X, axis=0)
    cal_y = np.concatenate(cal_y, axis=0)
    if cal_X.shape[0] > 150000:
        keep = rng.choice(cal_X.shape[0], 150000, replace=False)
        cal_X, cal_y = cal_X[keep], cal_y[keep]
    coefs = [c.astype(np.float64) for c in clf.coefs_]
    intercepts = [b.astype(np.float64) for b in clf.intercepts_]
    mean = scaler.mean_.astype(np.float64)
    scale = scaler.scale_.astype(np.float64)
    code_of = {int(c): i for i, c in enumerate(clf.classes_)}
    cal_targets = np.array([code_of[int(v)] for v in cal_y], dtype=np.int64)
    best_T, best_nll = 1.0, np.inf
    for temp in np.exp(np.linspace(np.log(0.15), np.log(5.0), 60)):
        proba = mlp_predict_proba(cal_X, mean, scale, coefs, intercepts, float(temp))
        value = _nll(proba, cal_targets)
        if value < best_nll:
            best_nll, best_T = value, float(temp)
    base_nll = _nll(
        mlp_predict_proba(cal_X, mean, scale, coefs, intercepts, 1.0), cal_targets
    )
    print(f"temperature={best_T:.3f} nll {base_nll:.4f} -> {best_nll:.4f}")

    import sklearn

    provenance = {
        "dataset": "semanticposs",
        "dataset_version": "SemanticPOSS-v1.0-LABEL_DICT",
        "root": str(root),
        "train_sequences": args.train_sequences,
        "calib_frames": [f"{p.parent.parent.name}/{p.stem}" for p in calib_frames],
        "train_frames": len(train_frames),
        "train_samples": int(X_all.shape[0]),
        "cap_per_class": args.cap_per_class,
        "hidden_layers": list(args.hidden),
        "max_iter": args.max_iter,
        "seed": args.seed,
        "n_iter": int(clf.n_iter_),
        "train_loss": float(clf.loss_),
        "best_validation_score": float(clf.best_validation_score_),
        "temperature": best_T,
        "classes": [int(c) for c in clf.classes_.tolist()],
        "features": list(FEATURE_NAMES),
        "git_sha": _git_sha(),
        "sklearn_version": sklearn.__version__,
        "numpy_version": np.__version__,
    }
    out = Path(args.output)
    if not out.is_absolute():
        out = _REPOS[0] / out
    out.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {
        "scaler_mean": mean,
        "scaler_scale": scale,
        "n_layers": np.array(len(coefs), dtype=np.int64),
        "classes": np.asarray(clf.classes_, dtype=np.int32),
        "temperature": np.array(best_T, dtype=np.float64),
    }
    for i, (coef, intercept) in enumerate(zip(coefs, intercepts)):
        arrays[f"coef_{i}"] = coef
        arrays[f"intercept_{i}"] = intercept
    np.savez(out, **arrays)
    out.with_suffix(".provenance.json").write_text(json.dumps(provenance, indent=2))
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"wrote {out} sha256={sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
