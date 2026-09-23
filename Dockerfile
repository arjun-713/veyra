# syntax=docker/dockerfile:1
#
# Veyra headless image: C++20 mapper + Python perception/runtime/viewer.
# CPU only (no CUDA); the Tauri desktop app is a native GUI and is not built
# here. Datasets and model weights are never copied in: docker-compose.yml
# bind-mounts ./data at /app/data.
#
#   docker build -t veyra:dev .
#   docker compose run --rm test
#
# All stages share one pinned base so the compiled binaries, the venv and the
# interpreter agree on glibc/libstdc++ and on the /usr/local/bin/python3.12 path.
# Debian 13 (trixie): g++ 14, CMake 3.31 (>= 3.22 required by CMakeLists.txt).
ARG PYTHON_IMAGE=python:3.12.14-slim-trixie

# ---------------------------------------------------------------------------
# Stage 1: compile the C++ core, apps and C++ tests (Release, BUILD_TESTING=ON)
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS cpp-build

RUN apt-get update \
 && apt-get install --yes --no-install-recommends g++ cmake ninja-build \
 && rm -rf /var/lib/apt/lists/*

# The build tree must live at /app/build with sources at /app: the engine bakes
# VEYRA_SOURCE_DIR (/app) into the binary to find /app/configs/*.yaml, CTest
# records absolute paths, and the Python side looks for build/apps/... under
# the repo root. The runtime stage uses the same paths.
WORKDIR /app

# Only C++ inputs, so Python-only edits do not invalidate this layer.
COPY CMakeLists.txt ./
COPY include/ include/
COPY src/ src/
COPY apps/CMakeLists.txt apps/
COPY apps/benchmark/ apps/benchmark/
COPY apps/live/ apps/live/
COPY apps/player/ apps/player/
COPY apps/runtime/ apps/runtime/
COPY tests/CMakeLists.txt tests/*.cpp tests/*.hpp tests/

# Same options as the CI C++ job, minus -Werror (a newer g++ may add warnings;
# CI on ubuntu-24.04 stays the -Werror gate). Object files are dropped
# afterwards; CTest only needs the executables and CTestTestfile.cmake files.
RUN cmake -S . -B build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_TESTING=ON \
      -DVEYRA_BUILD_APPS=ON \
 && cmake --build build --parallel \
 && find build -name '*.o' -delete \
 && test -x build/apps/runtime/veyra_runtime \
 && test -x build/apps/benchmark/veyra_benchmark

# ---------------------------------------------------------------------------
# Stage 2: Python virtualenv from the pinned requirement files
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS py-deps

# Wheel availability for cp312 on PyPI (checked against the pins):
#   numpy, scipy==1.15.3, pyyaml==6.0.2, onnxruntime==1.22.0, ruff==0.8.0:
#     manylinux wheels for both x86_64 and aarch64.
#   pypatchworkpp==1.4.1: manylinux wheel for x86_64 only; no aarch64 wheel in
#     any release. Its PyPI sdist cannot build out of tree either: the wrapper
#     CMakeLists has no project VERSION, so it FetchContent-downloads
#     .../archive/refs/tags/v.tar.gz (HTTP 404).
# Minimal fix, same pin: on arches without a wheel (arm64, e.g. Apple Silicon)
# build 1.4.1 from the upstream v1.4.1 tag's python/ directory, which has the
# C++ core in tree. That build downloads scikit-build-core/pybind11/cmake from
# PyPI and Eigen 3.4.0 from gitlab.com (applied with `patch`), hence the tools.
ARG PATCHWORKPP_VERSION=1.4.1
ARG PATCHWORKPP_SHA256=00f2455af0c66e7bb1938396e3b7483491608803032c2623728164b91ff889a7

RUN apt-get update \
 && apt-get install --yes --no-install-recommends g++ make patch curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN set -eux; \
    mkdir -p /wheels; \
    if pip download --no-deps --only-binary=:all: --dest /wheels \
         "pypatchworkpp==${PATCHWORKPP_VERSION}"; then \
      echo "using PyPI binary wheel for pypatchworkpp ${PATCHWORKPP_VERSION}"; \
    else \
      curl -fsSL -o /tmp/patchworkpp.tar.gz \
        "https://github.com/url-kaist/patchwork-plusplus/archive/refs/tags/v${PATCHWORKPP_VERSION}.tar.gz"; \
      echo "${PATCHWORKPP_SHA256}  /tmp/patchworkpp.tar.gz" | sha256sum -c -; \
      tar -xzf /tmp/patchworkpp.tar.gz -C /tmp; \
      pip wheel --no-deps --wheel-dir /wheels \
        "/tmp/patchwork-plusplus-${PATCHWORKPP_VERSION}/python"; \
      rm -rf /tmp/patchworkpp.tar.gz "/tmp/patchwork-plusplus-${PATCHWORKPP_VERSION}"; \
    fi

# Requirements before sources: this layer is reused until a pin changes.
# --only-binary guarantees nothing else silently compiles from an sdist;
# pypatchworkpp resolves from /wheels.
COPY requirements.txt requirements-dev.txt /tmp/req/
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --only-binary=:all: --find-links /wheels \
      -r /tmp/req/requirements.txt -r /tmp/req/requirements-dev.txt \
 && /opt/venv/bin/python -c "import numpy, scipy, yaml, onnxruntime, pypatchworkpp"

# ---------------------------------------------------------------------------
# Stage 3: runtime image (sources + venv + built binaries, non-root)
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# The mapper itself needs only libstdc++ (already in the base). The `test`
# service needs cmake for ctest, and g++ because tests/test_player_cli.py
# compiles apps/player/main.cpp with `c++` at test time.
RUN apt-get update \
 && apt-get install --yes --no-install-recommends cmake g++ \
 && rm -rf /var/lib/apt/lists/*

ARG VEYRA_UID=1000
ARG VEYRA_GID=1000
RUN groupadd --gid "${VEYRA_GID}" veyra \
 && useradd --uid "${VEYRA_UID}" --gid veyra --create-home --shell /bin/bash veyra \
 && install -d -o veyra -g veyra /app

# The venv is owned by the unprivileged user so a throwaway container can add
# a conversion-only package (the `pandaset` service installs pandas that way)
# without that package ever entering the image.
COPY --from=py-deps --chown=veyra:veyra /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    VIRTUAL_ENV=/opt/venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY --chown=veyra:veyra . /app
COPY --from=cpp-build --chown=veyra:veyra /app/build /app/build
# Mount point for the bind-mounted data volume (empty in the image).
RUN install -d -o veyra -g veyra /app/data /app/data/raw /app/data/processed /app/data/cache

USER veyra

# Web viewer port (python viewer/server.py --host 0.0.0.0 --port 8765).
EXPOSE 8765

CMD ["bash"]
