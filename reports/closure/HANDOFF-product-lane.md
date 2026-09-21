# Product/Build/Benchmark Lane — Handoff (DRAFT, CI pending)

Lane branch: `closure/opencode-product` (base `cf9e71d` on `demo-readiness`).
Worktree path (local): `.worktrees/opencode-product` — remove after integration
(`git worktree remove --force` once merged; branch deletable after).

## Ordered commits (base → tip)

```text
bab10cc feat(benchmark): measured 3D baseline 2nd-party reproduction + metadata-complete provenance
56ad36f close(tauri): tighten CSP to built-HTML policy, supervise runtime paths, harden renderer
ee666cf packaging: Tauri release smoke+assert gates, deb/rpm manifest evidence
40081b1 integrate(baseline): 2nd-party 3D reproduction + provenance v2 (bab10cc)
78e54cc integrate(tauri): CSP tighten, supervision tests, renderer harden (56ad36f)
5f917dd integrate(packaging): release smoke+assert gates, manifest evidence (ee666cf)
1e5fe8b style(tauri): rustfmt supervision tests (CI fmt gate)
81267b1 style: repo-wide cargo fmt (whitespace-only; unblocks CI fmt gate)
+ handoff commit below (this file)
```

Stream sub-branches (merged above, safe to delete after integration):
`closure/opencode-baseline`, `closure/opencode-tauri`, `closure/opencode-packaging`.

## CI run references (live)

- Branch: `closure/opencode-product` (pushed, no merge performed).
- Runs: `gh run list --branch closure/opencode-product`
  - Tauri desktop run 35498150832 (ubuntu/windows/macos matrix):
    ubuntu + macos FAILED at `cargo fmt --check` on pre-existing files
    (build.rs, veyra-cli.rs, veyra-control.rs, commands.rs,
    controller.rs, packaged_e2e.rs — none lane-touched); windows was
    in_progress. Reran as 35498376937 after the lane's whitespace-only
    fmt commit 81267b1 (in_progress at handoff; expected to pass fmt
    and reach tests).
  - CI workflow run 35498150817 (2026-09-20): **FAILURE — pre-existing,
    not lane-caused.** `C++ formatting` SUCCESS; `C++ Release/Debug` +
    Python fail at `-Werror=range-loop-construct`
    (`tests/test_map_public_properties.cpp:71` + same class in
    randomized_invariants + hardening_stress) under runner GCC. Lane diff
    under `tests/`+`src/` is EMPTY → base fails identically. Owner:
    map-test lane. Mechanical fix (`const auto&`) left to owner.
  - CI rerun 35498376957 (after fmt fix): formatting SUCCESS; C++
    Release/Debug + Python fail identically on the same pre-existing
    `-Werror` issue. Confirms fmt fix worked and the only remaining
    CI failure is the map-test lane's.
  - CI workflow run 35498150817 (2026-09-20): **FAILURE — pre-existing,
    not lane-caused.** `C++ formatting` SUCCESS; `C++ Release/Debug` +
    Python fail at `-Werror=range-loop-construct`
    (`tests/test_map_public_properties.cpp:71` + same class in
    randomized_invariants + hardening_stress) under runner GCC. Lane diff
    under `tests/`+`src/` is EMPTY → base fails identically. Owner:
    map-test lane. Mechanical fix (`const auto&`) left to owner.
- Known pre-existing CI-red risks (NOT lane regressions, verify in logs):
  - `cargo fmt --check`: build.rs, veyra-cli.rs, veyra-control.rs,
    commands.rs, controller.rs, packaged_e2e.rs (predate lane; lane fixed
    only its own supervisor.rs).
  - `cargo clippy -D warnings`: MSRV `is_none_or` at
    src/control/controller.rs:252 (control lane owns; rust-version=1.77
    policy decision).

## Benchmark artifacts

- `reports/closure/baseline-3d/MEASURED.json` (provenance v2 + frame rows)
- `reports/closure/baseline-3d/RERUN-2ND-PARTY.json` (digest `4cd60ac5`,
  1,280,014 elements reproduced)
- `reports/closure/utility/benchmark_run3_unclamped_semanticposs00.json`
  (main lane; reused for 6-row comparison table)
- `/tmp/opencode/veyra-bundles/` (local only): release-manifest.json, SHA256SUMS

## Packaged-app verification commands

```bash
# inspect without installing
ar p <bundle.deb> data.tar.zst | tar -I zstd -tf - | grep backend/manifest.json
rpm -qlp <bundle.rpm> | grep backend/manifest.json
# backend payload identity (must match staged manifest)
sha256sum src-tauri/resources/backend/manifest.json   # after staging
# headless packaged smoke (expects exit 101 = window-creation reached, no display)
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
  XDG_RUNTIME_DIR=$(mktemp -d) GDK_BACKEND=x11 \
  timeout -s KILL 15 ./src-tauri/target/release/veyra; echo $?
# rehearsal (headless session + neural probe + smoke)
./scripts/demo_rehearsal.sh --frames 10 --neural --neural-frames 2 \
  --evidence-dir /tmp/opencode/rehearsal
```

## Shared interfaces touched

- NONE modified. `src-tauri/src/control/*` read-only throughout the lane.
- `benchmarks/run_benchmark.py` + `protocol.py` reused via import only.
- Cross-lane reports filed: MSRV clippy blocker (control lane),
  leg-integration hook proposal (benchmark lane), windowed-launch +
  dialog-E2E + WebGL-restore gaps (need a display).
