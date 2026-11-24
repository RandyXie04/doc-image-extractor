# -*- coding: utf-8 -*-
"""
tests/test_formula_detector_adversarial.py: Adversarial Stress Test Suite for MFD
==================================================================================
Empirical verification suite challenging Stage 1 FormulaDetector against:
1. Numerical Parity: Bit-for-bit / epsilon comparison between ONNX and PyTorch weights.
2. Dense Mixed Prose Encapsulation: Mixed Chinese and English paragraphs surrounding
   inline formulas, verifying 0 false positives and non-encroaching bounding boxes.
3. Proximity & NMS Separation: Multiple inline formulas on the same line or tightly
   adjacent lines cleanly resolved as independent detections without NMS merging.
4. Extreme Boundary Conditions: Formula touching canvas borders (x < 5, y < 5),
   giant multi-line matrix expressions, and tiny font sizes (18, 20, 24).
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw, ImageFont
import pytest
import torch

from config import PATHS
from src.extraction.formula_detector import FormulaDetector

pytestmark = pytest.mark.heavy


@pytest.fixture(scope="session")
def onnx_model_path() -> Path:
    p = PATHS.models_dir / "pdf_extract_mfd.onnx"
    if not p.is_file():
        pytest.skip(f"MFD ONNX model not found at {p}")
    return p


@pytest.fixture(scope="session")
def pytorch_model_path() -> Path:
    p = PATHS.models_dir / "yolo_v8_ft.pt"
    if not p.is_file():
        pytest.skip(f"MFD PyTorch weights not found at {p}")
    return p


@pytest.fixture(scope="session")
def detector(onnx_model_path: Path) -> FormulaDetector:
    return FormulaDetector(model_path=onnx_model_path)


@pytest.fixture(scope="session")
def fonts():
    """Resolves standard TrueType fonts available on the OS."""
    def _font(name: str, size: int) -> ImageFont.ImageFont:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            return ImageFont.load_default()

    return {
        "cn_regular": _font("msyh.ttc", 28),
        "en_regular": _font("times.ttf", 28),
        "math_regular": _font("times.ttf", 28),
        "math_large": _font("times.ttf", 36),
        "math_18": _font("times.ttf", 18),
        "math_20": _font("times.ttf", 20),
        "math_24": _font("times.ttf", 24),
    }


class TestNumericalParity:
    """Verifies that the exported ONNX model maintains numerical parity with PyTorch weights."""

    def test_pytorch_vs_onnx_random_input_parity(
        self, onnx_model_path: Path, pytorch_model_path: Path
    ) -> None:
        """Compares raw forward pass tensors on synthetic random float32 input."""
        np.random.seed(42)
        dummy = np.random.randn(1, 3, 1280, 1280).astype(np.float32)

        # ONNX Runtime forward pass
        sess = ort.InferenceSession(str(onnx_model_path), providers=["CPUExecutionProvider"])
        onnx_out = sess.run(None, {"images": dummy})[0]

        # PyTorch forward pass
        from ultralytics import YOLO
        pt = YOLO(str(pytorch_model_path))
        net = pt.model.eval()
        with torch.no_grad():
            pt_out = net(torch.from_numpy(dummy))[0].cpu().numpy()

        diff = np.abs(pt_out - onnx_out)
        max_diff = float(np.max(diff))
        mean_diff = float(np.mean(diff))

        assert max_diff < 2e-3, f"Max diff exceeded threshold: {max_diff}"
        assert mean_diff < 5e-5, f"Mean diff exceeded threshold: {mean_diff}"

    def test_pytorch_vs_onnx_document_image_parity(
        self, detector: FormulaDetector, pytorch_model_path: Path, fonts: dict
    ) -> None:
        """Compares end-to-end postprocessed detections on a realistic document image."""
        img = Image.new("RGB", (1600, 2000), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((200, 400), "f(x) = ax + bx", fill=(0, 0, 0), font=fonts["math_large"])
        draw.text((200, 800), "E = mc^2 + int_0^1 x dx", fill=(0, 0, 0), font=fonts["math_large"])

        tensor = detector.preprocess(img)

        # ONNX forward pass
        onnx_preds = detector.session.run([detector.output_name], {detector.input_name: tensor})[0]

        # PyTorch forward pass
        from ultralytics import YOLO
        pt = YOLO(str(pytorch_model_path))
        net = pt.model.eval()
        with torch.no_grad():
            pt_preds = net(torch.from_numpy(tensor))[0].cpu().numpy()

        orig_w, orig_h = img.width, img.height
        _, ratio, (dw, dh) = detector.letterbox(np.array(img), (1280, 1280))

        dets_onnx = detector.postprocess(onnx_preds, orig_w, orig_h, ratio, (dw, dh))
        dets_pt = detector.postprocess(pt_preds, orig_w, orig_h, ratio, (dw, dh))

        assert len(dets_onnx) == len(dets_pt), f"Detection count mismatch: {len(dets_onnx)} vs {len(dets_pt)}"
        for do, dp in zip(dets_onnx, dets_pt):
            assert do.category == dp.category
            assert do.class_id == dp.class_id
            assert abs(do.score - dp.score) < 0.01, f"Score drift: {do.score} vs {dp.score}"
            for bo, bp in zip(do.box, dp.box):
                assert abs(bo - bp) < 1.0, f"Box coordinate drift: {do.box} vs {dp.box}"


class TestDenseProseEncapsulation:
    """Verifies that surrounding dense mixed CJK and English text produces zero false positives and tight boxes."""

    def test_dense_prose_zero_false_positives(
        self, detector: FormulaDetector, fonts: dict
    ) -> None:
        """Verifies 0 false positive detections across multi-line Chinese and English prose blocks."""
        img = Image.new("RGB", (1600, 2200), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # 8 lines of pure Chinese prose
        cn_lines = [
            "在本章的數值分析中，我們探討高階偏微分方程在多維網格上的離散化誤差。",
            "傳統的有限差分方法在邊界層附近往往會產生數值振盪，導致收斂速度顯著下降。",
            "為了解決此一問題，近期的研究多採用加權本質無振盪格式以及間斷伽遼金方法。",
            "這些方法能夠在保持高階精度的同時，有效地抑制激波與強梯度區域的數值假訊號。",
            "然而在計算流體力學的實際工程應用中，網格生成與自適應加密依然耗費大量資源。",
            "因此，結合機器學習輔助的數值求解器近年來受到廣泛關注，展現出極高的潛力。",
            "特別是基於物理資訊的神經網路，能夠將微分算子直接納入損失函數的約束條件中。",
            "在這種架構下，系統的泛化能力取決於殘差項在計算域內部與邊界上的積分精度。"
        ]
        y = 100
        for line in cn_lines:
            draw.text((100, y), line, fill=(0, 0, 0), font=fonts["cn_regular"])
            y += 45
        cn_prose_end = y

        # 8 lines of pure English prose (pure alphabetic, no standalone numbers)
        en_lines = [
            "To rigorously quantify the asymptotic stability of the proposed dynamical system,",
            "we construct a Lyapunov candidate function that maps the phase space onto real numbers.",
            "Under standard assumptions regarding Lipschitz continuity and uniform boundedness,",
            "the time derivative along the trajectories satisfies a strict negative definiteness condition.",
            "Furthermore, singular perturbation analysis reveals that the fast and slow manifolds decouple,",
            "enabling the reduction of order without sacrificing the fidelity of transient dynamics.",
            "Experimental evaluations on standard benchmark datasets confirm our theoretical derivations,",
            "achieving substantial reduction in error propagation relative to classical schemes."
        ]
        y += 30
        en_prose_start = y
        for line in en_lines:
            draw.text((100, y), line, fill=(0, 0, 0), font=fonts["en_regular"])
            y += 42
        en_prose_end = y

        # Mixed line: inline formula embedded in Chinese prose
        y += 40
        formula_y = y
        draw.text((100, y), "由此可得狀態方程式 ", fill=(0, 0, 0), font=fonts["cn_regular"])
        bbox_pre = draw.textbbox((100, y), "由此可得狀態方程式 ", font=fonts["cn_regular"])
        draw.text((bbox_pre[2] + 10, y), "f(x) = ax + bx", fill=(0, 0, 0), font=fonts["math_regular"])
        bbox_form = draw.textbbox((bbox_pre[2] + 10, y), "f(x) = ax + bx", font=fonts["math_regular"])
        draw.text((bbox_form[2] + 10, y), " 在定義域區間內具備一致連續性。", fill=(0, 0, 0), font=fonts["cn_regular"])

        # 4 lines of trailing Chinese prose
        y += 60
        trailing_cn_start = y
        for line in cn_lines[:4]:
            draw.text((100, y), line, fill=(0, 0, 0), font=fonts["cn_regular"])
            y += 45

        dets = detector.detect(img)

        # Check zero false positives in pure prose regions
        fp_cn = [d for d in dets if d.box[3] < cn_prose_end]
        fp_en = [d for d in dets if en_prose_start < d.box[1] and d.box[3] < en_prose_end]
        fp_trailing = [d for d in dets if d.box[1] > trailing_cn_start]

        assert len(fp_cn) == 0, f"False positive in pure Chinese prose: {fp_cn}"
        assert len(fp_en) == 0, f"False positive in pure English prose: {fp_en}"
        assert len(fp_trailing) == 0, f"False positive in trailing Chinese prose: {fp_trailing}"

        # Confirm formula was detected
        form_dets = [d for d in dets if abs(d.box[1] - formula_y) < 40]
        assert len(form_dets) == 1, f"Expected 1 formula detection, got {len(form_dets)}"
        assert form_dets[0].category == "inline"

    def test_bounding_box_tightness_and_non_encroachment(
        self, detector: FormulaDetector, fonts: dict
    ) -> None:
        """Verifies formula box tightly bounds glyphs and does NOT swallow preceding or succeeding Chinese characters."""
        img = Image.new("RGB", (1600, 400), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        y = 150
        pre_str = "根據定義方程式 "
        form_str = "f(x) = ax + bx"
        post_str = " 恆成立於實數空間。"

        draw.text((100, y), pre_str, fill=(0, 0, 0), font=fonts["cn_regular"])
        b_pre = draw.textbbox((100, y), pre_str, font=fonts["cn_regular"])

        form_start = b_pre[2] + 10
        draw.text((form_start, y), form_str, fill=(0, 0, 0), font=fonts["math_regular"])
        b_form = draw.textbbox((form_start, y), form_str, font=fonts["math_regular"])

        post_start = b_form[2] + 10
        draw.text((post_start, y), post_str, fill=(0, 0, 0), font=fonts["cn_regular"])
        b_post = draw.textbbox((post_start, y), post_str, font=fonts["cn_regular"])

        dets = detector.detect(img)
        assert len(dets) == 1, f"Expected exactly 1 detection, got {len(dets)}"
        det_box = dets[0].box

        # Non-encroachment assertions:
        # Box must start at or after the end of preceding text (with 5px safety margin for antialiasing)
        assert det_box[0] >= b_pre[2] - 5.0, (
            f"Formula box encroach on preceding Chinese: box x1={det_box[0]} < pre_end={b_pre[2]}"
        )
        # Box must end at or before the start of succeeding text (with 5px safety margin)
        assert det_box[2] <= post_start + 5.0, (
            f"Formula box encroach on succeeding Chinese: box x2={det_box[2]} > post_start={post_start}"
        )
        # Bounding box tightness: within 15px of rendered glyph boundaries
        assert abs(det_box[0] - b_form[0]) <= 15.0, f"Left edge misalignment: {det_box[0]} vs {b_form[0]}"
        assert abs(det_box[2] - b_form[2]) <= 15.0, f"Right edge misalignment: {det_box[2]} vs {b_form[2]}"


class TestProximityAndNmsSeparation:
    """Verifies that multiple inline formulas in close proximity are cleanly separated by NMS."""

    def test_multiple_inline_formulas_same_line(
        self, detector: FormulaDetector, fonts: dict
    ) -> None:
        """Verifies two inline formulas separated by a short Chinese connector on the same line are not merged."""
        img = Image.new("RGB", (1600, 400), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        y = 150
        draw.text((100, y), "若 ", fill=(0, 0, 0), font=fonts["cn_regular"])
        b1 = draw.textbbox((100, y), "若 ", font=fonts["cn_regular"])

        f1_x = b1[2] + 10
        draw.text((f1_x, y), "f(x) = ax + b", fill=(0, 0, 0), font=fonts["math_regular"])
        b_f1 = draw.textbbox((f1_x, y), "f(x) = ax + b", font=fonts["math_regular"])

        conn_x = b_f1[2] + 10
        draw.text((conn_x, y), " 且 ", fill=(0, 0, 0), font=fonts["cn_regular"])
        b_conn = draw.textbbox((conn_x, y), " 且 ", font=fonts["cn_regular"])

        f2_x = b_conn[2] + 10
        draw.text((f2_x, y), "g(y) = cy + d", fill=(0, 0, 0), font=fonts["math_regular"])
        b_f2 = draw.textbbox((f2_x, y), "g(y) = cy + d", font=fonts["math_regular"])

        draw.text((b_f2[2] + 10, y), " 為兩組映射函數。", fill=(0, 0, 0), font=fonts["cn_regular"])

        dets = detector.detect(img)
        assert len(dets) == 2, f"Expected 2 separate detections on same line, got {len(dets)}"
        assert dets[0].category == "inline"
        assert dets[1].category == "inline"
        # Verify clean horizontal gap between detections
        assert dets[0].box[2] < dets[1].box[0], (
            f"Detections overlap horizontally: {dets[0].box} and {dets[1].box}"
        )

    def test_multiple_inline_formulas_adjacent_lines(
        self, detector: FormulaDetector, fonts: dict
    ) -> None:
        """Verifies two inline formulas on consecutive prose lines with dense line pitch (38px) are separated."""
        img = Image.new("RGB", (1600, 500), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        y1 = 150
        draw.text((100, y1), "我們知道狀態函數 ", fill=(0, 0, 0), font=fonts["cn_regular"])
        b1 = draw.textbbox((100, y1), "我們知道狀態函數 ", font=fonts["cn_regular"])
        draw.text((b1[2], y1), "f(x) = ax + b", fill=(0, 0, 0), font=fonts["math_regular"])
        b_f1 = draw.textbbox((b1[2], y1), "f(x) = ax + b", font=fonts["math_regular"])
        draw.text((b_f1[2], y1), " 在全域均成立，", fill=(0, 0, 0), font=fonts["cn_regular"])

        # Dense 38px line pitch
        y2 = y1 + 38
        draw.text((100, y2), "另外伴隨函數 ", fill=(0, 0, 0), font=fonts["cn_regular"])
        b2 = draw.textbbox((100, y2), "另外伴隨函數 ", font=fonts["cn_regular"])
        draw.text((b2[2], y2), "g(y) = cy + d", fill=(0, 0, 0), font=fonts["math_regular"])
        b_f2 = draw.textbbox((b2[2], y2), "g(y) = cy + d", font=fonts["math_regular"])
        draw.text((b_f2[2], y2), " 則在局部有效。", fill=(0, 0, 0), font=fonts["cn_regular"])

        dets = detector.detect(img)
        assert len(dets) == 2, f"Expected 2 separate detections across adjacent lines, got {len(dets)}"
        assert dets[0].category == "inline"
        assert dets[1].category == "inline"
        # Verify vertical separation: bottom of line 1 < top of line 2
        assert dets[0].box[3] <= dets[1].box[1] + 2.0, (
            f"Vertical overlap between adjacent lines: {dets[0].box[3]} vs {dets[1].box[1]}"
        )


class TestExtremeBoundaryConditions:
    """Verifies edge cases: canvas borders, giant formulas, and tiny font sizes."""

    def test_formula_touching_page_borders(
        self, detector: FormulaDetector, fonts: dict
    ) -> None:
        """Verifies formulas touching top-left (x < 5, y < 5) and bottom-right borders are clamped and detected."""
        w, h = 1600, 2000
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Touching top-left: x=2, y=2
        draw.text((2, 2), "f(x) = ax^2 + bx + c", fill=(0, 0, 0), font=fonts["math_large"])

        # Touching bottom-right: x=1250, y=1960
        draw.text((1250, 1960), "E = mc^2", fill=(0, 0, 0), font=fonts["math_large"])

        dets = detector.detect(img)
        assert len(dets) >= 2, f"Expected at least 2 border detections, got {len(dets)}"

        # Verify clamping: all coordinates within [0, w] x [0, h]
        for d in dets:
            assert d.box[0] >= 0.0 and d.box[1] >= 0.0
            assert d.box[2] <= float(w) and d.box[3] <= float(h)

        # Top-left formula detected with x1 < 5.0 and y1 < 5.0
        tl = [d for d in dets if d.box[0] < 5.0 and d.box[1] < 5.0]
        assert len(tl) == 1, f"Top-left border formula not detected: {dets}"

    def test_giant_isolated_multiline_formula(
        self, detector: FormulaDetector, fonts: dict
    ) -> None:
        """Verifies giant multiline matrix equation is detected as a cohesive isolated formula."""
        img = Image.new("RGB", (1600, 1000), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        matrix_lines = [
            "[ a_11  a_12  a_13  a_14 ]   [ x_1 ]   [ b_1 ]",
            "[ a_21  a_22  a_23  a_24 ] * [ x_2 ] = [ b_2 ]",
            "[ a_31  a_32  a_33  a_34 ]   [ x_3 ]   [ b_3 ]",
            "[ a_41  a_42  a_43  a_44 ]   [ x_4 ]   [ b_4 ]",
        ]
        y = 200
        for line in matrix_lines:
            draw.text((200, y), line, fill=(0, 0, 0), font=fonts["math_large"])
            y += 32

        dets = detector.detect(img)
        assert len(dets) >= 1, f"Expected giant formula detected, got {len(dets)}"

        # Find the major detection covering the matrix
        matrix_det = max(dets, key=lambda d: (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]))
        assert matrix_det.category == "isolated"
        assert matrix_det.class_id == 1
        box_w = matrix_det.box[2] - matrix_det.box[0]
        box_h = matrix_det.box[3] - matrix_det.box[1]
        assert box_w > 500.0, f"Expected box width > 500px, got {box_w}"
        assert box_h > 120.0, f"Expected box height > 120px, got {box_h}"

    def test_tiny_font_formulas_retention(
        self, detector: FormulaDetector, fonts: dict
    ) -> None:
        """Verifies formulas rendered in small fonts (sizes 18, 20, 24) are detected and retained."""
        img = Image.new("RGB", (1600, 800), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        sizes = [18, 20, 24]
        y = 100
        for sz in sizes:
            draw.text((100, y), f"f(x) = ax + b", fill=(0, 0, 0), font=fonts[f"math_{sz}"])
            y += 80

        dets = detector.detect(img)
        assert len(dets) == len(sizes), (
            f"Expected {len(sizes)} detections for sizes {sizes}, got {len(dets)}"
        )
        for d in dets:
            bw = d.box[2] - d.box[0]
            bh = d.box[3] - d.box[1]
            assert bw >= 12.0 and bh >= 10.0, f"Box fell below absolute size threshold: {d.box}"
