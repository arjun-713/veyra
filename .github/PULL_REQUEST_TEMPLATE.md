## What / why

## How to verify

```bash
cmake --preset dev 2>/dev/null || cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
```

## Checklist

- [ ] Local build/tests run, or the reason they could not be run is documented
- [ ] Map invariants hold — see `docs/map-correctness.md` (or N/A)
- [ ] Baseline noted for adaptive changes (`DistanceLOD vs UtilityLOD`) or N/A
- [ ] No data/weights/maps committed (see `.gitignore`)
- [ ] Docs/config updated
