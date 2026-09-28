# Tauri Release CI Repair Implementation Plan

> **For agentic workers:** Execute inline in the current `main` checkout. The user explicitly authorized direct pushes to `main`; do not create a branch or worktree.

**Goal:** Repair the failing cross-platform Tauri release workflow, publish the requested native release, and verify that the production downloads endpoint exposes real installer assets.

**Architecture:** Keep the existing Tauri release workflow and backend packager. Fix platform-specific packaging inputs and Python-runtime staging, and make the small portable C++ launcher change required by Windows. Preserve the existing release manifest and landing-page API contract.

**Tech Stack:** GitHub Actions, CMake/C++20, Python 3.13, PyPI wheels, Tauri, GitHub Releases, Next.js/Vercel.

**Spec:** User request and failing run `36457975710`.

## Global Constraints

- Work directly on `main`; preserve the pre-existing untracked `:memory:.ses` file.
- Do not change DistanceLOD, production mapping defaults, or unrelated app UI.
- Publish only installer assets, checksums, and the release manifest through the existing workflow.
- A successful build is not release completion: verify a GitHub Release and the live `/api/releases` payload.

---

### Task 1: Repair portable runtime launcher compilation

**Files:** `apps/player/main.cpp`.

- [ ] Use the failing Windows release job as the regression: it reports `apps/player/main.cpp:6` cannot include `unistd.h`.
- [ ] Replace the POSIX-only `execvp` include/call with a platform-conditional `_execvp` on Windows and `execvp` elsewhere, keeping argument ownership and current exit semantics.
- [ ] Run the local C++ build/tests; require the release matrix to compile the Windows target.

### Task 2: Make backend staging tolerate optional dangling framework links

**Files:** `scripts/package_backend.py`, `tests/test_package_backend.py`.

- [ ] Add a test using `_copy_tree(..., materialize_internal_links=True)` with a dangling symlink to an optional framework path; expect it to be omitted from the staged runtime.
- [ ] Run that focused test and confirm it fails on strict resolution.
- [ ] Skip only dangling symlinks when materializing Python runtime trees; continue rejecting valid links that escape the runtime root and verify all required runtime files afterward.
- [ ] Run focused package-backend tests.

### Task 3: Select an ONNX Runtime wheel available on macOS Intel

**Files:** `requirements.txt` and release workflow if needed.

- [ ] Use a platform marker to keep the current ONNX Runtime pin on supported platforms and select the verified macOS x86_64-compatible release.
- [ ] Keep the dependency required for real ONNX inference; do not silently omit it from the Intel package.
- [ ] Validate PEP 508 selection and let all release matrix jobs exercise `pip install -r requirements.txt`.

### Task 4: Verify, push, publish, and confirm downloads

**Files:** no further implementation expected.

- [ ] Run focused Python tests, C++ Release build/CTest, Ruff, frontend checks/build as relevant, and `git diff --check`.
- [ ] Commit only scoped changes and the plan; push directly to `origin/main` as authorized.
- [ ] Re-run the existing `workflow_dispatch` release with the same intended version/channel after inspecting its inputs; wait for every platform and publish job.
- [ ] Confirm release asset names, SHA-256 manifest/checksums, `/download` HTTP 200, and `/api/releases` `status: ok` with actual installer links.

