# GitHub Actions CI tiers

Veyra separates inexpensive regression detection from validations that require
large datasets, multiple operating systems, or long-running native builds.

## Fast CI

`CI` runs on pushes to `main` and pull requests that touch implementation, tests,
configuration, workflow, or desktop paths. A small classifier then runs only
the affected jobs:

- `C++ Release core checks`: one strict Release build, CTest, and the existing
  owned C++ formatting check.
- `Python tests and static checks`: pinned dependencies, Ruff, syntax checks,
  benchmark/unit tests, and the full Python test discovery.
- `Desktop frontend and Rust checks`: Ubuntu frontend tests/check/build plus
  Rust fmt/test/clippy; it does not package Tauri installers.

The jobs run independently after path classification, and newer pushes cancel
obsolete validation for the same branch or pull request. Documentation-only
changes do not match the CI trigger paths.

`tests/**` intentionally feeds both C++ and Python jobs because the repository
contains tests for both production stacks and the classifier cannot safely
infer test ownership from filenames alone.

## Manual heavy validation

`SemanticPOSS benchmark` is now `workflow_dispatch` only. It retains the
official archive URL, pinned size/SHA-256 verification, cache, extraction,
perception/map policies, provenance, correctness gates, artifacts, and report
comment workflow. It accepts sequence, frame count, perception mode, policy,
and repetition inputs. It is not a pull-request or scheduled workflow.

`Tauri desktop` is also `workflow_dispatch` only. Its Ubuntu, Windows, and
macOS matrix remains available for deliberate cross-platform validation but is
not part of every pull request.

Release workflows remain tag/manual driven and continue to own installer
creation and release artifacts.

## Cost evidence

Recent repository runs provide the baseline for this change:

| Workflow | Observed run | Observed wall time | Interpretation |
| --- | ---: | ---: | --- |
| SemanticPOSS benchmark | `35429194932` | about 54 minutes | scheduled real-data run failed after consuming a long runner interval |
| Tauri desktop matrix | `35461418773` | about 3.5 minutes | three hosted OS jobs ran for one pull request |
| CI | `35461418877` | about 46 seconds | four jobs, including duplicate C++ Debug/Release setup |

These are wall-clock observations, not a billing-minute calculation. The
expected PR design removes the benchmark and three-OS matrix from ordinary PR
events, removes the C++ Debug matrix leg, and skips unaffected language jobs.
Actual savings depend on changed paths and hosted-runner billing.

## Required-check note

The C++ status name changes from `C++ Debug`/`C++ Release` to `C++ Release core
checks`, and the separate `C++ formatting` check is folded into that job.
Repository branch protection should require the new fast-gate names after this
PR is reviewed. The manual benchmark and cross-platform workflows should not
be required checks for ordinary pull requests.
