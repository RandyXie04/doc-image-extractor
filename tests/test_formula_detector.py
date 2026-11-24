# -*- coding: utf-8 -*-
"""
tests/test_formula_detector.py: Comprehensive Test Suite for Stage 1 FormulaDetector
===================================================================================
Covers 7 test classes and 31 test cases verifying:
1. Model loading, ONNX graph integrity, and execution provider fallback.
2. Preprocessing, aspect-preserving letterbox, and tensor normalization.
3. Coordinate unmapping, geometry transforms, boundary clamping, and NMS.
4. Short inline formula retention (f(x)=ax+bx, w < 0.15W) and dense mixed-text encapsulation.
5. FormulaDetectionContract compliance, immutability, and schema enforcement.
6. Forensic anti-gaming checks (dynamic 1300px shift, pure prose negative control, threshold response).
7. Robustness, solid canvases, extreme aspect ratios, and input polymorphism.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import onnxruntime as ort
from pydantic import ValidationError
from PIL import Image, ImageDraw, ImageFont
import pytest

from config import PATHS
from src.extraction.contracts import FormulaDetectionContract
from src.extraction.formula_detector import FormulaDetector

pytestmark = pytest.mark.heavy


# ── Shared Session Fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def formula_onnx_path() -> Path:
    """Locates pdf_extract_mfd.onnx or falls back to yolo_v8_ft.onnx."""
    candidates = [
        PATHS.models_dir / "pdf_extract_mfd.onnx",
        PATHS.models_dir / "yolo_v8_ft.onnx",
        Path("models/pdf_extract_mfd.onnx"),
        Path("models/yolo_v8_ft.onnx"),
    ]
    for p in candidates:
        resolved = p.resolve()
        if resolved.is_file() and resolved.stat().st_size > 100_000_000:
            return resolved
    pytest.skip("No MFD ONNX model available on disk. Run export_mfd_onnx.py first.")


@pytest.fixture(scope="session")
def detector(formula_onnx_path: Path) -> FormulaDetector:
    """Cached FormulaDetector instance using default provider chain."""
    return FormulaDetector(model_path=formula_onnx_path)


@pytest.fixture(scope="session")
def detector_cpu(formula_onnx_path: Path) -> FormulaDetector:
    """Cached FormulaDetector instance strictly pinned to CPUExecutionProvider."""
    return FormulaDetector(model_path=formula_onnx_path, providers=["CPUExecutionProvider"])


@pytest.fixture(scope="session")
def test_font_factory():
    """Dynamically resolves available TrueType fonts for synthetic text generation."""
    def _get_font(size: int = 36, lang: str = "en") -> ImageFont.ImageFont:
        font_candidates = (
            ["msyh.ttc", "simsun.ttc", "arial.ttf"]
            if lang == "cn"
            else ["times.ttf", "arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]
        )
        for name in font_candidates:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    return _get_font


@pytest.fixture
def synthetic_doc_factory(test_font_factory):
    """Factory fixture generating document page images with rendered text elements."""
    def _create(
        width: int = 1600,
        height: int = 2000,
        bg_color: Tuple[int, int, int] = (255, 255, 255),
        items: Optional[List[Dict[str, Any]]] = None,
    ) -> Image.Image:
        img = Image.new("RGB", (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        default_font = test_font_factory(36)
        if items:
            for item in items:
                pos = item.get("pos", (100, 100))
                text = item.get("text", "")
                fill = item.get("fill", (0, 0, 0))
                font = item.get("font", default_font)
                draw.text(pos, text, fill=fill, font=font)
        return img

    return _create


# ── Class 1: Model Loading & Execution Providers ─────────────────────────────

@pytest.mark.integration
class TestFormulaDetectorModelLoading:
    """Validates ONNX file integrity, session creation, and provider fallback."""

    def test_onnx_model_file_validity(self, formula_onnx_path: Path) -> None:
        onnx = pytest.importorskip("onnx")
        assert formula_onnx_path.exists()
        assert formula_onnx_path.stat().st_size > 150_000_000

        onnx.checker.check_model(str(formula_onnx_path))
        proto = onnx.load(str(formula_onnx_path))

        assert len(proto.graph.input) == 1
        inp = proto.graph.input[0]
        assert inp.name == "images"
        in_dims = [d.dim_value for d in inp.type.tensor_type.shape.dim]
        assert in_dims == [1, 3, 1280, 1280]

        assert len(proto.graph.output) == 1
        out = proto.graph.output[0]
        assert out.name == "output0"
        out_dims = [d.dim_value for d in out.type.tensor_type.shape.dim]
        assert out_dims == [1, 6, 33600]

    def test_session_initialization_default_providers(self, detector: FormulaDetector) -> None:
        assert detector.session is not None
        assert detector.active_provider in [
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
        info = detector.get_model_info()
        assert info["target_imgsz"] == 1280
        assert info["input_name"] == "images"
        assert info["output_name"] == "output0"

    def test_explicit_cpu_provider(self, detector_cpu: FormulaDetector) -> None:
        assert detector_cpu.active_provider == "CPUExecutionProvider"

    def test_unsupported_provider_fallback(self, formula_onnx_path: Path) -> None:
        fallback_detector = FormulaDetector(
            model_path=formula_onnx_path,
            providers=["NonExistentProvider", "CPUExecutionProvider"],
        )
        assert fallback_detector.session is not None
        assert fallback_detector.active_provider == "CPUExecutionProvider"

    def test_missing_model_raises_filenotfound(self, tmp_path: Path) -> None:
        missing_file = tmp_path / "absent_model.onnx"
        with pytest.raises(FileNotFoundError):
            FormulaDetector(model_path=missing_file)


# ── Class 2: Preprocessing & Letterbox Geometry ──────────────────────────────

@pytest.mark.integration
class TestPreprocessingAndLetterbox:
    """Validates aspect-ratio preservation, padding math, and tensor normalization."""

    def test_letterbox_portrait(self, detector: FormulaDetector) -> None:
        # Portrait: 1600 (W) x 2000 (H)
        img = np.ones((2000, 1600, 3), dtype=np.uint8) * 255
        padded, r, (dw, dh) = detector.letterbox(img, (1280, 1280))

        # r = 1280 / 2000 = 0.64
        assert abs(r - 0.64) < 1e-4
        assert abs(dw - 128.0) < 0.5
        assert abs(dh - 0.0) < 0.5
        assert padded.shape == (1280, 1280, 3)

        # Padding pixels on left should be neutral gray (114, 114, 114)
        assert tuple(padded[640, 10]) == (114, 114, 114)

    def test_letterbox_landscape(self, detector: FormulaDetector) -> None:
        # Landscape: 2000 (W) x 1200 (H)
        img = np.ones((1200, 2000, 3), dtype=np.uint8) * 255
        padded, r, (dw, dh) = detector.letterbox(img, (1280, 1280))

        # r = 1280 / 2000 = 0.64
        assert abs(r - 0.64) < 1e-4
        assert abs(dw - 0.0) < 0.5
        assert abs(dh - 256.0) < 0.5
        assert padded.shape == (1280, 1280, 3)

        # Padding pixels on top should be neutral gray
        assert tuple(padded[10, 640]) == (114, 114, 114)

    def test_letterbox_square(self, detector: FormulaDetector) -> None:
        img = np.ones((1280, 1280, 3), dtype=np.uint8) * 200
        padded, r, (dw, dh) = detector.letterbox(img, (1280, 1280))

        assert abs(r - 1.0) < 1e-4
        assert abs(dw - 0.0) < 1e-4
        assert abs(dh - 0.0) < 1e-4
        assert padded.shape == (1280, 1280, 3)

    def test_tensor_format_and_normalization(self, detector: FormulaDetector) -> None:
        pil_img = Image.new("RGB", (1600, 2000), (200, 200, 200))
        tensor = detector.preprocess(pil_img)

        assert isinstance(tensor, np.ndarray)
        assert tensor.dtype == np.float32
        assert tensor.shape == (1, 3, 1280, 1280)
        assert tensor.min() >= 0.0
        assert tensor.max() <= 1.0


# ── Class 3: Postprocessing & Coordinate Geometry ────────────────────────────

@pytest.mark.integration
class TestPostprocessingAndCoordinateUnmapping:
    """Validates xywh->xyxy, unmapping precision, boundary clamping, and NMS."""

    def test_xywh_to_xyxy(self) -> None:
        # 1D test: [cx=100, cy=200, w=50, h=80] -> [75, 160, 125, 240]
        out_1d = FormulaDetector.xywh2xyxy([100, 200, 50, 80])
        np.testing.assert_allclose(out_1d, [75.0, 160.0, 125.0, 240.0])

        # 2D test
        arr_2d = np.array([[100, 200, 50, 80], [300, 400, 100, 120]], dtype=np.float32)
        out_2d = FormulaDetector.xywh2xyxy(arr_2d)
        expected = np.array([[75, 160, 125, 240], [250, 340, 350, 460]], dtype=np.float32)
        np.testing.assert_allclose(out_2d, expected)

    def test_coordinate_unmapping_roundtrip_precision(self) -> None:
        orig_box = (300.0, 400.0, 500.0, 460.0)
        r = 0.64
        dw, dh = 128.0, 0.0

        # Project into letterbox coordinates
        lb_box = (
            orig_box[0] * r + dw,
            orig_box[1] * r + dh,
            orig_box[2] * r + dw,
            orig_box[3] * r + dh,
        )

        unmapped = FormulaDetector.unmap_box(lb_box, ratio=r, pad=(dw, dh))
        for u, o in zip(unmapped, orig_box):
            assert abs(u - o) < 1e-4

    def test_boundary_coordinate_clamping(self) -> None:
        # Box extending past canvas boundaries
        lb_box = (10.0, -50.0, 1500.0, 1400.0)
        unmapped = FormulaDetector.unmap_box(
            lb_box, ratio=0.64, pad=(128.0, 0.0), orig_w=1600.0, orig_h=2000.0
        )
        x1, y1, x2, y2 = unmapped
        assert 0.0 <= x1 <= x2 <= 1600.0
        assert 0.0 <= y1 <= y2 <= 2000.0

    def test_nms_suppression(self) -> None:
        boxes = np.array(
            [
                [100.0, 100.0, 200.0, 200.0],
                [105.0, 105.0, 205.0, 205.0],  # IoU > 0.8 with box 0
                [500.0, 500.0, 600.0, 600.0],  # Disjoint box
            ],
            dtype=np.float32,
        )
        scores = np.array([0.90, 0.80, 0.85], dtype=np.float32)
        keep = FormulaDetector.nms(boxes, scores, iou_threshold=0.45)

        # Box 1 suppressed by Box 0; Box 2 retained
        assert keep == [0, 2]

    def test_absolute_noise_size_filtering(self, detector: FormulaDetector) -> None:
        # Construct synthetic prediction matrix (33600, 6)
        preds = np.zeros((1, 6, 33600), dtype=np.float32)
        # Small noise box: w=5, h=5 (in letterbox space, unmapped w < 12)
        preds[0, 0, 0] = 500.0  # cx
        preds[0, 1, 0] = 500.0  # cy
        preds[0, 2, 0] = 5.0    # w
        preds[0, 3, 0] = 5.0    # h
        preds[0, 4, 0] = 0.95   # Class 0 confidence

        results = detector.postprocess(
            preds=preds,
            orig_w=1600,
            orig_h=2000,
            ratio=0.64,
            pad=(128.0, 0.0),
            conf_threshold=0.20,
            min_width=12.0,
            min_height=10.0,
        )
        assert len(results) == 0


# ── Class 4: Short Formula Retention & Dense Text Encapsulation ──────────────

@pytest.mark.integration
class TestShortFormulaRetention:
    """Validates preservation of short formulas (f(x)=ax+bx) and dense text immunity."""

    def test_short_inline_formula_f_x_ax_bx_detected(
        self, detector: FormulaDetector, test_font_factory
    ) -> None:
        width, height = 1600, 2000
        img = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = test_font_factory(36, lang="en")

        text = "Given a linear mapping f(x) = ax + bx for all real x in R."
        draw.text((100, 300), text, fill=(0, 0, 0), font=font)

        detections = detector.detect(img)
        assert len(detections) >= 1

        inline_dets = [d for d in detections if d.category == "inline"]
        assert len(inline_dets) >= 1

        det = inline_dets[0]
        assert det.class_id == 0
        assert det.score >= 0.70

        box_w = det.box[2] - det.box[0]
        # Invariant: formula is strictly within previously dropped bracket (< 0.15 * 1600 = 240)
        assert box_w < width * 0.15
        assert box_w >= 12.0

    def test_short_formula_retention_on_wide_page(
        self, detector: FormulaDetector, test_font_factory
    ) -> None:
        width, height = 2400, 1600
        img = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = test_font_factory(36, lang="en")

        draw.text((200, 400), "Consider the identity f(x) = ax + bx in domain D.", fill=(0, 0, 0), font=font)

        detections = detector.detect(img)
        assert len(detections) >= 1
        det = detections[0]
        box_w = det.box[2] - det.box[0]
        # Box width is ~7% of page width, well below 15%
        assert box_w < width * 0.15

    def test_multiple_short_formulas_in_single_paragraph(
        self, detector: FormulaDetector, test_font_factory
    ) -> None:
        width, height = 1600, 2000
        img = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = test_font_factory(36, lang="en")

        draw.text((100, 300), "First equation is a^2 + b^2 = c^2 and second is f(x) = y.", fill=(0, 0, 0), font=font)

        detections = detector.detect(img)
        assert len(detections) >= 1
        # Reading order sorting: boxes sorted by y then x
        for i in range(len(detections) - 1):
            assert detections[i].box[1] <= detections[i + 1].box[1]

    def test_dense_text_surrounding_inline_formula(
        self, detector: FormulaDetector, test_font_factory
    ) -> None:
        """
        User Feedback Mandate: Verifies that short formula f(x)=ax+bx embedded in dense
        mixed Chinese and English explanatory prose is detected cleanly, surrounding prose
        produces ZERO false positives, and the bounding box tightly encapsulates the formula.
        """
        w, h = 1600, 2200
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font_cn = test_font_factory(32, lang="cn")
        font_en = test_font_factory(36, lang="en")

        # 1. Dense Chinese prose preamble (5 lines)
        y = 120
        preamble = [
            "第 1 章 偏微分方程與流體力學基礎理論分析",
            "在現代計算流體力學與數值模擬工程中，我們經常需要針對複雜流場進行多物理量聯合求解。",
            "本節將探討一維對流擴散方程在不同邊界條件下的解析解與有限差分格式的穩定性準則。",
            "根據柯西-柯瓦列夫斯卡婭定理，給定充分光滑的初邊值條件時，解在局部區域內存在且唯一。",
            "考慮一個典型的線性對流系統，其狀態演化關係式由以下行內方程式給出：",
        ]
        for line in preamble:
            draw.text((100, y), line, fill=(0, 0, 0), font=font_cn)
            y += 55

        # 2. Mixed text line with formula embedded
        y += 20
        draw.text((100, y), "假設狀態轉移函數滿足公式 ", fill=(0, 0, 0), font=font_cn)
        formula_x_start = 520
        formula_y_start = y
        draw.text((formula_x_start, y), "f(x) = ax + bx", fill=(0, 0, 0), font=font_en)
        draw.text((830, y), "，其中係數 a 與 b 皆為實數常數。", fill=(0, 0, 0), font=font_cn)
        y += 75

        # 3. Dense Chinese prose following text (4 lines without standalone formulas)
        following = [
            "更進一步地，當我們將上述局部代數結構推廣至高維緊緻黎曼流形上時，必須引入協變導數。",
            "這意味著在局部坐標系下的差分算子必須保持幾何協變性，否則將導致數值耗散與偽震盪現象。",
            "文獻指出，若未能適當處理邊界層網格縱橫比，誤差將以指數級傳播並破壞全局收斂。",
            "綜上所述，在進行大規模並行計算之前，必須先對原始控制方程進行無量綱化預處理。",
        ]
        for line in following:
            draw.text((100, y), line, fill=(0, 0, 0), font=font_cn)
            y += 55

        detections = detector.detect(img)
        assert len(detections) >= 1

        # Locate the formula detection corresponding to f(x)=ax+bx
        f_det = None
        for d in detections:
            # Check vertical alignment with formula line (formula_y_start ~ 415)
            if abs(d.box[1] - formula_y_start) < 40:
                f_det = d
                break

        assert f_det is not None, "Failed to locate inline formula detection near formula line!"
        assert f_det.category == "inline"
        assert f_det.class_id == 0
        assert f_det.score >= 0.75

        # Tight encapsulation assertions:
        # Formula was rendered at x=520, ending ~750. Surrounding Chinese text starts at x=830.
        assert f_det.box[0] >= 480.0, f"Box x1 ({f_det.box[0]}) encroaches on preceding text!"
        assert f_det.box[2] <= 820.0, f"Box x2 ({f_det.box[2]}) encroaches on succeeding text!"
        assert f_det.box[1] >= formula_y_start - 30.0
        assert f_det.box[3] <= formula_y_start + 70.0

        # Assert dense text lines do NOT generate formula detections
        for d in detections:
            # Preamble lines y: [120, 395]. None of preamble lines should be detected.
            assert not (100.0 <= d.box[1] <= 380.0), f"False positive detected in preamble: {d}"


# ── Class 5: FormulaDetectionContract Compliance ─────────────────────────────

@pytest.mark.integration
class TestFormulaDetectionContractCompliance:
    """Validates contract structure, field constraints, immutability, and forbid extra."""

    def test_return_type_is_contract_list(
        self, detector: FormulaDetector, synthetic_doc_factory, test_font_factory
    ) -> None:
        img = synthetic_doc_factory(
            items=[{"text": "f(x) = ax + bx", "pos": (200, 400), "font": test_font_factory(36)}]
        )
        detections = detector.detect(img)
        assert isinstance(detections, list)
        assert all(isinstance(d, FormulaDetectionContract) for d in detections)

    def test_contract_immutability(
        self, detector: FormulaDetector, synthetic_doc_factory, test_font_factory
    ) -> None:
        img = synthetic_doc_factory(
            items=[{"text": "f(x) = ax + bx", "pos": (200, 400), "font": test_font_factory(36)}]
        )
        detections = detector.detect(img)
        assert len(detections) >= 1
        det = detections[0]
        with pytest.raises((ValidationError, TypeError)):
            det.score = 0.999  # Should be rejected because frozen=True

    def test_contract_forbid_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            FormulaDetectionContract(
                box=(0.0, 0.0, 10.0, 10.0),
                score=0.9,
                category="inline",
                class_id=0,
                forbidden_extra="invalid",  # type: ignore
            )

    def test_contract_class_category_consistency(
        self, detector: FormulaDetector, synthetic_doc_factory, test_font_factory
    ) -> None:
        img = synthetic_doc_factory(
            items=[{"text": "f(x) = ax + bx", "pos": (200, 400), "font": test_font_factory(36)}]
        )
        detections = detector.detect(img)
        for det in detections:
            assert 0.0 <= det.score <= 1.0
            assert 0.0 <= det.box[0] < det.box[2] <= 1600.0
            assert 0.0 <= det.box[1] < det.box[3] <= 2000.0
            if det.category == "inline":
                assert det.class_id == 0
            elif det.category == "isolated":
                assert det.class_id == 1


# ── Class 6: Forensic Anti-Gaming Integrity Guardrails ───────────────────────

@pytest.mark.integration
class TestForensicIntegrityAndDynamicSensitivity:
    """Anti-gaming tests preventing hardcoded, stubbed, or facade implementations."""

    def test_forensic_position_sensitivity(
        self, detector: FormulaDetector, test_font_factory
    ) -> None:
        font = test_font_factory(36, lang="en")
        w, h = 1600, 2000

        # Position A: Render formula at y = 200
        img_a = Image.new("RGB", (w, h), (255, 255, 255))
        ImageDraw.Draw(img_a).text((100, 200), "f(x) = ax + bx", fill=(0, 0, 0), font=font)
        dets_a = detector.detect(img_a)
        assert len(dets_a) >= 1
        y1_a = dets_a[0].box[1]

        # Position B: Render formula at y = 1500 (1300px offset)
        img_b = Image.new("RGB", (w, h), (255, 255, 255))
        ImageDraw.Draw(img_b).text((100, 1500), "f(x) = ax + bx", fill=(0, 0, 0), font=font)
        dets_b = detector.detect(img_b)
        assert len(dets_b) >= 1
        y1_b = dets_b[0].box[1]

        measured_shift = y1_b - y1_a
        # Shift must be proportional to 1300px within 30px tolerance
        assert abs(measured_shift - 1300.0) < 30.0, (
            f"Expected ~1300px shift, got {measured_shift:.1f}px. "
            "Model output must dynamically track rendered geometry."
        )

    def test_forensic_negative_control_pure_prose(
        self, detector: FormulaDetector, test_font_factory
    ) -> None:
        w, h = 1600, 2000
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = test_font_factory(32, lang="en")

        prose_lines = [
            "This is a standard document paragraph describing software architecture and design.",
            "It explains modular boundaries, interfaces, adapters, and separation of concerns.",
            "No mathematical formulas, variables, or equations are included anywhere in this section.",
            "All sentences are composed entirely of ordinary English dictionary words and punctuation.",
        ]
        y = 200
        for line in prose_lines:
            draw.text((100, y), line, fill=(0, 0, 0), font=font)
            y += 60

        detections = detector.detect(img)
        assert len(detections) == 0, f"Expected 0 false positives on pure prose, got {len(detections)}"

    def test_forensic_confidence_threshold_filtering(
        self, detector: FormulaDetector, test_font_factory
    ) -> None:
        w, h = 1600, 2000
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = test_font_factory(36, lang="en")
        draw.text((100, 300), "f(x) = ax + bx", fill=(0, 0, 0), font=font)

        dets_low = detector.detect(img, conf_threshold=0.20)
        dets_high = detector.detect(img, conf_threshold=0.95)

        assert len(dets_high) <= len(dets_low)
        for d in dets_high:
            assert d.score >= 0.95

    def test_forensic_live_session_attributes(self, detector: FormulaDetector) -> None:
        assert isinstance(detector.session, ort.InferenceSession)
        assert len(detector.session.get_inputs()) == 1
        assert detector.session.get_inputs()[0].name == "images"
        assert len(detector.session.get_outputs()) == 1
        assert detector.session.get_outputs()[0].name == "output0"


# ── Class 7: Robustness & Adversarial Boundaries ─────────────────────────────

@pytest.mark.integration
class TestRobustnessAndEdgeCases:
    """Stress tests across solid backgrounds, unusual dimensions, and polymorph inputs."""

    def test_robustness_solid_colors(self, detector: FormulaDetector) -> None:
        for color in [(255, 255, 255), (0, 0, 0), (114, 114, 114)]:
            img = Image.new("RGB", (800, 800), color)
            dets = detector.detect(img)
            assert len(dets) == 0

    def test_robustness_oversized_canvas(
        self, detector: FormulaDetector, test_font_factory
    ) -> None:
        w, h = 3000, 4000
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = test_font_factory(48, lang="en")
        draw.text((200, 600), "f(x) = ax + bx", fill=(0, 0, 0), font=font)

        dets = detector.detect(img)
        assert isinstance(dets, list)
        for d in dets:
            assert 0.0 <= d.box[0] < d.box[2] <= float(w)
            assert 0.0 <= d.box[1] < d.box[3] <= float(h)

    def test_robustness_undersized_canvas(self, detector: FormulaDetector) -> None:
        img = Image.new("RGB", (80, 80), (255, 255, 255))
        dets = detector.detect(img)
        assert isinstance(dets, list)
        assert len(dets) == 0

    def test_robustness_extreme_aspect_ratios(
        self, detector: FormulaDetector, test_font_factory
    ) -> None:
        font = test_font_factory(36, lang="en")

        # Tall vertical strip: 400 x 3000
        tall = Image.new("RGB", (400, 3000), (255, 255, 255))
        ImageDraw.Draw(tall).text((50, 500), "f(x) = ax", fill=(0, 0, 0), font=font)
        dets_tall = detector.detect(tall)
        assert isinstance(dets_tall, list)

        # Wide horizontal banner: 3000 x 400
        wide = Image.new("RGB", (3000, 400), (255, 255, 255))
        ImageDraw.Draw(wide).text((200, 150), "f(x) = ax + bx", fill=(0, 0, 0), font=font)
        dets_wide = detector.detect(wide)
        assert isinstance(dets_wide, list)

    def test_input_polymorphism(
        self, detector: FormulaDetector, tmp_path: Path, test_font_factory
    ) -> None:
        w, h = 1600, 2000
        pil_img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(pil_img)
        font = test_font_factory(36, lang="en")
        draw.text((200, 400), "f(x) = ax + bx", fill=(0, 0, 0), font=font)

        # Save to disk for Path / str tests
        img_path = tmp_path / "poly_test.png"
        pil_img.save(str(img_path))

        rgb_arr = np.array(pil_img)
        bgr_arr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)

        # Execute 5 polymorphic formats
        res_pil = detector.detect(pil_img)
        res_rgb = detector.detect(rgb_arr)
        res_bgr = detector.detect(bgr_arr, is_bgr=True)
        res_path = detector.detect(img_path)
        res_str = detector.detect(str(img_path))

        assert len(res_pil) >= 1
        assert len(res_pil) == len(res_rgb) == len(res_bgr) == len(res_path) == len(res_str)

        # Verify bounding box equivalence across input modalities
        box_pil = res_pil[0].box
        box_rgb = res_rgb[0].box
        for bp, br in zip(box_pil, box_rgb):
            assert abs(bp - br) < 0.5
