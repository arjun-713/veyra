"""Durable cache of completed four-policy benchmark reports.

A benchmark report is measured evidence: it is only reused when everything
that can change its numbers is identical (selection, perception config,
benchmark binary, harness source, repository commit and host). A cache hit
is always presented as ``CACHED`` with the original measurement timestamp and
host, never as a fresh measurement. Partial, failed or cancelled runs are
never stored; entries are written atomically (temp file + rename) and the
metadata file, renamed last, is the commit marker.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import POLICIES

CACHE_SCHEMA = 1
REPORT_SCHEMA = 2
# Presentation delay for a cache hit: long enough that the UI visibly shows
# its running/loading state, short enough not to pretend a measurement ran.
PRESENTATION_DELAY_S = 3.0
# Source trees that can change benchmark numbers without changing the
# benchmark binary (Python harness, loaders, perception, configs). Edits to
# the desktop UI or docs do not invalidate cached measurements.
RESULT_SOURCES = ("benchmarks", "datasets", "perception", "configs", "src", "include")


def cache_directory() -> Path:
    """Keep cached reports outside the installed, read-only app bundle."""
    configured = os.environ.get("VEYRA_BENCHMARK_CACHE_DIR")
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".cache" / "veyra" / "benchmarks"
    )


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def binary_identity(path: Path) -> dict:
    """Identify the exact benchmark executable by content, not just by name."""
    path = Path(path)
    stat = path.stat()
    return {"size": stat.st_size, "sha256": _sha256_file(path)}


def repo_commit(repo: Path) -> dict:
    """Commit and dirty flag when the repository is a git checkout, else nulls."""

    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    sha = git("rev-parse", "HEAD")
    if not sha:
        return {"git_sha": None, "dirty": None}
    status = git("status", "--porcelain", "--untracked-files=no", "--", *RESULT_SOURCES)
    diff = git("diff", "HEAD", "--", *RESULT_SOURCES) if status else None
    return {
        "git_sha": sha,
        "dirty": None if status is None else bool(status),
        # A dirty result-affecting tree only matches itself: hash its diff.
        "diff_sha256": hashlib.sha256(diff.encode()).hexdigest() if diff is not None else None,
    }


def host_identity() -> dict:
    return {
        "node": platform.node() or None,
        "machine": platform.machine() or None,
        "system": platform.system() or None,
        "processor": platform.processor() or None,
    }


def key_material(
    *,
    config: dict,
    sequence: str,
    start: int,
    count: int,
    warmup_frames: int,
    repetitions: int,
    hardware_profile: str,
    binary: Path,
    repo: Path,
) -> dict:
    """Everything that can change the numbers in a benchmark report."""
    repo = Path(repo)
    return {
        "cache_schema": CACHE_SCHEMA,
        "report_schema": REPORT_SCHEMA,
        "dataset": config["dataset"],
        "dataset_root": str(Path(config["dataset_root"]).expanduser().resolve()),
        "sequence": sequence,
        "start": start,
        "count": count,
        "warmup_frames": warmup_frames,
        "repetitions": repetitions,
        "hardware_profile": hardware_profile,
        "policies": list(POLICIES),
        "pipeline": config.get("pipeline"),
        "binary": binary_identity(binary),
        "harness_sha256": _sha256_file(repo / "benchmarks" / "run_benchmark.py"),
        "repo": repo_commit(repo),
        "host": host_identity(),
    }


def cache_key(material: dict) -> str:
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _paths(key: str, directory: Path) -> tuple[Path, Path, Path]:
    return (
        directory / f"{key}.json",
        directory / f"{key}.csv",
        directory / f"{key}.meta.json",
    )


def complete_report(report: object, count: int | None = None) -> bool:
    """True only for a full schema-v2 run covering all four policies."""
    if not isinstance(report, dict) or report.get("schema_version") != REPORT_SCHEMA:
        return False
    policies = report.get("policies")
    provenance = report.get("provenance")
    if not isinstance(policies, dict) or not isinstance(provenance, dict):
        return False
    if not set(POLICIES) <= set(policies):
        return False
    if any(not isinstance(policies[name], dict) for name in POLICIES):
        return False
    if count is not None:
        measured = (provenance.get("frame_range") or {}).get("count")
        if measured is not None and measured != count:
            return False
    return True


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}-{threading.get_ident()}.part"
    )
    try:
        with temporary.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def store(
    key: str,
    material: dict,
    output: Path,
    csv: Path | None,
    *,
    count: int | None = None,
    directory: Path | None = None,
) -> Path | None:
    """Persist a successful full run; returns the cached report path.

    Returns ``None`` (and writes nothing) when the report is not a complete
    four-policy run. The metadata file is renamed last so a reader never
    sees a half-written entry.
    """
    raw = Path(output).read_bytes()
    try:
        report = json.loads(raw)
    except ValueError:
        return None
    if not complete_report(report, count):
        return None
    root = directory if directory is not None else cache_directory()
    root.mkdir(parents=True, exist_ok=True)
    report_path, csv_path, meta_path = _paths(key, root)
    _atomic_write(report_path, raw)
    csv_raw = Path(csv).read_bytes() if csv is not None and Path(csv).is_file() else None
    if csv_raw is not None:
        _atomic_write(csv_path, csv_raw)
    provenance = report.get("provenance") or {}
    meta = {
        "cache_schema": CACHE_SCHEMA,
        "key": key,
        "key_material": material,
        "report_bytes": len(raw),
        "report_sha256": hashlib.sha256(raw).hexdigest(),
        "csv": csv_raw is not None,
        "measured_at": provenance.get("timestamp_utc"),
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "host": (material.get("host") or {}).get("node"),
        "hardware": provenance.get("hardware"),
    }
    _atomic_write(meta_path, json.dumps(meta, sort_keys=True).encode())
    return report_path


def lookup(key: str, directory: Path | None = None) -> dict | None:
    """Return a verified cache entry for ``key`` or ``None``."""
    root = directory if directory is not None else cache_directory()
    report_path, csv_path, meta_path = _paths(key, root)
    try:
        meta = json.loads(meta_path.read_text())
        raw = report_path.read_bytes()
    except (OSError, ValueError):
        return None
    if (
        not isinstance(meta, dict)
        or meta.get("cache_schema") != CACHE_SCHEMA
        or meta.get("key") != key
        or meta.get("report_bytes") != len(raw)
        or meta.get("report_sha256") != hashlib.sha256(raw).hexdigest()
    ):
        return None
    try:
        report = json.loads(raw)
    except ValueError:
        return None
    if not complete_report(report):
        return None
    return {
        "key": key,
        "report": report_path,
        "csv": csv_path if meta.get("csv") and csv_path.is_file() else None,
        "meta": meta,
    }


def cache_descriptor(entry: dict) -> dict:
    """Event fields that label a served report as cached evidence."""
    meta = entry["meta"]
    hardware = meta.get("hardware") if isinstance(meta.get("hardware"), dict) else {}
    return {
        "hit": True,
        "key": entry["key"],
        "measured_at": meta.get("measured_at"),
        "stored_at": meta.get("stored_at"),
        "host": meta.get("host"),
        "processor": hardware.get("processor"),
        "machine": hardware.get("machine"),
    }


def present_delay(stopping: threading.Event, seconds: float = PRESENTATION_DELAY_S) -> bool:
    """Wait the presentation delay; False when the runtime is shutting down."""
    return not stopping.wait(seconds)


def serve_cached(
    entry: dict,
    publish: Callable[[dict], None],
    completion: Callable[[Path, Path], dict],
    stopping: threading.Event,
    delay: Callable[[threading.Event], bool] | None = None,
) -> None:
    """After the presentation delay, announce the cached report as complete."""
    if not (delay or present_delay)(stopping):
        return
    report = Path(entry["report"])
    csv = Path(entry["csv"]) if entry.get("csv") else report.with_suffix(".csv")
    try:
        event = completion(report, csv)
    except Exception as error:  # noqa: BLE001 - worker boundary reports cache failure.
        publish({"type": "benchmark", "state": "error", "error": f"cached benchmark report is unusable: {error}"})
        return
    event["cache"] = cache_descriptor(entry)
    publish(event)
