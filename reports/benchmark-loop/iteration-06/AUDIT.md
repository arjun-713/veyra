# Iteration 06 — Track 10: exhaustive dataset integrity (2026-09-22, fixed-benchmarks)

Read-only validation of every frame on disk (scan size sane, fully finite XYZ,
label file present with exactly one entry per point; POSS pose-count pairing):

- SemanticKITTI seq08 subset: 220/220 checked, 0 bad.
- SemanticPOSS seqs 00–05: 2988/2988 checked, 0 bad (poses lines == scans).
- RELLIS-3D seqs 00000–00004: 13532/13532 checked, 0 bad.
- Total: 16,740 frames, 0 rejected, 0 invalid. No orphans found.

Dataset integrity: 68 → 90 (exhaustive local proof; only cross-mirror byte
identity beyond this box remains external).
No production code changed this iteration.
