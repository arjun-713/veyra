"""Strict product configuration composed around existing subsystem settings."""

from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

POLICIES = ("uniform5", "uniform40", "distance_lod", "utility_lod")
DATASETS = ("rellis3d", "semanticposs", "semantickitti", "generic")
PRESETS = {
    "Performance": {
        "map": {"resource_profile": "performance", "governor_override": "automatic"},
        "playback": {"fps": 10},
        "visualization": {"point_budget": 20000, "cell_budget": 10000, "update_hz": 10},
    },
    "Balanced": {
        "map": {"resource_profile": "balanced", "governor_override": "automatic"},
        "playback": {"fps": 10},
        "visualization": {"point_budget": 50000, "cell_budget": 20000, "update_hz": 15},
    },
    "Quality": {
        "map": {"resource_profile": "quality", "governor_override": "automatic"},
        "playback": {"fps": 10},
        "visualization": {
            "point_budget": 100000,
            "cell_budget": 50000,
            "update_hz": 30,
        },
    },
}


def _keys(value, allowed, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f'unknown {name} fields: {", ".join(sorted(unknown))}')


def number(value, name, minimum, maximum, integer=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number")
    if not minimum <= value <= maximum or (integer and int(value) != value):
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return int(value) if integer else float(value)


def validate_config(config, repo: Path, *, check_paths=True):
    _keys(
        config,
        (
            "dataset",
            "dataset_root",
            "sequence",
            "pipeline",
            "map",
            "playback",
            "visualization",
        ),
        "config",
    )
    if config.get("dataset") not in DATASETS:
        raise ValueError("unsupported dataset")
    if (
        not isinstance(config.get("sequence"), str)
        or not config["sequence"]
        or len(config["sequence"]) > 256
    ):
        raise ValueError("sequence must be a nonempty string")
    if not isinstance(config.get("dataset_root"), str) or not config["dataset_root"]:
        raise ValueError("dataset_root is required")
    root = Path(config["dataset_root"]).expanduser().resolve()
    if check_paths and not root.is_dir():
        raise ValueError(f"dataset root does not exist: {root}")
    map_config = dict(config.get("map", {}))
    _keys(
        map_config,
        (
            "executable",
            "policy",
            "window_radius_m",
            "resource_profile",
            "governor_override",
        ),
        "map",
    )
    policy = map_config.get("policy", "distance_lod")
    if policy not in POLICIES:
        raise ValueError("unsupported map policy")
    executable = Path(map_config.get("executable", "build/apps/runtime/veyra_runtime"))
    if not executable.is_absolute():
        executable = repo / executable
    if check_paths and not executable.is_file():
        raise ValueError(f"mapper executable does not exist: {executable}")
    try:
        executable.resolve().relative_to(repo.resolve())
    except ValueError as error:
        raise ValueError(
            "mapper executable must be an installed Veyra backend"
        ) from error
    radius = number(
        map_config.get("window_radius_m", 100.001), "window_radius_m", 60.001, 10000
    )
    resource_profile = map_config.get("resource_profile", "balanced")
    if resource_profile not in ("performance", "balanced", "quality"):
        raise ValueError("unsupported resource profile")
    governor_override = map_config.get("governor_override", "automatic")
    if governor_override not in ("automatic", "disabled", "conserve"):
        raise ValueError("unsupported governor override")
    pipeline = config.get("pipeline", {"semantic": {"mode": "ground_truth"}})
    if not isinstance(pipeline, dict):
        raise ValueError("pipeline must be an object")
    playback = dict(config.get("playback", {}))
    _keys(playback, ("fps", "speed"), "playback")
    playback = {
        "fps": number(playback.get("fps", 10), "fps", 0.1, 120),
        "speed": number(playback.get("speed", 1), "speed", 0.1, 8),
    }
    visual = dict(config.get("visualization", {}))
    _keys(visual, ("point_budget", "cell_budget", "update_hz"), "visualization")
    visual = {
        "point_budget": number(
            visual.get("point_budget", 50000), "point_budget", 1, 100000, True
        ),
        "cell_budget": number(
            visual.get("cell_budget", 20000), "cell_budget", 1, 100000, True
        ),
        "update_hz": number(visual.get("update_hz", 15), "update_hz", 1, 60),
    }
    return {
        "dataset": config["dataset"],
        "dataset_root": str(root),
        "sequence": config["sequence"],
        "pipeline": pipeline,
        "map": {
            "executable": str(executable),
            "policy": policy,
            "window_radius_m": radius,
            "resource_profile": resource_profile,
            "governor_override": governor_override,
        },
        "playback": playback,
        "visualization": visual,
    }


def config_digest(config):
    return hashlib.sha256(
        json.dumps(
            config, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()
