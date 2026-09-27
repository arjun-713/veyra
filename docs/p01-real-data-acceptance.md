# P01 Real-Data Acceptance (SemanticPOSS + CENet, CPU-only)

Factual acceptance record for #53 finalization. Only orchestrator-verified
facts are listed below. Interpretive notes are explicitly labelled.

## 1. Dataset

- Dataset: SemanticPOSS, local layout `SemanticPOSS_dataset/dataset`.
- Local dataset directory is untracked and NOT committed.
- Sequence 00: 488 `.bin` scans + 488 `.label` files.
- Production SemanticPOSS adapter is compatible with this layout.

## 2. Model

- Model file: `SENet_valid_best`.
- Size: 54393487 bytes, verified via `sha256sum`.
- SHA-256: `9c07ceadcd005a11bddc6c92b61d6f7724339f9519ef177afdebc3c59ffbb0ce`.
- Bundle: 291128300 bytes, verified via `sha256sum`.
- Bundle SHA-256: `d466d387a69933ce87d380e106b3f4d3d45734bf236391280d2894b09bc416c2`.
- Weights are NOT committed and are kept outside git.

## 3. Environment

- OS: Linux, CPU-only.
- Interpreter: `.venv` Python 3.14.4.
- Torch: `2.14.0+cpu` (CPU build; CUDA unavailable).
- Provider-verified device: `cpu`.

## 4. Inference (frame 000000, real data)

- Points in: 66658; aligned points out: 66658.
- Inference time: 4033.8 ms.
- Confidence mean: 0.9438.
- Agreement with independent ground-truth labels: 0.8654.
- Interpretation (labelled): the agreement figure compares neural output
  against independent GT labels; it is not a GT-vs-GT comparison.
- Reported mode: `model`.

## 5. Pipeline (frames 000000 / 000001)

- Semantic stage: `model`.
- Requested backend: `cenet`; actual backend: `model`.
- Fallback field: `null` (no fallback taken).
- Model field: verified checkpoint path.
- Execution device: `cpu`.
- Ground / terrain stages: `unavailable`, with an explicit diagnostic that
  the Patchwork++ binding (`pypatchworkpp`) is missing.
- Frame 000000 total: 4078.0 ms (semantic 4069.1 ms).
- Frame 000001 total: 2014.8 ms (semantic 2009.2 ms).

## 6. Truthfulness labelling

- Neural path reports neural (`model`) status.
- Ground-truth paths report `ground_truth` with bypassed-model marking and
  DEBUG/EVAL designation.
- A fallback path, when taken, is bannered as fallback and never as neural.
- The model field is null on non-neural paths.

## 7. Limitations

- CPU-only execution is non-realtime at the timings above.
- Patchwork++ is unavailable in this environment, so ground/terrain stages
  are unavailable and the `validate_sih --full` gate is blocked.
- Interpretation (labelled): the `--full` blockage is environmental and
  separate from the #53 semantic scope.
- Scratch artifacts from the validation run were not committed and are not
  independently reviewable from git.
- Positive / negative real terrain classes were unobserved in this env.
