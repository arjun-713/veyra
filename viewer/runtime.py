"""Configurable local playback runtime for real Veyra dataset adapters.

The runtime deliberately composes public dataset and perception interfaces; it
does not duplicate either subsystem.  It serializes only decimated views for
the browser.  Map results are optional and are surfaced only when the existing
``veyra_benchmark`` executable returned an actual report.
"""

from __future__ import annotations

import io
import json
import queue
import subprocess
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from benchmarks.protocol import PROTOCOL_VERSION, BinaryFrameEncoder, frame_records
from datasets.common.adapter import DatasetAdapter
from perception.pipeline import PerceptionPipeline


class RuntimeConfigurationError(ValueError):
    """The viewer runtime configuration cannot safely be applied."""


class DatasetUnavailableError(FileNotFoundError):
    """The selected local dataset adapter cannot be constructed."""


_DATASETS = frozenset({"generic", "rellis3d", "semanticposs", "semantickitti"})


@dataclass(frozen=True)
class RuntimeConfig:
    dataset: str
    sequence: str
    pipeline: dict[str, Any]
    map: dict[str, Any]


# Seventeen float32 per display cell (visualization schema v3); 100,000
# cells is the engine's budget ceiling.
_CELL_ROW_BYTES = 17 * 4
_PHYSICAL_LAYER_ROW_BYTES = 15 * 4
_MAX_BINARY_CELL_BYTES = 100000 * (_CELL_ROW_BYTES + _PHYSICAL_LAYER_ROW_BYTES)


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    """Load the viewer-owned JSON selection and optional-stage settings."""

    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text())
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as error:
        raise RuntimeConfigurationError(
            f"runtime config is not valid JSON: {config_path}"
        ) from error
    if not isinstance(raw, dict):
        raise RuntimeConfigurationError("runtime config must be an object")
    dataset = raw.get("dataset")
    sequence = raw.get("sequence")
    if dataset not in _DATASETS:
        raise RuntimeConfigurationError(
            "runtime config dataset must be one of: generic, rellis3d, semanticposs, semantickitti"
        )
    if not isinstance(sequence, (str, int)) or not str(sequence):
        raise RuntimeConfigurationError("runtime config sequence is required")
    pipeline = raw.get("pipeline", {})
    map_config = raw.get("map", {})
    if not isinstance(pipeline, dict) or not isinstance(map_config, dict):
        raise RuntimeConfigurationError(
            "runtime pipeline and map settings must be objects"
        )
    return RuntimeConfig(str(dataset), str(sequence), pipeline, map_config)


class _MapRunner(Protocol):
    def process_frame(self, frame: Any) -> dict[str, Any]: ...

    def reset(self) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class PersistentMapEngine:
    """Own one ordered C++ map/policy engine for a playback session."""

    def __init__(
        self,
        executable: str | Path,
        *,
        policy: str = "distance_lod",
        window_radius_m: float = 100.001,
        timeout_s: float = 30.0,
        transport: str = "text",
        utility_config: str | Path | None = None,
        governor_config: str | Path | None = None,
        clear_free_space: bool = False,
    ) -> None:
        if not np.isfinite(window_radius_m) or window_radius_m <= 60.0:
            raise RuntimeConfigurationError(
                "map window_radius_m must be finite and exceed the 60 m LOD boundary"
            )
        self.executable = Path(executable)
        self.policy = policy
        self.window_radius_m = float(window_radius_m)
        if transport not in ("text", "binary"):
            raise RuntimeConfigurationError("unknown engine transport")
        self.transport = transport
        self.utility_config = (
            Path(utility_config) if utility_config is not None else None
        )
        self.governor_config = (
            Path(governor_config) if governor_config is not None else None
        )
        self.clear_free_space = bool(clear_free_space)
        self.timeout_s = float(timeout_s)
        if not np.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise RuntimeConfigurationError("timeout_s must be positive and finite")
        self._process: subprocess.Popen[bytes] | None = None
        self._responses = queue.Queue(maxsize=2)
        self._stderr_tail = deque(maxlen=16)
        self._lock = threading.RLock()
        self._frame_encoder = BinaryFrameEncoder()
        self._physical_layers_version = None

    def _start(self) -> dict[str, Any] | None:
        if not self.executable.is_file():
            return {
                "status": "unavailable",
                "reason": f"map executable does not exist: {self.executable}",
            }
        try:
            command = [
                str(self.executable),
                "--policy",
                self.policy,
                "--window-radius",
                f"{self.window_radius_m:.9g}",
                "--engine",
            ]
            if self.utility_config is not None:
                command.extend(("--utility-config", str(self.utility_config)))
            if self.governor_config is not None:
                command.extend(("--governor-config", str(self.governor_config)))
            if self.clear_free_space:
                command.append("--clear-free-space")
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            assert self._process.stdin is not None
            self._responses = queue.Queue(maxsize=2)
            self._stderr_tail.clear()
            threading.Thread(
                target=self._read_stdout,
                args=(self._process, self._responses),
                daemon=True,
            ).start()
            threading.Thread(
                target=self._drain_stderr, args=(self._process,), daemon=True
            ).start()
            # The handshake version must match the records this process
            # writes. They are the same constant deliberately: a writer that
            # emits V3 records behind a V2 handshake is parsed field-by-field
            # against the wrong layout, which surfaces as an unrelated
            # "nonfinite point value" rather than as a version error.
            ready = self._exchange(f"VEYRA_ENGINE {PROTOCOL_VERSION}\n")
        except OSError as error:
            self._process = None
            return {"status": "unavailable", "reason": f"map engine failed: {error}"}
        if ready.get("status") != "ready":
            self.close()
            return ready
        self._physical_layers_version = ready.get("physical_layers_version")
        return None

    @property
    def pid(self):
        return self._process.pid if self._process is not None else None

    def _read_stdout(self, process, responses):
        output = None
        try:
            # stdin remains unbuffered for command delivery. Buffer only stdout:
            # FileIO.readline otherwise performs one pipe read per JSON byte.
            output = io.BufferedReader(process.stdout, buffer_size=64 * 1024)
            while True:
                line = output.readline(32 * 1024 * 1024 + 1)
                if len(line) > 32 * 1024 * 1024:
                    responses.put_nowait(
                        {
                            "status": "unavailable",
                            "reason": "map engine response exceeds size limit",
                        }
                    )
                    process.kill()
                    return
                if not line:
                    responses.put_nowait(
                        {
                            "status": "unavailable",
                            "reason": "map engine closed its output",
                        }
                    )
                    return
                try:
                    response = json.loads(line)
                    if not isinstance(response, dict):
                        raise ValueError(  # noqa: TRY004 - malformed protocol uses one error path
                            "expected object"
                        )
                except (ValueError, UnicodeDecodeError):
                    response = {
                        "status": "unavailable",
                        "reason": "map engine returned invalid JSON",
                    }
                if "binary_bytes" in response:
                    # A binary response is a JSON header line followed by
                    # exactly `binary_bytes` raw bytes (see MB in engine.cpp).
                    size = response.pop("binary_bytes")
                    if (
                        isinstance(size, bool)
                        or not isinstance(size, int)
                        or not 0 <= size <= _MAX_BINARY_CELL_BYTES
                    ):
                        responses.put_nowait(
                            {
                                "status": "unavailable",
                                "reason": "map engine binary response size is invalid",
                            }
                        )
                        process.kill()
                        return
                    payload = output.read(size)
                    if len(payload) != size:
                        responses.put_nowait(
                            {
                                "status": "unavailable",
                                "reason": "map engine closed its output",
                            }
                        )
                        return
                    response["binary"] = payload
                responses.put_nowait(response)
        except (OSError, ValueError, queue.Full):
            if process.poll() is None:
                process.kill()
        finally:
            if output is not None:
                # The process lifecycle owns the raw stream and may close it
                # concurrently during shutdown; do not transfer that ownership.
                try:
                    output.detach()
                except (OSError, ValueError):
                    pass

    def _drain_stderr(self, process):
        try:
            while chunk := process.stderr.read(4096):
                self._stderr_tail.append(chunk.decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            pass

    def _exchange(self, command):
        process = self._process
        if process is None:
            return {"status": "unavailable", "reason": "map engine is not running"}
        error = []

        def write():
            try:
                data = memoryview(
                    command.encode("ascii") if isinstance(command, str) else command
                )
                while data:
                    written = process.stdin.write(data)
                    if not written:
                        raise BrokenPipeError("map engine input closed")
                    data = data[written:]
            except (OSError, ValueError) as exc:
                error.append(str(exc))

        writer = threading.Thread(target=write, daemon=True)
        deadline = time.monotonic() + self.timeout_s
        writer.start()
        writer.join(self.timeout_s)
        if writer.is_alive():
            # The abandoned writer may still reference the reused frame
            # buffer; give later frames a fresh encoder rather than overwrite it.
            self._frame_encoder = BinaryFrameEncoder()
            self.close()
            return {"status": "unavailable", "reason": "map engine write timed out"}
        if error:
            self.close()
            return {
                "status": "unavailable",
                "reason": "map engine write failed: " + error[0],
            }
        try:
            response = self._responses.get(
                timeout=max(0.001, deadline - time.monotonic())
            )
        except queue.Empty:
            self.close()
            return {"status": "unavailable", "reason": "map engine response timed out"}
        if response.get("status") == "unavailable":
            detail = "".join(self._stderr_tail).strip()
            if detail:
                response["reason"] += ": " + detail[-4096:]
            self.close()
        return response

    def _command(self, command: str) -> dict[str, Any]:
        unavailable = self._start() if self._process is None else None
        return unavailable if unavailable is not None else self._exchange(command)

    def process_frame(self, frame: Any) -> dict[str, Any]:
        """Process one canonical V2 frame without restarting map/policy state."""

        with self._lock:
            if self.transport == "binary":
                # The record aliases the encoder's reused buffer; _exchange
                # finishes (or abandons, see there) the write before returning.
                command = self._frame_encoder.encode(frame)
                known = self._frame_encoder.known_drivability_points
            else:
                command = "".join(frame_records(frame))
                known = None
            response = self._command(command)
        if response.get("status") == "unavailable":
            return response
        if known is None:
            known = np.count_nonzero(
                np.isin(frame.drivable, ("drivable", "non_drivable"))
            )
        return {
            "status": "available",
            "source": "veyra_persistent_engine",
            "input_points": int(frame.points.shape[0]),
            "unknown_traversability_points": int(frame.points.shape[0] - known),
            "input": response.get("input", {}),
            "snapshot": response.get("snapshot", {}),
            "metrics": _viewer_metrics(response.get("metrics", {})),
            "governor": response.get("governor"),
        }

    def reset(self) -> dict[str, Any]:
        with self._lock:
            return self._command("R\n")

    def map_cells(self, budget: int = 20000) -> dict[str, Any]:
        """Return decimated live map leaves without advancing map state."""

        with self._lock:
            clipped = max(1, min(int(budget), 100000))
            response = self._command(f"M {clipped}\n")
        if response.get("status") != "available" or "cells" not in response:
            return {
                "status": "unavailable",
                "reason": response.get("reason", "map cells unavailable"),
            }
        return response

    def map_cells_binary(self, budget: int = 20000) -> dict[str, Any]:
        """Like map_cells, but rows arrive as packed display floats.

        ``cells_binary`` holds ``cell_count`` rows of seventeen little-endian
        float32 in the visualization schema-v3 cell layout (see
        runtime/visualization.py): the frame's cell section, unparsed.
        Negotiated layer support adds a separate ``physical_layers_binary``
        buffer in exactly the same sampled order, without changing those rows.
        """

        with self._lock:
            clipped = max(1, min(int(budget), 100000))
            unavailable = self._start() if self._process is None else None
            if unavailable is not None:
                return unavailable
            command = "ML" if self._physical_layers_version == 1 else "MB"
            response = self._exchange(f"{command} {clipped}\n")
        payload = response.get("binary")
        if response.get("status") != "available" or not isinstance(payload, bytes):
            return {
                "status": "unavailable",
                "reason": response.get("reason", "map cells unavailable"),
            }
        count = response.get("cell_count")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 0 <= count <= clipped
        ):
            return {"status": "unavailable", "reason": "map cell count is invalid"}
        cell_bytes = count * _CELL_ROW_BYTES
        has_layers = response.get("physical_layers_version") == 1
        expected_bytes = cell_bytes + (
            count * _PHYSICAL_LAYER_ROW_BYTES if has_layers else 0
        )
        if len(payload) != expected_bytes:
            return {"status": "unavailable", "reason": "map cells size mismatch"}
        result = {
            "status": "available",
            "cell_count": response["cell_count"],
            "total_leaves": response.get("total_leaves", 0),
            "cells_binary": payload[:cell_bytes],
        }
        if has_layers:
            result["physical_layers_binary"] = payload[cell_bytes:]
        return result

    def set_governor_override(self, mode: str) -> dict[str, Any]:
        if mode not in {"automatic", "disabled", "conserve"}:
            raise ValueError(
                "governor override must be automatic, disabled, or conserve"
            )
        with self._lock:
            return self._command(f"G {mode}\n")

    def status(self) -> dict[str, Any]:
        with self._lock:
            response = self._command("S\n")
        if response.get("status") != "available":
            return response
        return {
            "status": "available",
            "source": "veyra_persistent_engine",
            "policy": response.get("policy", self.policy),
            "frames": response.get("input_frames", 0),
            "snapshot": response.get("snapshot", {}),
            "metrics": _viewer_metrics(response.get("metrics", {})),
            "governor": response.get("governor"),
        }

    def close(self) -> None:
        if not hasattr(self, "_lock"):
            return
        with self._lock:
            process, self._process = self._process, None
            if process is None:
                return
            try:
                if process.poll() is None:
                    try:
                        process.stdin.write(b"C\n")
                        response = self._responses.get(timeout=0.25)
                        if response.get("status") == "closed":
                            process.wait(timeout=0.25)
                    except (
                        OSError,
                        ValueError,
                        queue.Empty,
                        subprocess.TimeoutExpired,
                    ):
                        pass
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            finally:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()

    def __del__(self) -> None:
        try:
            self.close()
        except (OSError, RuntimeError, AttributeError):
            pass


class BenchmarkMapRunner(PersistentMapEngine):
    """Compatibility name for callers that need one persistent map session."""

    def process(self, frame: Any) -> dict[str, Any]:
        return self.process_frame(frame)


def _enabled(settings: Mapping[str, Any], name: str) -> bool:
    stage = settings.get(name, {})
    if not isinstance(stage, Mapping):
        raise RuntimeConfigurationError(f"pipeline.{name} must be an object")
    return bool(stage.get("enabled", False))


def build_pipeline(
    settings: Mapping[str, Any], *, repo_root: str | Path | None = None
) -> PerceptionPipeline:
    """Build the same configured pipeline used by acceptance tools."""

    config = dict(settings)
    semantic = config.get("semantic")
    if semantic is None:
        config["semantic"] = {"mode": "ground_truth"}
    elif not isinstance(semantic, Mapping):
        raise RuntimeConfigurationError("pipeline.semantic must be an object")
    else:
        semantic = dict(semantic)
        for key in ("model_path", "checkpoint"):
            value = semantic.get(key)
            if repo_root is not None and isinstance(value, str) and value.strip():
                model = Path(value)
                if not model.is_absolute():
                    semantic[key] = str(Path(repo_root) / model)
        config["semantic"] = semantic
    try:
        return PerceptionPipeline.from_config(config)
    except (ValueError, RuntimeError) as error:
        raise RuntimeConfigurationError(str(error)) from error


def build_runtime_session(
    config: RuntimeConfig,
    *,
    dataset_settings: Mapping[str, Any],
    repo_root: str | Path,
) -> RuntimeSession:
    """Compose a session from read-only dataset settings and viewer settings."""

    spec = dataset_settings.get(config.dataset)
    if not isinstance(spec, Mapping):
        raise RuntimeConfigurationError(
            f"dataset settings do not contain {config.dataset}"
        )
    sequences = [str(value) for value in spec.get("sequences", [])]
    if config.sequence not in sequences:
        raise RuntimeConfigurationError(
            f"sequence {config.sequence} is not enabled for {config.dataset}"
        )
    root = Path(repo_root) / str(spec.get("root", ""))
    if not root.is_dir():
        raise DatasetUnavailableError(f"dataset root does not exist: {root}")
    if config.dataset == "generic":
        from datasets.generic import ManifestDataset

        adapter: DatasetAdapter = ManifestDataset(root)
    elif config.dataset == "rellis3d":
        from datasets.rellis import Rellis3DDataset

        adapter: DatasetAdapter = Rellis3DDataset(
            root,
            sequences=sequences,
            scan_dir=str(spec.get("scan_dir", "vel_cloud_node_kitti_bin")),
            label_dir=str(
                spec.get("label_dir", "vel_cloud_node_semantickitti_label_id")
            ),
        )
    elif config.dataset == "semanticposs":
        from datasets.semanticposs import SemanticPOSSDataset

        adapter = SemanticPOSSDataset(
            root,
            sequences=sequences,
            scan_dir=str(spec.get("scan_dir", "velodyne")),
            label_dir=str(spec.get("label_dir", "labels")),
        )
    elif config.dataset == "semantickitti":
        from datasets.semantickitti import SemanticKITTIDataset

        adapter = SemanticKITTIDataset(
            root,
            sequences=sequences,
            scan_dir=str(spec.get("scan_dir", "velodyne")),
            label_dir=str(spec.get("label_dir", "labels")),
        )
    else:
        raise RuntimeConfigurationError(f"unsupported dataset: {config.dataset}")
    maximum = spec.get("max_range_m")
    executable = config.map.get("executable")
    map_runner = None
    if executable is not None:
        executable_path = Path(str(executable))
        if not executable_path.is_absolute():
            executable_path = Path(repo_root) / executable_path
        default_window = float(maximum) + 0.001 if maximum is not None else 100.001
        map_runner = PersistentMapEngine(
            executable_path,
            policy=str(config.map.get("policy", "distance_lod")),
            window_radius_m=float(config.map.get("window_radius_m", default_window)),
            clear_free_space=bool(config.map.get("clear_free_space", False)),
        )
    return RuntimeSession(
        adapter,
        dataset=config.dataset,
        sequence=config.sequence,
        pipeline_config=config.pipeline,
        min_range_m=float(spec.get("min_range_m", 0.0)),
        max_range_m=float(maximum) if maximum is not None else None,
        map_runner=map_runner,
        repo_root=repo_root,
    )


class RuntimeSession:
    """Stateful real-adapter playback with explicit reset boundaries."""

    def __init__(
        self,
        adapter: DatasetAdapter,
        *,
        dataset: str,
        sequence: str,
        pipeline_config: Mapping[str, Any],
        min_range_m: float = 0.0,
        max_range_m: float | None = None,
        map_runner: _MapRunner | None = None,
        repo_root: str | Path | None = None,
    ) -> None:
        self.adapter = adapter
        self.dataset = dataset
        self.sequence = str(sequence)
        self.pipeline_config = dict(pipeline_config)
        self.min_range_m = min_range_m
        self.max_range_m = max_range_m
        self.map_runner = map_runner
        self.repo_root = Path(repo_root).resolve() if repo_root is not None else None
        self.index = 0
        self._lock = threading.RLock()
        self.pipeline = build_pipeline(self.pipeline_config, repo_root=self.repo_root)
        self._frames = self._require_frames(self.sequence)
        self._last_output: Any | None = None
        self._last_map_payload: dict[str, Any] | None = None

    @classmethod
    def from_adapter(
        cls,
        adapter: DatasetAdapter,
        *,
        dataset: str,
        sequence: str,
        pipeline_config: Mapping[str, Any],
        **kwargs: Any,
    ) -> RuntimeSession:
        return cls(
            adapter,
            dataset=dataset,
            sequence=sequence,
            pipeline_config=pipeline_config,
            **kwargs,
        )

    @classmethod
    def from_dataset_settings(
        cls,
        *,
        dataset: str,
        dataset_root: str | Path,
        sequences: list[str],
        pipeline_config: Mapping[str, Any],
        **kwargs: Any,
    ) -> RuntimeSession:
        root = Path(dataset_root)
        if not root.is_dir():
            raise DatasetUnavailableError(f"dataset root does not exist: {root}")
        if dataset == "generic":
            from datasets.generic import ManifestDataset

            adapter: DatasetAdapter = ManifestDataset(root)
        elif dataset == "rellis3d":
            from datasets.rellis import Rellis3DDataset

            adapter: DatasetAdapter = Rellis3DDataset(root, sequences=sequences)
        elif dataset == "semanticposs":
            from datasets.semanticposs import SemanticPOSSDataset

            adapter = SemanticPOSSDataset(root, sequences=sequences)
        elif dataset == "semantickitti":
            from datasets.semantickitti import SemanticKITTIDataset

            adapter = SemanticKITTIDataset(root, sequences=sequences)
        else:
            raise RuntimeConfigurationError(f"unsupported dataset: {dataset}")
        if not sequences:
            raise RuntimeConfigurationError("runtime requires at least one sequence")
        return cls(
            adapter,
            dataset=dataset,
            sequence=str(sequences[0]),
            pipeline_config=pipeline_config,
            **kwargs,
        )

    def _require_frames(self, sequence: str) -> list[Any]:
        try:
            frames = self.adapter.list_frames(sequence)
        except FileNotFoundError as error:
            raise DatasetUnavailableError(str(error)) from error
        if not frames:
            raise DatasetUnavailableError(f"sequence has no frames: {sequence}")
        return frames

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": "configured",
                "dataset": self.dataset,
                "sequence": self.sequence,
                "index": self.index,
                "frames": len(self._frames),
                "map": "configured" if self.map_runner is not None else "unavailable",
            }

    def _reset_locked(self) -> None:
        self.pipeline = build_pipeline(self.pipeline_config, repo_root=self.repo_root)
        if self.map_runner is not None:
            self.map_runner.reset()
        self.index = 0
        self._last_output = None
        self._last_map_payload = None

    def reset(self, *, budget: int) -> dict[str, Any]:
        with self._lock:
            self._reset_locked()
            return self._payload_locked(0, budget)

    def map_cells(self, *, budget: int) -> dict[str, Any]:
        with self._lock:
            if self.map_runner is None:
                return {
                    "status": "unavailable",
                    "reason": "no map runtime executable configured",
                }
            return self.map_runner.map_cells(budget=budget)

    def map_cells_binary(self, *, budget: int) -> dict[str, Any]:
        """Packed display cells; runners without binary support use JSON."""

        runner = self.map_runner
        if runner is None or not hasattr(runner, "map_cells_binary"):
            return self.map_cells(budget=budget)
        with self._lock:
            return runner.map_cells_binary(budget=budget)

    def select_sequence(self, sequence: str, *, budget: int) -> dict[str, Any]:
        with self._lock:
            frames = self._require_frames(str(sequence))
            self.sequence = str(sequence)
            self._frames = frames
            self._reset_locked()
            return self._payload_locked(0, budget)

    def next(self, *, budget: int) -> dict[str, Any]:
        with self._lock:
            return self._payload_locked(
                min(self.index + 1, len(self._frames) - 1), budget
            )

    def previous(self, *, budget: int) -> dict[str, Any]:
        with self._lock:
            return self._payload_locked(max(self.index - 1, 0), budget)

    def frame_payload(
        self, index: int, *, budget: int, binary: bool = False
    ) -> dict[str, Any]:
        with self._lock:
            return self._payload_locked(index, budget, binary=binary)

    def _payload_locked(
        self, requested_index: int, budget: int, binary: bool = False
    ) -> dict[str, Any]:
        if budget <= 0:
            raise ValueError("point budget must be positive")
        target = max(0, min(int(requested_index), len(self._frames) - 1))
        if self._last_output is not None and target == self.index:
            assert self._last_map_payload is not None
            return self._serialize(
                self._last_output, target, budget, self._last_map_payload, binary=binary
            )
        if self._last_output is not None and target < self.index:
            self._reset_locked()
        start = 0 if self._last_output is None else self.index + 1
        output = self._last_output
        for current in range(start, target + 1):
            ref = self._frames[current]
            observation = self.adapter.load_frame(
                self.sequence,
                ref.frame_id,
                min_range_m=self.min_range_m,
                max_range_m=self.max_range_m,
            )
            output = self.pipeline.process(observation)
            self._last_map_payload = self._map_payload(output.frame)
        self.index = target
        assert output is not None
        self._last_output = output
        return self._serialize(
            output, target, budget, self._last_map_payload, binary=binary
        )

    def _map_payload(self, frame: Any) -> dict[str, Any]:
        if self.map_runner is None:
            return {
                "status": "unavailable",
                "reason": "no map runtime executable configured",
            }
        return self.map_runner.process_frame(frame)

    def close(self) -> None:
        with self._lock:
            if self.map_runner is not None:
                self.map_runner.close()

    def _serialize(
        self,
        output: Any,
        index: int,
        budget: int,
        map_payload: dict[str, Any],
        binary: bool = False,
    ) -> dict[str, Any]:
        frame = output.frame
        count = int(frame.points.shape[0])
        stride = max(1, -(-count // budget))
        sample = slice(None, None, stride)
        sampled = frame.points[sample]
        raw = (
            frame.raw_semantic_class
            if frame.raw_semantic_class is not None
            else frame.semantic_class
        )
        labels = raw[sample]
        semantic = frame.semantic_class[sample]
        histogram = {
            str(int(value)): int(amount)
            for value, amount in zip(*np.unique(raw, return_counts=True))
        }
        status = output.status
        return {
            "dataset": self.dataset,
            "seq": self.sequence,
            "index": index,
            "id": frame.frame_id,
            "frames": len(self._frames),
            "n_points": count,
            "shown": int(sampled.shape[0]),
            "stride": stride,
            "points": sampled[:, :3]
            if binary
            else [[round(float(value), 3) for value in row[:3]] for row in sampled],
            "intensity": sampled[:, 3]
            if binary
            else [round(float(value), 3) for value in sampled[:, 3]],
            "labels": labels if binary else labels.astype(int, copy=False).tolist(),
            "raw_semantic_labels": labels
            if binary
            else labels.astype(int, copy=False).tolist(),
            "semantic_labels": semantic
            if binary
            else semantic.astype(int, copy=False).tolist(),
            "paired": frame.raw_semantic_class is not None,
            "hist": histogram,
            "source": type(self.adapter).__name__,
            "timestamp": frame.timestamp,
            "pose": {
                "available": frame.provenance.coordinate_frame == "world",
                "matrix": frame.pose.matrix.tolist(),
                "provenance": {
                    "coordinate_frame": frame.provenance.coordinate_frame,
                    "timestamp_source": frame.provenance.timestamp_source,
                    "pose_source": frame.provenance.pose_source,
                    "calibration_source": frame.provenance.calibration_source,
                },
            },
            "cropped": self.max_range_m is not None or self.min_range_m > 0,
            "range_m": self.max_range_m,
            "ground": frame.ground[sample] if binary else frame.ground[sample].tolist(),
            "drivable": frame.drivable[sample]
            if binary
            else frame.drivable[sample].tolist(),
            "slope": frame.slope[sample]
            if binary
            else _nullable_floats(frame.slope[sample]),
            "roughness": frame.roughness[sample]
            if binary
            else _nullable_floats(frame.roughness[sample]),
            "height_complexity": frame.height_complexity[sample]
            if binary
            else _nullable_floats(frame.height_complexity[sample]),
            "motion_probability": frame.motion_probability[sample]
            if binary
            else frame.motion_probability[sample].astype(float).tolist(),
            "semantic_confidence": frame.semantic_confidence[sample]
            if binary
            else frame.semantic_confidence[sample].astype(float).tolist(),
            "velocity_xy": frame.velocity_xy[sample]
            if binary
            else frame.velocity_xy[sample].astype(float).tolist(),
            "motion_state": frame.motion_state[sample]
            if binary
            else frame.motion_state[sample].tolist(),
            # Genuine tracker identity, sampled with the frame. None stays
            # None (unavailable) rather than becoming a fabricated zero.
            "track_ids": (
                None
                if getattr(frame, "track_id", None) is None
                else (
                    frame.track_id[sample]
                    if binary
                    else frame.track_id[sample].tolist()
                )
            ),
            "terrain_confidence": frame.terrain_confidence[sample]
            if binary
            else frame.terrain_confidence[sample].astype(float).tolist(),
            "step": frame.step[sample]
            if binary
            else _nullable_floats(frame.step[sample]),
            "observation_quality": frame.observation_quality[sample]
            if binary
            else frame.observation_quality[sample].astype(float).tolist(),
            "pipeline_status": {
                "semantic": status.semantic,
                "ground": status.ground,
                "terrain": status.terrain,
                "temporal": status.temporal,
                "diagnostics": list(status.diagnostics),
                "semantic_execution": status.semantic_execution,
                "semantic_requested": getattr(
                    status,
                    "semantic_requested",
                    getattr(status, "semantic_requested_mode", None),
                ),
                "semantic_fallback_reason": getattr(
                    status, "semantic_fallback_reason", None
                ),
                "semantic_model": getattr(
                    status,
                    "semantic_model",
                    getattr(status, "semantic_checkpoint", None),
                ),
                "semantic_device_requested": getattr(
                    status, "semantic_device_requested", None
                ),
                "semantic_device_fallback_reason": getattr(
                    status, "semantic_device_fallback_reason", None
                ),
            },
            "perception_timings_ms": {
                key: float(value) for key, value in output.timings_ms.items()
            },
            "map": map_payload,
        }


def _nullable_floats(values: np.ndarray) -> list[float | None]:
    return [float(value) if np.isfinite(value) else None for value in values]


def _optional_number(value: float) -> str:
    return "NA" if not np.isfinite(value) else f"{float(value):.9g}"


def _viewer_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Expose measured benchmark fields under the compact viewer schema."""

    stage_latencies = metrics.get("stage_latency_ns", {})
    memory = metrics.get("memory", {})
    return {
        "fps": metrics.get("fps"),
        "map_update_latency_ns": stage_latencies.get("map_update"),
        "measured_rss_bytes": memory.get("current_rss_bytes"),
        "peak_rss_bytes": memory.get("peak_rss_bytes"),
        "logical_map_bytes": memory.get("logical_map_bytes"),
        "allocated_map_bytes": memory.get("allocated_map_bytes"),
        "allocated_map_bytes_available": memory.get("allocated_map_bytes_available"),
        "topology": metrics.get("topology"),
        "stream": metrics.get("stream"),
    }
