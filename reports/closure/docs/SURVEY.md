# Docs / Demo / Reproducibility — Survey slice 1 (no rewrites)

Worktree: `worktrees/docs-demo`, branch `agent/docs-demo`, base `demo-readiness @ 1ad1388`
(confirmed via `git log`; worktree newly created, no reset/clean used).
Scope: survey only. No doc file was modified in this slice except this report.

Scorecard context: `docs-demo` node is 55/OPEN ("Fresh-clone setup/build/test/
validate/benchmark/launch from docs only; docs claims match evidence; provenance
recorded; packaged demo rehearsal all policies/layers/telemetry").
`reports/submission_closure.json` (48-row gate) reports **0/48 rows closed**.

## 1. Command audit (spot-check only, no full build)

| # | Command (from docs) | Result in this worktree |
|---|---|---|
| 1 | `cmake -S . -B <dir> -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DVEYRA_BUILD_APPS=ON` (README, product-runtime) | PASS — configure done, GCC 16.2.1, Python 3.14.7 found. Output to `/tmp/opencode/veyra-docs-demo-configure` |
| 2 | Same + `-DCMAKE_CXX_FLAGS="-Wall -Wextra -Wpedantic -Werror"` (validate_sih.sh --ci flags) | PASS — strict-flags configure done (`/tmp/opencode/veyra-docs-demo-strict`) |
| 3 | `cmake --build` / `ctest` | NOT RUN this slice (out of scope; full build not attempted) |
| 4 | `python3 -m pytest --collect-only -q` (repo root) | PASS — **317 tests collected** (system python3, pytest 8.4.2) |
| 5 | `python3 -m pytest --collect-only -q benchmarks` | PASS — **48 tests collected** |
| 6 | `python3 scripts/validate_submission_closure.py reports/submission_closure.json` | PASS (structural) — `submission closure scorecard: 0/48 rows closed`, exit 0 |
| 7 | `python3 scripts/check_docs_links.py` | PASS — `docs links OK` |
| 8 | `bash benchmarks/run_local.sh --help` | PASS — usage prints, no network/download performed |
| 9 | `bash scripts/validate_sih.sh --ci` (fresh-worktree equivalent of fresh-clone) | FAILS FAST (expected, informative): `Python interpreter is unavailable: .../worktrees/docs-demo/.venv/bin/python`, exit 2. No build attempted |
| 10 | `python -m pytest -q tests/test_rellis_adapter.py tests/test_semanticposs_adapter.py tests/test_semantickitti_adapter.py` (dataset-validation.md) | NOT RUN this slice (collect-only scope); listed for slice 2 |

### Fresh-clone gaps found (docs-only path does not reach green)

- G1. **README quick start omits dependency install.** It ends at
  `python -m venv .venv && source .venv/bin/activate` with no
  `pip install -r requirements.txt -r requirements-dev.txt` (that step exists
  only in `docs/product-runtime.md:33`). `validate_sih.sh --ci` then fails at
  its first gate (missing `.venv/bin/python`).
- G2. **`validate_sih.sh --ci` hard-requires `apps/desktop/node_modules`**
  (`scripts/validate_sih.sh:122-132`, exit 2 otherwise). Fresh clone has no
  `node_modules`; no doc strings together the full order
  (venv → pip install → `npm ci` in `apps/desktop/` → `validate_sih.sh --ci`).
  The failure message is honest, but the prerequisite chain is not documented
  in one place.
- G3. **`data/raw/` is empty in a fresh clone** (datasets gitignored, verified:
  `ls data/raw/` → empty; `benchmark-results/` absent). All `run_local.sh` /
  `--full` dataset commands therefore fail without local data. Docs are mostly
  honest about this (`run_local.sh --help`: "No network access or dataset
  download is performed"), but there is no single "what you need to supply"
  prerequisites table.
- G4. **Two build idioms disagree.** README/product-runtime use
  `cmake -S . -B build`; CONTRIBUTING.md prescribes `cmake --preset dev`
  (preset exists — verified `dev` in `CMakePresets.json`). CONTRIBUTING also
  pins "Python 3.11" while this host runs 3.13/3.14. Minor drift, worth one line.
- G5. **Two desktop shells documented in parallel.** `product-runtime.md` Run
  section is Electron (`npm start`); `tauri.md` is Tauri (`npm run tauri:dev`);
  the `product-runtime.md` pipeline diagram still shows
  `-> Electron main/preload -> Svelte renderer`. Tauri is partial (scorecard
  `tauri` node 55/OPEN). A newcomer cannot tell which shell the demo uses.

## 2. What the validators gate (and what they do not)

### `scripts/validate_sih.sh --ci | --full`

- `--ci`: (a) `validate_submission_closure.py` structural check; (b) strict
  CMake configure+build (`-Werror`); (c) full `ctest`; (d) python unittest
  discovery over `benchmarks/` and `tests/`; (e) `ruff check` + format check +
  `compileall`; (f) `bash -n` syntax; (g) desktop `npm test`, `npm run check`,
  `npm run build` — else hard fail. Ends with
  `REAL DATA: NOT RUN (use ... --full)`. **Gates: build/test/lint/desktop
  determinism. Does NOT gate: any real-data or performance claim.**
- `--full`: additionally requires official local SemanticPOSS seq 00 AND a
  dataset-compatible perception config that **passes the quality gate first**
  (`validate_perception.py`, `quality_frames` default 16). Default config
  `configs/perception-salsanext.yaml` **intentionally fails for SemanticPOSS**
  (SemanticKITTI-only model) — so `--full` cannot pass today without a native
  POSS model (CENet, unverified) or KITTI data. Then runs the 4-policy
  benchmark. **Gates: perception quality before map numbers — the anti-gaming
  choke point. Currently red by design on local data.**

### `scripts/validate_submission_closure.py`

Structural schema gate over `reports/submission_closure.json`: `schema_version==1`,
exact 48 expected capabilities, required row keys, `target==100`,
`100% ⟺ CLOSED + non-empty evidence_artifact + hex closing_commit SHA`,
open rows require `blocking_issue`. **It validates shape, not truth: it never
checks that evidence files exist.** Passing it (currently 0/48, exit 0) is not
closure evidence.

## 3. Claim-vs-evidence mismatches (perf, OS, neural)

Grading: OK = claim matches evidence; DRIFT = wording outruns evidence.

1. **Perf posture — OK (with two watch items).** README Status:
  "No FPS/accuracy/RAM claim is published until a reproducible benchmark on
  named hardware supports it." `datasets-benchmarks.md` labels `94.3%` an
  analytical estimate and states the 3D reference "is never allocated, timed,
  or presented as measured RSS". Watch items: (a) `semantic-model-evidence.md`
  carries two SalsaNext latency pairs for different runs — p50/p95 **1.96/2.07 s**
  (§Current pinned backend, 16 frames) vs **3.0/4.4 s** (closure run, i5-8350U
  under load avg ~16) — explainable but confusable; (b) `development.md`
  guiding principle says "real-time capable" while no end-to-end rate is
  measured (scorecard Performance/FPS node low) — aspirational adjective in an
  otherwise careful tree.
2. **OS support — OK in prose, thin in artifacts.** `tauri.md:46-49` honestly
  states non-Linux artifacts need their native OS. `desktop-electron-audit.md`
  records: no `.rpm`, no `.AppImage`, Squirrel-only (no NSIS/MSI), no Tauri CI
  yet; scorecard `platform` node 25/OPEN. No doc claims Windows/macOS parity —
  but nothing stops a reader assuming the release workflow equals support.
3. **Neural quality — OK, and the gate works.** `semantic-model-evidence.md`:
  SalsaNext-on-POSS measures **8.74% mIoU / 29.41% accuracy** (16 frames) and
  "fails the semantic mIoU floor, as it should"; geometry proven correct,
  checkpoint wrong-domain (FOV/rows/intensity/range/taxonomy table). No doc
  presents cross-domain output as a quality result. **Consequence: there is no
  demo-able neural backend for POSS data today.**
4. **CENet — DRIFT RISK (external to docs, internal to demo plan).** The task
  checklist names a "neural CENet" demo step, but `semantic-model-evidence.md`
  §Native candidate: checkpoint license/digest/compatibility **not verified**,
  "not downloaded, packaged, enabled, or represented as a Veyra backend yet".
  A CENet demo step today would misrepresent the tree. Must stay BLOCKED until
  the 5-point acceptance list (§Acceptance) is met.
5. **Temporal — OK but narrow.** `temporal-validation.md` + `perception-acceptance.md`:
  real motion unproven (no timestamps on POSS; no KITTI asset); 335/383/387 ms
  clustering figure explicitly "a spatial performance measurement, not temporal
  motion validation". Demo may show tracker behavior, never motion validation.
6. **Telemetry/UI numbers — DRIFT (catalogued, unfixed).** `desktop-electron-audit.md`
  M1–M5: FPS cards show processing throughput as FPS; `Semantic mIoU` card is
  permanently `—` (field never emitted); map bytes vs RSS share one MB formatter;
  100k-point/100k-cell GPU caps with no sampling indicator; no ctx-loss handling.
  Any demo telemetry narration must use the audit's honest labels.
7. **Terrain — OK.** `ground-terrain-evidence.md`: POSS 10-frame P/R/F1/IoU
  0.776/0.950/0.854/0.746 with config SHA, hardware named (i5-8350U, Fedora),
  far-field degradation retained as measured; RELLIS/terrain quality marked
  unavailable with reasons. Post-fix 1.3x speedup recorded as interleaved A/B
  medians. Model of how to report.

## 4. Demo rehearsal checklist (draft, status as of 1ad1388)

Conventions: READY = works on documented path; COND = works with caveat script;
BLOCKED = must not be shown as working. Dataset assumption: local SemanticPOSS
seq 00 present (absent in fresh clone — G3); no KITTI asset (gated).

| Step | Action | Status | Command / path | Expect / fallback narration |
|---|---|---|---|---|
| 0 | Start from packaged Tauri app | BLOCKED | `npm run tauri:build` (`tauri.md:43`); staging via `scripts/stage_tauri_backend.py` | No packaged Tauri artifact proven (tauri 55/OPEN, no Tauri CI). Fallback: dev shell `npm run tauri:dev` or Electron reference (`npm start`), narrated as dev-only |
| 1 | Select dataset + sequence | COND | Desktop dataset picker → SemanticPOSS seq 00; or `benchmarks/run_local.sh --dataset semanticposs --sequence 00` | Fresh clone: directory empty — pre-stage data before rehearsal; show picker refusing gracefully with no data |
| 2 | Neural semantics (CENet) | BLOCKED | — (`semantic-model-evidence.md` §Acceptance) | Do NOT demo. Narrate instead: SalsaNext geometry-correct but wrong-domain (8.7% mIoU), CENet acceptance pending. GT-provider replay only if explicitly labeled passthrough, never as model accuracy |
| 3 | Ground: Patchwork++ | READY (COND fresh) | `scripts/validate_perception.py --dataset semanticposs ... --config configs/perception.yaml` (`ground-terrain-evidence.md:34-37`) | Expect ground ratio ~0.33-0.34, F1 ~0.85 (10-frame). Narrate 60-100 m degradation as measured |
| 4 | Terrain: drivable/non-drivable/unknown | READY (COND fresh) | Same artifact: terrain counts + proxies (P(drivable\|ref ground) ~0.91) | Narrate: no drivability labels exist — counts only, quality unavailable, unknown ≠ free |
| 5 | Temporal / motion states | COND | Tracker on POSS replay (poses, timestamps absent → cluster-only) | Show STATIC/POSSIBLY/MOVING plumbing; narrate explicitly: spatial only, real motion validation BLOCKED on KITTI + `validate_temporal.py` 100-frame checkpoint |
| 6 | Map: 4 policies incl. DistanceLOD vs UtilityLOD | READY (COND data+build) | `benchmarks/run_local.sh ... --policies uniform5,uniform40,distance_lod,utility_lod` | Show per-policy cells/RSS/latency + `utility_vs_distance_detail`; never compare only vs dense-3D strawman; 3D reference is analytical |
| 7 | Layers: ground/terrain/motion/utility heatmap | COND | Desktop layer buttons; `layerUnavailable` n/a badge path | Audit notes missing-data badges exist — rehearse the unavailable path too; utility heatmap = engine-normalized score |
| 8 | Telemetry: FPS/RAM/latency | COND | Performance workspace + metric strip | Use honest labels only (processing FPS; backend RSS vs map bytes); point out permanently-`—` mIoU card and sampling caps per audit M1/R1 |
| 9 | Stop / supervision | COND | Stop, restart, crash paths | Rehearse: no orphan/duplicate processes (audit B6/sigkill-orphan gaps known); show diagnostics export |
| 10 | Provenance close-out | COND | Artifact JSON: config SHA, git identity, host facts, frame range | Every number shown must trace to an artifact; analytical vs measured labeled aloud |

Pre-rehearsal gate (all must be true): C++ build green; `.venv` + requirements
installed; `apps/desktop/node_modules` present; SemanticPOSS seq 00 staged;
`validate_sih.sh --ci` PASS; CENet/temporal caveats printed on the run sheet.

## 5. Gaps / next slices (no fixes applied here)

1. Slice 2 (repro): single prerequisites table + README install line (G1–G3);
   reconcile `preset dev` vs `-B build` (G4); name the demo shell (G5).
2. Slice 3 (claims): disambiguate the two SalsaNext latency pairs in place;
   soften "real-time capable" or attach the missing measurement (watch items §3.1).
3. Demo unblockers (other streams): CENet 5-point acceptance; KITTI asset for
   `validate_temporal.py` 100-frame checkpoint; packaged-Tauri artifact + native
   OS smoke; telemetry M1–M5 presentation fixes.
4. Evidence hygiene: `validate_submission_closure.py` could optionally warn on
   missing `evidence_artifact` paths (currently shape-only) — orchestrator call.

## Appendix — exact spot-check outputs

- `cmake -S . -B /tmp/opencode/veyra-docs-demo-configure ...` → `Build files
  have been written to: /tmp/opencode/veyra-docs-demo-configure` (0.7 s).
- Strict-flags configure → same, `/tmp/opencode/veyra-docs-demo-strict`.
- `pytest --collect-only -q` (root) → `317 tests collected in 0.61s`.
- `pytest --collect-only -q benchmarks` → `48 tests collected in 0.16s`.
- `validate_submission_closure.py` → `submission closure scorecard: 0/48 rows closed`.
- `check_docs_links.py` → `docs links OK`.
- `validate_sih.sh --ci` → `Python interpreter is unavailable:
  .../worktrees/docs-demo/.venv/bin/python` (exit 2, pre-build).
- `data/raw/` → empty; `benchmark-results/` → absent (this worktree).
