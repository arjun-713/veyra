# Veyra Submission Closure Scorecard

This is the authoritative project closure register. A row stays here until its evidence is current, reproducible, and independently checkable. Initial values are deliberately **0% / UNVERIFIED** until the corresponding production-path evidence is collected.

| Capability | Current | Target | Status | Required closure evidence |
| --- | ---: | ---: | --- | --- |
| Raw LiDAR ingestion | 0% | 100% | UNVERIFIED | Real dataset parser, malformed-input regression, deterministic replay artifact |
| Dataset-agnostic architecture | 0% | 100% | UNVERIFIED | Canonical adapter contract across real datasets |
| Neural semantic segmentation | 0% | 100% | UNVERIFIED | Real model execution, aligned point output, confidence and provider failure tests |
| Semantic quality | 0% | 100% | UNVERIFIED | Range-binned accuracy/mIoU/IoU/precision/recall/F1 on real labelled data |
| Ground segmentation | 0% | 100% | UNVERIFIED | Real Patchwork++ precision/recall/F1/IoU evidence |
| Drivable/non-drivable terrain | 0% | 100% | UNVERIFIED | Real terrain classes plus explicit unknown evidence |
| Static obstacles | 0% | 100% | UNVERIFIED | Wall/pole retention through viewer/map path |
| Dynamic classes | 0% | 100% | UNVERIFIED | Vehicle/pedestrian retention through viewer/map path |
| Real temporal motion | 0% | 100% | UNVERIFIED | Real poses/timestamps and dynamic ghosting evidence |
| Variable-resolution 2.5D map | 0% | 100% | UNVERIFIED | Production map stream, snapshots, and invariant tests |
| Mixed-resolution correctness | 0% | 100% | UNVERIFIED | Randomized boundary/topology stress evidence |
| Split/merge preservation | 0% | 100% | UNVERIFIED | Long numerical-statistics round-trip evidence |
| Rolling 100 m map | 0% | 100% | UNVERIFIED | Movement/eviction stress evidence |
| 5/10/20/40 hierarchy | 0% | 100% | UNVERIFIED | Real policy snapshots at all levels |
| DistanceLOD | 0% | 100% | UNVERIFIED | Same-stream measured baseline evidence |
| UtilityLOD | 0% | 100% | UNVERIFIED | Controlled ablation with task-quality gain |
| Resource governor | 0% | 100% | UNVERIFIED | Sustained pressure and protected-region evidence |
| Reversible detail-preserving refinement | 0% | 100% | UNVERIFIED | Bounded cache recovery/memory evidence |
| Memory reduction proof | 0% | 100% | UNVERIFIED | Measured RSS/allocated/logical comparison |
| Measured 3D baseline comparison | 0% | 100% | UNVERIFIED | Same-input sparse 3D measured baseline |
| Performance/FPS | 0% | 100% | UNVERIFIED | Long-run p50/p95/p99/FPS against named hardware |
| Range-binned evaluation | 0% | 100% | UNVERIFIED | 0–10/10–30/30–60/60–100 m quality report |
| Benchmark quality | 0% | 100% | UNVERIFIED | Repeated real-data provenance-complete artifacts |
| SemanticPOSS validation | 0% | 100% | UNVERIFIED | Real adapter/perception/map validation |
| RELLIS validation | 0% | 100% | UNVERIFIED | Real adapter/perception/map validation |
| SemanticKITTI validation | 0% | 100% | UNVERIFIED | Real sequential posed/timestamped validation |
| Generic/custom dataset path | 0% | 100% | UNVERIFIED | Manifest real-data validation |
| Tauri desktop | 0% | 100% | UNVERIFIED | Packaged real-backend session on native platforms |
| UI functionality | 0% | 100% | UNVERIFIED | Complete control inventory and E2E evidence |
| Telemetry correctness | 0% | 100% | UNVERIFIED | Source/freshness/unit verified metrics |
| Renderer stability | 0% | 100% | UNVERIFIED | Native WebView stress/context recovery evidence |
| Runtime supervision | 0% | 100% | UNVERIFIED | Crash/timeout/shutdown/orphan tests |
| Electron removal | 0% | 100% | UNVERIFIED | No Electron production dependencies/workflows/references |
| Shared Control API | 0% | 100% | UNVERIFIED | Desktop/CLI/MCP one-authority integration |
| CLI | 0% | 100% | UNVERIFIED | Complete command and JSON integration tests |
| MCP | 0% | 100% | UNVERIFIED | Typed tool integration and security tests |
| Security | 0% | 100% | UNVERIFIED | Capability/path/process/error boundary tests |
| Ubuntu/Debian | 0% | 100% | UNVERIFIED | Native package, sidecar, installer smoke evidence |
| Fedora/RPM | 0% | 100% | UNVERIFIED | Native RPM package and sidecar smoke evidence |
| Windows | 0% | 100% | UNVERIFIED | Native installer and sidecar smoke evidence |
| macOS | 0% | 100% | UNVERIFIED | Native DMG/app and sidecar smoke evidence |
| Packaging | 0% | 100% | UNVERIFIED | Checksummed inspectable artifacts |
| Release readiness | 0% | 100% | UNVERIFIED | Native release pipeline evidence |
| Test quality | 0% | 100% | UNVERIFIED | Critical paths have non-mock regression evidence |
| CI | 0% | 100% | UNVERIFIED | All required remote checks green |
| Documentation | 0% | 100% | UNVERIFIED | Fresh-clone commands and claims match evidence |
| Reproducibility | 0% | 100% | UNVERIFIED | Dataset/model/config/commit/hardware provenance |
| Demo readiness | 0% | 100% | UNVERIFIED | Packaged real-data scripted rehearsal |

## Closure policy

Each JSON row records acceptance criteria, required test/real-data/benchmark/platform evidence, active blocker, artifact path, and closing commit. Missing evidence is a blocker; no requirement may be removed to improve a score.
