"""Affordable real-scan perception regression; no mapper or policy execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datasets.common.observation import FrameProvenance, ObservationFrame, PoseSE3
from datasets.common.taxonomy import TAXONOMY_VERSION
from perception.pipeline import load_perception_pipeline

DEFAULT_SCAN_URL = (
    "https://qaihub-public-assets.s3.us-west-2.amazonaws.com/"
    "qai-hub-models/models/salsanext/v3/000000.bin"
)
DEFAULT_SCAN_SHA256 = "bf272996d5b6d25cc5589e1089137cb20a98b63bd4823a7fea5631b359f6d68c"
DEFAULT_SCAN_SIZE_BYTES = 1_994_688
MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_TAXONOMY_CLASS = 19


def asset_manifest() -> dict[str, Any]:
    """Return immutable provenance for the one affordable CI scan."""
    return {
        "url": DEFAULT_SCAN_URL,
        "sha256": DEFAULT_SCAN_SHA256,
        "size_bytes": DEFAULT_SCAN_SIZE_BYTES,
        "format": "float32_xyzi",
        "publisher": "Qualcomm AI Hub public asset",
        "upstream_app": "https://github.com/qualcomm/ai-hub-models/blob/v0.62.1/src/qai_hub_models/models/salsanext/app.py",
        "upstream_license": "https://github.com/TiagoCortinhal/SalsaNext/blob/master/LICENSE",
        "object_version_id": "X7e_uhOV0M3zyfyE2YIiylSOk4Iua70M",
        "pose_source": "absent",
        "timestamp_source": "absent",
    }


def verify_download(path: Path, *, sha256: str, max_bytes: int = MAX_SCAN_BYTES) -> None:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"asset exceeds bounded download limit: {size} > {max_bytes} bytes")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sha256:
        raise ValueError(f"asset sha256 mismatch: expected {sha256}, got {actual}")


def download_asset(url: str, destination: Path, *, sha256: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        verify_download(destination, sha256=sha256)
        return destination
    temporary = destination.with_name(destination.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > MAX_SCAN_BYTES:
                raise ValueError("asset Content-Length exceeds bounded download limit")
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_SCAN_BYTES:
                    raise ValueError("asset exceeds bounded download limit")
                output.write(chunk)
        verify_download(temporary, sha256=sha256)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def load_scan_frame(path: Path) -> ObservationFrame:
    values = np.fromfile(path, dtype=np.float32)
    if values.size == 0 or values.size % 4:
        raise ValueError("real scan must contain a non-empty float32 XYZ+intensity stream")
    points = values.reshape((-1, 4))
    if not np.isfinite(points).all():
        raise ValueError("real scan contains non-finite values")
    count = len(points)
    return ObservationFrame(
        timestamp=None,
        pose=PoseSE3.identity(),
        points=points,
        semantic_class=np.zeros(count, dtype=np.int32),
        semantic_confidence=np.zeros(count, dtype=np.float32),
        ground=np.zeros(count, dtype=bool),
        drivable=np.full(count, "unknown"),
        slope=np.full(count, np.nan, dtype=np.float32),
        roughness=np.full(count, np.nan, dtype=np.float32),
        height_complexity=np.full(count, np.nan, dtype=np.float32),
        motion_probability=np.zeros(count, dtype=np.float32),
        velocity_xy=np.zeros((count, 2), dtype=np.float32),
        dataset="qualcomm-salsanext-public",
        sequence="v3",
        frame_id="000000",
        provenance=FrameProvenance(
            coordinate_frame="lidar",
            timestamp_source="absent",
            pose_source="identity_absent",
        ),
    )


def taxonomy_range_report(points: np.ndarray, frame: ObservationFrame) -> dict[str, Any]:
    """Report observable taxonomy/range validity without inventing labels."""
    ranges = np.linalg.norm(points[:, :3], axis=1)
    classes = np.asarray(frame.semantic_class)
    valid = (classes >= 0) & (classes <= MAX_TAXONOMY_CLASS)
    bins = ((0.0, 10.0), (10.0, 30.0), (30.0, 60.0), (60.0, 100.0), (100.0, None))
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "valid_class_fraction": float(np.mean(valid)),
        "ground_truth_accuracy": None,
        "accuracy_note": "No paired upstream labels were verified for this scan.",
        "range_bins": [
            {
                "min_m": lower,
                "max_m": upper,
                "points": int(np.count_nonzero(
                    (ranges >= lower)
                    & (ranges < upper if upper is not None else True)
                )),
            }
            for lower, upper in bins
        ],
    }


def correspondence_report(input_frame: ObservationFrame, output_frame: ObservationFrame) -> dict[str, Any]:
    same_shape = input_frame.points.shape == output_frame.points.shape
    same_points = same_shape and bool(np.array_equal(input_frame.points, output_frame.points))
    aligned_fields = (
        "semantic_class",
        "semantic_confidence",
        "ground",
        "drivable",
        "slope",
        "roughness",
        "height_complexity",
        "motion_probability",
        "velocity_xy",
        "terrain_confidence",
        "step",
        "motion_state",
        "observation_quality",
        "raw_semantic_class",
    )
    field_alignment = {
        name: np.asarray(getattr(output_frame, name)).shape[0] == len(input_frame.points)
        for name in aligned_fields
    }
    return {
        "input_points": len(input_frame.points),
        "output_points": len(output_frame.points),
        "shape_matches": same_shape,
        "xyz_intensity_exactly_preserved": same_points,
        "per_point_fields_aligned": all(field_alignment.values()),
        "field_alignment": field_alignment,
    }


def max_rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage * (1024 if sys.platform != "darwin" else 1))


def _load_pipeline(repo: Path, config_path: Path, intensity_scale: float | None):
    config = yaml.safe_load(config_path.read_text())
    if not isinstance(config, dict) or config.get("semantic", {}).get("mode") != "salsanext":
        raise ValueError("perception regression requires explicit SalsaNext config")
    if intensity_scale is None:
        raise ValueError(
            "pass --intensity-scale explicitly for this raw scan; refusing implicit config scale"
        )
    if not np.isfinite(intensity_scale) or intensity_scale <= 0:
        raise ValueError("--intensity-scale must be finite and positive")
    config["semantic"]["intensity_scale"] = intensity_scale
    effective_config_sha256 = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    model_path = config["semantic"].get("model_path")
    if isinstance(model_path, str) and not Path(model_path).is_absolute():
        config["semantic"]["model_path"] = str(repo / model_path)
    fd, temporary_name = tempfile.mkstemp(prefix="veyra-perception-", suffix=".yaml")
    os.close(fd)
    temporary_config = Path(temporary_name)
    try:
        temporary_config.write_text(yaml.safe_dump(config, sort_keys=False))
        return load_perception_pipeline(temporary_config), effective_config_sha256
    finally:
        temporary_config.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).resolve()
    manifest = asset_manifest()
    scan_path = (
        Path(args.scan).resolve()
        if args.scan
        else download_asset(manifest["url"], Path(args.cache_dir).resolve() / "000000.bin", sha256=manifest["sha256"])
    )
    verify_download(scan_path, sha256=manifest["sha256"])
    config_path = (repo / args.perception_config).resolve()
    pipeline, effective_config_sha256 = _load_pipeline(
        repo, config_path, args.intensity_scale
    )
    source = load_scan_frame(scan_path)
    started = time.perf_counter_ns()
    output = pipeline.process(source)
    total_ns = time.perf_counter_ns() - started
    if output.status.semantic != "model" or output.status.ground in {"disabled", "unavailable"} or output.status.terrain in {"disabled", "unavailable"}:
        raise RuntimeError(f"required perception stage missing: {output.status}")
    correspondence = correspondence_report(source, output.frame)
    if not all(correspondence.values()):
        raise RuntimeError(f"input/output correspondence failed: {correspondence}")
    return {
        "regression_schema_version": 2,
        "status": "real_data_perception_single_frame",
        "asset": manifest | {"local_sha256": hashlib.sha256(scan_path.read_bytes()).hexdigest()},
        "input_scan": {
            "points": len(source.points),
            "intensity_min": float(source.points[:, 3].min()),
            "intensity_max": float(source.points[:, 3].max()),
            "intensity_mean": float(source.points[:, 3].mean()),
            "intensity_values_above_one": int(np.count_nonzero(source.points[:, 3] > 1.0)),
        },
        "pipeline": {
            "config": str(config_path.relative_to(repo)),
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "effective_config_sha256": effective_config_sha256,
            "effective_intensity_scale": args.intensity_scale,
            "stage_status": output.status.__dict__,
            "stage_timings_ms": output.timings_ms,
            "total_latency_ms": total_ns / 1_000_000,
            "rss_bytes_max": max_rss_bytes(),
        },
        "correspondence": correspondence,
        "taxonomy_and_range": taxonomy_range_report(source.points, output.frame),
        "input_frames": 1,
        "limitations": [
            "one real public scan frame on PR smoke",
            "no paired upstream labels were verified; accuracy is reported as null",
            "no pose or timestamp is present; temporal behavior cannot be validated with this sample",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--cache-dir", default=os.environ.get("VEYRA_BENCHMARK_CACHE", ".cache/veyra-perception"))
    parser.add_argument("--scan")
    parser.add_argument("--perception-config", default="configs/perception-salsanext.yaml")
    parser.add_argument("--intensity-scale", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run(args)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"veyra perception regression: {error}", file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
