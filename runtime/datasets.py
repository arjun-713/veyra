"""Read-only dataset discovery through existing adapters."""

from pathlib import Path


def open_adapter(dataset, root):
    from datasets.generic import ManifestDataset
    from datasets.rellis import Rellis3DDataset
    from datasets.semanticposs import SemanticPOSSDataset
    from datasets.semantickitti import SemanticKITTIDataset

    adapters = {
        "generic": ManifestDataset,
        "rellis3d": Rellis3DDataset,
        "semanticposs": SemanticPOSSDataset,
        "semantickitti": SemanticKITTIDataset,
    }
    if dataset not in adapters:
        raise ValueError("unsupported dataset")
    return adapters[dataset](root)


def inspect_dataset(root, dataset=None):
    root = Path(root).expanduser().resolve()
    if dataset is None:
        if (root / "manifest.json").is_file():
            dataset = "generic"
        elif any(root.glob("*/vel_cloud_node_kitti_bin")):
            dataset = "rellis3d"
        else:
            # KITTI and POSS share layout; require explicit taxonomy selection.
            return {
                "root": str(root),
                "dataset": None,
                "status": "partial",
                "sequences": [],
                "diagnostics": [
                    "Select SemanticPOSS or SemanticKITTI explicitly; directory structure does not identify taxonomy."
                ],
            }
    result = {
        "root": str(root),
        "dataset": dataset,
        "status": "invalid",
        "sequences": [],
        "diagnostics": [],
    }
    try:
        adapter = open_adapter(dataset, root)
        for sequence in adapter.list_sequences():
            refs = adapter.list_frames(sequence)
            labels = sum(
                ref.label_path is not None and ref.label_path.is_file() for ref in refs
            )
            missing = sum(not ref.scan_path.is_file() for ref in refs)
            if missing:
                result["diagnostics"].append(f"{sequence}: {missing} missing scans")
            pose = timestamp = None
            if refs:
                try:
                    frame = adapter.load_frame(sequence, refs[0].frame_id)
                    pose = frame.provenance.coordinate_frame == "world"
                    timestamp = frame.timestamp is not None
                except (ValueError, OSError) as error:
                    result["diagnostics"].append(f"{sequence}: {error}")
            result["sequences"].append(
                {
                    "id": sequence,
                    "frames": len(refs),
                    "labels": labels,
                    "poses": pose,
                    "timestamps": timestamp,
                }
            )
        if any(sequence["frames"] for sequence in result["sequences"]):
            result["status"] = (
                "partial"
                if result["diagnostics"]
                or any(
                    s["labels"] < s["frames"] or not s["poses"] or not s["timestamps"]
                    for s in result["sequences"]
                )
                else "valid"
            )
        else:
            result["diagnostics"].append("No supported frames found")
    except (ValueError, OSError, KeyError) as error:
        result["diagnostics"].append(str(error))
    return result
