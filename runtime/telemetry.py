"""Bounded measured telemetry; unsupported counters stay null."""

import ctypes
import ctypes.util
import math
import os
import sys
import time
from collections import deque

import numpy as np


def summary(values):
    values = sorted(values)
    if not values:
        return {"count": 0, "p50": None, "p95": None, "p99": None}
    return {
        "count": len(values),
        **{
            name: values[max(0, math.ceil(len(values) * p) - 1)]
            for name, p in [("p50", 0.5), ("p95", 0.95), ("p99", 0.99)]
        },
    }


class _ProcTaskInfo(ctypes.Structure):
    """Darwin ``struct proc_taskinfo`` (sys/proc_info.h), PROC_PIDTASKINFO."""

    _fields_ = [
        ("pti_virtual_size", ctypes.c_uint64),
        ("pti_resident_size", ctypes.c_uint64),
        ("pti_total_user", ctypes.c_uint64),
        ("pti_total_system", ctypes.c_uint64),
        ("pti_threads_user", ctypes.c_uint64),
        ("pti_threads_system", ctypes.c_uint64),
        ("pti_policy", ctypes.c_int32),
        ("pti_faults", ctypes.c_int32),
        ("pti_pageins", ctypes.c_int32),
        ("pti_cow_faults", ctypes.c_int32),
        ("pti_messages_sent", ctypes.c_int32),
        ("pti_messages_received", ctypes.c_int32),
        ("pti_syscalls_mach", ctypes.c_int32),
        ("pti_syscalls_unix", ctypes.c_int32),
        ("pti_csw", ctypes.c_int32),
        ("pti_threadnum", ctypes.c_int32),
        ("pti_numrunning", ctypes.c_int32),
        ("pti_priority", ctypes.c_int32),
    ]


class _MachTimebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


_PROC_PIDTASKINFO = 4
_darwin = None


def _darwin_task_info(pid):
    """Resident bytes and CPU seconds of any process on macOS, else None.

    macOS has no /proc. libproc's proc_pidinfo reports another process's
    task counters; CPU times are in mach absolute-time units, which are not
    nanoseconds on Apple Silicon, so they are scaled by the mach timebase.
    """
    global _darwin
    if sys.platform != "darwin":
        return None
    if _darwin is None:
        try:
            libc = ctypes.CDLL(ctypes.util.find_library("c") or "libSystem.dylib")
            timebase = _MachTimebase()
            libc.mach_timebase_info(ctypes.byref(timebase))
            libc.proc_pidinfo.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint64,
                ctypes.c_void_p,
                ctypes.c_int,
            ]
            libc.proc_pidinfo.restype = ctypes.c_int
            _darwin = (libc, timebase.numer / timebase.denom if timebase.denom else 1.0)
        except (OSError, AttributeError):
            _darwin = False
    if not _darwin:
        return None
    libc, ns_per_tick = _darwin
    info = _ProcTaskInfo()
    size = libc.proc_pidinfo(
        int(pid), _PROC_PIDTASKINFO, 0, ctypes.byref(info), ctypes.sizeof(info)
    )
    if size != ctypes.sizeof(info):
        return None
    ticks = info.pti_total_user + info.pti_total_system
    return info.pti_resident_size, ticks * ns_per_tick / 1e9


def rss_bytes(pid):
    if pid is None:
        return None
    darwin = _darwin_task_info(pid)
    if darwin is not None:
        return darwin[0] or None
    try:
        with open(f"/proc/{pid}/statm") as stream:
            fields = stream.read(256).split()
        return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError, AttributeError):
        return None


def cpu_seconds(pid):
    if pid is None:
        return None
    if pid == os.getpid():
        return time.process_time()
    darwin = _darwin_task_info(pid)
    if darwin is not None:
        return darwin[1]
    try:
        with open(f"/proc/{pid}/stat") as stream:
            stat = stream.read(4096)
        fields = stat[stat.rfind(")") + 2 :].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, AttributeError):
        return None


FPS_WINDOW_S = 5.0


def processing_fps(completed, window_s=FPS_WINDOW_S):
    """Throughput over the completions in the trailing window.

    Measuring across the whole history counted idle time (opening a preview,
    pausing) as processing time and reported e.g. 0.1 fps while frames were
    completing at ~2 fps.
    """
    if not completed:
        return None
    recent = [stamp for stamp in completed if completed[-1] - stamp <= window_s]
    if len(recent) < 2 or recent[-1] <= recent[0]:
        return None
    return (len(recent) - 1) / (recent[-1] - recent[0])


class Telemetry:
    def __init__(self, capacity=600):
        self.latencies = deque(maxlen=capacity)
        self.completed = deque(maxlen=capacity)
        self.cpu_previous = {}

    def record(self, elapsed_ms):
        self.latencies.append(elapsed_ms)
        self.completed.append(time.monotonic())

    def report(self, state, frame, visual_ms, pid, semantic_config=None):
        metrics = frame.get("map", {}).get("metrics", {})
        snapshot = frame.get("map", {}).get("snapshot", {})
        timings = frame.get("perception_timings_ms", {})
        pipeline_status = frame.get("pipeline_status", {})
        latency = metrics.get("map_update_latency_ns") or {}
        levels = snapshot.get("levels", {})
        topology = metrics.get("topology", {})
        topology_frames = topology.get("per_frame", {})
        now = time.monotonic()
        semantic_config = semantic_config or {}

        def counts(values):
            if values is None:
                return None
            array = np.asarray(values)
            if array.size == 0:
                return {}
            unique, amounts = np.unique(array, return_counts=True)
            return {str(value): int(amount) for value, amount in zip(unique, amounts)}

        def finite_mean(values):
            if values is None:
                return None
            array = np.asarray(values, dtype=float)
            finite = array[np.isfinite(array)]
            return float(finite.mean()) if finite.size else None

        ground = frame.get("ground")
        semantic = frame.get("semantic_labels")
        point_count = int(
            frame.get("n_points") or (len(semantic) if semantic is not None else 0)
        )
        # Fail closed on unknown provenance: a missing ground status means the
        # stage did not report, so the ratio stays UNAVAILABLE (None) rather
        # than rendering a plausible-looking number from whatever array is
        # present. The real PipelineStatus dataclass + viewer serializer always
        # forward all four stage keys, so None only occurs on synthetic inputs
        # or a dropped-key plumbing fault -- both must not read as measured.
        # (See PR #42 da881f6 / iteration-01 audit; reverts the PR #41
        # telemetry hunk, keeps its pandora.py FOV edge tolerance.)
        ground_count = (
            int(np.count_nonzero(np.asarray(ground)))
            if ground is not None
            and pipeline_status.get("ground")
            not in {None, "unavailable", "disabled", "invalid", "skipped"}
            else None
        )
        semantic_counts = counts(semantic)
        # Runtime-verified execution device wins over static config: the
        # running provider reports what it actually uses; config may be stale.
        # Ground Truth bypasses neural inference by construction.
        runtime_execution = pipeline_status.get("semantic_execution")
        if runtime_execution in (None, "", "unavailable"):
            runtime_execution = None
        execution_provider = runtime_execution or semantic_config.get(
            "execution_provider"
        )
        provider = (
            semantic_config.get("provider")
            or semantic_config.get("backend")
            or semantic_config.get("mode")
        )
        model = semantic_config.get("model") or semantic_config.get("checkpoint")
        if provider == "ground_truth":
            provider = "Ground Truth"
            if not execution_provider:
                execution_provider = "bypassed"
        semantic_status = pipeline_status.get("semantic", "unavailable")

        def cpu_percent(process_id):
            current = cpu_seconds(process_id)
            previous = self.cpu_previous.get(process_id)
            self.cpu_previous[process_id] = (now, current)
            if (
                current is None
                or previous is None
                or previous[1] is None
                or now <= previous[0]
            ):
                return None
            return 100 * (current - previous[1]) / (now - previous[0])

        fps = processing_fps(self.completed)
        splits_per_frame = (topology_frames.get("splits") or {}).get("mean")
        merges_per_frame = (topology_frames.get("merges") or {}).get("mean")
        return {
            "type": "telemetry",
            "schema_version": 1,
            "timestamp": time.time(),
            **{
                key: state[key]
                for key in (
                    "state",
                    "index",
                    "frames",
                    "queue_depth",
                    "dropped_frames",
                    "visualization_dropped",
                )
            },
            "fps": fps,
            "latency_ms": {
                "end_to_end": summary(self.latencies),
                "perception": timings.get("total")
                if "total" in timings
                else sum(timings.values())
                if timings
                else None,
                "ipc": frame.get("runtime_timings_ms", {}).get("bridge"),
                "mapping": latency.get("p50") / 1e6
                if latency.get("p50") is not None
                else None,
                "mapping_p50": latency.get("p50") / 1e6
                if latency.get("p50") is not None
                else None,
                "mapping_p95": latency.get("p95") / 1e6
                if latency.get("p95") is not None
                else None,
                "mapping_p99": latency.get("p99") / 1e6
                if latency.get("p99") is not None
                else None,
                "visualization": visual_ms,
            },
            "processes": [
                {
                    "name": "runtime",
                    "pid": os.getpid(),
                    "cpu_percent": cpu_percent(os.getpid()),
                    "rss_bytes": rss_bytes(os.getpid()),
                },
                {
                    "name": "mapper",
                    "pid": pid,
                    "cpu_percent": cpu_percent(pid),
                    "rss_bytes": rss_bytes(pid),
                },
            ],
            "map": {
                "active_cells": snapshot.get("active_leaf_count"),
                "cells_by_level": [levels.get(str(level), 0) for level in range(4)],
                "logical_bytes": metrics.get("logical_map_bytes"),
                "allocated_bytes": metrics.get("allocated_map_bytes"),
                "topology_changes": snapshot.get("topology_change_count"),
                "splits_per_frame": splits_per_frame,
                "merges_per_frame": merges_per_frame,
                "splits_per_second": (
                    splits_per_frame * fps
                    if splits_per_frame is not None and fps is not None
                    else None
                ),
                "merges_per_second": (
                    merges_per_frame * fps
                    if merges_per_frame is not None and fps is not None
                    else None
                ),
            },
            "governor": frame.get("map", {}).get("governor")
            or {"state": "unavailable", "budget": None},
            "perception_stages_ms": timings,
            "perception": {
                "status": {
                    name: pipeline_status.get(name, "unavailable")
                    for name in ("semantic", "ground", "terrain", "temporal")
                },
                "provenance": frame.get("pose", {}).get("provenance", {}),
                "backend": semantic_status,
                "provider": provider,
                "model": model,
                "execution_provider": execution_provider,
                "points": point_count,
                "sampled_points": len(semantic) if semantic is not None else None,
                "ground_ratio": (
                    ground_count / len(ground)
                    if ground_count is not None and len(ground)
                    else None
                ),
                "semantic_confidence_mean": finite_mean(
                    frame.get("semantic_confidence")
                ),
                "unknown_ratio": (
                    semantic_counts.get("0", 0) / len(semantic)
                    if semantic_counts is not None and len(semantic)
                    else None
                ),
                "drivable_counts": counts(frame.get("drivable")),
                "semantic_class_counts": semantic_counts,
                "motion_point_counts": counts(frame.get("motion_state")),
                "track_counts": None,
            },
            "health": {
                "runtime": state.get("state", "unavailable"),
                "perception": semantic_status,
                "mapper": "available" if snapshot else "unavailable",
                "telemetry": "fresh",
            },
        }
