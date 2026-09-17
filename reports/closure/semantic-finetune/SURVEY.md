# Survey: native-Pandora semantic path (fine-tune track)

- Status: **survey complete — adopt existing native checkpoint, do not train**
- Branch: `agent/semantic-finetune` (worktree `worktrees/semantic-finetune`)
- Prior: `reports/closure/semantic/RESULT.md` — SalsaNext KITTI checkpoint
  proven wrong-domain (mIoU 0.087 / 29% acc, overconfident). **Do not retry it.**

## Decision

The cheapest viable path is the **already-downloaded CENet SemanticPOSS
checkpoint** (Pandora-native, 40x1800, FOV -16..+7). It is measured on the
closure frames at Veyra **mIoU 0.6504 / accuracy 0.8942** (7.5x the
SalsaNext mIoU on identical frames) with differentiated confidence
(0.96 correct vs 0.77 wrong). No fine-tune training run is needed to
unblock the neural path. The per-point MLP baseline is a documented
negative result (mIoU 0.096) — kept as fallback evidence only.

## Checkpoint inventory (measured, not quoted)

| Checkpoint | Location | Size / sha256 | Format |
| --- | --- | --- | --- |
| CENet `res/SENet_valid_best` (worktree copy) | `worktrees/semantic-finetune/data/cache/models/cenet-poss/SENet_valid_best` | 54,393,487 B / `9c07cead…ffbb0ce` (matches `configs/semantic-cenet-model.json`) | torch.save dict, strict state-dict match vs vendored arch |
| CENet bundle (main checkout) | `/home/arjun/Captain/SIH/Lidar/data/cache/models/cenet-poss/cenet-poss-291MB.bin` | 291,128,300 B / `d466d387…09bc416c2` | upstream Drive bundle ("POSS Result") |
| CENet unpacked (main checkout) | `/home/arjun/Captain/SIH/Lidar/data/cache/cenet-work/model/` | `SENet_valid_best` + `arch_cfg.yaml` + `data_cfg.yaml` | same weights + configs |
| Pandora MLP (worktree) | `worktrees/semantic-finetune/data/cache/models/pandora-mlp/pandora_mlp_seed0.npz` | 85 kB / sha in `configs/semantic-pandora-native-model.json` | NumPy-only MLP 128x64 |
| SalsaNext KITTI ONNX (rejected) | `data/cache/models/salsanext-onnx-float/salsanext.onnx` | sha `067086f8…` | 64x2048, FOV -25..+3 |

**No Pandora-native ONNX checkpoint exists anywhere** (repo, data/,
cache): the native path is torch CENet + NumPy MLP. An ONNX export of
the CENet provider is a possible follow-up, not a prerequisite.

## Provider interface (what changed, all additive)

- `perception/semantic/semantic_provider.py` — **unchanged** (Protocol +
  `OnnxSemanticProvider` + `GroundTruthSemanticProvider` intact).
- New: `perception/semantic/cenet.py` (`CENetSemanticProvider`, CPU torch,
  torch import is lazy/optional — construction fails closed without it),
  `perception/semantic/pandora.py` (`PandoraNativeSemanticProvider`,
  NumPy-only; beam LUT + 40x1800 projection shared by CENet).
- `perception/semantic/__init__.py` — two additive exports only.
- `perception/pipeline.py` — **untouched**; `mode: cenet` /
  `mode: pandora_native` are constructor-injected until the pipeline
  owner's follow-up wires them (8-question checklist applies there).
- Gate behavior preserved: providers declare
  `supported_datasets == {"semanticposs"}`; the SalsaNext refusal of POSS
  frames is unchanged.

## What `scripts/fetch_semantic_model.py` pins

Only the rejected SalsaNext KITTI asset
(`configs/salsanext-model.json`, Qualcomm AI Hub, sha-pinned zip).
There is **no fetch pin for CENet** — the bundle came from the upstream
Drive link recorded in `configs/semantic-cenet-model.json` (bundle +
weight sha256 pinned there instead). A `fetch_cenet_model.py` mirroring
the SalsaNext fetcher (URL + size + sha256) is a small follow-up; the
Drive URL is not curl-friendly, which is why it was left manual.

## Fine-tune spec (fallback only — not recommended)

Only if the CENet checkpoint ever becomes unusable:

- Dataset: SemanticPOSS v1.0, on disk
  `/home/arjun/Captain/SIH/Lidar/data/raw/semanticposs/dataset/sequences/`
  (`00`–`05`). Author split: train 0,1,3,4,5 / valid 2.
- MLP reference (reproducible today):
  `python3 scripts/train_pandora_semantic.py --train-sequences 01 02 03`
  → 340k balanced samples (20k/class cap), 6 features
  (x,y,z,intensity,range,pitch), sklearn MLP 128x64, max_iter 150,
  seed 0; CPU-only, minutes on the i5-8350U. Result: 0.727
  resampled-val → 0.31 test accuracy. Proves context-free heads do not
  transfer — do not scale this up; any retrain must be convolutional.
- CENet retrain estimate: author schedule is 45 epochs on 40x1800
  5-channel inputs; local CPU inference alone is ~6–9 s/frame, so CPU
  retraining is infeasible — budget a CUDA host (single-GPU
  tens-of-hours class, unmeasured; never invent the number — measure on
  first run). Quality gate before enabling: model-FOV mIoU >= 0.30 /
  coverage >= 0.90 / ground F1 >= 0.75 (same floors as
  `configs/perception-cenet-semantic.yaml`).
- Taxonomy: native 14-class CENet head + explicit POSS→Veyra projection
  (POSS `ground` → Veyra 12, IoU 0.884 — the closure collision resolved).

## Tests run (targeted file only)

- `pytest tests/test_semantic_provider.py` (hermetic): **37 passed,
  4 skipped** (env-gated real-data/checkpoint pins absent).
- Same file with `VEYRA_CENET_CHECKPOINT` (worktree weight) +
  `VEYRA_SEMANTICPOSS_ROOT` (main-checkout dataset): **41 passed** —
  all env-gated pins execute against the real checkpoint and real
  seq-00 frames.

## Gaps / next steps

1. `reports/closure/semantic-finetune/RESULT.md` is stale vs its
   artifacts: Tests section still says "FILL (run after KNN job…)",
   group-metrics line is "TBD — rerun FILL", and its latency text
   (p50 6011 ms / p95 7178 ms, RSS 989 MB) predates the committed
   `cenet-poss-metrics.json` (p50 **8553.6** ms / p95 **17616.2** ms,
   peak RSS **1009.8** MB). Refresh the text from the artifacts.
2. Wire `mode: cenet` into `PerceptionPipeline.from_config` (pipeline
   owner + checklist; interface already preserved for it).
3. Optional `fetch_cenet_model.py` pin (see above); weights stay
   git-ignored regardless (no weight-license file ships upstream).
4. Confidence calibration before traversability weighting (0.96/0.77
   split is promising but uncalibrated); unknown-at-0 kept regardless.
5. Full-seq-02 + seq-04/05 sweep before any production enable;
   16-frame windows are closure evidence, not release qualification.
6. GPU/TensorRT port for real-time (CPU ~6–9 s/frame full 40x1800);
   governor/advanced tracks own the runtime response.
