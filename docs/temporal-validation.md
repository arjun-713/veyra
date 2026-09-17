# Temporal validation evidence and checkpoint

This note records what the local dataset roots can prove and the command that
must be used when a real timed and posed sequence is supplied. It does not
turn frame IDs, file order, or filesystem metadata into timestamps.

## Local evidence audit

The checked local roots are:

- `data/raw/semanticposs/dataset`: 2,988 `.bin` scans and 2,988 labels across
  sequences `00`–`05`; six per-sequence `poses.txt` files and six `calib.txt`
  files; no `times.txt` or `timestamps.txt` files. The adapter reads pose and
  calibration from `sequences/<id>/`, and only reads timestamps from
  `timestamps/<id>.txt` or `sequences/<id>/timestamps.txt`. A replayed frame
  therefore has dataset pose/world coordinates but absent timestamp provenance.
- `data/raw/rellis3d/Rellis-3D`: 13,532 scans and 13,532 labels across
  sequences `00000`–`00004`; no pose, timestamp, or calibration files in the
  adapter's root, per-sequence, or configured metadata-root search locations.
  Replay consequently remains in the LiDAR frame with `identity_absent` pose
  and timestamp provenance `absent`.
- `data/raw/semantickitti`: absent in this checkout. The adapter expects the
  original layout `sequences/<id>/velodyne/*.bin` and, for this checkpoint,
  aligned `sequences/<id>/times.txt`, `poses.txt`, and `calib.txt`; labels are
  required by the default adapter configuration. `times.txt` is read in sorted
  scan order, each pose row must contain 12 finite values, and `Tr:` calibration
  is used to expose world-frame points.

These local roots cannot close real temporal-motion validation. Synthetic tests
exercise production association behavior only; they are not dataset evidence.

## Required real checkpoint

After SemanticKITTI is supplied at `SEMANTICKITTI_ROOT`, run exactly 100
contiguous frames from sequence `00` with no assumed rate:

```bash
.venv/bin/python scripts/validate_temporal.py \
  --dataset semantickitti \
  --root "$SEMANTICKITTI_ROOT" \
  --sequence 00 \
  --start 0 \
  --count 100 \
  --stride 1 \
  --max-range-m 100 \
  --output reports/temporal-semantickitti-00-100.json
```

The checkpoint passes only if all 100 adapter frames have finite, strictly
increasing dataset timestamps, dataset pose provenance, world coordinates, and
pose/frame timestamp agreement. Missing or untrusted metadata exits nonzero
and writes no success report. The report's motion section is observed tracker
evidence, not object-level ground truth.
