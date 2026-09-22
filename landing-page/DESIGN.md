# DESIGN.md — Veyra Landing Page

Recorded from the built world (`landing-page/`), ground truth over intention.
Mode: Persuade. Parent world: the Veyra desktop instrument UI (dark ops).

## World

Night-operations instrument panel. Near-black blue ground (`#070c12` voids,
`#0b1118` ground, `#101a23` panels), 1px hairline borders (`#263642`), no
shadows except screenshot frames and the hero stage. One signal color —
teal `#62e0d7` — reserved for live value, primary action, and evidence chips.
LOD hues (cyan/green/amber/violet) appear only where resolution is the subject.
Light neutrals exist in tokens for future prose surfaces; the shipped page is
dark throughout.

## Type

Space Grotesk 600 display (hero, section titles, wordmark), Inter 400–600 UI
body and controls, IBM Plex Mono tabular for every number, chip, annotation,
and code line. All three self-hosted via Fontsource — zero runtime font CDN.

## Signature

The hero stage: a procedural UGV whose LiDAR sweep lights semantic points that
resolve into L0–L3 colored cells over polar range rings, with mono HTML
annotations (2.5D MAP / ACTIVE RADIUS / ADAPTIVE CELLS / SEMANTIC POINTS) and
an honest "cell sizes exaggerated" caption. Copy renders before WebGL; a static
SVG poster and an error boundary cover no-WebGL and crash paths.

## Composition

Left-weighted hero (copy 5fr / stage 7fr), then alternating rhythms: density
rows (Problem), a five-cell instrument strip (Pipeline), sticky voxel contrast
(2.5D), interactive rings (Resolution), full-width evidence table with
MEASURED/ANALYTICAL/UNAVAILABLE chips, 2×2 screenshot frames, dashed
coming-soon release cards, six-cell stack grid, centered close. One spacing
scale; reveals are single-orchestration IntersectionObserver fades, off under
reduced motion.

## Honesty rules (structural)

Benchmark values live only in `lib/benchmark-data.ts` with evidence kinds;
downloads only in `lib/releases.ts` with `coming-soon` states. No fake
screenshots (labeled placeholders under fixed filenames), no invented
partnerships, no analytical-as-measured claims. UtilityLOD ships no win claim.
