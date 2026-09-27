"""Strict product configuration composed around existing subsystem settings."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

POLICIES = ("uniform5", "uniform40", "distance_lod", "utility_lod")
DATASETS = ("rellis3d", "semanticposs", "semantickitti", "generic")
DEFAULT_PIPELINE = {
    "semantic": {"mode": "ground_truth"},
    "ground": {
        "enabled": True,
        "parameter_overrides": {"min_range": 0.0, "max_range": 100.0},
    },
    "terrain": {"enabled": True},
    "temporal": {"enabled": False},
}
PRESETS = {
    "LowResource": {
        "map": {
            "policy": "distance_lod",
            "resource_profile": "performance",
            "governor_override": "automatic",
        },
        "playback": {
            "fps": 10,
            "frame_limit": 30,
            "full_sequence": False,
        },
        "visualization": {
            "point_budget": 15000,
            "cell_budget": 10000,
            "update_hz": 2,
            "max_in_flight": 1,
        },
    },
    "Performance": {
        "map": {"resource_profile": "performance", "governor_override": "automatic"},
        "playback": {"fps": 10},
        "visualization": {
            "point_budget": 20000,
            "cell_budget": 10000,
            "update_hz": 10,
            "max_in_flight": 1,
        },
    },
    "Balanced": {
        "map": {"resource_profile": "balanced", "governor_override": "automatic"},
        "playback": {"fps": 10},
        "visualization": {
            "point_budget": 50000,
            "cell_budget": 20000,
            "update_hz": 15,
            "max_in_flight": 1,
        },
    },
    "Quality": {
        "map": {"resource_profile": "quality", "governor_override": "automatic"},
        "playback": {"fps": 10},
        "visualization": {
            "point_budget": 100000,
            "cell_budget": 50000,
            "update_hz": 30,
            "max_in_flight": 1,
        },
    },
}


def _keys(value, allowed, name):
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f"unknown {name} fields: {', '.join(sorted(unknown))}")


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


def normalized_pipeline(value):
    """Apply explicit production defaults without sharing mutable config state."""

    if value is None:
        return copy.deepcopy(DEFAULT_PIPELINE)
    if not isinstance(value, dict):
        raise TypeError("pipeline must be an object")
    pipeline = copy.deepcopy(DEFAULT_PIPELINE)
    for name, settings in value.items():
        if name in pipeline and isinstance(settings, dict):
            pipeline[name].update(copy.deepcopy(settings))
        else:
            pipeline[name] = copy.deepcopy(settings)
    return pipeline


def _merged_section(preset, supplied, name):
    value = copy.deepcopy(preset.get(name, {}))
    value.update(copy.deepcopy(supplied.get(name, {})))
    return value


def validate_config(config, repo: Path, *, check_paths=True):
    _keys(
        config,
        (
            "dataset",
            "dataset_root",
            "sequence",
            "preset",
            "pipeline",
            "map",
            "playback",
            "visualization",
        ),
        "config",
    )
    preset_name = config.get("preset", "LowResource")
    if preset_name not in PRESETS:
        raise ValueError("unsupported runtime preset")
    preset = PRESETS[preset_name]
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
    map_config = _merged_section(preset, config, "map")
    _keys(
        map_config,
        (
            "executable",
            "policy",
            "window_radius_m",
            "resource_profile",
            "governor_override",
            "clear_free_space",
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
    clear_free_space = map_config.get("clear_free_space", False)
    if not isinstance(clear_free_space, bool):
        raise TypeError("map clear_free_space must be a boolean")
    pipeline = normalized_pipeline(config.get("pipeline"))
    playback = _merged_section(preset, config, "playback")
    _keys(playback, ("fps", "speed", "frame_limit", "full_sequence"), "playback")
    playback = {
        "fps": number(playback.get("fps", 10), "fps", 0.1, 120),
        "speed": number(playback.get("speed", 1), "speed", 0.1, 8),
        "frame_limit": number(
            playback.get("frame_limit", 30), "frame_limit", 1, 1000000, True
        ),
        "full_sequence": playback.get("full_sequence", False),
    }
    if not isinstance(playback["full_sequence"], bool):
        raise TypeError("playback full_sequence must be a boolean")
    visual = _merged_section(preset, config, "visualization")
    _keys(
        visual,
        ("point_budget", "cell_budget", "update_hz", "max_in_flight"),
        "visualization",
    )
    visual = {
        "point_budget": number(
            visual.get("point_budget", 50000), "point_budget", 1, 100000, True
        ),
        "cell_budget": number(
            visual.get("cell_budget", 20000), "cell_budget", 1, 100000, True
        ),
        "update_hz": number(visual.get("update_hz", 15), "update_hz", 1, 60),
        "max_in_flight": number(
            visual.get("max_in_flight", 1), "max_in_flight", 1, 1, True
        ),
    }
    return {
        "preset": preset_name,
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
            "clear_free_space": clear_free_space,
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
