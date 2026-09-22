# DESIGN.md — Veyra Landing Page (light world)

Recorded from the built world (`landing-page/`), ground truth over intention.
Mode: Persuade. This page is a full visual-system redesign of the earlier dark
instrument concept; the dark ops language survives only in the desktop app.

## World

Bright premium light instrument. Near-white cool ground (`#f7f9fb`), white
cards only where elevation is earned, navy-black ink (`#0c1522`), hairline
dividers (`#dfe7ef`), teal signal (`#14b8b0` fills, `#0b6e6c` text accents,
`#5eead4` glow) used sparingly. Pale-blue background washes only — never
purple, never gradient headline text (one cyan period).

## Type

Space Grotesk 600 display (hero clamp 52–108px, section titles), Inter UI
body/controls, IBM Plex Mono tabular for measures, chips, annotations, code.
All self-hosted via Fontsource — zero runtime font CDN.

## Signature

Hero: editorial left column (eyebrow rule, huge black headline, factual
subcopy, dual CTA, divider-separated metrics, honest footnote) beside a
seamless generated LiDAR scene that bleeds into the page via mask-dissolve —
no rectangular frame. Four HTML map annotations (mono title + value, hairline
border, connector dot) overlay the scene; the asset swaps at
`public/hero/veyra-lidar-map.webp` with zero structural change, and an inline
SVG stand-in covers failure.

## Composition

Oversized left-aligned heads, strong whitespace, asymmetric grids, thin rules
instead of card walls. Evidence is an engineering report table with
MEASURED/ANALYTICAL/UNAVAILABLE chips; range quality is a four-band scale;
downloads are a ruled five-column list with honest release notes. Motion is
restrained: one slow hero drift, single-orchestration reveals, off under
reduced motion.

## Honesty rules (structural)

Benchmarks only in `lib/benchmark-data.ts` (FINAL fixed-benchmarks round:
DistanceLOD headline, UtilityLOD experimental). Downloads only in
`lib/releases.ts`, all cards linking the real GitHub releases page with
ships-with-first-tag microcopy. Screenshots are labeled `.webp` placeholders.
