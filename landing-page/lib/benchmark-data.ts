/**
 * Benchmark evidence for the landing page — single source of truth.
 *
 * Values below are MEASURED on named hardware unless marked ANALYTICAL.
 * - MEASURED: executed by the benchmark harness, timings + RSS + cell counts.
 * - ANALYTICAL: computed from geometry, never allocated or timed.
 * - UNAVAILABLE: not measured on this selection; renders as N/A.
 *
 * Primary selection: SemanticPOSS seq 00, frames 0–29, 3 repetitions,
 * ground-truth semantics (see reports/closure/utility/RESULT.md).
 * Hardware: Intel i5-8350U, 8 logical CPUs, 15.4 GB RAM, Fedora 44.
 * Secondary: single-frame probe, SemanticPOSS seq 00 frame 0 (66,156 points).
 */

export type EvidenceKind = "MEASURED" | "ANALYTICAL" | "UNAVAILABLE";

export interface EvidenceMetric {
  label: string;
  uniform5: number | null;
  adaptive: number | null;
  unit: string;
  kind: EvidenceKind;
  /** Lower is better for memory/latency/RMSE; higher for coverage/retention. */
  note: string;
}

export const PROVENANCE = {
  selection: "SemanticPOSS sequence 00 · frames 0–29 · 3 repetitions",
  hardware: "Intel i5-8350U · 8 logical CPUs · 15.4 GB RAM · Fedora 44",
  reference: "Elevation RMSE vs the executed Uniform 5 cm map on identical frames",
} as const;

export const EVIDENCE: EvidenceMetric[] = [
  {
    label: "Active map cells",
    uniform5: 630611,
    adaptive: 247845,
    unit: "cells",
    kind: "MEASURED",
    note: "DistanceLOD final snapshot. −61% state vs uniform fine.",
  },
  {
    label: "Peak process RSS",
    uniform5: 307.9,
    adaptive: 168.4,
    unit: "MB",
    kind: "MEASURED",
    note: "Mapper process, OS-measured. −45% resident memory.",
  },
  {
    label: "Map-update latency p95",
    uniform5: 543.6,
    adaptive: 207.0,
    unit: "ms",
    kind: "MEASURED",
    note: "Per-frame C++ map update, nearest-rank p95 over 84 samples.",
  },
  {
    label: "Elevation RMSE vs Uniform5",
    uniform5: 0,
    adaptive: 0.46653,
    unit: "m",
    kind: "MEASURED",
    note: "Adaptive error against the fine reference it compresses.",
  },
  {
    label: "Reference-bin coverage",
    uniform5: 1,
    adaptive: 0.99,
    unit: "×",
    kind: "MEASURED",
    note: "Observed 5 cm bins owned by exactly one active leaf.",
  },
  {
    label: "Semantic retention",
    uniform5: 1,
    adaptive: 0.9617,
    unit: "×",
    kind: "MEASURED",
    note: "Dominant-label 5 cm bins keeping their class (574,569 / 597,451).",
  },
  {
    label: "Uniform 5 cm grid over 100 m",
    uniform5: 12570000,
    adaptive: null,
    unit: "cells",
    kind: "ANALYTICAL",
    note: "Dense 100 m-radius grid at 5 cm. Never allocated — geometry only.",
  },
  {
    label: "Uniform grid memory at 32 B/cell",
    uniform5: 383.5,
    adaptive: null,
    unit: "MB",
    kind: "ANALYTICAL",
    note: "12.57M cells × 32 B. Estimate, not a measurement.",
  },
  {
    label: "UtilityLOD quality gain",
    uniform5: null,
    adaptive: null,
    unit: "",
    kind: "UNAVAILABLE",
    note: "Inconclusive on the tested selection; DistanceLOD ships as baseline.",
  },
];

export const SINGLE_FRAME_PROBE = {
  selection: "SemanticPOSS seq 00 frame 0 · 66,156 input points · single frame",
  uniform5: { leaves: 52824, logicalMB: 3.27, rssMB: 17.6, mapMs: 159.53, fps: 5.37 },
  distanceLod: { leaves: 36821, logicalMB: 2.28, rssMB: 13.4, mapMs: 141.13, fps: 6.36 },
  note: "One frame only, so p50 == p95 here. Shown for scale, not as an SLO.",
} as const;
