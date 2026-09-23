# PandaSet (showcase dataset)

PandaSet (Hesai + Scale AI, CC BY 4.0) is an urban San Francisco / Peninsula
dataset: a 64-beam spinning Pandar64, a forward PandarGT, GPS/IMU poses and
point-wise semantic labels for 76 of its 103 sequences (80 sweeps at 10 Hz,
~8 s each). Veyra uses it as a dense, visually strong demo source; the
quantitative benchmark remains SemanticKITTI / SemanticPOSS.

There is no dedicated adapter. PandaSet is converted once into the
[generic manifest](../../docs/generic-dataset.md) and replayed through
`datasets.generic.ManifestDataset`, so the desktop's `generic` dataset type
opens it directly.

```bash
# 1. Fetch only what is needed (~330 MB per labelled sequence, no cameras)
python -m datasets.pandaset.download --list-labelled
python -m datasets.pandaset.download --sequences 011 021 039

# 2. Convert (pandas is a conversion-only dependency)
pip install pandas
python -m datasets.pandaset.convert   # -> data/raw/pandaset/veyra/manifest.json
```

In the desktop, choose `data/raw/pandaset/veyra` as the dataset root.

## Conversion choices

- **Coordinate frame.** Source sweeps are world-frame; they are moved into
  the Pandar64 frame so the manifest's pose carries the motion.
- **Beam origin (estimated).** The published lidar pose is not the beam
  origin: the road sits a steady ~0.27 m below it. Ring-sharpness estimation
  over labelled non-ground returns puts the origin 1.30 / 1.60 / 1.75 m above
  the published position for sequences 021 / 011 / 039; the pooled 1.55 m is
  applied (road ≈ −1.83 m in the sensor frame afterwards). It is recorded as
  `sensor_origin.source = estimated_from_beam_ring_sharpness`. Override with
  `--origin-offset`.
- **Sensors.** Pandar64 only by default. `--sensors both` adds PandarGT
  returns, which breaks the single-origin assumption of depth-image
  visibility clearing.
- **Taxonomy.** `PANDASET_LABELS` in `datasets/common/taxonomy.py` maps by
  meaning; smoke, exhaust, spray, reflection, scooters, animals, cones,
  pylons and rolling containers stay unknown.

Selected demo sequences (from front-camera previews): 011 Embarcadero with
the Bay Bridge, 021 palm-lined boulevard, 039 downtown high-rises.
