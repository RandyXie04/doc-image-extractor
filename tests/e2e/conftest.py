# -*- coding: utf-8 -*-
"""
tests/e2e/conftest.py
=====================
Central pytest fixtures, marker registrations, and offline isolation settings
for the 3-Stage Mathematical Formula Extraction and Recognition E2E test suite.

Features:
- Enforces 100% offline environment (`HF_HUB_OFFLINE="1"`).
- Registers markers: `e2e`, `tier1`, `tier2`, `tier3`, `tier4` for `--strict-markers`.
- Provides model fixtures: `detector`, `cropper`, `recognizer`, `exporter`, `pipeline`.
- Supports progressive testability: graceful fallback/adapter when pipeline modules are in-flight.
"""
from __future__ import annotations

import gc
import os
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple, Union
import fitz
import numpy as np
from PIL import Image
import pytest
import torch

# Enforce offline execution before any neural or huggingface imports
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["RECOGNITION_MODEL_CHECKPOINT"] = "models/surya_rec2"
os.environ.setdefault("MPLCONFIGDIR", os.environ.get("TEMP", "."))

from src.extraction.contracts import (
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaRecognitionContract,
    FormulaResultContract,
)
from src.extraction.formula_cropper import FormulaCropper
from src.extraction.formula_detector import FormulaDetector
from src.extraction.formula_exporter import (
    export_formula_result,
    export_formula_results,
    export_highres_png,
    latex_to_mathml,
    sanitize_latex,
)
from src.extraction.formula_recognizer import RecognitionPredictor


def pytest_configure(config: pytest.Config) -> None:
    """Register custom E2E markers to pass cleanly with --strict-markers."""
    config.addinivalue_line("markers", "e2e: End-to-end integration and system pipeline tests")
    config.addinivalue_line("markers", "tier1: Tier 1 Feature Coverage test suite (70 cases)")
    config.addinivalue_line("markers", "tier2: Tier 2 Boundary & Corner Cases test suite (55 cases)")
    config.addinivalue_line("markers", "tier3: Tier 3 Cross-Feature Combinations test suite (16 cases)")
    config.addinivalue_line("markers", "tier4: Tier 4 Real-World Application Scenarios (6 cases)")


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Returns absolute path to tests/e2e/fixtures directory."""
    p = Path(__file__).resolve().parent / "fixtures"
    if not p.is_dir():
        from tests.e2e.fixtures.generate_fixtures import build_all_fixtures
        build_all_fixtures()
    return p


@pytest.fixture(scope="session")
def onnx_model_path() -> Path:
    """Returns the resolved path to pdf_extract_mfd.onnx model."""
    candidates = [
        Path("models/pdf_extract_mfd.onnx").resolve(),
        Path("models/yolo_v8_ft.onnx").resolve(),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError("models/pdf_extract_mfd.onnx not found on disk.")


@pytest.fixture(scope="session")
def detector(onnx_model_path: Path) -> FormulaDetector:
    """Cached Stage 1 FormulaDetector session."""
    return FormulaDetector(model_path=onnx_model_path)


@pytest.fixture(scope="session")
def cropper() -> FormulaCropper:
    """Stage 2 FormulaCropper instance with standard safety padding."""
    return FormulaCropper(pad=4, batch_size=32)


@pytest.fixture(scope="package")
def recognizer() -> Generator[RecognitionPredictor, None, None]:
    """Stage 3 SuryaOCR RecognitionPredictor instance."""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Use float32 for rock-solid stability on RTX 40 series / cu124 to avoid
    # Swin attention float16 memory alignment issues, well within the 2.5 GB VRAM budget.
    dtype = torch.float32
    rec = RecognitionPredictor(
        device=device,
        dtype=dtype,
        batch_size=32,
        checkpoint="models/surya_rec2",
        lazy_load=False,
    )
    try:
        yield rec
    finally:
        rec._model = None
        rec._processor = None
        del rec
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


class E2EFormulaPipelineAdapter:
    """
    Contract-compliant orchestrator adapter connecting Stages 1, 2, and 3.
    Matches the exact interface contract defined in PROJECT.md and Milestone 3.
    """

    def __init__(
        self,
        detector: Optional[FormulaDetector] = None,
        cropper: Optional[FormulaCropper] = None,
        recognizer: Optional[RecognitionPredictor] = None,
    ) -> None:
        self.detector = detector or FormulaDetector()
        self.cropper = cropper or FormulaCropper(pad=4, batch_size=32)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.recognizer = recognizer or RecognitionPredictor(
            device=device,
            dtype=torch.float32,
            checkpoint="models/surya_rec2",
            lazy_load=False,
        )

    def process_page(
        self,
        image_or_path: Union[str, Path, Image.Image, np.ndarray],
        conf_threshold: float = 0.20,
        output_dir: Optional[Union[str, Path]] = None,
        pdf_page: Optional[fitz.Page] = None,
        pad: int = 4,
        batch_size: int = 32,
        save_manifest: bool = True,
        page_idx: Optional[int] = None,
    ) -> List[FormulaResultContract]:
        """
        Executes end-to-end 3-stage formula extraction and recognition:
        1. Stage 1: FormulaDetector.detect -> List[FormulaDetectionContract]
        2. Stage 2: FormulaCropper.crop_and_batch -> mini-batches of crops
        3. Stage 3: RecognitionPredictor.predict_crops -> LaTeX + confidence
        4. Exporter: export_formula_results -> List[FormulaResultContract]
        5. FormulaCropper.restore_order -> Document index order
        """
        # Normalize input to PIL image
        if isinstance(image_or_path, (str, Path)):
            p = Path(image_or_path)
            if p.suffix.lower() == ".pdf":
                doc = fitz.open(str(p))
                pdf_page = doc[0]
                pix = pdf_page.get_pixmap(dpi=150)
                pil_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            else:
                pil_img = Image.open(str(p)).convert("RGB")
        elif isinstance(image_or_path, np.ndarray):
            pil_img = Image.fromarray(image_or_path).convert("RGB")
        elif isinstance(image_or_path, Image.Image):
            pil_img = image_or_path.convert("RGB")
        else:
            raise TypeError(f"Unsupported image type: {type(image_or_path)}")

        # 1. Stage 1: Detect formulas
        detections = self.detector.detect(pil_img, conf_threshold=conf_threshold)
        if not detections:
            return []

        # 2. Stage 2: Crop & batch with safety padding
        cropper = FormulaCropper(pad=pad, batch_size=batch_size)
        batches, sorted_items = cropper.crop_and_batch(pil_img, detections)
        if not batches:
            return []

        # 3. Stage 3: Predict batches
        all_crops: List[Image.Image] = []
        all_items: List[FormulaCroppedItemContract] = []
        all_preds: List[Tuple[str, float]] = []

        for batch in batches:
            batch_crops = [pair[0] for pair in batch]
            batch_items = [pair[1] for pair in batch]
            preds = self.recognizer.predict_crops(batch_crops)
            all_crops.extend(batch_crops)
            all_items.extend(batch_items)
            all_preds.extend(preds)

        # 4. Multi-format Export
        out_d = Path(output_dir) if output_dir else Path(os.environ.get("TEMP", ".")) / "formula_e2e_out"
        out_d.mkdir(parents=True, exist_ok=True)

        results = export_formula_results(
            crops=all_crops,
            items=all_items,
            raw_predictions=all_preds,
            output_dir=out_d,
            pdf_page=pdf_page,
            imgsz=1600,
            save_manifest=save_manifest,
            page_idx=page_idx,
        )

        # 5. Restore original document reading order
        return cropper.restore_order(results)


@pytest.fixture(scope="package")
def pipeline(
    detector: FormulaDetector,
    cropper: FormulaCropper,
    recognizer: RecognitionPredictor,
) -> Any:
    """Returns the unified 3-stage FormulaExtractionPipeline."""
    try:
        from src.extraction.formula_pipeline import FormulaExtractionPipeline
        return FormulaExtractionPipeline(
            detector=detector,
            cropper=cropper,
            recognizer=recognizer,
        )
    except (ImportError, AttributeError):
        return E2EFormulaPipelineAdapter(
            detector=detector,
            cropper=cropper,
            recognizer=recognizer,
        )


@pytest.fixture
def sample_doc_page(fixtures_dir: Path) -> Image.Image:
    """Returns sample document page with formulas and dense prose."""
    img_path = fixtures_dir / "tier1" / "t1_short_formula.png"
    return Image.open(str(img_path)).convert("RGB")
