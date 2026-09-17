"""CENet native Pandora/SemanticPOSS semantic provider (CPU, torch).

Architecture vendored from CENet (Huixian Cheng et al., ICME 2022;
https://github.com/huixiancheng/CENet, MIT license, source commit
``9a84103d186a1f93637cae3d96426760deb04140``). Only the network definition
is vendored, verbatim apart from the removed CUDA demo ``__main__`` block;
submodule and parameter names are kept identical so the published
SemanticPOSS weights (``res/SENet_valid_best``) load with a strict
state-dict match. Adaptations versus upstream, all documented and measured
in ``reports/closure/semantic-finetune/``:

- CPU-only inference (upstream calls ``.cuda()`` unconditionally).
- Tag-free analytic range projection: the dataset's ``.tag`` files are a
  training-pipeline input, not available to a point-in/point-out provider.
  The provider renders the ``40 x 1800`` image with nearest-return
  compositing under the Pandora ``-16..+7`` deg geometry
  (``perception.semantic.pandora``) plus the measured yaw-column offset
  versus the dataset tags (``CENET_YAW_COL_OFFSET``); per-point predictions
  are read back at each point's own pixel (no KNN).
- No KNN post-processing (upstream default); KNN is timed and scored
  separately in the measurement notes, never silently.
- Raw byte remission (``[0, 255]``, NOT divided): the checkpoint's
  normalization statistics (``poss.yml`` means) are fit to raw bytes, as
  verified by the local forward pass.

The graph already ends in softmax (as does SalsaNext): never apply softmax
twice. Input is sensor-frame XYZI with byte intensity; output follows the
original point order as Veyra canonical class IDs with ``mode="model"``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from datasets.common.taxonomy import SEMANTIC_POSS_LABELS
from perception.semantic.pandora import project_pandora_beams
from perception.semantic.semantic_provider import SemanticResult

CENET_IMAGE_HEIGHT = 40
CENET_IMAGE_WIDTH = 1800
CENET_FOV_UP_DEGREES = 7.0
CENET_FOV_DOWN_DEGREES = -16.0
CENET_N_LEARNING_CLASSES = 14

#: poss.yml img_means / img_stds for (range, x, y, z, signal); signal is raw
#: byte remission, matching common/posslaserscan.py (verified by measurement).
CENET_MEANS = (22.26779, 0.51144063, 1.5727469, -0.6350901, 13.875261)
CENET_STDS = (17.735949, 17.422485, 22.217215, 1.6433295, 14.0925865)

#: res/data_cfg.yaml learning_map_inv: learning ID -> SemanticPOSS raw ID.
CENET_LEARNING_TO_RAW = (0, 4, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17, 21, 22)

#: Measured column offset between the analytic yaw projection and the
#: dataset .tag layout: tag_col == (analytic_col + 675) % 1800 on seq-00
#: frames 000000/000007/000015 (top histogram bin, +/-1 floor jitter).
#: Convolutions are translation-invariant, but matching the training column
#: convention removes avoidable border-padding mismatch.
CENET_YAW_COL_OFFSET = 675


# ---------------------------------------------------------------------------
# Vendored CENet ResNet-pipeline network (MIT, huixiancheng/CENet).
# Names are load-bearing: they must match the published state dict exactly.
# ---------------------------------------------------------------------------


def conv3x3(in_planes, out_planes, stride=1, groups=1, dilation=1):
    """3x3 convolution with padding (CENet, unchanged)."""
    torch_nn = __import__("torch").nn
    return torch_nn.Conv2d(
        in_planes,
        out_planes,
        kernel_size=3,
        stride=stride,
        padding=dilation,
        groups=groups,
        bias=False,
        dilation=dilation,
    )


def conv1x1(in_planes, out_planes, stride=1):
    """1x1 convolution (CENet, unchanged)."""
    torch_nn = __import__("torch").nn
    return torch_nn.Conv2d(
        in_planes, out_planes, kernel_size=1, stride=stride, bias=False
    )


# Module-level names mirroring upstream. They resolve on first provider
# construction (torch stays an optional, explicitly-installed dependency);
# use _network_types() rather than these globals directly.
BasicConv2d = None
BasicBlock = None
ResNet_34 = None


def _build_network_types():
    torch = __import__("torch")
    torch_nn = torch.nn
    torch_f = torch.nn.functional

    class _BasicConv2d(torch_nn.Module):
        def __init__(self, in_planes, out_planes, kernel_size, stride=1,
                     padding=0, dilation=1, relu=True):
            super().__init__()
            self.relu = relu
            self.conv = torch_nn.Conv2d(
                in_planes, out_planes, kernel_size=kernel_size, stride=stride,
                padding=padding, dilation=dilation, bias=False)
            self.bn = torch_nn.BatchNorm2d(out_planes)
            if self.relu:
                self.relu = torch_nn.LeakyReLU()

        def forward(self, x):
            x = self.conv(x)
            x = self.bn(x)
            if self.relu:
                x = self.relu(x)
            return x

    class _BasicBlock(torch_nn.Module):
        expansion = 1

        def __init__(self, inplanes, planes, stride=1, downsample=None, groups=1,
                     base_width=64, dilation=1, if_BN=None):
            super().__init__()
            self.if_BN = if_BN
            if self.if_BN:
                norm_layer = torch_nn.BatchNorm2d
            if groups != 1 or base_width != 64:
                raise ValueError('BasicBlock only supports groups=1 and base_width=64')
            if dilation > 1:
                raise NotImplementedError("Dilation > 1 not supported in BasicBlock")
            self.conv1 = conv3x3(inplanes, planes, stride)
            if self.if_BN:
                self.bn1 = norm_layer(planes)
            self.relu = torch_nn.LeakyReLU()
            self.conv2 = conv3x3(planes, planes)
            if self.if_BN:
                self.bn2 = norm_layer(planes)
            self.downsample = downsample
            self.stride = stride

        def forward(self, x):
            identity = x
            out = self.conv1(x)
            if self.if_BN:
                out = self.bn1(out)
            out = self.relu(out)
            out = self.conv2(out)
            if self.if_BN:
                out = self.bn2(out)
            if self.downsample is not None:
                identity = self.downsample(x)
            out += identity
            out = self.relu(out)
            return out

    class _ResNet34(torch_nn.Module):
        def __init__(self, nclasses, aux, block=None, layers=(3, 4, 6, 3),
                     if_BN=True, zero_init_residual=False, norm_layer=None,
                     groups=1, width_per_group=64):
            super().__init__()
            if block is None:
                block = _BasicBlock
            if norm_layer is None:
                norm_layer = torch_nn.BatchNorm2d
            self._norm_layer = norm_layer
            self.if_BN = if_BN
            self.dilation = 1
            self.aux = aux
            self.groups = groups
            self.base_width = width_per_group
            self.conv1 = _BasicConv2d(5, 64, kernel_size=3, padding=1)
            self.conv2 = _BasicConv2d(64, 128, kernel_size=3, padding=1)
            self.conv3 = _BasicConv2d(128, 128, kernel_size=3, padding=1)
            self.inplanes = 128
            self.layer1 = self._make_layer(block, 128, layers[0])
            self.layer2 = self._make_layer(block, 128, layers[1], stride=2)
            self.layer3 = self._make_layer(block, 128, layers[2], stride=2)
            self.layer4 = self._make_layer(block, 128, layers[3], stride=2)
            self.conv_1 = _BasicConv2d(640, 256, kernel_size=3, padding=1)
            self.conv_2 = _BasicConv2d(256, 128, kernel_size=3, padding=1)
            self.semantic_output = torch_nn.Conv2d(128, nclasses, 1)
            if self.aux:
                self.aux_head1 = torch_nn.Conv2d(128, nclasses, 1)
                self.aux_head2 = torch_nn.Conv2d(128, nclasses, 1)
                self.aux_head3 = torch_nn.Conv2d(128, nclasses, 1)

        def _make_layer(self, block, planes, blocks, stride=1, dilate=False):
            norm_layer = self._norm_layer
            downsample = None
            previous_dilation = self.dilation
            if dilate:
                self.dilation *= stride
                stride = 1
            if stride != 1 or self.inplanes != planes * block.expansion:
                if self.if_BN:
                    downsample = torch_nn.Sequential(
                        conv1x1(self.inplanes, planes * block.expansion, stride),
                        norm_layer(planes * block.expansion),
                    )
                else:
                    downsample = torch_nn.Sequential(
                        conv1x1(self.inplanes, planes * block.expansion, stride)
                    )
            layers = [block(self.inplanes, planes, stride, downsample, self.groups,
                            self.base_width, previous_dilation, if_BN=self.if_BN)]
            self.inplanes = planes * block.expansion
            for _ in range(1, blocks):
                layers.append(block(self.inplanes, planes, groups=self.groups,
                                    base_width=self.base_width, dilation=self.dilation,
                                    if_BN=self.if_BN))
            return torch_nn.Sequential(*layers)

        def forward(self, x):
            x = self.conv1(x)
            x = self.conv2(x)
            x = self.conv3(x)
            x_1 = self.layer1(x)
            x_2 = self.layer2(x_1)
            x_3 = self.layer3(x_2)
            x_4 = self.layer4(x_3)
            res_2 = torch_f.interpolate(x_2, size=x.size()[2:], mode='bilinear',
                                        align_corners=True)
            res_3 = torch_f.interpolate(x_3, size=x.size()[2:], mode='bilinear',
                                        align_corners=True)
            res_4 = torch_f.interpolate(x_4, size=x.size()[2:], mode='bilinear',
                                        align_corners=True)
            res = [x, x_1, res_2, res_3, res_4]
            out = torch.cat(res, dim=1)
            out = self.conv_1(out)
            out = self.conv_2(out)
            out = self.semantic_output(out)
            out = torch_f.softmax(out, dim=1)
            if self.aux:
                aux_outputs = []
                for head, feat in ((self.aux_head1, res_2),
                                   (self.aux_head2, res_3),
                                   (self.aux_head3, res_4)):
                    aux_outputs.append(torch_f.softmax(head(feat), dim=1))
                return [out, *aux_outputs]
            return out

    # Alias inner classes to upstream names so state-dict keys and reprs match.
    _BasicConv2d.__name__ = "BasicConv2d"
    _BasicConv2d.__qualname__ = "BasicConv2d"
    _BasicBlock.__name__ = "BasicBlock"
    _BasicBlock.__qualname__ = "BasicBlock"
    _ResNet34.__name__ = "ResNet_34"
    _ResNet34.__qualname__ = "ResNet_34"
    return _BasicConv2d, _BasicBlock, _ResNet34


def _require_torch():
    try:
        import torch
    except ImportError as error:
        raise ValueError(
            "torch is required for CENet semantic inference; "
            "install it explicitly with the selected backend"
        ) from error
    return torch


# Module-level names mirroring upstream (resolved lazily; torch optional).
BasicConv2d = None
BasicBlock = None
ResNet_34 = None


def _network_types():
    global BasicConv2d, BasicBlock, ResNet_34
    _require_torch()
    if ResNet_34 is None:
        BasicConv2d, BasicBlock, ResNet_34 = _build_network_types()
    return BasicConv2d, BasicBlock, ResNet_34


def _swap_leaky_relu_to_hardswish(module, torch_nn) -> None:
    """Mirror user_poss.py: LeakyReLU -> Hardswish when act == Hardswish."""
    for name, child in module.named_children():
        if isinstance(child, torch_nn.LeakyReLU):
            setattr(module, name, torch_nn.Hardswish())
        else:
            _swap_leaky_relu_to_hardswish(child, torch_nn)


_MEANS = np.array(CENET_MEANS, np.float32)[..., None, None]
_STDS = np.array(CENET_STDS, np.float32)[..., None, None]
_LEARNING_TO_RAW = np.array(CENET_LEARNING_TO_RAW, np.int32)


def render_cenet_image(
    points: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Render the CENet 5-channel range image from sensor-frame XYZI.

    Returns ``(image, rows, cols, valid)`` with one row/col/valid entry per
    input point in input order. Nearest return wins each pixel with stable
    first-input tie-break (same rule as the SalsaNext provider). Columns are
    shifted by ``CENET_YAW_COL_OFFSET`` to match the training tag layout.
    Remission is the raw byte value (see module docstring).
    """
    points = np.asarray(points, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 4 or not np.isfinite(points).all():
        raise ValueError("CENet rendering requires finite sensor-frame XYZI (N, 4)")
    rows, cols, valid = project_pandora_beams(points)
    cols = (cols + CENET_YAW_COL_OFFSET) % CENET_IMAGE_WIDTH
    depth = np.linalg.norm(points[:, :3], axis=1)
    image = np.zeros((5, CENET_IMAGE_HEIGHT, CENET_IMAGE_WIDTH), np.float32)
    ordered = np.flatnonzero(valid)
    ordered = ordered[np.argsort(depth[ordered], kind="stable")]
    _, first = np.unique(rows[ordered] * CENET_IMAGE_WIDTH + cols[ordered],
                         return_index=True)
    selected = ordered[first]
    image[0, rows[selected], cols[selected]] = depth[selected]
    image[1:, rows[selected], cols[selected]] = points[selected].T
    occupied = np.zeros((CENET_IMAGE_HEIGHT, CENET_IMAGE_WIDTH), bool)
    occupied[rows[selected], cols[selected]] = True
    image = ((image - _MEANS) / _STDS) * occupied[None]
    return image[None].astype(np.float32), rows, cols, valid


def model_contract() -> dict[str, object]:
    """Return the CENet provider contract for measurement artifacts."""
    return {
        "architecture": "CENet ResNet-pipeline (vendored ResNet_34, Hardswish)",
        "source": "huixiancheng/CENet @ 9a84103 (MIT)",
        "image_shape": (CENET_IMAGE_HEIGHT, CENET_IMAGE_WIDTH),
        "channels": ("range", "x", "y", "z", "remission_raw_byte"),
        "fov_degrees": {"up": CENET_FOV_UP_DEGREES, "down": CENET_FOV_DOWN_DEGREES},
        "normalization_means": CENET_MEANS,
        "normalization_stds": CENET_STDS,
        "learning_classes": CENET_N_LEARNING_CLASSES,
        "learning_to_raw": tuple(int(v) for v in _LEARNING_TO_RAW),
        "yaw_column_offset": CENET_YAW_COL_OFFSET,
        "postprocessing": "per-point argmax at own pixel, no KNN",
    }


class CENetSemanticProvider:
    """Run the published CENet SemanticPOSS weights on CPU torch."""

    # Trained and labelled for SemanticPOSS/Pandora. The pipeline dataset
    # gate uses this to accept POSS frames and refuse anything else.
    supported_datasets = frozenset({"semanticposs"})

    def __init__(self, checkpoint_path: str | Path, *, threads: int = 4) -> None:
        torch = _require_torch()
        if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
            raise ValueError("threads must be a positive integer")
        path = Path(checkpoint_path)
        if not path.is_file():
            raise ValueError(f"CENet checkpoint does not exist: {path}")
        _, _, net_type = _network_types()
        model = net_type(CENET_N_LEARNING_CLASSES, True)
        _swap_leaky_relu_to_hardswish(model, torch.nn)
        try:
            payload = torch.load(str(path), map_location="cpu", weights_only=False)
        except Exception as error:
            raise ValueError(f"cannot load CENet checkpoint: {error}") from error
        state = payload.get("state_dict", payload) if isinstance(payload, dict) else None
        if not isinstance(state, dict):
            raise TypeError("CENet checkpoint has no state_dict mapping")
        try:
            model.load_state_dict(state, strict=True)
        except Exception as error:
            raise ValueError(
                f"checkpoint is incompatible with the CENet ResNet contract: {error}"
            ) from error
        model.eval()
        self._torch = torch
        self._model = model
        # Intra-op thread count is process-global in torch; documented here so
        # callers profiling latency know where it comes from.
        torch.set_num_threads(threads)
        self.threads = threads
        self.checkpoint_path = path

    def infer_raw(
        self, points: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return ``(raw_ids, confidence, probabilities)`` per point in order.

        ``raw_ids`` are SemanticPOSS raw IDs (unmapped stay unknown/0);
        ``probabilities`` is the ``(N, 14)`` learning-class matrix.
        """
        points_array = np.asarray(points, dtype=np.float32)
        if (
            points_array.ndim != 2
            or points_array.shape[1] != 4
            or not np.all(np.isfinite(points_array))
        ):
            raise ValueError("CENet inference requires finite sensor-frame XYZI (N, 4)")
        count = points_array.shape[0]
        if count == 0:
            return (
                np.zeros(0, np.int32),
                np.zeros(0, np.float32),
                np.zeros((0, CENET_N_LEARNING_CLASSES), np.float32),
            )
        tensor, rows, cols, valid = render_cenet_image(points_array)
        proba = np.zeros((count, CENET_N_LEARNING_CLASSES), np.float32)
        if valid.any():
            with self._torch.no_grad():
                output = self._model(self._torch.from_numpy(tensor))
            main = output[0] if isinstance(output, (list, tuple)) else output
            scores = np.asarray(main[0].detach().cpu(), dtype=np.float64)
            if scores.shape != (
                CENET_N_LEARNING_CLASSES, CENET_IMAGE_HEIGHT, CENET_IMAGE_WIDTH):
                raise ValueError("CENet output breaks the 14x40x1800 contract")
            selected = scores[:, rows[valid], cols[valid]]
            if not np.allclose(selected.sum(axis=0), 1.0, atol=2e-3):
                raise ValueError("CENet outputs must be probabilities summing to one")
            proba[valid] = selected.T.astype(np.float32)
        best = proba.argmax(axis=1)
        return (
            _LEARNING_TO_RAW[best].astype(np.int32),
            proba[np.arange(count), best].astype(np.float32),
            proba,
        )

    def infer(
        self, points: np.ndarray, labels: np.ndarray | None = None
    ) -> SemanticResult:
        del labels
        points_array = np.asarray(points, dtype=np.float32)
        if (
            points_array.ndim != 2
            or points_array.shape[1] != 4
            or not np.all(np.isfinite(points_array))
        ):
            raise ValueError("CENet inference requires finite sensor-frame XYZI (N, 4)")
        count = points_array.shape[0]
        if count == 0:
            return SemanticResult(np.zeros(0, np.int32), np.zeros(0, np.float32), "model")
        raw, confidence, _ = self.infer_raw(points_array)
        mapped = np.array(
            [SEMANTIC_POSS_LABELS.get(int(raw_id), 0) for raw_id in raw],
            dtype=np.int32,
        )
        return SemanticResult(mapped, confidence, "model")


__all__ = [
    "CENET_IMAGE_HEIGHT",
    "CENET_IMAGE_WIDTH",
    "CENET_LEARNING_TO_RAW",
    "CENET_MEANS",
    "CENET_N_LEARNING_CLASSES",
    "CENET_STDS",
    "CENET_YAW_COL_OFFSET",
    "BasicBlock",
    "BasicConv2d",
    "CENetSemanticProvider",
    "ResNet_34",
    "model_contract",
    "render_cenet_image",
]
