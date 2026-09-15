# Repository Structure — Veyra

Snapshot of `arjun-713/veyra` (SIH26053) as it exists on disk.

Read on branch `feat/cell-statistics` at commit `da739dd`, 2026-09-10.
Excludes `.git/`, `.venv/`, `.ruff_cache/` and the two build trees
(`build/`, `build-debug/`).

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
├── include/veyra/
│   ├── core/types.hpp                 CellId, resolution_m
│   ├── map/{cell.hpp, fwd.hpp}
│   ├── metrics/fwd.hpp
│   ├── policy/fwd.hpp
│   ├── temporal/fwd.hpp
│   └── terrain/fwd.hpp
│
├── src/                               CMakeLists.txt + map/ metrics/ policy/ temporal/ terrain/
│                                      each: CMakeLists.txt + stub.cpp
├── apps/                              CMakeLists.txt + benchmark/ live/ player/
│                                      each: CMakeLists.txt + main.cpp
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
├── perception/                        README.md, ground/, semantic/semantic_provider.hpp
├── benchmarks/README.md
├── ros2/README.md
└── viewer/README.md
```

---

## Where the code actually is

**All real C++ is header-only under `include/veyra/`.** Every module under
`src/` is still a `stub.cpp` with a `CMakeLists.txt` beside it — the directory
layout for the five subsystems exists, but none of them has an implementation.
The same is true of `apps/`: three `main.cpp` files, all placeholders.

| Header | Contents |
| --- | --- |
| `core/types.hpp` | `CellId`, `resolution_m`. Shared ground across all three domains. |
| `map/cell.hpp` | `Cell`, `updateCell`, `mergeCells`, `varianceOf`. |
| `map/fwd.hpp`, `metrics/fwd.hpp`, `policy/fwd.hpp`, `temporal/fwd.hpp`, `terrain/fwd.hpp` | one-line forward-declaration markers |

Note this snapshot is taken on `feat/cell-statistics`, which branches from
`main`. `core/types.hpp` here is the original short version; the expanded one
— `parentOf`, `childrenOf`, `worldToKey`, `extentOf`, the tile helpers — lives
on `feat/strengthen-index-alignment` and is not in this working tree.

## Tests

`docs/map-correctness.md` mandates eight invariant tests. **Two exist:**

| Test | File | State |
| --- | --- | --- |
| `test_index_alignment` | `tests/test_index_alignment.cpp` | exists |
| `test_split_merge` | `tests/test_split_merge.cpp` | exists, statistics half only |
| `test_point_conservation` | — | no file |
| `test_parent_child_exclusivity` | — | no file |
| `test_boundary_neighbors` | — | no file |
| `test_rolling_window` | — | no file |
| `test_memory_accounting` | — | no file |
| `test_near_field_protection` | — | no file |

`tests/check.hpp` is the assertion macro all of them use; it survives
`-DNDEBUG`, which `assert()` does not.

## Files that are not part of the repository

- `prompt.md`, `rule.md`, `structure.md` — untracked, personal, at the repo
  root. They stay out of every branch and every PR.
- `observation.md` — one level up at `~/SIH'26/`, entirely outside the
  repository, which is why it has never appeared in a commit.
- `scripts/check_docs_links.py` — tracked, but currently carries uncommitted
  local changes (ruff formatting) that belong in their own PR.

## Directories that are deliberately empty

`data/{raw,processed,cache}` and the five `datasets/*` subdirectories contain
only `.gitkeep`. `AGENTS.md` forbids committing datasets, weights, maps, dumps,
engines and bags; these are mount points, not content.
