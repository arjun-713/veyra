# Docker

Docker packages the headless parts of Veyra: the C++ core, the Python
perception/runtime stack, the test suites, the web viewer and the PandaSet
tooling. It is a reproducible Linux environment, not a deployment target and
not a benchmark platform.

## What runs where

| Runs in Docker | Stays native |
| --- | --- |
| C++ build + `ctest`, `pytest` (`test`) | Tauri desktop GUI (`src-tauri/`) |
| Web viewer, `viewer/server.py` (`viewer`) | Named-hardware benchmark runs |
| PandaSet download + convert (`pandaset`) | |
| Headless runtime, `python -m runtime` (`shell`) | |
| Dev shell with the built tree (`shell`) | |

The desktop stays native. The Tauri shell starts `python -m runtime` as a
local child process and speaks the framed protocol over its stdin/stdout
(`docs/product-runtime.md`). The runtime then starts
`build/apps/runtime/veyra_runtime --engine` the same way. Putting that stdio
chain inside a container gives no benefit and breaks the local-process
model, so build and run the desktop on the host.

## Commands

```bash
docker compose build                 # C++ build + Python deps, no data
docker compose run --rm test         # ctest + pytest inside the image
docker compose up viewer             # http://localhost:8765
docker compose run --rm pandaset     # download + convert into data/raw/pandaset/
docker compose run --rm shell        # interactive shell at /app
```

The viewer binds to loopback by default. In the container it runs with
`--host 0.0.0.0` so the published port is reachable. Compose publishes it to
the host as `localhost:8765`. Outside Docker, keep the default
`127.0.0.1`.

For a headless runtime session, use the `shell` service and run
`python -m runtime --repo /app`. It reads bounded NDJSON commands on stdin,
so any `docker run` invocation needs `-i`. `dataset_root` in a runtime config
must be a path inside the container, such as
`/app/data/raw/pandaset/veyra`. Host paths like `/Users/...` saved by the
desktop do not resolve there.

## Data and models

`data/` is bind-mounted from the host at `/app/data`. Nothing under it is
ever baked into the image, and `.dockerignore` keeps it out of the build
context. The layout is the one `configs/datasets.yaml` and the perception
configs already expect:

```text
data/raw/<dataset>/...           # RELLIS-3D, SemanticPOSS, SemanticKITTI, PandaSet
data/raw/pandaset/raw/<seq>/     # PandaSet download (lidar + semseg only)
data/raw/pandaset/veyra/         # generic manifest export (manifest.json)
data/cache/models/...            # pretrained weights / ONNX files
```

Every path is resolved relative to the repo root (`/app`), so the same
configs work on the host and in the container. Do not bind-mount the host
`build/` directory. On macOS it holds Mach-O binaries that cannot run in the
Linux image, and it would hide the tree built inside the image.

The web viewer reads the native RELLIS-3D, SemanticPOSS and SemanticKITTI
layouts from `configs/datasets.yaml`. It does not list generic-manifest
exports yet, so PandaSet (`data/raw/pandaset/veyra`) opens in the desktop's
`generic` dataset type or through `python -m runtime`, not in the web viewer.

## Apple Silicon

On an Apple Silicon Mac, Docker Desktop builds and runs native `linux/arm64`
images. Do not force `--platform linux/amd64`, because emulation is slow and
changes timing. CUDA/TensorRT is not available in these images, and the core
mapper does not need it.

## Performance numbers

Do not report timings, FPS, RSS or p50/p95/p99 measured inside Docker as
hardware results. Container overhead, the Docker Desktop VM and its CPU and
memory limits all distort them. `AGENTS.md` requires measured numbers on
named hardware, reported separately from analytical ones. Use the container
to check correctness, and run benchmarks natively
(`docs/benchmark-contract.md`).
