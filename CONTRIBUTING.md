# Contributing to Veyra

## No "works on my machine"

- Use a C++20 compiler, CMake ≥3.22, and Ninja for the checked-in presets.
- Build via preset: `cmake --preset dev && cmake --build build` (fallback in PR template).
- Use a Python venv with the platform-compatible `requirements*.txt` dependencies. Never commit data/weights/maps (see `.gitignore`).
- LF line endings enforced by `.gitattributes` + pre-commit. Run `pre-commit install` once.

## Branches + PRs

- Never push to `main`. Branch: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`.
- One concern per PR. Fill the PR template and include local verification results.
- Rebase on `main` before merge (linear history). Squash-merge. Require 1 review from any teammate.
- Map changes must cite `docs/map-correctness.md`; adaptive changes need a baseline (`DistanceLOD vs UtilityLOD`).

## Issues

- Templates only (bug / feature / task). Replace `needs-triage` with an owner + priority within 48h.
- Reproduce build or test issues from a clean checkout and paste the relevant logs.

## Protect `main` (repo Settings → Branches)

Require: PR before merging, 1 approval, no force-push, stale-review dismissal on.
