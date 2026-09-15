"""Quality measures for binary ground-segmentation evidence."""

from __future__ import annotations

from typing import Any

import numpy as np


def ground_quality_report(
    predicted: np.ndarray,
    reference: np.ndarray,
    *,
    valid: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return auditable binary ground metrics without hiding unknown labels.

    ``reference`` is supplied by a dataset-specific adapter/evaluator.  An
    optional ``valid`` mask excludes reference points for which the dataset
    does not define a ground truth.  Precision is ``None`` when no predicted
    positives exist; recall is ``None`` when no reference positives exist.
    F1 and IoU are ``None`` when their denominator is zero.
    """

    predicted = np.asarray(predicted)
    reference = np.asarray(reference)
    if predicted.ndim != 1 or reference.ndim != 1 or predicted.shape != reference.shape:
        raise ValueError(
            "predicted and reference masks must be aligned one-dimensional arrays"
        )
    if predicted.dtype.kind != "b" or reference.dtype.kind != "b":
        raise TypeError("predicted and reference masks must be boolean")
    if valid is None:
        valid_mask = np.ones(predicted.shape, dtype=bool)
    else:
        valid_mask = np.asarray(valid)
        if valid_mask.shape != predicted.shape or valid_mask.dtype.kind != "b":
            raise ValueError("valid mask must be boolean and aligned with predictions")
    predicted = predicted[valid_mask]
    reference = reference[valid_mask]
    true_positive = int(np.count_nonzero(predicted & reference))
    false_positive = int(np.count_nonzero(predicted & ~reference))
    false_negative = int(np.count_nonzero(~predicted & reference))
    true_negative = int(np.count_nonzero(~predicted & ~reference))
    predicted_positive = true_positive + false_positive
    reference_positive = true_positive + false_negative
    union = true_positive + false_positive + false_negative
    f1_denominator = 2 * true_positive + false_positive + false_negative
    return {
        "evaluated_points": int(predicted.size),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "predicted_ground_fraction": (
            predicted_positive / predicted.size if predicted.size else None
        ),
        "reference_ground_fraction": (
            reference_positive / reference.size if reference.size else None
        ),
        "precision": true_positive / predicted_positive if predicted_positive else None,
        "recall": true_positive / reference_positive if reference_positive else None,
        "f1": true_positive * 2 / f1_denominator if f1_denominator else None,
        "iou": true_positive / union if union else None,
    }


def aggregate_ground_quality_reports(
    reports: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Combine per-frame reports by counts, preserving exact micro/macro scope."""

    if not reports:
        return None
    keys = ("true_positive", "false_positive", "false_negative", "true_negative")
    counts = {key: sum(int(report[key]) for report in reports) for key in keys}
    tp, fp, fn = (counts[key] for key in keys[:3])
    evaluated = sum(int(report["evaluated_points"]) for report in reports)
    predicted = tp + fp
    reference = tp + fn
    union = tp + fp + fn
    f1_denominator = 2 * tp + fp + fn
    return {
        "evaluated_points": evaluated,
        **counts,
        "predicted_ground_fraction": predicted / evaluated if evaluated else None,
        "reference_ground_fraction": reference / evaluated if evaluated else None,
        "precision": tp / predicted if predicted else None,
        "recall": tp / reference if reference else None,
        "f1": 2 * tp / f1_denominator if f1_denominator else None,
        "iou": tp / union if union else None,
        "frames": len(reports),
    }


__all__ = ["aggregate_ground_quality_reports", "ground_quality_report"]
