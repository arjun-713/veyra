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
The public `/api/releases` route reads published assets from the GitHub Releases
API and caches the result for five minutes. It does not need a GitHub token.

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
- Downloads: card metadata lives in `lib/releases.ts`; actual availability,
  file names, sizes, and direct download URLs come from `/api/releases` and the
  public GitHub Releases API. Cards link directly only when the latest
  published release contains a matching installer. Otherwise they link to the
  releases page. Desktop installers are downloaded and launched by the user's
  operating system; they do not execute inside the browser.
