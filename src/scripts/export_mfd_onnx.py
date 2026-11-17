# -*- coding: utf-8 -*-
"""
export_mfd_onnx.py: Convert YOLOv8 MFD PyTorch weights to ONNX format.
======================================================================
Converts models/yolo_v8_ft.pt (from opendatalab/PDF-Extract-Kit-1.0)
to models/pdf_extract_mfd.onnx with imgsz=1280, opset=17, and full
3-tier validation (file hash, ONNX checker, ORT session dry-run).

Input Tensor:  'images'  shape [1, 3, 1280, 1280], dtype float32
Output Tensor: 'output0' shape [1, 6, 33600],     dtype float32
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import PATHS

EXPECTED_SHA256 = "41029d5abb9b0b6df825ecaf8adf9151762ea0688ac0fc4ea0ea34ab9a5808fc"
EXPECTED_SIZE = 349867002
HF_REPO_ID = "opendatalab/PDF-Extract-Kit-1.0"
HF_SUBFOLDER = "models/MFD/YOLO"
HF_FILENAME = "yolo_v8_ft.pt"


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file in chunks."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_pytorch_weights(weights_path: Path, download_if_missing: bool = True) -> Path:
    """Verify PyTorch weights exist and match expected checksum, downloading if needed."""
    if weights_path.exists():
        actual_size = weights_path.stat().st_size
        if actual_size == EXPECTED_SIZE:
            return weights_path
        print(f"[MFD Export] Size mismatch: expected {EXPECTED_SIZE}, got {actual_size}. Validating hash...")
        actual_hash = calculate_sha256(weights_path)
        if actual_hash == EXPECTED_SHA256:
            return weights_path
        print("[MFD Export] Corrupted weights detected. Re-downloading...")
        weights_path.unlink()

    if not download_if_missing:
        raise FileNotFoundError(f"PyTorch weights not found at {weights_path} and download disabled.")

    print(f"[MFD Export] Downloading weights from HuggingFace ({HF_REPO_ID})...")
    from huggingface_hub import hf_hub_download
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded_path = hf_hub_download(
        repo_id=HF_REPO_ID,
        filename=f"{HF_SUBFOLDER}/{HF_FILENAME}",
        local_dir=weights_path.parent,
        local_dir_use_symlinks=False
    )
    downloaded_file = Path(downloaded_path)
    if downloaded_file != weights_path and downloaded_file.exists():
        shutil.move(str(downloaded_file), str(weights_path))

    # Verify downloaded file
    actual_hash = calculate_sha256(weights_path)
    if actual_hash != EXPECTED_SHA256:
        weights_path.unlink(missing_ok=True)
        raise ValueError(f"Downloaded weights failed SHA256 checksum: {actual_hash} != {EXPECTED_SHA256}")

    print("[MFD Export] Weights successfully downloaded and verified.")
    return weights_path


def validate_onnx_model(onnx_path: Path, imgsz: int = 1280, dynamic: bool = False) -> None:
    """Perform Tier 2 (graph structural) and Tier 3 (ORT execution) verification."""
    import onnx
    import onnxruntime as ort
    import numpy as np

    print(f"[MFD Export] Validating ONNX structure for {onnx_path}...")
    onnx.checker.check_model(str(onnx_path))
    model_proto = onnx.load(str(onnx_path))

    # Inspect inputs
    assert len(model_proto.graph.input) == 1, f"Expected 1 input, got {len(model_proto.graph.input)}"
    inp = model_proto.graph.input[0]
    assert inp.name == "images", f"Expected input name 'images', got '{inp.name}'"
    inp_dims = [d.dim_value if d.HasField("dim_value") else d.dim_param for d in inp.type.tensor_type.shape.dim]
    if not dynamic:
        assert inp_dims == [1, 3, imgsz, imgsz], f"Input shape mismatch: expected [1, 3, {imgsz}, {imgsz}], got {inp_dims}"

    # Inspect outputs
    assert len(model_proto.graph.output) == 1, f"Expected 1 output, got {len(model_proto.graph.output)}"
    out = model_proto.graph.output[0]
    assert out.name == "output0", f"Expected output name 'output0', got '{out.name}'"
    out_dims = [d.dim_value if d.HasField("dim_value") else d.dim_param for d in out.type.tensor_type.shape.dim]
    expected_anchors = (imgsz // 8)**2 + (imgsz // 16)**2 + (imgsz // 32)**2
    if not dynamic:
        assert out_dims == [1, 6, expected_anchors], f"Output shape mismatch: expected [1, 6, {expected_anchors}], got {out_dims}"

    # Tier 3: InferenceSession dry-run
    available_providers = ort.get_available_providers()
    provider_candidates = ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]
    active_providers = [p for p in provider_candidates if p in available_providers]
    print(f"[MFD Export] Testing ORT inference with providers: {active_providers}")

    session = ort.InferenceSession(str(onnx_path), providers=active_providers)
    dummy_input = np.zeros((1, 3, imgsz, imgsz), dtype=np.float32)
    raw_outputs = session.run(None, {"images": dummy_input})
    assert len(raw_outputs) == 1, "Expected single inference output"
    assert raw_outputs[0].shape == (1, 6, expected_anchors), f"Inference output shape mismatch: {raw_outputs[0].shape}"

    print(f"[MFD Export] ONNX validation passed! Model is ready for deployment on {session.get_providers()[0]}.")


def export_mfd_to_onnx(
    weights_path: Path | str = PATHS.models_dir / "yolo_v8_ft.pt",
    output_path: Path | str = PATHS.models_dir / "pdf_extract_mfd.onnx",
    imgsz: int = 1280,
    opset: int = 17,
    dynamic: bool = False,
    simplify: bool = True,
    verify: bool = True,
    force: bool = False,
    download_if_missing: bool = True,
) -> Path:
    """Programmatic API to export YOLOv8 MFD PyTorch weights to ONNX format."""
    weights_path = Path(weights_path).resolve()
    output_path = Path(output_path).resolve()

    if output_path.exists() and not force:
        print(f"[MFD Export] Target ONNX already exists at {output_path}.")
        if verify:
            validate_onnx_model(output_path, imgsz=imgsz, dynamic=dynamic)
        return output_path

    # Step 1: Ensure weights are available and verified
    weights_path = ensure_pytorch_weights(weights_path, download_if_missing=download_if_missing)

    # Step 2: Load YOLO model and execute export
    from ultralytics import YOLO
    print(f"[MFD Export] Loading PyTorch model from {weights_path}...")
    model = YOLO(str(weights_path))

    print(f"[MFD Export] Exporting to ONNX (imgsz={imgsz}, opset={opset}, dynamic={dynamic}, simplify={simplify})...")
    exported_raw = model.export(
        format="onnx",
        imgsz=imgsz,
        opset=opset,
        dynamic=dynamic,
        simplify=simplify,
    )

    exported_path = Path(exported_raw).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Relocate to desired target if different
    if exported_path != output_path:
        print(f"[MFD Export] Moving exported model {exported_path.name} -> {output_path.name}...")
        if output_path.exists():
            output_path.unlink()
        shutil.copy2(exported_path, output_path)

    # Step 3: Validation
    if verify:
        validate_onnx_model(output_path, imgsz=imgsz, dynamic=dynamic)

    print(f"[MFD Export] Successfully exported MFD model to: {output_path}")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export YOLOv8 MFD PyTorch weights to ONNX format.")
    parser.add_argument("--weights", "-w", type=Path, default=PATHS.models_dir / "yolo_v8_ft.pt", help="Path to input .pt weights")
    parser.add_argument("--output", "-o", type=Path, default=PATHS.models_dir / "pdf_extract_mfd.onnx", help="Path to output .onnx model")
    parser.add_argument("--imgsz", type=int, default=1280, help="Image resolution for export (default: 1280)")
    parser.add_argument("--opset", type=int, default=17, help="ONNX opset version (default: 17)")
    parser.add_argument("--dynamic", action="store_true", default=False, help="Enable dynamic input/output axes")
    parser.add_argument("--no-simplify", dest="simplify", action="store_false", default=True, help="Disable onnxslim")
    parser.add_argument("--no-verify", dest="verify", action="store_false", default=True, help="Skip post-export validation")
    parser.add_argument("--force", "-f", action="store_true", help="Force export even if output file exists")
    parser.add_argument("--no-download", dest="download", action="store_false", default=True, help="Do not download weights if missing")

    args = parser.parse_args()
    try:
        export_mfd_to_onnx(
            weights_path=args.weights,
            output_path=args.output,
            imgsz=args.imgsz,
            opset=args.opset,
            dynamic=args.dynamic,
            simplify=args.simplify,
            verify=args.verify,
            force=args.force,
            download_if_missing=args.download,
        )
        return 0
    except Exception as e:
        print(f"[MFD Export ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
