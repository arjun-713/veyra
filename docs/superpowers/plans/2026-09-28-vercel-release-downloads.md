# Veyra Release Downloads and Landing Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish platform-native Tauri installers and expose only real published GitHub Release assets as downloads on Veyra's existing landing page.

**Architecture:** `release-tauri.yml` becomes the only automatic tagged desktop release workflow and publishes curated installer assets plus aggregate checksums/manifest. A small Next.js API route reads the public GitHub Releases API with framework caching; the existing download component resolves actual asset filenames against the existing OS cards and shows honest loading, error, and unavailable states.

**Tech Stack:** GitHub Actions, GitHub CLI, Python 3, Next.js 15 App Router, React 19, TypeScript, Node's built-in test runner.

**Spec:** User request in this task and merged download-card contract from PR #92.

## Global Constraints

- Preserve the existing `landing-page/DESIGN.md` light-instrument visual system.
- Never fabricate a release, installer URL, asset size, or availability state.
- Tauri is the canonical release workflow; the legacy workflow must not auto-trigger on version tags.
- Native desktop apps download from the site and run after installation; they do not execute inside the browser.
- Preserve untracked `:memory:.ses`; do not stage or remove it.
- Do not publish stale local installer binaries as current releases.
- Vercel deployment requires valid account authentication and a verified available project alias.

---

### Task 1: Curate and publish Tauri release assets

**Files:**
- Modify: `.github/workflows/release-tauri.yml`
- Delete: `.github/workflows/release.yml`
- Create: `scripts/build_tauri_release_manifest.py`
- Create: `tests/scripts/test_build_tauri_release_manifest.py`

**Interfaces:**
- Release trigger: `v*` tags and explicit workflow dispatch.
- Aggregate manifest: schema version, release version, and each installer filename, platform, architecture, byte size, SHA-256.
- Release assets: only `.deb`, `.rpm`, `.AppImage`, Windows NSIS `-setup.exe`, and `.dmg` installers, plus `release-manifest.json` and `SHA256SUMS`.

- [ ] Write failing tests for artifact aggregation: platform/architecture extraction from matrix artifact folders, installer-only filtering, checksum/size recording, duplicate filename rejection, and missing-artifact failure.
- [ ] Run the focused Python tests and confirm they fail because the aggregate helper does not exist.
- [ ] Implement the aggregate manifest helper with deterministic ordering and streamed SHA-256 reads.
- [ ] Run the focused tests and confirm they pass.
- [ ] Change `release-tauri.yml` to trigger on `v*`, stage only native installer files per matrix leg, download all matrix assets in a publish job, write aggregate manifest/checksums, and create/update the GitHub Release with `contents: write` scoped to that job.
- [ ] Remove the obsolete `release.yml` path so only the Tauri workflow can publish desktop releases.
- [ ] Validate workflow YAML and run release-helper tests.

### Task 2: Resolve real published assets on the landing page

**Files:**
- Modify: `landing-page/lib/releases.ts`
- Create: `landing-page/lib/releases.test.ts`
- Create: `landing-page/app/api/releases/route.ts`
- Modify: `landing-page/components/download/Download.tsx`
- Modify: `landing-page/components/download/Download.css` only if the existing tokens need a small state treatment.
- Modify: `landing-page/README.md`
- Create: `landing-page/vercel.json`

**Interfaces:**
- `GET /api/releases` returns a typed published release (tag, URL, assets) or an explicit unavailable/error response; upstream GitHub fetch is cached for five minutes.
- Asset resolver maps the existing six download-card IDs to actual release assets by case-insensitive Tauri filename/architecture patterns.
- A card is live only when a matching GitHub asset URL exists; actual file name and size replace placeholders.

- [ ] Write failing Node tests for all six asset mappings, case-insensitive Tauri filenames, missing architectures, unrelated assets, and byte-size formatting.
- [ ] Run focused tests and confirm expected failures.
- [ ] Implement the typed resolver and tests using Node's built-in test runner with TypeScript stripping; add a `test` script if supported by the locked Node version.
- [ ] Run focused tests and confirm they pass.
- [ ] Implement the server API route with GitHub API validation, caching, timeout/error handling, and no token requirement for this public repository.
- [ ] Update the existing download component to fetch release metadata, show honest loading/error/no-release/per-artifact-unavailable states, and link only to matched asset URLs.
- [ ] Keep platform tabs and current visual hierarchy; ensure accessible status announcements and usable links.
- [ ] Document that web users download the native installer and launch Veyra locally; the desktop binary does not execute inside the browser.
- [ ] Pin the landing deployment's Vercel framework to Next.js so route handlers and generated Next output are deployed as functions/assets.
- [ ] Run landing-page lint, tests, typecheck, and production build.

### Task 3: Validate and deploy the landing page

**Files:**
- No application source changes unless verification finds a specific defect.

**Interfaces:**
- Vercel project root: `landing-page`.
- Preferred hostname: `veyra.vercel.app`; fallback: `veyra-lidar.vercel.app`, chosen only after authenticated availability check.

- [ ] Confirm the production build and API no-release behavior locally.
- [ ] Check `vercel whoami`, existing Vercel projects, and both requested aliases with authenticated CLI access.
- [ ] Link/deploy only `landing-page` to the selected available alias; do not deploy the repository root or desktop app.
- [ ] Verify the production URL, `/download`, and `/api/releases` responses. If there is no published release yet, confirm cards honestly remain unavailable while linking to the releases page.
- [ ] Record the exact deployment URL and any remaining publication blocker.

## Self-review

- The release workflow task owns packaging/publishing; the landing-page task only consumes the public release API.
- Real availability is keyed to actual asset URLs, not tag existence or hard-coded status text.
- Missing OS/architecture builds remain unavailable independently; other platform downloads continue working.
- No stale local package is uploaded, and no installer is claimed to run in-browser.
- Final rollout requires the release workflow to be merged and a tagged release to finish; production Vercel deployment additionally requires a valid Vercel CLI session.
