"""Bounded measured telemetry; unsupported counters stay null."""

import math
import os
import sys
import time
from collections import deque


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


def _valid_pid(pid):
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 0


def rss_bytes(pid):
    """Return current resident bytes when the platform exposes them safely.

    Linux provides current per-process RSS through procfs. The Python standard
    library exposes only peak RSS on macOS and no portable current-process RSS
    on Windows, so those platforms deliberately report unavailable instead of
    relabelling a different measurement.
    """

    if not _valid_pid(pid) or not sys.platform.startswith("linux"):
        return None
    try:
        with open(f"/proc/{pid}/statm", encoding="ascii") as stream:
            fields = stream.read(256).split()
        resident_pages = int(fields[1])
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        if resident_pages < 0 or page_size <= 0:
            return None
        return resident_pages * page_size
    except (OSError, ValueError, IndexError, TypeError, AttributeError):
        return None


def cpu_seconds(pid):
    """Return consumed process CPU seconds, or ``None`` when unavailable.

    The current process is portable via ``time.process_time``. Per-PID CPU time
    is read from Linux procfs; macOS and Windows intentionally stay unavailable
    without an external process-inspection dependency.
    """

    if not _valid_pid(pid):
        return None
    if pid == os.getpid():
        return time.process_time()
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as stream:
            stat = stream.read(4096)
        fields = stat[stat.rfind(")") + 2 :].split()
        consumed_ticks = int(fields[11]) + int(fields[12])
        clock_ticks = int(os.sysconf("SC_CLK_TCK"))
        if consumed_ticks < 0 or clock_ticks <= 0:
            return None
        return consumed_ticks / clock_ticks
    except (OSError, ValueError, IndexError, TypeError, AttributeError):
        return None


class Telemetry:
    def __init__(self, capacity=600):
        self.latencies = deque(maxlen=capacity)
        self.completed = deque(maxlen=capacity)
        self.cpu_previous = {}

    def record(self, elapsed_ms):
        self.latencies.append(elapsed_ms)
        self.completed.append(time.monotonic())

    def report(self, state, frame, visual_ms, pid):
        metrics = frame.get("map", {}).get("metrics", {})
        snapshot = frame.get("map", {}).get("snapshot", {})
        timings = frame.get("perception_timings_ms", {})
        latency = metrics.get("map_update_latency_ns") or {}
        levels = snapshot.get("levels", {})
        topology = metrics.get("topology", {})
        topology_frames = topology.get("per_frame", {})
        now = time.monotonic()

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

        fps = (
            (len(self.completed) - 1) / (self.completed[-1] - self.completed[0])
            if len(self.completed) > 1 and self.completed[-1] > self.completed[0]
            else 0
        )
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
                "perception": sum(timings.values()) if timings else None,
                "ipc": frame.get("runtime_timings_ms", {}).get("bridge"),
                "mapping": latency.get("p50") / 1e6
                if latency.get("p50") is not None
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
                    splits_per_frame * fps if splits_per_frame is not None else None
                ),
                "merges_per_second": (
                    merges_per_frame * fps if merges_per_frame is not None else None
                ),
            },
            "governor": frame.get("map", {}).get("governor")
            or {"state": "unavailable", "budget": None},
            "perception_stages_ms": timings,
        }
