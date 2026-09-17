# Veyra landing page (`site/`)

Standalone static page. No build step, no dependencies, no framework.
Open directly or serve from the repo root:

```bash
python3 -m http.server 8123
# http://127.0.0.1:8123/site/
```

## Files

- `index.html` — all sections, semantic markup, honest figure labels.
- `styles.css` — extends the Veyra Scope instrument tokens from the repo
  root `DESIGN.md` (`#141414` charcoal, bone silkscreen, signal-red /
  sweep-amber / pair-green lamps, square corners, tabular mono numerals).
- `app.js` — Canvas visualizations, toggles, scroll reveal, counters.
  Zero dependencies. Pauses off-screen animation; honors
  `prefers-reduced-motion`.

## Rules for editing numbers

- Analytical cell math (12.57M → 714.7K, 94.3%) is computed in-page from
  `πr²/cell²` and must stay labeled **analytical / theoretical**.
- Measured values come from `benchmark-results/` in the repo root
  (currently one single-frame C++ map snapshot + Python research-pipeline
  stage timings). Never present them as fleet, hardware, or real-time
  claims. Anything without data stays **Benchmark pending**.
- Do not advertise the reversible detail cache, validated temporal
  motion tracking, or SemanticKITTI / Great Outdoors validation until the
  repository holds the evidence. See root `README.md` status section.
