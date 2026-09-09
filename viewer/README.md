# Viewer — Veyra Scope (Vinay + team)

Local dataset visualizer. Real files only: it serves the exact `.bin` /
`.label` bytes in `data/` that the future adapters will consume.

## Run

From the repo root:

```bash
python3 viewer/server.py
# Veyra viewer  repo=...  ->  http://127.0.0.1:8765/
```

Requires `numpy` (`requirements.txt`). `pyyaml` used when present.

## What it does

- Dataset switch (RELLIS-3D / SemanticPOSS) from `configs/datasets.yaml`
- Sequence banks, frame scrubber + step strip, RUN playback with tempo
- Color modes: semantic / elevation / intensity; views: orbit / top / driver
- Readouts: frame id, point counts, class histogram, scan↔label pairing LED
- Keyboard: `←/→` step (`shift` ×10), `space` run, `1/2/3` color, `O/T/D` view
- Deep links: `#d=rellis3d&s=00000&i=42`

Viz latency stays separate from map-update latency by design: the browser
renders decimated frames, Python does all file I/O.
