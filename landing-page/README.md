# Veyra landing page — local development, production build, Vercel deployment.

## Local development

```bash
cd landing-page
npm install
npm run dev
```

Open http://localhost:3000. The hero 3D scene lazy-loads; copy and CTAs render first.

## Production build

```bash
npm run build
npm start
```

`next build` must pass with zero TypeScript/ESLint errors. Fonts ship as local
woff2 (Fontsource), with no runtime Google Fonts dependency. Release discovery
and installer downloads require network access.

## Vercel deployment

Import the repository, set **Root Directory** to `landing-page`, keep defaults
(`npm run build`, output `.next`). No environment variables required.
The public `/api/releases` route reads published assets from the GitHub Releases
API's `/releases/latest` endpoint and caches the result for five minutes. It does
not need a GitHub token. It enables downloads only for a published stable release
containing all six supported installers, never a draft, prerelease or partial
upload. Successful main releases therefore update download links without a
website redeploy. Cached responses can lag publication; the route allows ten
minutes of stale-while-revalidate on top of its five-minute cache lifetime.

## Asset replacement

- Logo: `public/veyra-logo.png` (official mark, do not redraw).
- Hero: `public/hero/veyra-lidar-map.webp`, rendered by `components/hero/Hero.tsx`
  with an inline SVG fallback. This generated illustration is not an app capture.
- Screenshots: drop real captures into `public/screenshots/` using the exact
  filenames referenced in `components/screenshots/Showcase.tsx`
  (`map.webp`, `performance.webp`, `compare.webp`, `validation.webp`).
  Placeholders render until each file exists — no layout change needed.

## Data updates

- Benchmarks: edit `lib/benchmark-data.ts` only. Every metric carries
  `MEASURED` / `ANALYTICAL` / `UNAVAILABLE` semantics; never market analytical
  dense-3D memory as measured RSS.
- Downloads: card metadata lives in `lib/releases.ts`; actual availability,
  file names, sizes, and direct download URLs come from `/api/releases` and the
  public GitHub Releases API. Cards link directly only when the latest
  published release contains a matching installer. Otherwise they link to the
  releases page. Desktop installers are downloaded and launched by the user's
  operating system; they do not execute inside the browser.

## Visual conventions

The landing page uses a bright, light instrument theme: near-white `#f7f9fb`,
white elevated surfaces, navy ink `#0c1522`, hairlines `#dfe7ef` and restrained
teal (`#14b8b0` fills, `#0b6e6c` text, `#5eead4` glow). Pale-blue washes are
background only; no purple or gradient headlines.

Space Grotesk 600 owns display type (hero 52–108 px clamp), Inter body/controls,
and IBM Plex Mono measurements/annotations. Use left-aligned oversized headings,
asymmetric grids and thin rules rather than repeated cards. The hero pairs
editorial copy/CTAs with a mask-dissolved LiDAR illustration and four HTML
map annotations. Evidence tables carry measured/analytical/unavailable chips;
download rows expose all platforms. Keep slow hero drift and reveal motion
restrained and disable them for reduced-motion preferences.

Preserve the provenance labels in `lib/benchmark-data.ts` (DistanceLOD headline,
UtilityLOD experimental). Real screenshots and generated illustrations must
remain distinguishable; missing screenshots retain labelled placeholders.
