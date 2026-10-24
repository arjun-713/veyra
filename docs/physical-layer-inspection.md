# Physical map layer inspection

Open **Viewer**, process a dataset frame, select **Map** or **Both**, and
click a rendered cell. The inspector shows separate **ground**,
**obstacle**, and **overhead** support counts, mean heights, and height extents.
Pooled height remains available but is explicitly not a physical surface.

An empty layer is **Unavailable**, not a surface at height zero. Ground assignment
comes from the observation ground flag; obstacle/overhead separation uses the
mapper's existing height-above-ground rules. Missing ground/terrain stages cannot
establish trustworthy ground or overhead surfaces. This change exposes stored
evidence; it does not infer a new ground plane or change map fusion.

## Additive transport

- The engine advertises `physical_layers_version: 1` in its handshake.
- Existing `MB` responses retain their 17-float (68-byte) cell rows unchanged.
- `ML` returns those same sampled rows followed by corresponding layer rows.
- Each layer row has 15 little-endian float32 values: ground, obstacle, overhead;
  each stores count, mean z, min z, max z, and population variance.
- Empty layers have count zero and NaN height statistics. JSON represents those
  absent statistics as null.
- Python negotiates `ML` only when advertised, otherwise retaining `MB` support.
- Visualization schema 3 has an optional `physical_layers` descriptor containing
  version, count, offset, and stride (60 bytes). Count must match displayed cells.
  Frontend validation rejects overlapping, truncated, or incompatible sections.
- Sampling happens once in C++; layer rows follow exactly that selected order.
  Inspection uses the last painted frame, not a newer/rejected frame's metadata.

The Rust bridge accepts visualization schemas 2 and 3; unknown schemas are still
rejected. No leaf/statistics layout, observation protocol, policy default, or
point rendering layout changes are required.

## Focused verification

Build a fresh Release runtime and set `VEYRA_RUNTIME_BINARY` and
`VEYRA_BENCHMARK_BINARY` to that build. Run the engine service, visualization,
and map bridge tests, plus desktop physical-layer tests and Rust telemetry tests.
These include distinct surfaces at the same XY, unavailable layers, malformed
section bounds, and multi-cell sampling alignment. Synthetic fixtures prove the
transport contract; they are not real-scene perception quality measurements.
