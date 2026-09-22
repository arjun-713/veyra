#!/usr/bin/env python3
"""Prove whether the RTX GPU participates in Veyra inference (run on the RTX box).

Non-invasive: imports libraries, places one small tensor, runs ≤5 tiny
forward passes. Prints device facts; exit 0 always (facts, not gates).
Also captures `nvidia-smi` before/after when available.
"""
import shutil
import subprocess

print("== torch ==")
try:
    import torch

    print("torch:", torch.__version__, "| cuda_available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device:", torch.cuda.get_device_name(0))
        x = torch.randn(8, 5, 40, 60)
        xg = x.to("cuda")
        print("tensor device after .to(cuda):", xg.device)
        m = torch.nn.Conv2d(5, 8, 3, padding=1).to("cuda")
        print("param device:", next(m.parameters()).device)
        import time

        m.eval()
        with torch.no_grad():
            for _ in range(3):
                m(xg)
            t = time.perf_counter()
            for _ in range(5):
                m(xg)
            print(f"tiny-conv 5 iters: {(time.perf_counter() - t) * 1000:.1f} ms total")
    else:
        print("CUDA NOT visible to torch (CPU-only build or no driver)")
except ImportError:
    print("torch not installed")

print("== onnxruntime ==")
try:
    import onnxruntime as ort

    print("ort:", ort.__version__, "| available:", ort.get_available_providers())
except ImportError:
    print("onnxruntime not installed")

print("== nvidia-smi ==")
if shutil.which("nvidia-smi"):
    print(
        subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,power.draw", "--format=csv"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout.strip()
    )
else:
    print("nvidia-smi absent")
