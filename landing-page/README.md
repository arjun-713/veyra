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
woff2 (Fontsource); no runtime Google Fonts dependency, so the packaged page
works fully offline.

## Vercel deployment

Import the repository, set **Root Directory** to `landing-page`, keep defaults
(`npm run build`, output `.next`). No environment variables required.

## Asset replacement

- Logo: `public/veyra-logo.png` (official mark, do not redraw).
- Screenshots: drop real captures into `public/screenshots/` using the exact
  filenames referenced in `components/screenshots/Showcase.tsx`
  (`map.webp`, `performance.webp`, `compare.webp`, `validation.webp`).
  Placeholders render until each file exists — no layout change needed.

## Data updates

- Benchmarks: edit `lib/benchmark-data.ts` only. Every metric carries
  `MEASURED` / `ANALYTICAL` / `UNAVAILABLE` semantics; never market analytical
  dense-3D memory as measured RSS.
- Downloads: edit `lib/releases.ts`. Insert real GitHub release URLs when the
  `tauri-v*` release workflow publishes artifacts; `isArtifactLive()`
  (`url !== RELEASES_URL`) renders a disabled card instead of a fake link.
