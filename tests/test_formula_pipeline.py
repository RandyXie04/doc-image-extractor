# -*- coding: utf-8 -*-
"""
tests/test_formula_pipeline.py
==============================
Comprehensive unit and integration test suite for FormulaExtractionPipeline.
Covers 8 dedicated test classes (34 tests):
  1. TestPipelineInitialization
  2. TestPipelineInputPolymorphism
  3. TestPipelineEmptyAndDegenerateInputs
  4. TestPipelineSeamsAndOrderRestoration
  5. TestPipelineMultiPageDocument
  6. TestPipelineFilteringOptions
  7. TestPipelineDeliverablesAndManifest
  8. TestPipelineResourceAndErrorHandling
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock
import xml.etree.ElementTree as ET

import fitz
import numpy as np
from PIL import Image
import pytest

from src.extraction.contracts import (
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaResultContract,
)
from src.extraction.formula_cropper import FormulaCropper
from src.extraction.formula_detector import FormulaDetector
from src.extraction.formula_pipeline import FormulaExtractionPipeline
from src.extraction.formula_recognizer import RecognitionPredictor


# ----------------------------------------------------------------------------
# Test Fixtures & Helpers
# ----------------------------------------------------------------------------

def _make_dummy_pdf(path: Path, num_pages: int = 1) -> Path:
    """Creates a simple valid PDF document with text on each page."""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 100), f"Page {i + 1} content with $f(x)=ax+bx$", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _create_mock_pipeline(
    detections: List[FormulaDetectionContract] | None = None,
    predictions: List[Tuple[str, float]] | None = None,
    pad: int = 4,
    batch_size: int = 32,
) -> FormulaExtractionPipeline:
    """Creates a pipeline instance wired with mock stages for deterministic, rapid testing."""
    mock_det = MagicMock(spec=FormulaDetector)
    if detections is not None:
        mock_det.detect.return_value = detections
    else:
        det = FormulaDetectionContract(
            box=(10.0, 20.0, 110.0, 50.0),
            score=0.95,
            category="isolated",
            class_id=1,
        )
        mock_det.detect.return_value = [det]

    mock_rec = MagicMock(spec=RecognitionPredictor)
    if predictions is not None:
        mock_rec.predict_crops.return_value = predictions
    else:
        mock_rec.predict_crops.return_value = [("f(x) = ax + bx", 0.98)]

    cropper = FormulaCropper(pad=pad, batch_size=batch_size)
    return FormulaExtractionPipeline(
        detector=mock_det,
        cropper=cropper,
        recognizer=mock_rec,
        pad=pad,
        batch_size=batch_size,
    )


# ============================================================================
# 1. TestPipelineInitialization (4 tests)
# ============================================================================

class TestPipelineInitialization:
    """Dependency injection, default configuration, and boundary parameter validation."""

    def test_default_initialization(self) -> None:
        """Verifies default initialization sets expected configurations."""
        pipe = FormulaExtractionPipeline()
        assert pipe.pad == 4
        assert pipe.batch_size == 32
        assert pipe.imgsz == 1280
        assert pipe.imgsz_export == 1600
        assert pipe.default_languages == ["_math", "zh"]
        assert pipe._detector is None
        assert pipe._cropper is None
        assert pipe._recognizer is None

    def test_custom_injected_components(self) -> None:
        """Verifies custom injected detector, cropper, and recognizer instances."""
        mock_det = MagicMock(spec=FormulaDetector)
        mock_crop = MagicMock(spec=FormulaCropper)
        mock_rec = MagicMock(spec=RecognitionPredictor)

        pipe = FormulaExtractionPipeline(
            detector=mock_det,
            cropper=mock_crop,
            recognizer=mock_rec,
            pad=6,
            batch_size=64,
            default_languages=["_math"],
        )
        assert pipe.detector is mock_det
        assert pipe.cropper is mock_crop
        assert pipe.recognizer is mock_rec
        assert pipe.pad == 6
        assert pipe.batch_size == 64
        assert pipe.default_languages == ["_math"]

    def test_invalid_pad_raises_value_error(self) -> None:
        """Verifies pad boundaries (1 <= pad <= 20)."""
        with pytest.raises(ValueError, match="pad must be between 1 and 20"):
            FormulaExtractionPipeline(pad=0)
        with pytest.raises(ValueError, match="pad must be between 1 and 20"):
            FormulaExtractionPipeline(pad=21)

    def test_invalid_batch_size_raises_value_error(self) -> None:
        """Verifies batch_size boundaries (1 <= batch_size <= 256)."""
        with pytest.raises(ValueError, match="batch_size must be between 1 and 256"):
            FormulaExtractionPipeline(batch_size=0)
        with pytest.raises(ValueError, match="batch_size must be between 1 and 256"):
            FormulaExtractionPipeline(batch_size=257)


# ============================================================================
# 2. TestPipelineInputPolymorphism (6 tests)
# ============================================================================

class TestPipelineInputPolymorphism:
    """Ingestion support across PIL Images, NumPy ndarrays, paths, and fitz Pages."""

    def test_input_pil_image_rgb(self, tmp_path: Path) -> None:
        """Verifies PIL RGB Image ingestion."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGB", (300, 200), (255, 255, 255))
        results = pipe.process_page(img, output_dir=tmp_path)
        assert len(results) == 1
        assert isinstance(results[0], FormulaResultContract)

    def test_input_pil_image_rgba(self, tmp_path: Path) -> None:
        """Verifies PIL RGBA Image ingestion converts safely to RGB."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGBA", (300, 200), (255, 255, 255, 255))
        results = pipe.process_page(img, output_dir=tmp_path)
        assert len(results) == 1

    def test_input_numpy_array(self, tmp_path: Path) -> None:
        """Verifies NumPy array (uint8 3-channel) ingestion."""
        pipe = _create_mock_pipeline()
        arr = np.ones((200, 300, 3), dtype=np.uint8) * 255
        results = pipe.process_page(arr, output_dir=tmp_path)
        assert len(results) == 1

    def test_input_str_and_pathlib_image_paths(self, tmp_path: Path) -> None:
        """Verifies image file path ingestion (both str and Path)."""
        pipe = _create_mock_pipeline()
        img_p = tmp_path / "sample.png"
        Image.new("RGB", (200, 100), (255, 255, 255)).save(str(img_p))

        # Test str
        res_str = pipe.process_page(str(img_p), output_dir=tmp_path / "out_str")
        assert len(res_str) == 1

        # Test Path
        res_path = pipe.process_page(img_p, output_dir=tmp_path / "out_path")
        assert len(res_path) == 1

    def test_input_direct_fitz_page(self, tmp_path: Path) -> None:
        """Verifies direct fitz.Page ingestion."""
        pipe = _create_mock_pipeline()
        pdf_path = _make_dummy_pdf(tmp_path / "dummy_page.pdf", num_pages=1)
        with fitz.open(str(pdf_path)) as doc:
            page = doc[0]
            results = pipe.process_page(page, output_dir=tmp_path / "out_fitz")
            assert len(results) == 1
            assert results[0].page_idx == 0

    def test_unsupported_input_type_raises_type_error(self, tmp_path: Path) -> None:
        """Verifies unsupported input type raises TypeError."""
        pipe = _create_mock_pipeline()
        with pytest.raises(TypeError, match="Unsupported image input type"):
            pipe.process_page(12345, output_dir=tmp_path)


# ============================================================================
# 3. TestPipelineEmptyAndDegenerateInputs (5 tests)
# ============================================================================

class TestPipelineEmptyAndDegenerateInputs:
    """Robust zero-crash handling on empty, blank, or degenerate inputs."""

    def test_pure_white_canvas_returns_empty(self, tmp_path: Path) -> None:
        """Verifies pure white image with zero detections returns empty list immediately."""
        pipe = _create_mock_pipeline(detections=[])
        img = Image.new("RGB", (400, 400), (255, 255, 255))
        results = pipe.process_page(img, output_dir=tmp_path)
        assert results == []

    def test_pure_noise_page_returns_empty(self, tmp_path: Path) -> None:
        """Verifies noise image producing zero detections returns empty list."""
        pipe = _create_mock_pipeline(detections=[])
        arr = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        results = pipe.process_page(arr, output_dir=tmp_path)
        assert results == []

    def test_degenerate_dimensions_return_empty(self, tmp_path: Path) -> None:
        """Verifies 1x1 or 0x0 images return empty list without crashing."""
        pipe = _create_mock_pipeline()
        tiny_img = Image.new("RGB", (1, 1), (255, 255, 255))
        assert pipe.process_page(tiny_img, output_dir=tmp_path) == []

        empty_arr = np.zeros((0, 0, 3), dtype=np.uint8)
        assert pipe.process_page(empty_arr, output_dir=tmp_path) == []

    def test_nonexistent_image_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """Verifies non-existent file path raises FileNotFoundError."""
        pipe = _create_mock_pipeline()
        with pytest.raises(FileNotFoundError):
            pipe.process_page(tmp_path / "does_not_exist.png", output_dir=tmp_path)

    def test_pdf_page_out_of_range_raises_index_error(self, tmp_path: Path) -> None:
        """Verifies requesting out-of-range page index raises IndexError."""
        pipe = _create_mock_pipeline()
        pdf_path = _make_dummy_pdf(tmp_path / "one_page.pdf", num_pages=1)
        with pytest.raises(IndexError, match="out of range"):
            pipe.process_page(pdf_path, page_idx=5, output_dir=tmp_path)


# ============================================================================
# 4. TestPipelineSeamsAndOrderRestoration (4 tests)
# ============================================================================

class TestPipelineSeamsAndOrderRestoration:
    """Stage seams coupling, order restoration, LaTeX sanitization, and MathML validation."""

    def test_reading_order_restoration_after_aspect_ratio_sort(self, tmp_path: Path) -> None:
        """
        Stage 2 sorts crops by aspect ratio for GPU batch collation efficiency.
        Verifies pipeline restores items to original document reading order indices [0, 1, 2].
        """
        # Det 0: wide formula (AR ~ 4.0)
        det0 = FormulaDetectionContract(box=(10.0, 10.0, 210.0, 60.0), score=0.9, category="isolated", class_id=1)
        # Det 1: tall formula (AR ~ 0.5)
        det1 = FormulaDetectionContract(box=(10.0, 70.0, 60.0, 170.0), score=0.9, category="inline", class_id=0)
        # Det 2: square formula (AR ~ 1.0)
        det2 = FormulaDetectionContract(box=(10.0, 180.0, 110.0, 280.0), score=0.9, category="isolated", class_id=1)

        # Expected aspect ratio sorted order in Stage 2: [det1 (AR 0.5), det2 (AR 1.0), det0 (AR 4.0)]
        # Predictor returns corresponding predictions in that sorted order
        predictions = [
            ("y_tall = 1", 0.95),    # corresponding to det1
            ("E_square = mc^2", 0.96), # corresponding to det2
            ("x_wide = a + b", 0.97),  # corresponding to det0
        ]

        pipe = _create_mock_pipeline(detections=[det0, det1, det2], predictions=predictions)
        img = Image.new("RGB", (400, 400), (255, 255, 255))
        results = pipe.process_page(img, output_dir=tmp_path)

        assert len(results) == 3
        # In restored order, original_index must be strictly [0, 1, 2]
        indices = [r.original_index for r in results]
        assert indices == [0, 1, 2]
        assert results[0].latex == "x_wide = a + b"
        assert results[1].latex == "y_tall = 1"
        assert results[2].latex == "E_square = mc^2"

    def test_contract_adherence_zero_raw_dict(self, tmp_path: Path) -> None:
        """Verifies every returned object is an immutable FormulaResultContract with all fields populated."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGB", (300, 200), (255, 255, 255))
        results = pipe.process_page(img, output_dir=tmp_path)

        assert len(results) == 1
        res = results[0]
        assert isinstance(res, FormulaResultContract)
        assert res.item_id
        assert res.category in ("inline", "isolated")
        assert len(res.box) == 4
        assert len(res.padded_box) == 4
        assert res.confidence >= 0.0
        assert res.latex
        assert res.mathml
        assert Path(res.image_path).is_file()

    def test_latex_sanitization_in_pipeline(self, tmp_path: Path) -> None:
        """Verifies delimiters and code blocks are stripped by multi-format exporter."""
        predictions = [("$$f(x) = \\frac{a}{b}$$", 0.99)]
        pipe = _create_mock_pipeline(predictions=predictions)
        img = Image.new("RGB", (300, 200), (255, 255, 255))
        results = pipe.process_page(img, output_dir=tmp_path)

        assert len(results) == 1
        assert results[0].latex == "f(x) = \\frac{a}{b}"
        assert not results[0].latex.startswith("$")

    def test_mathml_xml_validity(self, tmp_path: Path) -> None:
        """Verifies MathML output is valid XML parseable by ElementTree."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGB", (300, 200), (255, 255, 255))
        results = pipe.process_page(img, output_dir=tmp_path)

        assert len(results) == 1
        root = ET.fromstring(results[0].mathml)
        assert root.tag.endswith("math")
        assert len(root) >= 1


# ============================================================================
# 5. TestPipelineMultiPageDocument (4 tests)
# ============================================================================

class TestPipelineMultiPageDocument:
    """Multi-page document workflows, page indexing, and handle lifecycle."""

    def test_multipage_page_indexing_and_prefix(self, tmp_path: Path) -> None:
        """Verifies page_idx is recorded in result and prefixed in item_id."""
        pipe = _create_mock_pipeline()
        pdf_path = _make_dummy_pdf(tmp_path / "multi_idx.pdf", num_pages=3)

        results = pipe.process_page(pdf_path, page_idx=2, output_dir=tmp_path / "page_2")
        assert len(results) == 1
        assert results[0].page_idx == 2
        assert results[0].item_id.startswith("p002_")

    def test_process_document_page_range(self, tmp_path: Path) -> None:
        """Verifies process_document iterates through start_page to end_page."""
        pipe = _create_mock_pipeline()
        pdf_path = _make_dummy_pdf(tmp_path / "doc_range.pdf", num_pages=4)

        # Process pages 1 to 2 (2 pages total)
        results = pipe.process_document(
            pdf_path,
            start_page=1,
            end_page=2,
            output_dir=tmp_path / "doc_out",
        )
        assert len(results) == 2
        assert results[0].page_idx == 1
        assert results[1].page_idx == 2

    def test_process_document_progress_callback(self, tmp_path: Path) -> None:
        """Verifies progress_callback is invoked for each processed page."""
        pipe = _create_mock_pipeline()
        pdf_path = _make_dummy_pdf(tmp_path / "doc_prog.pdf", num_pages=3)

        calls: List[Tuple[int, int, str]] = []
        def on_progress(cur: int, tot: int, msg: str) -> None:
            calls.append((cur, tot, msg))

        pipe.process_document(pdf_path, output_dir=tmp_path / "prog_out", progress_callback=on_progress)
        assert len(calls) == 3
        assert calls[0][0] == 1 and calls[0][1] == 3
        assert calls[2][0] == 3 and calls[2][1] == 3

    def test_document_handle_cleanup_on_windows(self, tmp_path: Path) -> None:
        """Verifies fitz.Document handles are closed cleanly, allowing immediate unlinking."""
        pipe = _create_mock_pipeline()
        pdf_path = _make_dummy_pdf(tmp_path / "cleanup_test.pdf", num_pages=2)

        pipe.process_document(pdf_path, output_dir=tmp_path / "clean_out")
        # On Windows, if fitz.Document is still open, unlinking raises PermissionError
        pdf_path.unlink()
        assert not pdf_path.exists()


# ============================================================================
# 6. TestPipelineFilteringOptions (3 tests)
# ============================================================================

class TestPipelineFilteringOptions:
    """Category extraction filters and crop margin guideline filters."""

    def test_extract_inline_and_isolated_flags(self, tmp_path: Path) -> None:
        """Verifies extract_inline and extract_isolated flags are propagated to detector."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGB", (300, 200), (255, 255, 255))

        pipe.process_page(img, extract_inline=False, extract_isolated=True, output_dir=tmp_path)
        pipe.detector.detect.assert_called_with(
            img,
            conf_threshold=0.20,
            iou_threshold=0.45,
            min_width=12.0,
            min_height=10.0,
            extract_inline=False,
            extract_isolated=True,
        )

    def test_header_footer_margin_filtering(self, tmp_path: Path) -> None:
        """Verifies bounding boxes located inside header/footer margins are filtered out."""
        # Page size: 200x200
        # Header margin (0.2): y in [0, 40]
        # Content: y in (40, 160)
        # Footer margin (0.2): y in [160, 200]
        det_header = FormulaDetectionContract(box=(50.0, 10.0, 150.0, 30.0), score=0.9, category="inline", class_id=0)
        det_content = FormulaDetectionContract(box=(50.0, 80.0, 150.0, 120.0), score=0.9, category="isolated", class_id=1)
        det_footer = FormulaDetectionContract(box=(50.0, 170.0, 150.0, 190.0), score=0.9, category="inline", class_id=0)

        pipe = _create_mock_pipeline(
            detections=[det_header, det_content, det_footer],
            predictions=[("y_center = 1", 0.95)],
        )
        img = Image.new("RGB", (200, 200), (255, 255, 255))
        results = pipe.process_page(img, header_ratio=0.2, footer_ratio=0.2, output_dir=tmp_path)

        assert len(results) == 1
        assert results[0].latex == "y_center = 1"

    def test_left_right_margin_filtering(self, tmp_path: Path) -> None:
        """Verifies bounding boxes in left/right margins are filtered out."""
        det_left = FormulaDetectionContract(box=(5.0, 80.0, 25.0, 120.0), score=0.9, category="inline", class_id=0)
        det_center = FormulaDetectionContract(box=(80.0, 80.0, 120.0, 120.0), score=0.9, category="isolated", class_id=1)

        pipe = _create_mock_pipeline(
            detections=[det_left, det_center],
            predictions=[("y_valid = 1", 0.95)],
        )
        img = Image.new("RGB", (200, 200), (255, 255, 255))
        results = pipe.process_page(img, left_ratio=0.2, right_ratio=0.2, output_dir=tmp_path)

        assert len(results) == 1
        assert results[0].latex == "y_valid = 1"


# ============================================================================
# 7. TestPipelineDeliverablesAndManifest (4 tests)
# ============================================================================

class TestPipelineDeliverablesAndManifest:
    """Artifact filesystem layout, PNG resolution, and formulas.json serialization."""

    def test_filesystem_deliverable_layout(self, tmp_path: Path) -> None:
        """Verifies images/ directory and formulas.json manifest are created."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGB", (300, 200), (255, 255, 255))
        results = pipe.process_page(img, output_dir=tmp_path)

        assert len(results) == 1
        item_id = results[0].item_id
        img_file = tmp_path / "images" / f"{item_id}.png"
        manifest_file = tmp_path / "formulas.json"

        assert img_file.is_file()
        assert manifest_file.is_file()

    def test_highres_png_dimensions(self, tmp_path: Path) -> None:
        """Verifies exported crop has longest dimension scaled to 1600px (+-1px)."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGB", (300, 200), (255, 255, 255))
        results = pipe.process_page(img, output_dir=tmp_path)

        assert len(results) == 1
        with Image.open(results[0].image_path) as im:
            assert max(im.size) in (1599, 1600, 1601)

    def test_manifest_schema_matches_contract(self, tmp_path: Path) -> None:
        """Verifies formulas.json manifest contains all FormulaResultContract keys."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGB", (300, 200), (255, 255, 255))
        pipe.process_page(img, output_dir=tmp_path)

        manifest_path = tmp_path / "formulas.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == 1
        entry = data[0]
        required_keys = {
            "item_id", "original_index", "category", "box",
            "padded_box", "latex", "mathml", "image_path", "confidence"
        }
        assert required_keys.issubset(set(entry.keys()))

    def test_save_manifest_flag_false(self, tmp_path: Path) -> None:
        """Verifies manifest is not written when save_manifest=False."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGB", (300, 200), (255, 255, 255))
        pipe.process_page(img, output_dir=tmp_path, save_manifest=False)

        manifest_file = tmp_path / "formulas.json"
        assert not manifest_file.exists()


# ============================================================================
# 8. TestPipelineResourceAndErrorHandling (4 tests)
# ============================================================================

class TestPipelineResourceAndErrorHandling:
    """Temporary workspace allocation, zero-detection directories, and domain exceptions."""

    def test_output_dir_none_uses_temp_directory(self) -> None:
        """Verifies pipeline creates and uses a temporary directory when output_dir is None."""
        pipe = _create_mock_pipeline()
        img = Image.new("RGB", (300, 200), (255, 255, 255))
        results = pipe.process_page(img, output_dir=None)
        assert len(results) == 1
        assert Path(results[0].image_path).is_file()

    def test_zero_detections_does_not_create_images_dir(self, tmp_path: Path) -> None:
        """Verifies zero-detection page does not leave empty images/ folder."""
        pipe = _create_mock_pipeline(detections=[])
        out_d = tmp_path / "zero_out"
        results = pipe.process_page(Image.new("RGB", (200, 200)), output_dir=out_d)
        assert results == []
        assert not (out_d / "images").exists()

    def test_process_document_unsupported_type_raises_type_error(self, tmp_path: Path) -> None:
        """Verifies process_document raises TypeError for invalid input."""
        pipe = _create_mock_pipeline()
        with pytest.raises(TypeError, match="Unsupported document type"):
            pipe.process_document(12345, output_dir=tmp_path)

    def test_process_document_nonexistent_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """Verifies process_document raises FileNotFoundError for non-existent document."""
        pipe = _create_mock_pipeline()
        with pytest.raises(FileNotFoundError):
            pipe.process_document(tmp_path / "missing.pdf", output_dir=tmp_path)
