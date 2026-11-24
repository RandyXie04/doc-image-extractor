# -*- coding: utf-8 -*-
"""
Milestone 2 Unit & Integration Test Suite: Formula Cropping, Recognition & Export
=================================================================================
Covers:
  - Strict Pydantic contracts & immutability (FormulaDetectionContract, FormulaCroppedItemContract,
    FormulaRecognitionContract, FormulaResultContract, TypeAdapters).
  - FormulaCropper safety padding (3-5px), boundary clamping, zero-height AR safety,
    aspect ratio sorting, mini-batch chunking, degenerate skipping, and document order restoration.
  - Dense surrounding text fixtures: embedded short formulas f(x)=ax+bx and display formulas
    surrounded by dense mixed Chinese and English text paragraphs.
  - RecognitionPredictor direct crop batch ingestion, blank/degenerate crop short-circuiting,
    CUDA/CPU fallback, and document index preservation.
  - FormulaExporter multi-format generation: LaTeX sanitization (fences, delimiters, whitespace,
    CJK \\text{} wrapping without double-wrapping), valid MathML XML conversion and W3C <merror> fallback
    validated by xml.etree.ElementTree, and high-resolution PNG export strictly at max dimension 1600px
    (both vector PyMuPDF and raster Lanczos with 1px rounding guard).
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import List, Tuple
import xml.etree.ElementTree as ET

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError
import pytest
import torch

from src.extraction.contracts import (
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaRecognitionContract,
    FormulaResultContract,
    validate_formula_cropped_item,
    validate_formula_detection,
    validate_formula_detections,
    validate_formula_recognition,
    validate_formula_result,
    validate_formula_results,
)
from src.extraction.formula_cropper import (
    FormulaCropper,
    prepare_formula_batches,
    restore_document_order,
)
from src.extraction.formula_exporter import (
    export_formula_result,
    export_formula_results,
    export_highres_png,
    latex_to_mathml,
    normalize_katex_fences,
    sanitize_latex,
)
from src.extraction.formula_recognizer import (
    RecognitionPredictor,
    is_blank_or_degenerate,
)


# =============================================================================
# 1. Pydantic Contracts & Zero Raw-Dict Policy Tests
# =============================================================================

class TestFormulaContracts:
    """Verifies strict validation, extra-field rejection, and immutability."""

    def test_formula_detection_contract_valid(self):
        inline_det = FormulaDetectionContract(
            box=(10.0, 20.0, 100.0, 50.0),
            score=0.95,
            category="inline",
            class_id=0,
        )
        assert inline_det.category == "inline"
        assert inline_det.class_id == 0
        assert inline_det.box == (10.0, 20.0, 100.0, 50.0)

        isolated_det = FormulaDetectionContract(
            box=(50.0, 100.0, 300.0, 180.0),
            score=0.88,
            category="isolated",
            class_id=1,
        )
        assert isolated_det.category == "isolated"
        assert isolated_det.class_id == 1

    def test_formula_detection_contract_invalid_class_category_mismatch(self):
        with pytest.raises(ValueError, match="class_id 0 requires category='inline'"):
            FormulaDetectionContract(
                box=(10.0, 20.0, 100.0, 50.0),
                score=0.95,
                category="isolated",  # Mismatch with class_id 0
                class_id=0,
            )

        with pytest.raises(ValueError, match="class_id 1 requires category='isolated'"):
            FormulaDetectionContract(
                box=(10.0, 20.0, 100.0, 50.0),
                score=0.95,
                category="inline",  # Mismatch with class_id 1
                class_id=1,
            )

    def test_formula_detection_contract_invalid_box_coordinates(self):
        # Negative coordinate
        with pytest.raises(ValueError, match="coordinates cannot be negative"):
            FormulaDetectionContract(
                box=(-5.0, 20.0, 100.0, 50.0),
                score=0.9,
                category="inline",
                class_id=0,
            )

        # Inverted box (x2 <= x1)
        with pytest.raises(ValueError, match="width and height must be positive"):
            FormulaDetectionContract(
                box=(100.0, 20.0, 50.0, 50.0),
                score=0.9,
                category="inline",
                class_id=0,
            )

    def test_formula_detection_contract_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            FormulaDetectionContract(
                box=(10.0, 20.0, 100.0, 50.0),
                score=0.95,
                category="inline",
                class_id=0,
                undeclared_hallucinated_key=123,  # Forbidden
            )

    def test_formula_detection_contract_frozen(self):
        det = FormulaDetectionContract(
            box=(10.0, 20.0, 100.0, 50.0),
            score=0.95,
            category="inline",
            class_id=0,
        )
        with pytest.raises(ValidationError):
            det.score = 0.50  # Frozen model cannot be mutated

    def test_formula_cropped_item_contract_valid_and_frozen(self):
        det = FormulaDetectionContract(
            box=(10.0, 20.0, 110.0, 60.0),
            score=0.92,
            category="inline",
            class_id=0,
        )
        item = FormulaCroppedItemContract(
            item_id="eq_00000",
            original_index=0,
            detection=det,
            padded_box=(6, 16, 114, 64),
            aspect_ratio=2.25,
        )
        assert item.item_id == "eq_00000"
        assert item.padded_box == (6, 16, 114, 64)
        assert item.aspect_ratio == 2.25

        with pytest.raises(ValidationError):
            item.original_index = 5

    def test_formula_recognition_contract_valid(self):
        rec = FormulaRecognitionContract(
            item_id="eq_00001",
            original_index=1,
            latex="f(x) = ax + bx",
            confidence=0.985,
        )
        assert rec.item_id == "eq_00001"
        assert rec.latex == "f(x) = ax + bx"
        assert rec.confidence == 0.985

    def test_formula_result_contract_valid_and_frozen(self):
        res = FormulaResultContract(
            item_id="eq_00002",
            original_index=2,
            category="isolated",
            box=(50.0, 100.0, 300.0, 180.0),
            padded_box=(46, 96, 304, 184),
            latex=r"\int_0^1 x^2 dx = \frac{1}{3}",
            mathml="<math>...</math>",
            image_path="C:/path/to/img.png",
            confidence=0.97,
            page_idx=0,
        )
        assert res.item_id == "eq_00002"
        assert res.category == "isolated"
        assert res.latex == r"\int_0^1 x^2 dx = \frac{1}{3}"

        with pytest.raises(ValidationError):
            res.confidence = 0.1

    def test_type_adapters_and_validation_functions(self):
        raw_det = {
            "box": [15.0, 25.0, 120.0, 65.0],
            "score": 0.89,
            "category": "inline",
            "class_id": 0,
        }
        det = validate_formula_detection(raw_det)
        assert isinstance(det, FormulaDetectionContract)
        assert det.score == 0.89

        dets = validate_formula_detections([raw_det, raw_det])
        assert len(dets) == 2

        raw_item = {
            "item_id": "eq_00010",
            "original_index": 10,
            "detection": raw_det,
            "padded_box": [11, 21, 124, 69],
            "aspect_ratio": 2.35,
        }
        item = validate_formula_cropped_item(raw_item)
        assert isinstance(item, FormulaCroppedItemContract)

        raw_rec = {
            "item_id": "eq_00010",
            "original_index": 10,
            "latex": "y = kx + b",
            "confidence": 0.94,
        }
        rec = validate_formula_recognition(raw_rec)
        assert isinstance(rec, FormulaRecognitionContract)

        raw_res = {
            "item_id": "eq_00010",
            "original_index": 10,
            "category": "inline",
            "box": [15.0, 25.0, 120.0, 65.0],
            "padded_box": [11, 21, 124, 69],
            "latex": "y = kx + b",
            "mathml": "<math/>",
            "image_path": "images/eq_00010.png",
            "confidence": 0.94,
        }
        res = validate_formula_result(raw_res)
        assert isinstance(res, FormulaResultContract)
        results = validate_formula_results([raw_res])
        assert len(results) == 1


# =============================================================================
# 2. Stage 2 FormulaCropper Tests
# =============================================================================

class TestFormulaCropper:
    """Verifies padding, boundary clamping, AR calculation, batching and order restoration."""

    def test_cropper_init_validation(self):
        cropper = FormulaCropper(pad=4, batch_size=32)
        assert cropper.pad == 4
        assert cropper.batch_size == 32

        with pytest.raises(ValueError, match="pad must be between 1 and 20"):
            FormulaCropper(pad=0)
        with pytest.raises(ValueError, match="pad must be between 1 and 20"):
            FormulaCropper(pad=25)
        with pytest.raises(ValueError, match="batch_size must be between 1 and 256"):
            FormulaCropper(batch_size=0)

    def test_cropper_clamp_box_standard_and_boundaries(self):
        W, H = 1000, 1200
        pad = 4

        # Standard interior box
        box_std = (100.0, 200.0, 300.0, 250.0)
        clamped_std = FormulaCropper.clamp_box(box_std, W, H, pad=pad)
        assert clamped_std == (96, 196, 304, 254)

        # Top-left corner box (boundary clamping to 0)
        box_tl = (2.0, 1.0, 50.0, 30.0)
        clamped_tl = FormulaCropper.clamp_box(box_tl, W, H, pad=pad)
        assert clamped_tl[0] == 0  # 2 - 4 = -2 -> clamped to 0
        assert clamped_tl[1] == 0  # 1 - 4 = -3 -> clamped to 0
        assert clamped_tl[2] == 54
        assert clamped_tl[3] == 34

        # Bottom-right corner box (boundary clamping to W, H)
        box_br = (980.0, 1180.0, 1005.0, 1205.0)
        clamped_br = FormulaCropper.clamp_box(box_br, W, H, pad=pad)
        assert clamped_br[0] == 976
        assert clamped_br[1] == 1176
        assert clamped_br[2] == 1000  # Clamped to W
        assert clamped_br[3] == 1200  # Clamped to H

    def test_cropper_aspect_ratio_zero_height_safety(self):
        # Normal box
        ar_normal = FormulaCropper.calculate_aspect_ratio((10, 20, 110, 70))
        assert ar_normal == round(100.0 / 50.0, 4)

        # Zero-height safety: h = 0 -> uses max(1, 0) = 1, prevents ZeroDivisionError
        ar_zero_h = FormulaCropper.calculate_aspect_ratio((10, 20, 110, 20))
        assert ar_zero_h == 100.0
        assert isinstance(ar_zero_h, float)

    def test_cropper_degenerate_box_skipping(self):
        cropper = FormulaCropper(pad=4, batch_size=32)
        img = Image.new("RGB", (1000, 1000), (255, 255, 255))

        # A valid box and a degenerate box clamped entirely outside canvas
        valid_det = FormulaDetectionContract(
            box=(100.0, 100.0, 200.0, 150.0),
            score=0.9,
            category="inline",
            class_id=0,
        )
        # Outside canvas (1000x1000): box at (1005, 1005, 1020, 1020) clamps to (1000, 1000, 1000, 1000)
        # Resulting in w=0, h=0 -> skipped as degenerate
        degen_det = FormulaDetectionContract(
            box=(1005.0, 1005.0, 1020.0, 1020.0),
            score=0.9,
            category="inline",
            class_id=0,
        )
        batches, items = cropper.crop_and_batch(img, [valid_det, degen_det])
        assert len(items) == 1
        assert items[0].original_index == 0

    def test_cropper_crop_and_batch_aspect_ratio_sorting(self):
        cropper = FormulaCropper(pad=4, batch_size=32)
        img = Image.new("RGB", (1200, 1200), (255, 255, 255))

        # Box 1: Tall/square display formula (AR ~ 1.0)
        det_square = FormulaDetectionContract(
            box=(100.0, 100.0, 200.0, 200.0),  # 100x100 -> padded 108x108 -> AR=1.0
            score=0.95,
            category="isolated",
            class_id=1,
        )
        # Box 2: Very wide inline formula (AR ~ 10.0)
        det_wide = FormulaDetectionContract(
            box=(100.0, 300.0, 600.0, 350.0),  # 500x50 -> padded 508x58 -> AR=8.7586
            score=0.90,
            category="inline",
            class_id=0,
        )
        # Box 3: Medium formula (AR ~ 3.0)
        det_med = FormulaDetectionContract(
            box=(100.0, 500.0, 400.0, 600.0),  # 300x100 -> padded 308x108 -> AR=2.8519
            score=0.88,
            category="inline",
            class_id=0,
        )

        batches, sorted_items = cropper.crop_and_batch(img, [det_wide, det_square, det_med])
        # Sorted items must have ascending aspect ratios: square (1.0) < med (2.85) < wide (8.76)
        ars = [item.aspect_ratio for item in sorted_items]
        assert ars == sorted(ars)
        assert sorted_items[0].original_index == 1  # Square was index 1
        assert sorted_items[1].original_index == 2  # Med was index 2
        assert sorted_items[2].original_index == 0  # Wide was index 0

    def test_cropper_batch_chunking_and_order_restoration(self):
        cropper = FormulaCropper(pad=4, batch_size=32)
        img = Image.new("RGB", (2000, 2000), (255, 255, 255))

        # Generate 70 simulated detections
        detections: List[FormulaDetectionContract] = []
        for i in range(70):
            # Vary widths to produce different aspect ratios
            w = 50.0 + (i % 10) * 40.0
            h = 40.0
            x1 = 50.0
            y1 = 50.0 + (i % 20) * 60.0
            detections.append(
                FormulaDetectionContract(
                    box=(x1, y1, x1 + w, y1 + h),
                    score=0.90,
                    category="inline" if i % 2 == 0 else "isolated",
                    class_id=0 if i % 2 == 0 else 1,
                )
            )

        batches, sorted_items = cropper.crop_and_batch(img, detections)
        # 70 items batched with batch_size=32 should result in [32, 32, 6]
        assert len(batches) == 3
        assert len(batches[0]) == 32
        assert len(batches[1]) == 32
        assert len(batches[2]) == 6
        assert len(sorted_items) == 70

        # Verify restore_order brings back exact 0..69 sequence
        restored = FormulaCropper.restore_order(sorted_items)
        assert [item.original_index for item in restored] == list(range(70))

        # Test standalone restore_document_order helper
        restored_helper = restore_document_order(sorted_items)
        assert [item.original_index for item in restored_helper] == list(range(70))

    def test_cropper_numpy_and_empty_inputs(self):
        cropper = FormulaCropper(pad=4, batch_size=32)

        # Empty detections
        empty_batches, empty_items = cropper.crop_and_batch(Image.new("RGB", (100, 100)), [])
        assert empty_batches == []
        assert empty_items == []

        # NumPy array input
        np_img = np.ones((500, 500, 3), dtype=np.uint8) * 255
        det = FormulaDetectionContract(
            box=(50.0, 50.0, 150.0, 100.0),
            score=0.9,
            category="inline",
            class_id=0,
        )
        batches, items = cropper.crop_and_batch(np_img, [det])
        assert len(batches) == 1
        crop_img, item = batches[0][0]
        assert isinstance(crop_img, Image.Image)
        assert crop_img.mode == "RGB"
        assert item.padded_box == (46, 46, 154, 104)


# =============================================================================
# 3. Dense Surrounding Text Test Fixture (User Feedback Mandate)
# =============================================================================

class TestFormulaCropperDenseSurroundingText:
    """
    Directly addresses user directive:
    '測試夾具與邊界情境構建時，必須在公式周圍參雜大量文字／密集段落文本，
     以真實模擬出版物與真實文稿的圖文混排情境。包含密集段落內嵌短公式 f(x)=ax+bx'
    """

    @pytest.fixture
    def dense_document_page(self) -> Tuple[Image.Image, List[FormulaDetectionContract]]:
        """
        Synthesizes a realistic high-density document page (1200x1600)
        with dense Chinese and English paragraphs embedding short inline formulas
        and isolated display formulas.
        """
        page_w, page_h = 1200, 1600
        canvas = Image.new("RGB", (page_w, page_h), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        # Paragraph 1 (Top dense Chinese & English text)
        p1_lines = [
            "在現代數值計算與機器學習理論中，探討模型函數的局部平滑度與收斂階數是分析算法穩定性的關鍵基礎。",
            "Specifically, for high-dimensional parameter spaces with regularized Lipschitz gradients, we define the linear approximation:",
            "為了驗證局部展開式的有效性，我們在下式中將一階導數近似與非線性擾動項進行分離處理：",
        ]
        y_cursor = 50
        for line in p1_lines:
            draw.text((60, y_cursor), line, fill=(20, 20, 20))
            y_cursor += 30

        # Embedded Short Inline Formula: f(x) = ax + bx
        # Surrounding inline text: "給定自變數 x 時，函數 " [f(x)=ax+bx] " 表示加權線性疊加。"
        draw.text((60, y_cursor), "給定自變數 x 時，目標函數定義為 ", fill=(20, 20, 20))
        formula_1_x1, formula_1_y1 = 340, y_cursor - 2
        formula_1_x2, formula_1_y2 = 480, y_cursor + 24
        draw.text((formula_1_x1 + 4, formula_1_y1 + 4), "f(x) = ax + bx", fill=(0, 0, 0))
        draw.text((formula_1_x2 + 10, y_cursor), " ，其中 a, b 為非零實數係數。", fill=(20, 20, 20))
        y_cursor += 40

        # Paragraph 2 (Dense intermediate text)
        p2_lines = [
            "注意到上述短公式具有緊湊的結構特徵，在排版時與前後文字行距保持嚴格一致，不得產生任何基準線偏移。",
            "Furthermore, error bounds for numerical quadratures satisfy the Euler-Maclaurin summation formula under compact support:",
            "對於二次多項式的定積分運算，我們可以直接給出閉式解析解如下所示：",
        ]
        for line in p2_lines:
            draw.text((60, y_cursor), line, fill=(20, 20, 20))
            y_cursor += 30

        # Isolated Display Formula: \int_0^1 x^2 dx = \frac{1}{3}
        y_cursor += 20
        formula_2_x1, formula_2_y1 = 380, y_cursor
        formula_2_x2, formula_2_y2 = 680, y_cursor + 45
        draw.text((formula_2_x1 + 10, formula_2_y1 + 10), "int_0^1 x^2 dx = 1/3", fill=(0, 0, 0))
        draw.rectangle([formula_2_x1, formula_2_y1, formula_2_x2, formula_2_y2], outline=(240, 240, 240))
        y_cursor += 65

        # Paragraph 3 (Bottom dense text)
        p3_lines = [
            "由上述定積分計算可知，多項式在單位區間 [0, 1] 上的均值積分精確等於三分之一。",
            "In summary, the interplay between inline variables and displayed integral identities preserves topological continuity.",
            "上述所有公式均嚴格處於繁密段落的環繞包夾之中，構成了典型的出版級圖文混排情境。",
        ]
        for line in p3_lines:
            draw.text((60, y_cursor), line, fill=(20, 20, 20))
            y_cursor += 30

        detections = [
            FormulaDetectionContract(
                box=(float(formula_1_x1), float(formula_1_y1), float(formula_1_x2), float(formula_1_y2)),
                score=0.96,
                category="inline",
                class_id=0,
            ),
            FormulaDetectionContract(
                box=(float(formula_2_x1), float(formula_2_y1), float(formula_2_x2), float(formula_2_y2)),
                score=0.98,
                category="isolated",
                class_id=1,
            ),
        ]
        return canvas, detections

    def test_cropper_preserves_short_formula_in_dense_surrounding_text(
        self, dense_document_page: Tuple[Image.Image, List[FormulaDetectionContract]]
    ):
        """Verifies that short formula f(x)=ax+bx is accurately padded and cropped without indexing errors."""
        canvas, detections = dense_document_page
        pad = 4
        cropper = FormulaCropper(pad=pad, batch_size=32)

        batches, items = cropper.crop_and_batch(canvas, detections)
        assert len(batches) == 1
        assert len(items) == 2

        # Check short formula item
        short_formula_det = detections[0]
        x1, y1, x2, y2 = short_formula_det.box
        expected_padded = (int(x1 - pad), int(y1 - pad), int(x2 + pad), int(y2 + pad))

        # Find the cropped item for index 0
        item_0 = next(it for it in items if it.original_index == 0)
        assert item_0.padded_box == expected_padded
        assert item_0.detection.category == "inline"
        assert item_0.aspect_ratio > 0.0

        # Verify crop image dimensions match padded box dimensions exactly
        crop_pairs = batches[0]
        crop_img_0 = next(pair[0] for pair in crop_pairs if pair[1].original_index == 0)
        exp_w = expected_padded[2] - expected_padded[0]
        exp_h = expected_padded[3] - expected_padded[1]
        assert crop_img_0.size == (exp_w, exp_h)
        assert crop_img_0.mode == "RGB"

        # Verify display formula item
        item_1 = next(it for it in items if it.original_index == 1)
        disp_det = detections[1]
        dx1, dy1, dx2, dy2 = disp_det.box
        assert item_1.padded_box == (int(dx1 - pad), int(dy1 - pad), int(dx2 + pad), int(dy2 + pad))


# =============================================================================
# 4. Stage 3 RecognitionPredictor Tests
# =============================================================================

class TestFormulaRecognizer:
    """Verifies blank/degenerate short-circuiting, predictor configuration, and batch recognition."""

    def test_is_blank_or_degenerate(self):
        # 1. Pure solid white
        white = Image.new("RGB", (200, 50), (255, 255, 255))
        assert is_blank_or_degenerate(white) is True

        # 2. Pure solid black
        black = Image.new("RGB", (200, 50), (0, 0, 0))
        assert is_blank_or_degenerate(black) is True

        # 3. Degenerate size (<2px)
        tiny_1x1 = Image.new("RGB", (1, 1), (255, 255, 255))
        assert is_blank_or_degenerate(tiny_1x1) is True

        # 4. Real stroke content
        stroke_img = Image.new("RGB", (200, 50), (255, 255, 255))
        d = ImageDraw.Draw(stroke_img)
        d.text((10, 10), "f(x) = ax + b", fill=(0, 0, 0))
        assert is_blank_or_degenerate(stroke_img) is False

    def test_recognition_predictor_initialization_cpu_fallback(self):
        # Verify CPU initialization works smoothly
        pred = RecognitionPredictor(device="cpu", lazy_load=True)
        assert pred.device == "cpu"
        assert pred.dtype == torch.float32
        assert pred.batch_size == 32
        assert pred.default_languages == ["_math", "zh"]

        # If invalid cuda device is specified when CUDA is unavailable, auto falls back to CPU
        if not torch.cuda.is_available():
            fallback_pred = RecognitionPredictor(device="cuda", lazy_load=True)
            assert fallback_pred.device == "cpu"

    def test_recognition_predictor_empty_crops(self):
        pred = RecognitionPredictor(device="cpu", lazy_load=True)
        assert pred.predict_crops([]) == []

    def test_recognition_predictor_blank_crop_short_circuit_with_index_preservation(self):
        """Verifies blank/degenerate crops receive ('', 0.0) without crashing or shifting indices."""
        pred = RecognitionPredictor(device="cpu", lazy_load=True)

        # Mock internal neural batch call to avoid loading heavy weights for this unit test
        pred._model = "mock_model"
        pred._processor = "mock_processor"

        # Create mixed inputs: [valid, blank, valid, tiny, valid]
        c0 = Image.new("RGB", (200, 40), (255, 255, 255))
        ImageDraw.Draw(c0).text((10, 10), "f(x)=ax+bx", fill=(0, 0, 0))
        c1 = Image.new("RGB", (100, 30), (255, 255, 255))  # Solid white
        c2 = Image.new("RGB", (200, 40), (255, 255, 255))
        ImageDraw.Draw(c2).text((10, 10), "y=kx+b", fill=(0, 0, 0))
        c3 = Image.new("RGB", (1, 1), (0, 0, 0))  # Degenerate
        c4 = Image.new("RGB", (200, 40), (255, 255, 255))
        ImageDraw.Draw(c4).text((10, 10), "E=mc^2", fill=(0, 0, 0))

        crops = [c0, c1, c2, c3, c4]

        # Patch surya batch_recognition
        import surya.recognition
        original_batch_rec = surya.recognition.batch_recognition

        def mock_batch_recognition(images, languages, model, processor, batch_size=None):
            assert len(images) == 3  # Only the 3 valid crops
            return ["f(x) = ax + bx", "y = kx + b", "E = mc^2"], [0.98, 0.95, 0.99]

        surya.recognition.batch_recognition = mock_batch_recognition
        try:
            results = pred.predict_crops(crops)
            assert len(results) == 5
            # Indices 0, 2, 4 must have predictions; 1, 3 must be ("", 0.0)
            assert results[0] == ("f(x) = ax + bx", 0.98)
            assert results[1] == ("", 0.0)
            assert results[2] == ("y = kx + b", 0.95)
            assert results[3] == ("", 0.0)
            assert results[4] == ("E = mc^2", 0.99)
        finally:
            surya.recognition.batch_recognition = original_batch_rec

    @pytest.mark.heavy
    def test_recognition_predictor_live_cuda_inference(self):
        """Runs genuine live SuryaOCR inference on CUDA if available."""
        if not torch.cuda.is_available():
            pytest.skip("CUDA not available for live GPU test.")

        predictor = RecognitionPredictor(device="cuda")
        img = Image.new("RGB", (250, 40), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((10, 10), "f(x) = ax + bx", fill=(0, 0, 0))

        results = predictor.predict_crops([img])
        assert len(results) == 1
        text, conf = results[0]
        assert "f" in text and "x" in text
        assert conf > 0.5
        assert predictor.vram_allocated_mb() > 0


# =============================================================================
# 5. Multi-Format Exporter Tests (Format 1, 2, 3)
# =============================================================================

class TestFormulaExporter:
    """Verifies LaTeX sanitization, MathML XML conversion & fallback, and 1600px PNG export."""

    def test_sanitize_latex_fences_and_delimiters(self):
        bt = chr(96) * 3
        # Markdown latex block with $$ delimiters
        s1 = f"{bt}latex\n$$ f(x) = ax^2 + bx + c $$\n{bt}"
        assert sanitize_latex(s1) == "f(x) = ax^2 + bx + c"

        # Math block with \[ \]
        s2 = f"{bt}math\n\\[ y = kx + b \\]\n{bt}"
        assert sanitize_latex(s2) == "y = kx + b"

        # Single backtick inline code
        s3 = "`a^2 + b^2 = c^2`"
        assert sanitize_latex(s3) == "a^2 + b^2 = c^2"

        # Single dollar delimiter
        s4 = "$ x + y = z $"
        assert sanitize_latex(s4) == "x + y = z"

    def test_sanitize_latex_whitespace_normalization(self):
        s = "x ^2  +  y _i   =  z"
        # Spaces around ^ and _ should be collapsed
        assert sanitize_latex(s) == "x^2 + y_i = z"

    def test_sanitize_latex_cjk_wrapping_and_protection(self):
        # Raw CJK wrapped in \text{}
        s1 = "$$ y = kx + b (其中 k 为斜率) $$"
        clean1 = sanitize_latex(s1)
        assert clean1 == r"y = kx + b (\text{其中} k \text{为斜率})"

        # Already protected CJK preserved without duplicate wrapping
        s2 = r"y = kx + b \text{ (常數)}"
        clean2 = sanitize_latex(s2)
        assert clean2 == r"y = kx + b \text{ (常數)}"

    def test_normalize_katex_fences(self):
        latex = "f(x) = ax + b"
        assert normalize_katex_fences(latex, "inline") == "$f(x) = ax + b$"
        assert normalize_katex_fences(latex, "isolated") == "$$\nf(x) = ax + b\n$$"
        assert normalize_katex_fences("", "inline") == ""

    def test_latex_to_mathml_valid_conversion(self):
        latex = "f(x) = ax^2 + bx + c"
        xml_str = latex_to_mathml(latex, display="inline")
        root = ET.fromstring(xml_str)
        assert root.tag.endswith("math")
        assert root.attrib.get("display") == "inline"

        # Display block mode
        xml_block = latex_to_mathml(r"\sum_{i=1}^n x_i", display="block")
        root_block = ET.fromstring(xml_block)
        assert root_block.attrib.get("display") == "block"

    def test_latex_to_mathml_syntax_error_fallback(self):
        # Malformed LaTeX syntax that crashes latex2mathml
        broken_latex = r"\frac{a}{"
        xml_fallback = latex_to_mathml(broken_latex, display="inline")
        root = ET.fromstring(xml_fallback)
        assert root.tag.endswith("math")

        # Must contain W3C <merror> and <annotation>
        merror = root.find(".//{http://www.w3.org/1998/Math/MathML}merror")
        assert merror is not None
        annotation = root.find(".//{http://www.w3.org/1998/Math/MathML}annotation")
        assert annotation is not None
        assert annotation.text == broken_latex

    def test_latex_to_mathml_empty_string(self):
        xml_empty = latex_to_mathml("", display="inline")
        root = ET.fromstring(xml_empty)
        assert root.tag.endswith("math")

    def test_export_highres_png_raster_lanczos(self):
        with tempfile.TemporaryDirectory() as td:
            out_file = Path(td) / "crop_raster.png"
            # Wide aspect ratio crop: 200 x 50
            crop = Image.new("RGB", (200, 50), (255, 255, 255))
            export_highres_png(out_file, crop, (10, 10, 210, 60), pdf_page=None, imgsz=1600)

            with Image.open(out_file) as saved:
                assert max(saved.size) == 1600
                assert saved.size[0] == 1600  # Wide dimension scaled to exactly 1600
                assert saved.size[1] == 400   # 50 * (1600 / 200) = 400

    def test_export_highres_png_vector_pymupdf_with_1px_rounding_guard(self):
        """Tests PyMuPDF vector rendering and verifies the 1-pixel rounding guard."""
        with tempfile.TemporaryDirectory() as td:
            # Create a synthetic single-page PDF with fitz
            doc = fitz.open()
            page = doc.new_page(width=800, height=1000)
            page.draw_rect(fitz.Rect(50, 100, 300, 180), color=(0, 0, 0))

            out_file = Path(td) / "crop_vector.png"
            padded_box = (46, 96, 304, 184)  # 258 x 88 px
            crop_dummy = Image.new("RGB", (258, 88), (255, 255, 255))

            export_highres_png(out_file, crop_dummy, padded_box, pdf_page=page, imgsz=1600)
            doc.close()

            with Image.open(out_file) as saved:
                # The 1-pixel rounding guard strictly guarantees max(dim) == 1600
                assert max(saved.size) == 1600

    def test_export_formula_result_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            det = FormulaDetectionContract(
                box=(20.0, 30.0, 180.0, 80.0),
                score=0.94,
                category="inline",
                class_id=0,
            )
            item = FormulaCroppedItemContract(
                item_id="formula_0000",
                original_index=0,
                detection=det,
                padded_box=(16, 26, 184, 84),
                aspect_ratio=2.8966,
            )
            crop = Image.new("RGB", (168, 58), (255, 255, 255))
            latex_raw = "```latex\n$$ f(x) = ax + bx $$\n```"

            res = export_formula_result(
                crop=crop,
                item=item,
                latex_raw=latex_raw,
                output_dir=out_dir,
                pdf_page=None,
                imgsz=1600,
                confidence=0.96,
                page_idx=0,
            )

            assert isinstance(res, FormulaResultContract)
            assert res.latex == "f(x) = ax + bx"
            assert "<math" in res.mathml
            assert Path(res.image_path).exists()
            with Image.open(res.image_path) as im:
                assert max(im.size) == 1600

            # Test batch export with JSON manifest
            results = export_formula_results(
                crops=[crop],
                items=[item],
                raw_predictions=[(latex_raw, 0.96)],
                output_dir=out_dir,
                pdf_page=None,
                imgsz=1600,
                save_manifest=True,
            )
            assert len(results) == 1
            manifest_file = out_dir / "formulas.json"
            assert manifest_file.exists()
            with open(manifest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) == 1
            assert data[0]["item_id"] == "formula_0000"
            assert data[0]["latex"] == "f(x) = ax + bx"


# =============================================================================
# 6. End-to-End Milestone 2 Pipeline Integration Test
# =============================================================================

class TestEndToEndM2PipelineIntegration:
    """Ties together Stage 2 Cropping, Stage 3 Recognition, and Multi-Format Export."""

    @pytest.mark.heavy
    def test_full_m2_pipeline_dense_text_document(self):
        # 1. Create dense document page
        page_w, page_h = 1000, 1400
        canvas = Image.new("RGB", (page_w, page_h), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        # Dense text surrounding
        draw.text((50, 50), "段落一：考慮凸優化問題中的目標函數，以下為短公式：", fill=(0, 0, 0))
        draw.text((50, 100), "f(x) = ax + bx", fill=(0, 0, 0))
        draw.text((250, 100), " 其中係數滿足正定性條件。", fill=(0, 0, 0))
        draw.text((50, 150), "段落二：進一步計算二次型的定積分表示：", fill=(0, 0, 0))
        draw.text((150, 220), "int_0^1 x^2 dx = 1/3", fill=(0, 0, 0))
        draw.text((50, 300), "段落三：由上述計算結果可完成整個收斂性證明。", fill=(0, 0, 0))

        detections = [
            FormulaDetectionContract(
                box=(45.0, 95.0, 230.0, 125.0),
                score=0.95,
                category="inline",
                class_id=0,
            ),
            FormulaDetectionContract(
                box=(140.0, 210.0, 360.0, 250.0),
                score=0.92,
                category="isolated",
                class_id=1,
            ),
        ]

        # 2. Stage 2 Cropping & Batching
        cropper = FormulaCropper(pad=4, batch_size=32)
        batches, sorted_items = cropper.crop_and_batch(canvas, detections)
        assert len(batches) == 1
        assert len(sorted_items) == 2

        # 3. Stage 3 Recognition
        # Uses genuine RecognitionPredictor (CUDA or CPU fallback)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        predictor = RecognitionPredictor(device=device)

        crops = [pair[0] for pair in batches[0]]
        items = [pair[1] for pair in batches[0]]
        predictions = predictor.predict_crops(crops)
        assert len(predictions) == 2

        # 4. Multi-Format Export
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            results = export_formula_results(
                crops=crops,
                items=items,
                raw_predictions=predictions,
                output_dir=out_dir,
                imgsz=1600,
                save_manifest=True,
            )

            # Restore original document reading order
            ordered_results = restore_document_order(results)
            assert len(ordered_results) == 2
            assert ordered_results[0].original_index == 0
            assert ordered_results[1].original_index == 1

            # Format 1 LaTeX verification
            assert isinstance(ordered_results[0].latex, str)
            # Format 2 MathML verification
            ET.fromstring(ordered_results[0].mathml)
            ET.fromstring(ordered_results[1].mathml)
            # Format 3 PNG image verification
            p0 = Path(ordered_results[0].image_path)
            p1 = Path(ordered_results[1].image_path)
            assert p0.exists()
            assert p1.exists()
            with Image.open(p0) as im0:
                assert max(im0.size) == 1600
            with Image.open(p1) as im1:
                assert max(im1.size) == 1600
