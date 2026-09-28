"""Single-owner playback controller. Desktop commands never execute map work."""

from __future__ import annotations

import copy
import hashlib
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .config import POLICIES, PRESETS, _keys, config_digest, number, validate_config
from .datasets import inspect_dataset, open_adapter
from .protocol import Outbox
from .telemetry import Telemetry
from .visualization import pack_visualization

COMMANDS = {
    "configure": ("config",),
    "config_validate": ("config",),
    "datasets": ("root", "dataset"),
    "start": (),
    "pause": (),
    "step": (),
    "seek": ("index",),
    "reset": (),
    "sequence": ("sequence",),
    "policy": ("policy",),
    "layer": ("layer",),
    "speed": ("speed",),
    "status": (),
    "metrics": (),
    "shutdown": (),
    "governor": ("mode",),
    "benchmark": (
        "dataset",
        "sequence",
        "start",
        "count",
        "repetitions",
        "warmup_frames",
        "hardware_profile",
    ),
    "validation": (),
    "presets": (),
    "diagnostics": (),
}
BENCHMARK_ARTIFACT_LIMIT = 32 * 1024 * 1024
BENCHMARK_REPORT_SCHEMA = 2


def benchmark_completion_event(output: Path, csv: Path) -> dict:
    """Announce a finished benchmark artifact without truncating its evidence.

    Runtime events are capped at 1 MiB, while a complete schema-v2 report grows
    with frame count. The event therefore identifies the authoritative file
    (path, size and SHA-256); the desktop loads that file intact instead of
    receiving a lossy policy summary. ``summary`` is for event logs only.
    """
    raw = output.read_bytes()
    if len(raw) > BENCHMARK_ARTIFACT_LIMIT:
        raise RuntimeError("benchmark artifact exceeds UI import limit")
    report = json.loads(raw)
    if report.get("schema_version") != BENCHMARK_REPORT_SCHEMA:
        raise RuntimeError(
            f"benchmark wrote unsupported report schema {report.get('schema_version')!r}"
        )
    if not isinstance(report.get("provenance"), dict) or not isinstance(
        report.get("policies"), dict
    ):
        raise RuntimeError("benchmark report is missing provenance or policies")
    provenance = report["provenance"]
    return {
        "type": "benchmark",
        "state": "complete",
        "artifact": str(output),
        "csv_artifact": str(csv),
        "artifact_bytes": len(raw),
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "report_schema_version": report["schema_version"],
        "summary": {
            "dataset": report.get("dataset"),
            "sequence": report.get("sequence"),
            "input_frames": report.get("input_frames"),
            "policies": sorted(report["policies"]),
            "git_sha": provenance.get("git_sha"),
            "quality_resource_status": (report.get("quality_resource") or {}).get(
                "status"
            ),
        },
    }


class ProductRuntime:
    def __init__(self, repo, *, command_capacity=32):
        self.repo = Path(repo).resolve()
        self.outbox = Outbox()
        self.commands = queue.Queue(maxsize=command_capacity)
        self.session = None
        self.config = None
        self.state = "unconfigured"
        self.layer = "semantic"
        self.index = -1
        self.generation = 0
        self.error = None
        self.dropped_frames = 0
        self.telemetry = Telemetry()
        self.last_telemetry = None
        self.last_visual = 0.0
        self.next_frame = 0.0
        self.stopping = threading.Event()
        self._status_lock = threading.Lock()
        self._frame_in_flight = threading.Lock()
        self._cached_status = {}
        self._benchmark = None
        self._benchmark_thread = None
        self._artifacts = tempfile.TemporaryDirectory(prefix="veyra-session-")
        self._publish_status()

    def _publish_status(self):
        frames = self._frame_count() if self.session else 0
        status = {
            "state": self.state,
            "dataset": self.config["dataset"] if self.config else None,
            "sequence": self.config["sequence"] if self.config else None,
            "index": self.index,
            "frames": frames,
            "policy": self.config["map"]["policy"] if self.config else "distance_lod",
            "layer": self.layer,
            "speed": self.config["playback"]["speed"] if self.config else 1,
            "generation": self.generation,
            "queue_depth": self.commands.qsize(),
            "dropped_frames": self.dropped_frames,
            "visualization_dropped": self.outbox.visualization_dropped,
            "error": self.error,
            "config_digest": config_digest(self.config) if self.config else None,
        }
        with self._status_lock:
            self._cached_status = status
        self.outbox.publish({"type": "status", **status})

    def _frame_count(self):
        if self.session is None:
            return 0
        total = self.session.status()["frames"]
        playback = self.config["playback"] if self.config else {}
        if playback.get("full_sequence", False):
            return total
        return min(total, playback.get("frame_limit", total))

    def status(self):
        with self._status_lock:
            result = dict(self._cached_status)
        result["queue_depth"] = self.commands.qsize()
        result["visualization_dropped"] = self.outbox.visualization_dropped
        return result

    def submit(self, request):
        try:
            self.commands.put_nowait(request)
        except queue.Full:
            self.outbox.publish(
                {
                    "type": "response",
                    "id": request.get("id"),
                    "ok": False,
                    "status": self.status(),
                    "error": {
                        "code": "queue_full",
                        "message": "Runtime command queue is full",
                    },
                }
            )

    def handle(self, request):
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            _keys(request, ("id", "command", "args"), "request")
            if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                raise ValueError("request id must be a short string")
            command = request.get("command")
            if command not in COMMANDS:
                raise ValueError("unknown runtime command")
            args = request.get("args", {})
            _keys(args, COMMANDS[command], "command arguments")
            result = self._execute(command, args)
            self._publish_status()
            return {
                "type": "response",
                "id": request_id,
                "ok": True,
                "status": self.status(),
                "result": result,
            }
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
            return {
                "type": "response",
                "id": request_id,
                "ok": False,
                "status": self.status(),
                "error": {"code": "runtime_error", "message": str(error)},
            }

    def _create_session(self, config):
        from viewer.runtime import PersistentMapEngine, RuntimeSession

        adapter = open_adapter(config["dataset"], config["dataset_root"])
        if config["sequence"] not in adapter.list_sequences():
            raise ValueError("sequence is not present in dataset")
        engine = PersistentMapEngine(
            config["map"]["executable"],
            policy=config["map"]["policy"],
            window_radius_m=config["map"]["window_radius_m"],
            transport="binary",
            clear_free_space=config["map"].get("clear_free_space", False),
            utility_config=self.repo / "configs" / "utility_lod.yaml",
            governor_config=self.repo
            / "configs"
            / f"resource_governor-{config['map']['resource_profile']}.yaml",
        )
        try:
            session = RuntimeSession.from_adapter(
                adapter,
                dataset=config["dataset"],
                sequence=config["sequence"],
                pipeline_config=config["pipeline"],
                map_runner=engine,
                repo_root=self.repo,
            )
            status = engine.status()
            if status.get("status") != "available":
                raise RuntimeError(status.get("reason", "mapper failed to start"))
            if config["map"]["policy"] == "utility_lod":
                override = engine.set_governor_override(
                    config["map"]["governor_override"]
                )
                if override.get("status") != "available":
                    raise RuntimeError(
                        override.get("reason", "governor configuration failed")
                    )
            return session
        except Exception:
            engine.close()
            raise

    def _configure(self, config):
        config = validate_config(config, self.repo)
        replacement = self._create_session(config)
        previous, self.session = self.session, replacement
        if previous:
            previous.close()
        self.config = config
        self.state, self.index, self.error = "ready", -1, None
        self.dropped_frames = 0
        self.generation += 1
        self.telemetry = Telemetry()
        self.last_visual = 0
        return {"config": config, "config_digest": config_digest(config)}

    def _execute(self, command, args):
        if command == "status":
            return self.status()
        if command == "metrics":
            return self.last_telemetry or {
                "status": "unavailable",
                "reason": "no frame processed",
            }
        if command == "shutdown":
            self.stopping.set()
            return None
        if command == "presets":
            return PRESETS
        if command == "diagnostics":
            return {
                "status": self.status(),
                "config": self.config,
                "python": sys.version,
                "platform": sys.platform,
            }
        if command == "datasets":
            return inspect_dataset(args["root"], args.get("dataset"))
        if command == "config_validate":
            config = validate_config(args["config"], self.repo)
            from viewer.runtime import build_pipeline

            build_pipeline(config["pipeline"], repo_root=self.repo)
            return {"config": config, "config_digest": config_digest(config)}
        if command == "configure":
            return self._configure(args["config"])
        if command == "layer":
            layer = args["layer"]
            if layer not in (
                "semantic",
                "elevation",
                "ground",
                "terrain",
                "traversability",
                "motion",
                "lod",
                "utility",
            ):
                raise ValueError("unsupported layer")
            self.layer = layer
            return {"layer": self.layer}
        if self.session is None:
            raise ValueError("configure a dataset before playback")
        if command == "benchmark":
            return self._start_benchmark(args)
        if command == "validation":
            if self.session is None or self.config is None:
                raise ValueError("configure a dataset before validation")
            target = max(0, self.index)
            started = time.perf_counter()
            frame = self.session.frame_payload(
                target, budget=self.config["visualization"]["point_budget"], binary=True
            )
            map_status = frame.get("map", {}).get("status")
            pipeline = frame.get("pipeline_status", {})
            semantic = pipeline.get("semantic", "unavailable")
            ground = pipeline.get("ground", "unavailable")
            terrain = pipeline.get("terrain", "unavailable")
            semantic_requested = pipeline.get(
                "semantic_requested", pipeline.get("semantic_requested_mode")
            )
            semantic_fallback_reason = pipeline.get("semantic_fallback_reason")
            semantic_model = pipeline.get("semantic_model")
            allow_fallback = (self.config or {}).get("pipeline", {}).get(
                "semantic", {}
            ).get("allow_fallback_to_ground_truth") is True
            fallback_without_approval = bool(
                semantic_fallback_reason and not allow_fallback
            )
            result = {
                "status": "pass"
                if map_status == "available"
                and semantic != "unavailable"
                and not fallback_without_approval
                else "fail",
                "dataset": self.config["dataset"],
                "sequence": self.config["sequence"],
                "frame": target,
                "points": frame.get("n_points"),
                "semantic": semantic,
                "semantic_requested": semantic_requested,
                "semantic_actual": semantic,
                "semantic_fallback_reason": semantic_fallback_reason,
                "semantic_model": semantic_model,
                "ground": ground,
                "terrain": terrain,
                "map": map_status,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
                "diagnostics": frame.get("pipeline_status", {}).get("diagnostics", []),
            }
            self.outbox.publish(
                {"type": "validation", "state": "complete", "result": result}
            )
            if result["status"] != "pass":
                raise RuntimeError(
                    "session validation failed: " + "; ".join(result["diagnostics"])
                )
            return result
        if command == "start":
            if self.state == "error":
                raise RuntimeError("reset the failed session before restarting")
            if self.index >= self.status()["frames"] - 1:
                self._configure(self.config)
            self.state = "running"
            self.next_frame = time.monotonic()
            return None
        if command == "pause":
            self.state = "paused"
            return None
        if command == "speed":
            self.config["playback"]["speed"] = number(args["speed"], "speed", 0.1, 8)
            return None
        if command == "governor":
            mode = args["mode"]
            if mode not in ("automatic", "disabled", "conserve"):
                raise ValueError("unsupported governor override")
            response = self.session.map_runner.set_governor_override(mode)
            if response.get("status") != "available":
                raise RuntimeError(response.get("reason", "governor unavailable"))
            return {"governor": response.get("governor")}
        if command in ("reset", "sequence", "policy"):
            config = copy.deepcopy(self.config)
            if command == "sequence":
                if not isinstance(args["sequence"], str):
                    raise ValueError("sequence must be a string")
                config["sequence"] = args["sequence"]
            if command == "policy":
                if args["policy"] not in POLICIES:
                    raise ValueError("unsupported map policy")
                config["map"]["policy"] = args["policy"]
            return self._configure(config)
        if command in ("step", "seek"):
            target = (
                min(self.index + 1, self.status()["frames"] - 1)
                if command == "step"
                else number(
                    args["index"], "index", 0, self.status()["frames"] - 1, True
                )
            )
            if target < self.index:
                self.generation += 1
            self.state = "paused"
            self._process(target, force_visual=True)
            return None
        raise ValueError("unsupported command")

    def _process(self, target, force_visual=False):
        if not self._frame_in_flight.acquire(blocking=False):
            raise RuntimeError("frame already in flight")
        try:
            return self._process_locked(target, force_visual=force_visual)
        finally:
            self._frame_in_flight.release()

    def _should_publish_visual(self, *, force_visual):
        """Commands force their final visual; playback remains capped at 2 Hz."""

        return force_visual or (
            time.monotonic() - self.last_visual
            >= 1 / self.config["visualization"]["update_hz"]
        )

    def _process_locked(self, target, force_visual=False):
        started = time.perf_counter()
        try:
            frame = self.session.frame_payload(
                target, budget=self.config["visualization"]["point_budget"], binary=True
            )
            if frame["map"].get("status") != "available":
                raise RuntimeError(
                    "mapper: " + frame["map"].get("reason", "map unavailable")
                )
            semantic_status = frame["pipeline_status"]["semantic"]
            if semantic_status == "unavailable":
                raise RuntimeError(
                    "perception: semantic provider unavailable; "
                    + "; ".join(frame["pipeline_status"]["diagnostics"])
                )
            fallback_reason = frame["pipeline_status"].get("semantic_fallback_reason")
            allow_fallback = (self.config or {}).get("pipeline", {}).get(
                "semantic", {}
            ).get("allow_fallback_to_ground_truth") is True
            if fallback_reason and not allow_fallback:
                raise RuntimeError(
                    "perception: semantic fallback to ground_truth requires "
                    "explicit approval "
                    "(pipeline.semantic.allow_fallback_to_ground_truth must be "
                    f"true); reason: {fallback_reason}"
                )
            self.index = target
            dropped = (frame["map"].get("metrics", {}).get("stream") or {}).get(
                "dropped_frames"
            )
            if isinstance(dropped, int):
                self.dropped_frames = dropped
            visual_ms = None
            if self._should_publish_visual(force_visual=force_visual):
                visual_start = time.perf_counter()
                cells = self.session.map_cells_binary(
                    budget=self.config["visualization"]["cell_budget"]
                )
                if cells.get("status") != "available":
                    raise RuntimeError(
                        "mapper: "
                        + cells.get("reason", "map visualization unavailable")
                    )
                metadata, payload = pack_visualization(frame, cells, self.generation)
                self.outbox.publish(metadata, payload)
                visual_ms = (time.perf_counter() - visual_start) * 1000
                self.last_visual = time.monotonic()
            self.telemetry.record((time.perf_counter() - started) * 1000)
            self._publish_status()
            self.last_telemetry = self.telemetry.report(
                self.status(),
                frame,
                visual_ms,
                self.session.map_runner.pid,
                (self.config or {}).get("pipeline", {}).get("semantic", {}),
            )
            self.outbox.publish(self.last_telemetry)
        except Exception as error:
            self.state = "error"
            self.error = {
                "process": "mapper" if "mapper:" in str(error) else "perception",
                "message": str(error),
            }
            self._publish_status()
            Path(self._artifacts.name, "crash.json").write_text(
                json.dumps(
                    {
                        "status": self.status(),
                        "config_digest": config_digest(self.config),
                    },
                    indent=2,
                )
            )
            raise

    def tick(self):
        if self.state != "running" or time.monotonic() < self.next_frame:
            return
        if self.index >= self.status()["frames"] - 1:
            self.state = "ended"
            self._publish_status()
            return
        started = time.monotonic()
        self._process(self.index + 1)
        self.next_frame = started + 1 / (
            self.config["playback"]["fps"] * self.config["playback"]["speed"]
        )

    def _benchmark_binary(self) -> Path:
        """Resolve the benchmark executable for packaged and dev layouts.

        Packaged backends stage it under ``bin/`` next to the mapper;
        development checkouts keep it under ``build/``. A missing binary
        is an explicit error, never a silent fallback to another tool.
        """
        name = "veyra_benchmark.exe" if sys.platform == "win32" else "veyra_benchmark"
        staged = self.repo / "bin" / name
        if staged.is_file():
            return staged
        fallback = self.repo / "build/apps/benchmark" / name
        if fallback.is_file():
            return fallback
        raise ValueError(
            "benchmark executable is not available: expected "
            f"{staged} (staged package) or {fallback} (development build)"
        )

    def _start_benchmark(self, args):
        if self._benchmark_thread and self._benchmark_thread.is_alive():
            raise ValueError("benchmark already running")
        dataset = args.get("dataset", self.config["dataset"])
        sequence = args.get("sequence", self.config["sequence"])
        if (
            dataset != self.config["dataset"]
            or sequence not in self.session.adapter.list_sequences()
        ):
            raise ValueError("benchmark selection must use the configured dataset")
        start = number(
            args.get("start", 0), "start", 0, self.status()["frames"] - 1, True
        )
        count = number(
            args.get("count", min(10, self.status()["frames"] - start)),
            "count",
            1,
            100000,
            True,
        )
        repetitions = number(args.get("repetitions", 1), "repetitions", 1, 20, True)
        warmup = number(
            args.get("warmup_frames", 0), "warmup_frames", 0, count - 1, True
        )
        if count > self.status()["frames"] - start:
            raise ValueError(
                f"benchmark requests {count} frames from frame {start}, but this "
                f"session provides {self.status()['frames']} (the playback frame "
                "limit applies unless full_sequence is enabled)"
            )
        profile = args.get("hardware_profile", "auto")
        if not isinstance(profile, str) or len(profile) > 128:
            raise ValueError("invalid hardware profile")
        directory = Path(self._artifacts.name)
        config_file = directory / "perception.json"
        config_file.write_text(json.dumps(self.config["pipeline"]))
        output, csv = directory / "benchmark.json", directory / "benchmark.csv"
        binary = self._benchmark_binary()
        command = [
            sys.executable,
            "-m",
            "benchmarks.run_benchmark",
            "--repo",
            str(self.repo),
            "--binary",
            str(binary),
            "--dataset",
            dataset,
            "--dataset-root",
            self.config["dataset_root"],
            "--sequence",
            sequence,
            "--start",
            str(start),
            "--count",
            str(count),
            "--warmup-frames",
            str(warmup),
            "--repetitions",
            str(repetitions),
            "--hardware-profile",
            profile,
            "--output",
            str(output),
            "--csv-output",
            str(csv),
            "--perception-config",
            str(config_file),
        ]
        self.state = "paused"

        def run():
            log = directory / "benchmark.log"
            try:
                with log.open("wb") as stream:
                    self._benchmark = subprocess.Popen(
                        command, cwd=self.repo, stdout=stream, stderr=stream
                    )
                    code = self._benchmark.wait()
                if code:
                    raise RuntimeError(log.read_text(errors="replace")[-4096:])
                self.outbox.publish(benchmark_completion_event(output, csv))
            except Exception as error:  # noqa: BLE001 - worker boundary reports benchmark failure.
                self.outbox.publish(
                    {"type": "benchmark", "state": "error", "error": str(error)}
                )
            finally:
                self._benchmark = None

        self._benchmark_thread = threading.Thread(target=run, daemon=True)
        self._benchmark_thread.start()
        return {"state": "running"}

    def run(self):
        while not self.stopping.is_set():
            try:
                request = self.commands.get(timeout=0.02)
            except queue.Empty:
                request = None
            if request is not None:
                self.outbox.publish(self.handle(request))
                self.commands.task_done()
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001 - keep the playback worker alive to close cleanly.
                self.error = str(error)
                self.stopping.set()
        self.close()

    def close(self):
        self.stopping.set()
        if self._benchmark is not None and self._benchmark.poll() is None:
            self._benchmark.terminate()
            try:
                self._benchmark.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._benchmark.kill()
                self._benchmark.wait(timeout=2)
        if self._benchmark_thread:
            self._benchmark_thread.join(timeout=3)
        if self.session:
            self.session.close()
            self.session = None
        self.state = "stopped"
        self._publish_status()
        self.outbox.close()
        # Artifacts persist for the desktop session; native export reads them before shutdown.
        self._artifacts.cleanup()
