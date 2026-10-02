# Repository Structure — Veyra

Current orientation guide for the Veyra repository. Generated datasets,
model weights, build trees, and local environments are intentionally excluded
from version control.

---

## Tree

```
veyra/
├── AGENTS.md  CONTRIBUTING.md  README.md  CMakeLists.txt  CMakePresets.json
├── .clang-format  .editorconfig  .gitattributes  .gitignore
├── .pre-commit-config.yaml  skills-lock.json
├── requirements.txt  requirements-dev.txt
├── prompt.md                          ← untracked, personal
├── rule.md                            ← untracked, personal
├── structure.md                       ← this file, untracked
│
├── .agents/skills/                    cpp-pro/ (+references/), test-driven-development/,
│                                      using-git-worktrees/, verification-before-completion/,
│                                      writing-plans/
├── .devcontainer/devcontainer.json
├── .github/                           dependabot.yml, PULL_REQUEST_TEMPLATE.md,
│                                      ISSUE_TEMPLATE/{bug_report,config,feature_request,task}.yml
│
├── include/veyra/                     Public C++20 map, policy, runtime and metrics APIs
├── src/                               C++ map, policy, runtime and metrics implementations
├── apps/                              Native benchmark/live/player/runtime entry points
├── tests/
│   ├── CMakeLists.txt
│   ├── check.hpp
│   ├── test_index_alignment.cpp
│   └── test_split_merge.cpp
│
├── docs/                              architecture, datasets-benchmarks, development,
│                                      map-correctness, perception-terrain-temporal,
│                                      resolution-policies
├── configs/                           datasets, distance_lod, hardware_profiles, utility_lod (.yaml)
├── scripts/check_docs_links.py
│
├── data/                              cache/ processed/ raw/  (all .gitkeep only)
├── datasets/                          README.md, download_semantickitti.sh,
│                                      common/ great_outdoors/ rellis/ semantickitti/ semanticposs/
├── perception/                        Semantic, Patchwork++, terrain and temporal stages
├── benchmarks/                        Four-policy reports and regression checks
├── apps/desktop/                      Electron + Svelte desktop application
├── ros2/README.md                     Integration notes
└── viewer/                            Python HTTP viewer and static Three.js client
```

---

## Where the code actually is

The native map and policy implementations are under `src/` and are compiled
through the root CMake project. Python replay, perception, protocol and
telemetry run under `runtime/`, `datasets/` and `perception/`. Benchmark and
product entry points are wired through `apps/`, `benchmarks/`, `viewer/` and
`apps/desktop/`; these are not placeholder-only directories.

The primary runtime path is:

```text
dataset adapter → ObservationFrame → Python perception → V2 protocol
→ C++ mapper/policy → snapshot/telemetry → viewer or Electron renderer
```

## Tests

`docs/map-correctness.md` defines the map invariants. Native CTest and Python
tests cover indexing, split/merge, ownership, rolling windows, memory and
runtime/protocol integration; inspect the current test files for exact
coverage rather than relying on an old snapshot.

| Area | Representative tests |
| --- | --- |
| indexing and boundaries | `tests/test_index_alignment.cpp`, `tests/test_boundary_neighbors.cpp` |
| split/merge and ownership | `tests/test_split_merge.cpp`, `tests/test_parent_child_exclusivity.cpp` |
| conservation and rolling window | `tests/test_point_conservation.cpp`, `tests/test_rolling_window.cpp` |
| memory and safety floor | `tests/test_memory_accounting.cpp`, `tests/test_near_field_protection.cpp` |

`tests/check.hpp` is the assertion macro all of them use; it survives
`-DNDEBUG`, which `assert()` does not.

## Data and generated artifacts

`data/{raw,processed,cache}` is a local mount for original datasets, models and
derived artifacts. `AGENTS.md` forbids committing datasets, weights, maps,
dumps, engines and bags; the corresponding paths remain ignored.
