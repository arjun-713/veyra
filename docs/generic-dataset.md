# Generic dataset manifest

Datasets that do not match the native RELLIS-3D, SemanticPOSS, or
SemanticKITTI layouts can use `datasets.generic.ManifestDataset`. It is an
explicit interchange adapter, not an autodetector: the producer must declare
the point convention, intensity meaning, taxonomy mapping, frame ordering, and
metadata provenance in `manifest.json`.

The current schema is version `1`. It accepts finite little-endian XYZI scans
as `xyzi_f32_bin` or `xyzi_f32_npy`, and optional labels as `uint32_label` or
`integer_npy`. `uint32_label` follows the SemanticKITTI convention and uses
the low 16 bits as the semantic ID; instance bits are not semantic evidence.
Unknown or absent labels map to Veyra class `0` with confidence `0`.

Paths are relative to the dataset root and cannot escape it. Frame IDs are
explicit and sorted deterministically. A pose must be a rigid 4x4
sensor-to-world transform; if present, points are transformed into world
coordinates and provenance is marked as dataset-backed. Timestamps are
explicit seconds. Missing pose/time remains missing—filenames and row order
are never promoted into metadata.

Range filtering is applied in the sensor frame before the optional pose
transform. Malformed files, duplicate frame keys, non-finite points,
unaligned labels, invalid transforms, and invalid manifests fail closed.

Example construction:

```python
from datasets.generic import ManifestDataset

dataset = ManifestDataset("/path/to/export")
for frame in dataset.replay("sequence-01", max_range_m=100.0):
    consume(frame)
```
