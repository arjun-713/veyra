# Tauri Release CI Repair Implementation Plan

> **For agentic workers:** Execute inline in the current `main` checkout. The user explicitly authorized direct pushes to `main`; do not create a branch or worktree.

**Goal:** Repair the failing cross-platform Tauri release workflow, publish the requested native release, and verify that the production downloads endpoint exposes real installer assets.

**Architecture:** Keep the existing Tauri release workflow and backend packager. Fix platform-specific package selection, Python-runtime staging and CMake compiler flags, plus the portable C++ launcher required by Windows. Preserve the existing release manifest and landing-page API contract.

**Tech Stack:** GitHub Actions, CMake/C++20, Python 3.12/3.13, PyPI wheels, Tauri, GitHub Releases, Next.js/Vercel.

**Spec:** User request and failing run `36457975710`.

## Global Constraints

- Work directly on `main`; preserve the pre-existing untracked `:memory:.ses` file.
- Do not change DistanceLOD, production mapping defaults, or unrelated app UI.
- Publish only installer assets, checksums, and the release manifest through the existing workflow.
- A successful build is not release completion: verify a GitHub Release and the live `/api/releases` payload.

---

### Task 1: Repair Windows compiler compatibility

**Files:** `apps/player/main.cpp`, root and target CMake files.

- [x] Use the failing Windows release job as the regression: it reported `apps/player/main.cpp:6` could not include `unistd.h`, then exposed `-Wextra` passed to MSVC as `/Wextra`.
- [x] Use `_execvp`/`python.exe` on Windows and `execvp`/`python3` elsewhere, retaining current argument and failure semantics.
- [x] Centralize warning/assertion compile options so MSVC receives `/W4` and `/UNDEBUG`; other compilers retain `-Wall -Wextra -Wpedantic` and `-UNDEBUG`.
- [ ] Require the corrected release matrix to compile all Windows targets.

### Task 2: Make macOS backend staging robust to framework diagnostics

**Files:** `scripts/package_backend.py`, `tests/test_package_backend.py`.

- [x] Add a test using `_copy_tree(..., materialize_internal_links=True)` with an optional dangling framework symlink; verify the test first fails on strict resolution.
- [x] Omit dangling links from the flattened Python runtime; continue rejecting valid links that escape its root and validate required runtime files afterward.
- [x] Add a mocked `otool` output test and ignore its `is not an object file` diagnostic instead of treating it as a library dependency.
- [x] Run focused package-backend tests.

### Task 3: Select dependencies available for each release architecture

**Files:** `requirements.txt` and release workflow if needed.

- [x] Keep ONNX Runtime 1.30 on supported targets and select the PyPI-published 1.23.2 macOS x86_64 wheel; test marker selection.
- [x] Keep Patchwork++ on supported targets, omit its unavailable/broken macOS Intel source build with explicit unavailable ground/terrain behavior, and document the limitation.
- [x] Use Python 3.12 on Windows because the published Patchwork++ Windows wheel targets CPython 3.12; retain Python 3.13 on Linux and macOS.
- [ ] Let the corrected release matrix verify dependency installation and backend smoke on every target.

### Task 4: Verify, push, publish, and confirm downloads

**Files:** no further implementation expected.

- [x] Run focused Python tests, C++ Release build and 25/25 CTests (excluding the separate aggregate Python CTest), Ruff, and `git diff --check`.
- [ ] Re-run the updated CI/release workflow after the platform fixes.
- [ ] Commit only scoped changes and the plan; push directly to `origin/main` as authorized.
- [ ] Re-run the existing `workflow_dispatch` release with the same intended version/channel after inspecting its inputs; wait for every platform and publish job.
- [ ] Confirm release asset names, SHA-256 manifest/checksums, `/download` HTTP 200, and `/api/releases` `status: ok` with actual installer links.
