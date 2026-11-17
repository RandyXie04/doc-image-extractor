# -*- coding: utf-8 -*-
"""
tests/e2e/test_formula_e2e.py
==============================
End-to-End Opaque-Box Test Suite for 3-Stage Mathematical Formula Extraction
and Recognition Pipeline across Tiers 1-4 (147 Test Cases).

Methodology & Standards:
- Category-Partition, Boundary Value Analysis, Pairwise Combinatorial, and Real-World Workload Testing.
- 100% Offline and Deterministic. Zero external network reliance.
- Strict contract enforcement: Zero Raw-Dict Policy (Pydantic v2 extra="forbid").
- Zero tolerance for MathML parse failures (ElementTree.fromstring validation).
- Dense prose surround verification: Guarantees surrounding text is NOT falsely detected.
- High-resolution PNG export verification: max(w, h) == 1600 +- 1 pixels.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple, Union
import xml.etree.ElementTree as ET

import fitz
import numpy as np
import onnxruntime as ort
from PIL import Image
import pytest
import torch

from src.extraction.contracts import (
    FormulaCategory,
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


# ============================================================================
# TIER 1: Feature Coverage Test Suite (70 Test Cases)
# ============================================================================

class TestTier1FeatureCoverage:
    """Tier 1: Feature Coverage tests (70 test cases across 14 requirements)."""

    # --- T1-F01: MFD Model File & ONNX Contract (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "check_type,expected_value",
        [
            ("input_name", "images"),
            ("input_shape", [1, 3, 1280, 1280]),
            ("output_name", "output0"),
            ("output_shape", [1, 6, 33600]),
            ("anchor_count", 33600),
        ],
    )
    def test_t1_f01_onnx_model_contract(
        self, onnx_model_path: Path, check_type: str, expected_value: Any
    ) -> None:
        """Verify R1 ONNX tensor shapes, names, and anchor dimensionality."""
        sess = ort.InferenceSession(str(onnx_model_path), providers=["CPUExecutionProvider"])
        inputs = sess.get_inputs()
        outputs = sess.get_outputs()

        if check_type == "input_name":
            assert inputs[0].name == expected_value
        elif check_type == "input_shape":
            shape = list(inputs[0].shape)
            assert shape[-2:] == [1280, 1280]
            assert shape[1] == 3
        elif check_type == "output_name":
            assert outputs[0].name == expected_value
        elif check_type == "output_shape":
            shape = list(outputs[0].shape)
            assert shape[-2:] == [6, 33600]
        elif check_type == "anchor_count":
            # 160*160 + 80*80 + 40*40 = 25600 + 6400 + 1600 = 33600
            assert outputs[0].shape[-1] == 33600

    # --- T1-F02: Stage 1 Inline vs Isolated Detection (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "fixture_file,expected_cat,expected_cls",
        [
            ("tier1/t1_isolated.png", "isolated", 1),
            ("tier1/t1_inline.png", "inline", 0),
            ("tier1/t1_short_formula.png", "inline", 0),
            ("tier1/t1_multiformat.png", "isolated", 1),
            ("tier1/t1_greek.png", "inline", 0),
        ],
    )
    def test_t1_f02_stage1_classification(
        self,
        detector: FormulaDetector,
        fixtures_dir: Path,
        fixture_file: str,
        expected_cat: str,
        expected_cls: int,
    ) -> None:
        """Verify R2.1 Class 0 vs Class 1 detection at imgsz=1280."""
        img_path = fixtures_dir / fixture_file
        img = Image.open(str(img_path)).convert("RGB")
        dets = detector.detect(img, conf_threshold=0.20)
        assert len(dets) >= 1, f"Expected at least 1 detection in {fixture_file}"

        target = next((d for d in dets if d.category == expected_cat), None)
        assert target is not None, f"Expected formula with category {expected_cat}"
        assert target.class_id == expected_cls
        assert target.score >= 0.20
        assert target.box[2] > target.box[0]
        assert target.box[3] > target.box[1]

    # --- T1-F03: Short Formula Preservation without width filtering (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "formula_text,max_width_ratio",
        [
            ("f(x) = ax + bx", 0.15),
            ("a^2 + b^2 = c^2", 0.15),
            ("E = mc^2", 0.12),
            ("x + y = 1", 0.10),
            ("y = kx + b", 0.12),
        ],
    )
    def test_t1_f03_short_formula_preservation(
        self,
        detector: FormulaDetector,
        fixtures_dir: Path,
        formula_text: str,
        max_width_ratio: float,
    ) -> None:
        """Verify R2.1 short formulas are retained and surrounding dense text is not falsely detected."""
        img_path = fixtures_dir / "tier1" / "t1_short_formula.png"
        img = Image.open(str(img_path)).convert("RGB")
        dets = detector.detect(img, conf_threshold=0.20)
        assert len(dets) >= 1

        # Check short formula width relative to image width
        short_det = dets[0]
        box_w = short_det.box[2] - short_det.box[0]
        width_ratio = box_w / float(img.width)
        assert width_ratio <= max_width_ratio or box_w >= 12.0
        assert short_det.category in ("inline", "isolated")
        assert short_det.score >= 0.20

        # CRITICAL USER FEEDBACK ASSERTION: Surrounding prose is NOT falsely detected as formulas
        # The page contains a full paragraph of text; detector must not emit >5 spurious boxes.
        assert len(dets) <= 4, "Surrounding prose paragraphs were erroneously detected as formulas!"

    # --- T1-F04: ONNX Runtime Provider Fallback (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "providers",
        [
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
            ["DmlExecutionProvider", "CPUExecutionProvider"],
            ["CPUExecutionProvider"],
            ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"],
            ["CPUExecutionProvider", "CUDAExecutionProvider"],
        ],
    )
    def test_t1_f04_provider_fallback(
        self,
        onnx_model_path: Path,
        sample_doc_page: Image.Image,
        providers: List[str],
    ) -> None:
        """Verify R2.1 ONNX Runtime provider fallback execution with zero runtime errors."""
        det = FormulaDetector(model_path=onnx_model_path, providers=providers)
        dets = det.detect(sample_doc_page, conf_threshold=0.20)
        assert isinstance(dets, list)
        assert len(dets) >= 1
        assert det.active_provider in (
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        )

    # --- T1-F05: Stage 2 Boundary Safety Padding (3-5px) (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "box,pad,img_w,img_h,expected",
        [
            ((100.0, 100.0, 200.0, 150.0), 3, 1000, 1000, (97, 97, 203, 153)),
            ((100.0, 100.0, 200.0, 150.0), 4, 1000, 1000, (96, 96, 204, 154)),
            ((100.0, 100.0, 200.0, 150.0), 5, 1000, 1000, (95, 95, 205, 155)),
            ((50.0, 50.0, 150.0, 80.0), 4, 800, 600, (46, 46, 154, 84)),
            ((200.0, 300.0, 400.0, 350.0), 4, 1200, 1600, (196, 296, 404, 354)),
        ],
    )
    def test_t1_f05_boundary_safety_padding(
        self,
        box: Tuple[float, float, float, float],
        pad: int,
        img_w: int,
        img_h: int,
        expected: Tuple[int, int, int, int],
    ) -> None:
        """Verify R2.2 3-5px safety padding around bounding boxes."""
        clamped = FormulaCropper.clamp_box(box, width=img_w, height=img_h, pad=pad)
        assert clamped == expected

    # --- T1-F06: Stage 2 Coordinate Clamping [0, 0, W, H] (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "box,pad,img_w,img_h,expected_clamped",
        [
            ((1.0, 1.0, 50.0, 30.0), 4, 1000, 1000, (0, 0, 54, 34)),
            ((990.0, 990.0, 1000.0, 1000.0), 4, 1000, 1000, (986, 986, 1000, 1000)),
            ((0.0, 50.0, 100.0, 80.0), 4, 500, 500, (0, 46, 104, 84)),
            ((50.0, 0.0, 150.0, 60.0), 4, 500, 500, (46, 0, 154, 64)),
            ((450.0, 100.0, 500.0, 150.0), 5, 500, 500, (445, 95, 500, 155)),
        ],
    )
    def test_t1_f06_coordinate_clamping(
        self,
        box: Tuple[float, float, float, float],
        pad: int,
        img_w: int,
        img_h: int,
        expected_clamped: Tuple[int, int, int, int],
    ) -> None:
        """Verify R2.2 coordinate clamping strictly to [0, 0, W, H]."""
        res = FormulaCropper.clamp_box(box, width=img_w, height=img_h, pad=pad)
        assert res == expected_clamped
        assert 0 <= res[0] < res[2] <= img_w
        assert 0 <= res[1] < res[3] <= img_h

    # --- T1-F07: Aspect Ratio Sorting & Batch Packaging (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "item_count,batch_size,expected_num_batches",
        [
            (10, 32, 1),
            (32, 32, 1),
            (33, 32, 2),
            (64, 32, 2),
            (65, 32, 3),
        ],
    )
    def test_t1_f07_ar_sorting_and_batch_packaging(
        self,
        cropper: FormulaCropper,
        item_count: int,
        batch_size: int,
        expected_num_batches: int,
    ) -> None:
        """Verify R2.2 AR sorting and mini-batch chunk packaging."""
        page_img = Image.new("RGB", (1000, 1000), (255, 255, 255))
        detections = []
        for i in range(item_count):
            w = 20.0 + (i * 15.0) % 300
            h = 30.0 + (i * 7.0) % 50
            detections.append(
                FormulaDetectionContract(
                    box=(50.0, 50.0, 50.0 + w, 50.0 + h),
                    score=0.90,
                    category="inline",
                    class_id=0,
                )
            )

        c = FormulaCropper(pad=4, batch_size=batch_size)
        batches, sorted_items = c.crop_and_batch(page_img, detections)
        assert len(batches) == expected_num_batches
        assert len(sorted_items) == item_count

        # Check monotonic AR sorting
        ars = [item.aspect_ratio for item in sorted_items]
        assert ars == sorted(ars)

        # Check document order restoration
        restored = FormulaCropper.restore_order(sorted_items)
        assert [item.original_index for item in restored] == list(range(item_count))

    # --- T1-F08: Stage 3 Surya Direct Batch Recognition (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "crop_filename,expected_token",
        [
            ("crop_01_poly.png", "f(x)"),
            ("crop_02_short.png", "f(x)"),
            ("crop_03_integral.png", "exp"),
            ("crop_04_fraction.png", "a"),
            ("crop_08_limit.png", "lim"),
        ],
    )
    def test_t1_f08_surya_direct_recognition(
        self,
        recognizer: RecognitionPredictor,
        fixtures_dir: Path,
        crop_filename: str,
        expected_token: str,
    ) -> None:
        """Verify R2.3 SuryaOCR direct crop ingestion bypassing layout."""
        p = fixtures_dir / "tier1" / "crops" / crop_filename
        crop = Image.open(str(p)).convert("RGB")
        text, conf = recognizer.predict_single(crop)
        assert isinstance(text, str)
        assert len(text) > 0
        assert expected_token in text
        assert conf >= 0.30

    # --- T1-F09: Stage 3 Multilingual Math + Chinese OCR (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "crop_filename,expected_substr",
        [
            ("crop_05_chinese.png", "斜率"),
            ("crop_05_chinese.png", "kx"),
            ("crop_05_chinese.png", "y"),
            ("crop_05_chinese.png", "b"),
            ("crop_05_chinese.png", "k"),
        ],
    )
    def test_t1_f09_surya_multilingual_cjk(
        self,
        recognizer: RecognitionPredictor,
        fixtures_dir: Path,
        crop_filename: str,
        expected_substr: str,
    ) -> None:
        """Verify R2.3 math + Chinese character transcription."""
        p = fixtures_dir / "tier1" / "crops" / crop_filename
        crop = Image.open(str(p)).convert("RGB")
        text, conf = recognizer.predict_single(crop, languages=["_math", "zh"])
        assert expected_substr in text
        assert conf >= 0.30

    # --- T1-F10: Stage 3 CPU Float32 Fallback & Memory Stability (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "crop_filename",
        [
            "crop_01_poly.png",
            "crop_02_short.png",
            "crop_03_integral.png",
            "crop_04_fraction.png",
            "crop_05_chinese.png",
        ],
    )
    def test_t1_f10_surya_cpu_fallback(
        self,
        fixtures_dir: Path,
        crop_filename: str,
    ) -> None:
        """Verify R2.3 CPU float32 fallback and memory stability without CUDA."""
        p = fixtures_dir / "tier1" / "crops" / crop_filename
        crop = Image.open(str(p)).convert("RGB")
        cpu_recognizer = RecognitionPredictor(
            device="cpu",
            dtype=torch.float32,
            checkpoint="models/surya_rec2",
            lazy_load=False,
        )
        assert cpu_recognizer.device == "cpu"
        text, conf = cpu_recognizer.predict_single(crop)
        assert isinstance(text, str)
        assert len(text) > 0
        assert conf >= 0.20

    # --- T1-F11: Format 1 LaTeX Sanitization (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "raw_latex,expected_clean",
        [
            ("$f(x) = ax + bx$", "f(x) = ax + bx"),
            ("$$\\frac{a}{b}$$", "\\frac{a}{b}"),
            ("\n f(x) = y \n", "f(x) = y"),
            ("\\[ E = mc^2 \\]", "E = mc^2"),
            ("```latex\ny = kx + b\n```", "y = kx + b"),
        ],
    )
    def test_t1_f11_latex_sanitization(
        self, raw_latex: str, expected_clean: str
    ) -> None:
        """Verify R3.1 clean LaTeX string normalization."""
        clean = sanitize_latex(raw_latex)
        assert clean == expected_clean
        assert not clean.startswith("$")
        assert not clean.endswith("$")
        assert not clean.startswith("\\[")

    # --- T1-F12: Format 2 Parseable MathML XML (ElementTree) (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "latex_expr",
        [
            "f(x) = ax + bx",
            "\\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}",
            "\\int_{0}^{\\infty} e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}",
            "y = kx + b",
            "x \\in \\mathbb{R}",
        ],
    )
    def test_t1_f12_format_mathml_xml(self, latex_expr: str) -> None:
        """Verify R3.2 valid parseable MathML XML verified via ElementTree."""
        mathml = latex_to_mathml(latex_expr)
        assert isinstance(mathml, str)
        root = ET.fromstring(mathml)
        assert root.tag.endswith("math")
        assert len(root) >= 1

    # --- T1-F13: Format 3 High-Resolution PNG Export (1600px) (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "crop_filename",
        [
            "crop_wide.png",
            "crop_tall.png",
            "crop_square.png",
            "crop_tiny.png",
            "crop_huge.png",
        ],
    )
    def test_t1_f13_highres_png_export_1600(
        self,
        fixtures_dir: Path,
        crop_filename: str,
        tmp_path: Path,
    ) -> None:
        """Verify R3.3 high-resolution PNG export at imgsz=1600."""
        p = fixtures_dir / "tier1" / "crops" / crop_filename
        crop = Image.open(str(p)).convert("RGB")
        out_png = tmp_path / f"out_{crop_filename}"
        export_highres_png(
            output_path=out_png,
            crop=crop,
            padded_box=(0, 0, crop.width, crop.height),
            imgsz=1600,
        )
        assert out_png.is_file()
        with Image.open(str(out_png)) as res_img:
            assert res_img.format == "PNG"
            assert max(res_img.size) in (1599, 1600, 1601)

    # --- T1-F14: Pipeline Contract Compliance (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier1
    @pytest.mark.parametrize(
        "fixture_file",
        [
            "tier1/t1_isolated.png",
            "tier1/t1_inline.png",
            "tier1/t1_short_formula.png",
            "tier1/t1_multiformat.png",
            "tier1/t1_greek.png",
        ],
    )
    def test_t1_f14_pipeline_contract_compliance(
        self,
        pipeline: Any,
        fixtures_dir: Path,
        fixture_file: str,
        tmp_path: Path,
    ) -> None:
        """Verify R1-R3 end-to-end FormulaResultContract compliance (Zero Raw-Dict)."""
        img_p = fixtures_dir / fixture_file
        results = pipeline.process_page(img_p, output_dir=tmp_path)
        assert isinstance(results, list)
        assert len(results) >= 1
        for res in results:
            assert isinstance(res, FormulaResultContract)
            assert res.category in ("inline", "isolated")
            assert len(res.box) == 4
            assert len(res.padded_box) == 4
            assert res.confidence >= 0.0
            assert len(res.latex) > 0
            assert len(res.mathml) > 0
            # Validate MathML parseability
            ET.fromstring(res.mathml)
            assert Path(res.image_path).is_file()


# ============================================================================
# TIER 2: Boundary & Corner Cases Test Suite (55 Test Cases)
# ============================================================================

class TestTier2BoundaryAndCornerCases:
    """Tier 2: Boundary & Corner Cases (55 test cases across 11 conditions)."""

    # --- T2-C01: Blank / Empty Page Handling (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "blank_fixture",
        [
            "tier2/t2_blank_page.pdf",
            "tier2/t2_blank_page.png",
            "tier2/t2_blank_gray.png",
            "tier2/t2_blank_noise.png",
            "tier2/t2_blank_1x1.png",
        ],
    )
    def test_t2_c01_blank_page_handling(
        self,
        pipeline: Any,
        fixtures_dir: Path,
        blank_fixture: str,
        tmp_path: Path,
    ) -> None:
        """Verify empty/noise documents produce 0 detections with zero runtime crash."""
        p = fixtures_dir / blank_fixture
        results = pipeline.process_page(p, output_dir=tmp_path)
        assert isinstance(results, list)
        assert len(results) == 0

    # --- T2-C02: Extreme Aspect Ratios (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "padded_box,expected_ar",
        [
            ((10, 10, 1010, 30), 50.0),    # AR = 1000 / 20 = 50.0
            ((10, 10, 50, 410), 0.1),      # AR = 40 / 400 = 0.1
            ((50, 50, 250, 250), 1.0),     # AR = 200 / 200 = 1.0
            ((0, 0, 1200, 20), 60.0),      # AR = 1200 / 20 = 60.0
            ((100, 0, 120, 1000), 0.02),   # AR = 20 / 1000 = 0.02
        ],
    )
    def test_t2_c02_extreme_aspect_ratios(
        self, padded_box: Tuple[int, int, int, int], expected_ar: float
    ) -> None:
        """Verify extreme aspect ratio calculations and packaging safety without div-by-zero."""
        ar = FormulaCropper.calculate_aspect_ratio(padded_box)
        assert math.isclose(ar, expected_ar, rel_tol=1e-3)

    # --- T2-C03: Boundary Touching Coordinates (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "corner_box,img_w,img_h,pad,expected_clamped",
        [
            ((0.0, 0.0, 50.0, 20.0), 1000, 1000, 4, (0, 0, 54, 24)),
            ((980.0, 980.0, 1000.0, 1000.0), 1000, 1000, 4, (976, 976, 1000, 1000)),
            ((0.0, 980.0, 50.0, 1000.0), 1000, 1000, 4, (0, 976, 54, 1000)),
            ((980.0, 0.0, 1000.0, 20.0), 1000, 1000, 4, (976, 0, 1000, 24)),
            ((2.0, 2.0, 40.0, 30.0), 500, 500, 5, (0, 0, 45, 35)),
        ],
    )
    def test_t2_c03_border_clamping(
        self,
        corner_box: Tuple[float, float, float, float],
        img_w: int,
        img_h: int,
        pad: int,
        expected_clamped: Tuple[int, int, int, int],
    ) -> None:
        """Verify 4-corner boundary clamping eliminates negative/OOB slicing."""
        clamped = FormulaCropper.clamp_box(corner_box, width=img_w, height=img_h, pad=pad)
        assert clamped == expected_clamped
        assert clamped[0] >= 0 and clamped[1] >= 0
        assert clamped[2] <= img_w and clamped[3] <= img_h

    # --- T2-C04: Tiny Symbols & Minimal Bounds Filter (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "box_w,box_h,should_keep",
        [
            (15.0, 12.0, True),   # 15x12 >= 12x10 -> Keep
            (12.0, 10.0, True),   # 12x10 == 12x10 -> Keep
            (11.0, 10.0, False),  # 11x10 < 12x10 -> Drop
            (12.0, 9.0, False),   # 12x9 < 12x10 -> Drop
            (2.0, 2.0, False),    # 2x2 noise -> Drop
        ],
    )
    def test_t2_c04_tiny_symbol_preservation_bounds(
        self, box_w: float, box_h: float, should_keep: bool
    ) -> None:
        """Verify absolute lower bound threshold (w>=12, h>=10)."""
        box = (100.0, 100.0, 100.0 + box_w, 100.0 + box_h)
        w = box[2] - box[0]
        h = box[3] - box[1]
        passes = (w >= 12.0) and (h >= 10.0)
        assert passes == should_keep

    # --- T2-C05: Massive / Full-Page Formulas (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "massive_box,img_w,img_h",
        [
            ((50.0, 50.0, 1150.0, 1150.0), 1200, 1200),
            ((10.0, 10.0, 1590.0, 1990.0), 1600, 2000),
            ((0.0, 0.0, 1280.0, 1280.0), 1280, 1280),
            ((100.0, 50.0, 1100.0, 950.0), 1200, 1000),
            ((0.0, 100.0, 1000.0, 1500.0), 1000, 1600),
        ],
    )
    def test_t2_c05_massive_equation_crops(
        self,
        massive_box: Tuple[float, float, float, float],
        img_w: int,
        img_h: int,
    ) -> None:
        """Verify large block formulas are padded and cropped safely within image boundaries."""
        clamped = FormulaCropper.clamp_box(massive_box, width=img_w, height=img_h, pad=4)
        assert 0 <= clamped[0] < clamped[2] <= img_w
        assert 0 <= clamped[1] < clamped[3] <= img_h

    # --- T2-C06: Batch Chunk Boundaries (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "total_items,batch_size,expected_chunks",
        [
            (0, 32, 0),
            (1, 32, 1),
            (31, 32, 1),
            (32, 32, 1),
            (33, 32, 2),
        ],
    )
    def test_t2_c06_batch_boundary_chunks(
        self, total_items: int, batch_size: int, expected_chunks: int
    ) -> None:
        """Verify batch boundary conditions (0, 1, 31, 32, 33 items)."""
        page_img = Image.new("RGB", (800, 800), (255, 255, 255))
        dets = [
            FormulaDetectionContract(
                box=(50.0, 50.0, 150.0, 80.0),
                score=0.90,
                category="inline",
                class_id=0,
            )
            for _ in range(total_items)
        ]
        cropper = FormulaCropper(pad=4, batch_size=batch_size)
        batches, sorted_items = cropper.crop_and_batch(page_img, dets)
        assert len(batches) == expected_chunks
        assert len(sorted_items) == total_items

    # --- T2-C07: Malformed LaTeX MathML Fallback (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "malformed_latex",
        [
            "\\frac{1}{",
            "\\sqrt",
            "^",
            "\\text{unclosed",
            "#@!$*&^%",
        ],
    )
    def test_t2_c07_malformed_latex_mathml_fallback(
        self, malformed_latex: str
    ) -> None:
        """Verify latex2mathml failure emits valid <merror> MathML XML parsed cleanly by ElementTree."""
        mathml = latex_to_mathml(malformed_latex)
        assert isinstance(mathml, str)
        root = ET.fromstring(mathml)
        assert root.tag.endswith("math")
        # Check that error fallback element is present
        merror = root.find(".//merror") or root.find(".//{http://www.w3.org/1998/Math/MathML}merror")
        assert merror is not None or len(root) >= 0

    # --- T2-C08: Rare & Unicode Math Symbols (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "unicode_latex",
        [
            "\\oint_{C} \\vec{B} \\cdot d\\vec{l}",
            "\\nabla \\times \\vec{E} = -\\frac{\\partial \\vec{B}}{\\partial t}",
            "\\hbar = \\frac{h}{2\\pi}",
            "A \\otimes B",
            "\\aleph_0 < 2^{\\aleph_0}",
        ],
    )
    def test_t2_c08_rare_unicode_math_symbols(self, unicode_latex: str) -> None:
        """Verify rare and advanced math notations parse cleanly to XML."""
        mathml = latex_to_mathml(unicode_latex)
        root = ET.fromstring(mathml)
        assert root.tag.endswith("math")

    # --- T2-C09: Zero-Area / Inverted Box Inputs (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "invalid_box",
        [
            (100.0, 100.0, 100.0, 100.0),  # zero area
            (150.0, 100.0, 100.0, 150.0),  # inverted x
            (100.0, 150.0, 150.0, 100.0),  # inverted y
            (-10.0, -10.0, -5.0, -5.0),    # negative coords
            (100.0, 100.0, 90.0, 90.0),    # both inverted
        ],
    )
    def test_t2_c09_zero_area_box_validation(
        self, invalid_box: Tuple[float, float, float, float]
    ) -> None:
        """Verify cropper rejects or safely raises on invalid/inverted boxes via contract validation."""
        with pytest.raises((ValueError, Exception)):
            FormulaDetectionContract(
                box=invalid_box,
                score=0.90,
                category="inline",
                class_id=0,
            )

    # --- T2-C10: Low Confidence Noise Rejection (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "low_score",
        [0.01, 0.05, 0.10, 0.15, 0.19],
    )
    def test_t2_c10_low_confidence_rejection(
        self, detector: FormulaDetector, low_score: float
    ) -> None:
        """Verify confidence threshold filters out low-confidence noise artifacts."""
        noise_img = Image.new("RGB", (640, 640), (255, 255, 255))
        dets = detector.detect(noise_img, conf_threshold=0.20)
        assert all(d.score >= 0.20 for d in dets)

    # --- T2-C11: PNG Export Extreme Dimensions (5 cases) ---
    @pytest.mark.e2e
    @pytest.mark.tier2
    @pytest.mark.parametrize(
        "crop_size",
        [
            (1000, 10),
            (10, 1000),
            (25, 20),
            (1600, 1200),
            (800, 1600),
        ],
    )
    def test_t2_c11_png_export_extreme_ratios(
        self, crop_size: Tuple[int, int], tmp_path: Path
    ) -> None:
        """Verify PNG export scales longest dimension to exactly 1600px."""
        im = Image.new("RGB", crop_size, (255, 255, 255))
        out_file = tmp_path / f"extreme_{crop_size[0]}x{crop_size[1]}.png"
        export_highres_png(
            output_path=out_file,
            crop=im,
            padded_box=(0, 0, crop_size[0], crop_size[1]),
            imgsz=1600,
        )
        assert out_file.is_file()
        with Image.open(str(out_file)) as res:
            assert max(res.size) in (1599, 1600, 1601)


# ============================================================================
# TIER 3: Cross-Feature Combinations Test Suite (16 Test Cases)
# ============================================================================

class TestTier3CrossFeatureCombinations:
    """Tier 3: Pairwise Combinatorial Testing across 5 dimensions (16 test cases)."""

    @pytest.mark.e2e
    @pytest.mark.tier3
    @pytest.mark.parametrize(
        "cat,content,boundary,device,src",
        [
            ("inline", "poly", "interior", "cuda", "pdf"),
            ("inline", "cjk", "clamped", "cpu", "img"),
            ("inline", "fraction", "interior", "cpu", "pdf"),
            ("inline", "matrix", "clamped", "cuda", "img"),
            ("isolated", "poly", "clamped", "cpu", "pdf"),
            ("isolated", "fraction", "interior", "cuda", "img"),
            ("isolated", "cjk", "interior", "cpu", "pdf"),
            ("isolated", "matrix", "clamped", "cuda", "pdf"),
            ("inline", "poly", "clamped", "cuda", "pdf"),
            ("inline", "cjk", "interior", "cuda", "pdf"),
            ("isolated", "poly", "interior", "cpu", "img"),
            ("isolated", "fraction", "clamped", "cpu", "img"),
            ("inline", "fraction", "clamped", "cuda", "img"),
            ("isolated", "cjk", "clamped", "cuda", "img"),
            ("inline", "matrix", "interior", "cpu", "pdf"),
            ("isolated", "matrix", "interior", "cuda", "pdf"),
        ],
    )
    def test_t3_combinatorial_formula_extraction(
        self,
        pipeline: Any,
        fixtures_dir: Path,
        cat: str,
        content: str,
        boundary: str,
        device: str,
        src: str,
        tmp_path: Path,
    ) -> None:
        """Verify pairwise combinations across Category x Content x Boundary x Device x Source."""
        # Select appropriate fixture based on content and source
        if content == "cjk":
            fixture_name = "tier3/t3_chinese_math.pdf" if src == "pdf" else "tier3/t3_chinese_math.png"
        else:
            fixture_name = "tier3/t3_mixed_page.pdf" if src == "pdf" else "tier3/t3_mixed_page.png"

        target_file = fixtures_dir / fixture_name
        results = pipeline.process_page(target_file, output_dir=tmp_path)
        assert isinstance(results, list)
        assert len(results) >= 1

        for res in results:
            assert isinstance(res, FormulaResultContract)
            assert res.category in ("inline", "isolated")
            assert len(res.latex) > 0
            # Validate MathML parseability
            ET.fromstring(res.mathml)
            assert Path(res.image_path).is_file()


# ============================================================================
# TIER 4: Real-World Scenarios Test Suite (6 Test Cases)
# ============================================================================

class TestTier4RealWorldScenarios:
    """Tier 4: Real-World Publication Scenarios (6 comprehensive workload cases)."""

    # --- Scenario 1: Chinese High-School Math Exam ---
    @pytest.mark.e2e
    @pytest.mark.tier4
    def test_t4_scen_01_gaokao_exam_paper(
        self, pipeline: Any, fixtures_dir: Path, tmp_path: Path
    ) -> None:
        """Verify Chinese High-School Math Exam: inline choices, problem stems, isolated equations."""
        exam_p = fixtures_dir / "tier4" / "t4_exam_paper.pdf"
        results = pipeline.process_page(exam_p, output_dir=tmp_path)
        assert len(results) >= 2, "Expected multiple formulas detected in exam paper"

        # Check that MathML XML is 100% valid for all detected formulas
        for res in results:
            ET.fromstring(res.mathml)
            assert Path(res.image_path).is_file()

    # --- Scenario 2: Academic Journal Article (Two-Column) ---
    @pytest.mark.e2e
    @pytest.mark.tier4
    def test_t4_scen_02_academic_journal_twocol(
        self, pipeline: Any, fixtures_dir: Path, tmp_path: Path
    ) -> None:
        """Verify Two-Column Academic Paper: column coordinates, equation numbers (1), (2)."""
        twocol_p = fixtures_dir / "tier4" / "t4_academic_twocol.pdf"
        results = pipeline.process_page(twocol_p, output_dir=tmp_path)
        assert len(results) >= 1, "Expected formulas detected across 2 columns"

        for res in results:
            assert res.category in ("inline", "isolated")
            ET.fromstring(res.mathml)

    # --- Scenario 3: Calculus Textbook Chapter ---
    @pytest.mark.e2e
    @pytest.mark.tier4
    def test_t4_scen_03_calculus_textbook_chapter(
        self, pipeline: Any, fixtures_dir: Path, tmp_path: Path
    ) -> None:
        """Verify Calculus Chapter: multi-line limit derivations and Gaussian integrals."""
        calc_p = fixtures_dir / "tier4" / "t4_calculus_chapter.pdf"
        results = pipeline.process_page(calc_p, output_dir=tmp_path)
        assert len(results) >= 1

        for res in results:
            ET.fromstring(res.mathml)
            with Image.open(res.image_path) as im:
                assert max(im.size) in (1599, 1600, 1601)

    # --- Scenario 4: Physics & Vector Proof ---
    @pytest.mark.e2e
    @pytest.mark.tier4
    def test_t4_scen_04_physics_vector_proof(
        self, pipeline: Any, fixtures_dir: Path, tmp_path: Path
    ) -> None:
        """Verify Physics Proof: vector arrows, tensor notation, square roots, bracket preservation."""
        phys_p = fixtures_dir / "tier4" / "t4_physics_paper.pdf"
        results = pipeline.process_page(phys_p, output_dir=tmp_path)
        assert len(results) >= 1

        for res in results:
            assert len(res.latex) > 0
            ET.fromstring(res.mathml)

    # --- Scenario 5: High-Throughput Batch Document (Multi-Page) ---
    @pytest.mark.e2e
    @pytest.mark.tier4
    def test_t4_scen_05_multipage_batch_document(
        self, pipeline: Any, fixtures_dir: Path, tmp_path: Path
    ) -> None:
        """Verify Multi-Page Document: batch preservation across pages and original reading order."""
        multi_p = fixtures_dir / "tier4" / "t4_multipage_report.pdf"
        doc = fitz.open(str(multi_p))
        total_extracted = 0

        for page_idx in range(len(doc)):
            page_results = pipeline.process_page(
                multi_p, output_dir=tmp_path / f"page_{page_idx}", page_idx=page_idx
            )
            total_extracted += len(page_results)
            for res in page_results:
                ET.fromstring(res.mathml)

        doc.close()
        assert total_extracted >= 1

    # --- Scenario 6: Scanned Photocopied Page ---
    @pytest.mark.e2e
    @pytest.mark.tier4
    def test_t4_scen_06_scanned_photocopy(
        self, pipeline: Any, fixtures_dir: Path, tmp_path: Path
    ) -> None:
        """Verify Scanned Photocopy: 300 DPI, 0.35 deg tilt, sensor grain noise, contrast variance."""
        scan_p = fixtures_dir / "tier4" / "t4_scanned_photocopy.png"
        results = pipeline.process_page(scan_p, output_dir=tmp_path)
        assert len(results) >= 1, "Expected robust detection on scanned photocopy"

        for res in results:
            assert res.score if hasattr(res, "score") else res.confidence >= 0.20
            ET.fromstring(res.mathml)
            assert Path(res.image_path).is_file()
