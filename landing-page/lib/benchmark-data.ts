/**
 * Benchmark evidence — single source of truth.
 * FINAL round, fixed-benchmarks: SemanticPOSS 00 frames 0–9, warmup 2,
 * ground_truth + Patchwork++ + terrain, i5-8350U, GCC Release.
 * MEASURED = executed. ANALYTICAL = computed, never allocated.
 * UNAVAILABLE = not measured; renders as N/A.
 */

export type EvidenceKind = "MEASURED" | "ANALYTICAL" | "UNAVAILABLE";

export interface EvidenceMetric {
  label: string;
  uniform5: number | null;
  adaptive: number | null;
  unit: string;
  kind: EvidenceKind;
  note: string;
}

export const PROVENANCE = {
  selection: "SemanticPOSS sequence 00 · frames 0–9 · warmup 2",
  hardware: "Intel i5-8350U · GCC 16.2.1 Release",
  reference: "Elevation RMSE vs the executed Uniform 5 cm map on identical frames",
  verdict: "DistanceLOD is the production policy. UtilityLOD is experimental.",
} as const;

export const EVIDENCE: EvidenceMetric[] = [
  {
    label: "Logical map memory",
    uniform5: 53.2,
    adaptive: 25.8,
    unit: "MB",
    kind: "MEASURED",
    note: "Live map payload bytes. −52% state vs uniform fine.",
  },
  {
    label: "Active map cells",
    uniform5: 303205,
    adaptive: 145671,
    unit: "cells",
    kind: "MEASURED",
    note: "Final snapshot leaves. −52% cells vs uniform fine.",
  },
  {
    label: "Peak process RSS",
    uniform5: 262.8,
    adaptive: 139.5,
    unit: "MB",
    kind: "MEASURED",
    note: "Mapper process, OS-measured. −47% resident memory.",
  },
  {
    label: "Map-update latency p95",
    uniform5: 906,
    adaptive: 228,
    unit: "ms",
    kind: "MEASURED",
    note: "Per-frame C++ map update, nearest-rank tail.",
  },
  {
    label: "End-to-end frame p95",
    uniform5: 906,
    adaptive: 393,
    unit: "ms",
    kind: "MEASURED",
    note: "Dataset load through map commit per frame.",
  },
  {
    label: "Elevation RMSE vs Uniform5",
    uniform5: 0,
    adaptive: 0.4321,
    unit: "m",
    kind: "MEASURED",
    note: "What the compression costs against the fine reference.",
  },
  {
    label: "Reference-bin coverage",
    uniform5: 0.9988,
    adaptive: 0.9944,
    unit: "×",
    kind: "MEASURED",
    note: "Observed 5 cm bins owned by exactly one active leaf.",
  },
  {
    label: "Semantic retention",
    uniform5: 0.9952,
    adaptive: 0.9721,
    unit: "×",
    kind: "MEASURED",
    note: "Dominant-label bins keeping their class.",
  },
  {
    label: "Pedestrian retention",
    uniform5: 0.9684,
    adaptive: 0.8604,
    unit: "×",
    kind: "MEASURED",
    note: "Thin-class recall at range — the reason resolution matters.",
  },
  {
    label: "Dense 5 cm grid over 100 m",
    uniform5: 7330000000,
    adaptive: null,
    unit: "cells",
    kind: "ANALYTICAL",
    note: "Volumetric 5 cm estimate. Never allocated — geometry only.",
  },
  {
    label: "Dense grid memory estimate",
    uniform5: 117351,
    adaptive: null,
    unit: "MB",
    kind: "ANALYTICAL",
    note: "7.33B cells at map byte cost. Estimate, not a measurement.",
  },
  {
    label: "UtilityLOD quality gain",
    uniform5: null,
    adaptive: null,
    unit: "",
    kind: "UNAVAILABLE",
    note: "Experimental: heavier on every axis on this selection. No win claimed.",
  },
];

export interface RangeBand {
  range: string;
  resolution: string;
  lod: string;
  rmse: number;
  color: string;
}

/** DistanceLOD range bands: RMSE rises as resolution intentionally coarsens. */
export const RANGE_BANDS: RangeBand[] = [
  { range: "0–10 m", resolution: "5 cm", lod: "L0", rmse: 0.02, color: "var(--lod-0)" },
  { range: "10–30 m", resolution: "10 cm", lod: "L1", rmse: 0.24, color: "var(--lod-1)" },
  { range: "30–60 m", resolution: "20 cm", lod: "L2", rmse: 0.63, color: "var(--lod-2)" },
  { range: "60–100 m", resolution: "40 cm", lod: "L3", rmse: 0.72, color: "var(--lod-3)" },
];

export const HERO_REDUCTION = {
  value: -52,
  unit: "%",
  label: "Measured reduction",
  footnote: "DistanceLOD vs Uniform5 · SemanticPOSS 00 f0–9 · i5-8350U. See evidence.",
} as const;
