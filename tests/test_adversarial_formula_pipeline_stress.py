# -*- coding: utf-8 -*-
"""
tests/test_adversarial_formula_pipeline_stress.py
=================================================
Empirical Adversarial Stress Harness for FormulaExtractionPipeline.
Focuses on edge cases, boundary conditions, stress scenarios, and failure modes:
  1. TestMultiPagePdfStress: Random page skipping, out-of-order page extraction,
     inverted ranges, varying page sizes, interspersed empty pages.
  2. TestDegenerateAndAdversarialInputs: Zero-detection pages, solid color canvases
     (black, white, red), random noise, 1x1 / 0x0 images, extreme aspect ratios (50:1, 1:50).
  3. TestMarginBoundsAndPaddingStress: Box straddling margins, box overlapping canvas borders,
     extreme pad (pad=20), margin ratios >= 1.0, negative margin handling.
  4. TestDenseTextSurroundStress: Formulas embedded in dense CJK + Latin prose,
     text bleeding into recognition output, complex CJK LaTeX sanitization, MathML parseability.
  5. TestOrderRestorationStress: 1000 random shuffles for single-page reading order,
     multi-page ordering preservation, None original_index handling.
  6. TestResourceCleanupStress: Windows file locking, immediate unlinking of source PDFs
     on normal completion and during unhandled exceptions, dangling handle verification.
  7. TestVectorPngRenderingCoordinateIntegrity: Verification of high-resolution vector PNG
     crops against DPI coordinate mismatch (150 DPI pixel vs 72 DPI point coordinate space).
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import shutil
import tempfile
from typing import List, Tuple
from unittest.mock import MagicMock
import xml.etree.ElementTree as ET

import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageDraw
import pytest

from src.extraction.contracts import (
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaResultContract,
)
from src.extraction.formula_cropper import FormulaCropper
from src.extraction.formula_detector import FormulaDetector
from src.extraction.formula_exporter import export_formula_results, export_highres_png
from src.extraction.formula_pipeline import FormulaExtractionPipeline
from src.extraction.formula_recognizer import RecognitionPredictor


# ----------------------------------------------------------------------------
# Helpers & Fixture Generators
# ----------------------------------------------------------------------------

def _make_adversarial_pdf(
    path: Path,
    page_specs: List[Tuple[float, float, str]],
) -> Path:
    """Creates a multi-page PDF with custom dimensions and text for each page."""
    doc = fitz.open()
    for w, h, content in page_specs:
        page = doc.new_page(width=w, height=h)
        if content:
            page.insert_text((50, 50), content, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _create_mock_pipeline_with_boxes(
    boxes: List[Tuple[float, float, float, float]],
    predictions: List[Tuple[str, float]] | None = None,
    pad: int = 4,
    batch_size: int = 32,
) -> FormulaExtractionPipeline:
    """Creates a pipeline returning explicit detection boxes."""
    mock_det = MagicMock(spec=FormulaDetector)
    dets = [
        FormulaDetectionContract(
            box=b,
            score=0.95,
            category="isolated",
            class_id=1,
        )
        for b in boxes
    ]
    mock_det.detect.return_value = dets

    mock_rec = MagicMock(spec=RecognitionPredictor)
    if predictions is not None:
        mock_rec.predict_crops.return_value = predictions
    else:
        mock_rec.predict_crops.return_value = [
            (f"eq_{i}", 0.95) for i in range(len(boxes))
        ]

    cropper = FormulaCropper(pad=pad, batch_size=batch_size)
    return FormulaExtractionPipeline(
        detector=mock_det,
        cropper=cropper,
        recognizer=mock_rec,
        pad=pad,
        batch_size=batch_size,
    )


# ============================================================================
# 1. Multi-Page PDF Handling Stress
# ============================================================================

class TestMultiPagePdfStress:
    """Stress tests multi-page PDF processing, skipping, and out-of-order extraction."""

    def test_random_page_skipping_and_out_of_order_calls(self, tmp_path: Path) -> None:
        """Verifies calling process_page in random, non-contiguous order preserves page index metadata."""
        pdf_path = tmp_path / "multi_page.pdf"
        page_specs = [
            (595, 842, "Page 0: intro"),
            (595, 842, "Page 1: formulas"),
            (595, 842, "Page 2: text"),
            (595, 842, "Page 3: more formulas"),
            (595, 842, "Page 4: conclusion"),
        ]
        _make_adversarial_pdf(pdf_path, page_specs)

        pipe = _create_mock_pipeline_with_boxes([(50, 50, 200, 100)])
        out_dir = tmp_path / "random_skip_out"

        # Access in random order: page 3, then 0, then 4, then 1
        page_order = [3, 0, 4, 1]
        for p_idx in page_order:
            results = pipe.process_page(
                pdf_path,
                page_idx=p_idx,
                output_dir=out_dir,
                save_manifest=False,
            )
            assert len(results) == 1
            assert results[0].page_idx == p_idx
            assert results[0].item_id.startswith(f"p{p_idx:03d}_")
            assert Path(results[0].image_path).exists()

    def test_inverted_and_degenerate_page_ranges(self, tmp_path: Path) -> None:
        """Verifies process_document handles inverted start/end pages and out-of-bound ranges gracefully."""
        pdf_path = tmp_path / "range_test.pdf"
        _make_adversarial_pdf(pdf_path, [(595, 842, f"P{i}") for i in range(5)])

        pipe = _create_mock_pipeline_with_boxes([(50, 50, 200, 100)])

        # Inverted range: start_page=4, end_page=2 -> must return empty list without crash
        res_inverted = pipe.process_document(
            pdf_path, start_page=4, end_page=2, output_dir=tmp_path / "inv"
        )
        assert res_inverted == []

        # Out of bounds: start_page=100 -> must return empty list
        res_oob = pipe.process_document(
            pdf_path, start_page=100, end_page=110, output_dir=tmp_path / "oob"
        )
        assert res_oob == []

        # Negative start_page -> clamped to 0
        res_neg = pipe.process_document(
            pdf_path, start_page=-5, end_page=1, output_dir=tmp_path / "neg"
        )
        assert len(res_neg) == 2  # pages 0 and 1
        assert res_neg[0].page_idx == 0
        assert res_neg[1].page_idx == 1

    def test_varying_page_dimensions_across_document(self, tmp_path: Path) -> None:
        """Verifies multi-page document with portrait, landscape, and irregular sizes."""
        pdf_path = tmp_path / "mixed_sizes.pdf"
        page_specs = [
            (595, 842, "Standard A4 Portrait"),
            (842, 595, "Standard A4 Landscape"),
            (300, 300, "Small Square"),
            (1200, 1800, "Large High-Res Poster"),
        ]
        _make_adversarial_pdf(pdf_path, page_specs)

        pipe = _create_mock_pipeline_with_boxes([(20, 20, 100, 50)])
        out_dir = tmp_path / "mixed_out"
        results = pipe.process_document(pdf_path, output_dir=out_dir)

        assert len(results) == 4
        assert [r.page_idx for r in results] == [0, 1, 2, 3]
        for r in results:
            assert Path(r.image_path).exists()


# ============================================================================
# 2. Degenerate and Adversarial Inputs Stress
# ============================================================================

class TestDegenerateAndAdversarialInputsStress:
    """Stress tests zero-detection, solid color canvases, random noise, and extreme aspect ratios."""

    def test_interspersed_zero_detection_pages(self, tmp_path: Path) -> None:
        """Verifies process_document handles documents where some pages have 0 detections."""
        pdf_path = tmp_path / "sparse.pdf"
        _make_adversarial_pdf(pdf_path, [(595, 842, f"P{i}") for i in range(3)])

        # Page 0 has 2 formulas, Page 1 has 0 formulas, Page 2 has 1 formula
        mock_det = MagicMock(spec=FormulaDetector)
        det_box = FormulaDetectionContract(
            box=(50, 50, 150, 80), score=0.9, category="isolated", class_id=1
        )
        mock_det.detect.side_effect = [
            [det_box, det_box],  # Page 0: 2 detections
            [],                  # Page 1: 0 detections
            [det_box],           # Page 2: 1 detection
        ]

        mock_rec = MagicMock(spec=RecognitionPredictor)
        mock_rec.predict_crops.return_value = [("f(x)", 0.99), ("g(x)", 0.98), ("h(x)", 0.97)]

        pipe = FormulaExtractionPipeline(detector=mock_det, recognizer=mock_rec)
        out_dir = tmp_path / "sparse_out"
        results = pipe.process_document(pdf_path, output_dir=out_dir)

        assert len(results) == 3
        assert results[0].page_idx == 0
        assert results[1].page_idx == 0
        assert results[2].page_idx == 2

        # Verify manifest formulas.json contains exactly the 3 valid items
        manifest_path = out_dir / "formulas.json"
        assert manifest_path.exists()
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(manifest_data) == 3
        assert [item["page_idx"] for item in manifest_data] == [0, 0, 2]

    @pytest.mark.heavy
    def test_solid_color_and_random_noise_canvases(self, tmp_path: Path) -> None:
        """Verifies processing pure black, white, red, and noise canvases without exceptions."""
        pipe = FormulaExtractionPipeline()  # Uses real or default detector

        test_canvases = [
            ("solid_black", Image.new("RGB", (600, 800), (0, 0, 0))),
            ("solid_white", Image.new("RGB", (600, 800), (255, 255, 255))),
            ("solid_red", Image.new("RGB", (600, 800), (255, 0, 0))),
            (
                "uniform_noise",
                Image.fromarray(np.random.randint(0, 256, (600, 800, 3), dtype=np.uint8)),
            ),
        ]

        for name, img in test_canvases:
            # Must complete cleanly with 0 unhandled exceptions
            res = pipe.process_page(img, output_dir=tmp_path / name)
            # Typically 0 detections on solid canvases/noise
            assert isinstance(res, list)

    def test_degenerate_dimensions_1x1_and_0x0(self, tmp_path: Path) -> None:
        """Verifies 1x1, 0x0, and thin degenerate images cleanly return empty results."""
        pipe = _create_mock_pipeline_with_boxes([])

        assert pipe.process_page(Image.new("RGB", (1, 1))) == []
        assert pipe.process_page(Image.new("RGB", (1, 500))) == []
        assert pipe.process_page(Image.new("RGB", (500, 1))) == []
        assert pipe.process_page(np.zeros((0, 0, 3), dtype=np.uint8)) == []
        assert pipe.process_page(np.zeros((1, 1, 3), dtype=np.uint8)) == []

    def test_extreme_aspect_ratios_50_to_1_and_1_to_50(self, tmp_path: Path) -> None:
        """Verifies formula boxes and page images with 50:1 and 1:50 aspect ratios."""
        # 1. 50:1 extreme wide page
        img_wide = Image.new("RGB", (2500, 50), (255, 255, 255))
        # 2. 1:50 extreme tall page
        img_tall = Image.new("RGB", (50, 2500), (255, 255, 255))

        pipe_wide = _create_mock_pipeline_with_boxes([(50, 10, 2050, 30)])  # 2000x20 box = 100:1 AR
        res_wide = pipe_wide.process_page(img_wide, output_dir=tmp_path / "wide")
        assert len(res_wide) == 1
        assert res_wide[0].padded_box[2] - res_wide[0].padded_box[0] > 1000

        pipe_tall = _create_mock_pipeline_with_boxes([(10, 50, 30, 2050)])  # 20x2000 box = 1:100 AR
        res_tall = pipe_tall.process_page(img_tall, output_dir=tmp_path / "tall")
        assert len(res_tall) == 1
        assert res_tall[0].padded_box[3] - res_tall[0].padded_box[1] > 1000


# ============================================================================
# 3. Margin Bounds and Padding Stress
# ============================================================================

class TestMarginBoundsAndPaddingStress:
    """Stress tests boundary conditions: margin overlap, canvas bleed, extreme pad."""

    def test_box_straddling_crop_margins(self, tmp_path: Path) -> None:
        """Verifies filtering when boxes cross header/footer ratios."""
        # Canvas 1000 x 1000, header_ratio=0.1 (y=100), footer_ratio=0.1 (y=900)
        img = Image.new("RGB", (1000, 1000), (255, 255, 255))

        # Box A: center inside (cy=110), but top edge y1=70 straddles into header area (<100)
        box_a = (100.0, 70.0, 300.0, 150.0)  # cy = 110, y1=70
        # Box B: center outside (cy=80) in header area
        box_b = (100.0, 50.0, 300.0, 110.0)  # cy = 80
        # Box C: center inside (cy=880), bottom edge y2=940 straddles into footer area (>900)
        box_c = (100.0, 820.0, 300.0, 940.0)  # cy = 880

        pipe = _create_mock_pipeline_with_boxes([box_a, box_b, box_c])
        results = pipe.process_page(
            img,
            header_ratio=0.1,
            footer_ratio=0.1,
            output_dir=tmp_path / "margin_straddle",
        )

        # Box B should be filtered out. Box A and Box C must be retained!
        assert len(results) == 2
        # Verify Box A was padded and clamped safely
        assert results[0].padded_box[1] >= 0
        assert results[1].padded_box[3] <= 1000

    def test_extreme_padding_pad_20_near_boundary(self, tmp_path: Path) -> None:
        """Verifies pad=20 does not exceed canvas borders or produce negative coordinates."""
        img = Image.new("RGB", (500, 500), (255, 255, 255))
        # Box right at the edge: (2, 2, 50, 50)
        pipe = _create_mock_pipeline_with_boxes([(2.0, 2.0, 50.0, 50.0)], pad=20)
        results = pipe.process_page(img, output_dir=tmp_path / "pad20")

        assert len(results) == 1
        pb = results[0].padded_box
        assert pb[0] == 0  # 2 - 20 clamped to 0
        assert pb[1] == 0  # 2 - 20 clamped to 0
        assert pb[2] == 70  # 50 + 20
        assert pb[3] == 70  # 50 + 20

    def test_excessive_margin_ratios_sum_exceeding_one(self, tmp_path: Path) -> None:
        """Verifies header_ratio + footer_ratio >= 1.0 cleanly returns empty list without error."""
        img = Image.new("RGB", (500, 500), (255, 255, 255))
        pipe = _create_mock_pipeline_with_boxes([(100, 100, 200, 200)])
        results = pipe.process_page(
            img,
            header_ratio=0.6,
            footer_ratio=0.6,
            output_dir=tmp_path / "excessive_margin",
        )
        assert results == []


# ============================================================================
# 4. Dense Text Surround Stress
# ============================================================================

class TestDenseTextSurroundStress:
    """Stress tests formulas embedded in dense CJK + Latin prose."""

    def test_dense_prose_embedding_and_text_bleeding(self, tmp_path: Path) -> None:
        """Verifies dense surrounding text does not break LaTeX sanitization or MathML export."""
        img = Image.new("RGB", (1000, 1000), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Draw dense lines of text around formula
        for y in range(50, 400, 30):
            draw.text((50, y), "這是一段密集的中英文學術論文文本，包含各種上下文描述和標點符號。", fill=(0, 0, 0))

        # Formula with bleeding prose words returned by recognition
        bleeding_predictions = [
            ("```latex \\int_{0}^{\\infty} e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2} 其中 x 為實數 ```", 0.95),
            ("f(x) = y，如圖所示", 0.92),
            ("$$ \\sum_{k=1}^{n} k = \\frac{n(n+1)}{2} $$", 0.99),
        ]
        boxes = [
            (100.0, 450.0, 500.0, 500.0),
            (100.0, 550.0, 300.0, 600.0),
            (100.0, 650.0, 400.0, 700.0),
        ]

        pipe = _create_mock_pipeline_with_boxes(boxes, predictions=bleeding_predictions)
        out_dir = tmp_path / "dense_out"
        results = pipe.process_page(img, output_dir=out_dir)

        assert len(results) == 3
        for r in results:
            # 1. LaTeX should be sanitized (no ``` fences, no outer $$)
            assert not r.latex.startswith("```")
            assert not r.latex.endswith("```")
            assert not r.latex.startswith("$$")
            # 2. MathML must be valid, well-formed XML
            tree = ET.fromstring(r.mathml)
            assert tree.tag.endswith("math")


# ============================================================================
# 5. Order Restoration Stress
# ============================================================================

class TestOrderRestorationStress:
    """Stress tests reading order restoration stability and edge cases."""

    def test_single_page_1000_random_shuffles_guarantee_reading_order(self) -> None:
        """Verifies 1000 randomized permutations of detections restore exact original order."""
        n_items = 64
        base_items = [
            FormulaResultContract(
                item_id=f"eq_{i:05d}",
                original_index=i,
                category="isolated",
                box=(float(i * 10), 50.0, float(i * 10 + 20), 80.0),
                padded_box=(i * 10, 46, i * 10 + 20, 84),
                latex=f"x_{i}",
                mathml=f"<math><msub><mi>x</mi><mn>{i}</mn></msub></math>",
                image_path=f"img_{i}.png",
                confidence=0.99,
                page_idx=0,
            )
            for i in range(n_items)
        ]

        rng = random.Random(42)
        for _ in range(1000):
            shuffled = list(base_items)
            rng.shuffle(shuffled)
            restored = FormulaCropper.restore_order(shuffled)
            # Must match exact original sequence 0..63
            for expected_idx, item in enumerate(restored):
                assert item.original_index == expected_idx

    def test_multi_page_document_reading_order_restoration_bug(self) -> None:
        """
        Adversarial test revealing that FormulaCropper.restore_order sorts ONLY by original_index,
        failing to preserve document reading order across multi-page documents when page_idx is present.
        """
        # Create items from page 0 and page 1
        item_p0_0 = FormulaResultContract(
            item_id="p000_eq_00000", original_index=0, category="isolated",
            box=(10, 10, 100, 50), padded_box=(6, 6, 104, 54), latex="a", mathml="<math><mi>a</mi></math>",
            image_path="a.png", confidence=0.9, page_idx=0
        )
        item_p0_1 = FormulaResultContract(
            item_id="p000_eq_00001", original_index=1, category="isolated",
            box=(10, 60, 100, 100), padded_box=(6, 56, 104, 104), latex="b", mathml="<math><mi>b</mi></math>",
            image_path="b.png", confidence=0.9, page_idx=0
        )
        item_p1_0 = FormulaResultContract(
            item_id="p001_eq_00000", original_index=0, category="isolated",
            box=(10, 10, 100, 50), padded_box=(6, 6, 104, 54), latex="c", mathml="<math><mi>c</mi></math>",
            image_path="c.png", confidence=0.9, page_idx=1
        )
        item_p1_1 = FormulaResultContract(
            item_id="p001_eq_00001", original_index=1, category="isolated",
            box=(10, 60, 100, 100), padded_box=(6, 56, 104, 104), latex="d", mathml="<math><mi>d</mi></math>",
            image_path="d.png", confidence=0.9, page_idx=1
        )

        shuffled = [item_p1_1, item_p0_1, item_p1_0, item_p0_0]
        restored = FormulaCropper.restore_order(shuffled)
        restored_ids = [it.item_id for it in restored]

        # The expected true document reading order is all page 0 items then all page 1 items:
        expected_doc_order = ["p000_eq_00000", "p000_eq_00001", "p001_eq_00000", "p001_eq_00001"]

        # If restored_ids != expected_doc_order, this confirms the multi-page ordering defect!
        assert restored_ids == expected_doc_order, (
            f"FormulaCropper.restore_order failed multi-page ordering: got {restored_ids}, expected {expected_doc_order}"
        )

    def test_restore_order_handles_none_original_index_gracefully(self) -> None:
        """
        Verifies whether FormulaCropper.restore_order handles items with original_index=None
        or raises TypeError when comparing None with int.
        """
        class DummyItem:
            def __init__(self, original_index: int | None, item_id: str):
                self.original_index = original_index
                self.item_id = item_id

        items = [DummyItem(1, "b"), DummyItem(None, "a"), DummyItem(0, "c")]
        # If getattr default doesn't catch None values, this raises TypeError
        restored = FormulaCropper.restore_order(items)
        assert len(restored) == 3


# ============================================================================
# 6. Resource Cleanup and File Handle Stress
# ============================================================================

class TestResourceCleanupStress:
    """Stress tests PyMuPDF document handle cleanup and Windows file locking."""

    def test_unlink_immediately_after_process_document(self, tmp_path: Path) -> None:
        """Verifies PDF file handle is released immediately on Windows."""
        pdf_path = tmp_path / "cleanup_normal.pdf"
        _make_adversarial_pdf(pdf_path, [(595, 842, "Content")])

        pipe = _create_mock_pipeline_with_boxes([(50, 50, 150, 80)])
        pipe.process_document(pdf_path, output_dir=tmp_path / "clean_norm")

        # Must unlink cleanly without PermissionError
        pdf_path.unlink()
        assert not pdf_path.exists()

    def test_unlink_after_unhandled_exception_in_process_document(self, tmp_path: Path) -> None:
        """Verifies PDF file handle is released even if detector raises an unhandled error."""
        pdf_path = tmp_path / "cleanup_error.pdf"
        _make_adversarial_pdf(pdf_path, [(595, 842, "Content")])

        mock_det = MagicMock(spec=FormulaDetector)
        mock_det.detect.side_effect = RuntimeError("Adversarial crash")
        pipe = FormulaExtractionPipeline(detector=mock_det)

        with pytest.raises(RuntimeError):
            pipe.process_document(pdf_path, output_dir=tmp_path / "clean_err")

        # Must unlink cleanly without PermissionError on Windows!
        pdf_path.unlink()
        assert not pdf_path.exists()

    def test_unlink_after_unhandled_exception_in_process_page(self, tmp_path: Path) -> None:
        """Verifies process_page(pdf_path) releases PDF handle on unhandled exception."""
        pdf_path = tmp_path / "cleanup_page_error.pdf"
        _make_adversarial_pdf(pdf_path, [(595, 842, "Content")])

        mock_det = MagicMock(spec=FormulaDetector)
        mock_det.detect.side_effect = RuntimeError("Adversarial page crash")
        pipe = FormulaExtractionPipeline(detector=mock_det)

        with pytest.raises(RuntimeError):
            pipe.process_page(pdf_path, output_dir=tmp_path / "clean_page_err")

        # Must unlink cleanly without PermissionError on Windows!
        pdf_path.unlink()
        assert not pdf_path.exists()


# ============================================================================
# 7. High-Resolution Vector PNG Coordinate Integrity Stress
# ============================================================================

class TestVectorPngRenderingCoordinateIntegrity:
    """
    Empirically verifies whether high-resolution PNG vector rendering preserves
    actual formula content without DPI coordinate space corruption.
    """

    def test_vector_crop_contains_formula_pixels_not_blank_whitespace(self, tmp_path: Path) -> None:
        """
        Adversarial test revealing the 150 DPI vs 72 DPI coordinate mismatch bug in export_highres_png:
        Draws a blue box formula on a PDF page, processes through pipeline, and asserts
        the exported 1600px PNG actually contains the formula pixels instead of blank white space.
        """
        pdf_path = tmp_path / "vector_formula_test.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # Draw a distinct BLUE formula at points (100, 100, 300, 200)
        page.draw_rect(fitz.Rect(100, 100, 300, 200), color=(0, 0, 1), fill=(0, 0, 1))
        doc.save(str(pdf_path))
        doc.close()

        # At default dpi=150, scale factor is 150 / 72 = 2.08333.
        # The blue box in pixmap pixels is at:
        # x1 = 100 * 150/72 = 208.33, y1 = 208.33, x2 = 625.0, y2 = 416.67
        px_box = (208.0, 208.0, 625.0, 417.0)

        pipe = _create_mock_pipeline_with_boxes([px_box])
        out_dir = tmp_path / "vector_test_out"
        results = pipe.process_document(pdf_path, output_dir=out_dir)

        assert len(results) == 1
        res = results[0]
        exported_img_path = Path(res.image_path)
        assert exported_img_path.exists()

        exported_img = Image.open(exported_img_path)
        # Sample the center pixel of the exported formula
        center_color = exported_img.getpixel((exported_img.width // 2, exported_img.height // 2))

        # If vector rendering was corrupted by DPI coordinate mismatch, center pixel will be white (255, 255, 255)
        # If vector rendering is correct, center pixel will be blue (0, 0, 255)
        is_blank_white = (center_color[0] > 240 and center_color[1] > 240 and center_color[2] > 240)
        assert not is_blank_white, (
            f"Exported vector formula image is BLANK WHITE ({center_color})! "
            f"DPI coordinate mismatch in export_highres_png: padded_box was passed in 150 DPI pixels "
            f"to PyMuPDF clip_rect in 72 DPI points without coordinate transformation."
        )
