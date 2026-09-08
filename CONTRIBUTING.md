# Contributing — Veyra (3-person team)

## No "works on my machine"

- Use `.devcontainer` **or** match CI exactly: Ubuntu 22.04, GCC 11, CMake ≥3.22, Ninja, Python 3.11.
- Build via preset: `cmake --preset dev && cmake --build --preset dev` (fallback in PR template).
- Python in a venv from pinned `requirements*.txt`. Never commit data/weights/maps (see `.gitignore`).
- LF line endings enforced by `.gitattributes` + pre-commit. Run `pre-commit install` once.

## Branches + PRs

- Never push to `main`. Branch: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`.
- One concern per PR. Fill the PR template. CI + dependency review must be green.
- Rebase on `main` before merge (linear history). Squash-merge. Require 1 review from any teammate.
- Map changes must cite `docs/map-correctness.md`; adaptive changes need a baseline (`DistanceLOD vs UtilityLOD`).

## Issues

- Templates only (bug / feature / task). Automation adds `needs-triage` + domain labels — replace `needs-triage` with an owner + priority within 48h.
- Daily standup issue auto-opens Mon–Fri, rotates `arjun-713 → samay43 → bmvinay7`, closes the previous one.
- CI failure on `main` auto-files a `bug`+`ci` issue — repro from clean checkout, paste logs.

## Protect `main` (repo Settings → Branches)

Require: PR before merging, 1 approval, `CI` + `Dependency review` status checks, no force-push, stale-review dismissal on.
