# -*- coding: utf-8 -*-
"""
tests/test_adversarial_formula_detector.py: Empirical Adversarial Challenge Suite
================================================================================
Empirically stress-tests Milestone 1 (FormulaDetector & MFD ONNX) against:
1. Short formula retention across diverse document canvas sizes (800w, 1600w, 2400w, 3200w)
   specifically verifying formulas like f(x)=ax+bx, x in R, a^2+b^2=c^2 with w < 0.15W are never dropped.
2. Dynamic position shifting linearity (R^2 >= 0.998, slope ~ 1.0) along X and Y axes.
3. Negative controls: Blank documents, solid colors, pure prose (EN/ZH), and noisy scans (0 false positives).
4. Provider fallback equivalence: CPUExecutionProvider vs active hardware provider (DML/CUDA).
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import pytest

from config import PATHS
from src.extraction.contracts import FormulaDetectionContract
from src.extraction.formula_detector import FormulaDetector

pytestmark = pytest.mark.heavy


# ── Shared Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def formula_onnx_path() -> Path:
    """Locates pdf_extract_mfd.onnx or yolo_v8_ft.onnx."""
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
    pytest.skip("No MFD ONNX model available on disk.")


@pytest.fixture(scope="session")
def detector_default(formula_onnx_path: Path) -> FormulaDetector:
    return FormulaDetector(model_path=formula_onnx_path)


@pytest.fixture(scope="session")
def detector_cpu(formula_onnx_path: Path) -> FormulaDetector:
    return FormulaDetector(model_path=formula_onnx_path, providers=["CPUExecutionProvider"])


@pytest.fixture(scope="session")
def font_loader():
    """Resolves system fonts reliably across platforms."""
    def _get(size: int = 36, lang: str = "en") -> ImageFont.ImageFont:
        candidates = (
            ["msyh.ttc", "simsun.ttc", "simhei.ttf"]
            if lang == "cn"
            else ["times.ttf", "arial.ttf", "calibri.ttf", "DejaVuSans.ttf"]
        )
        for name in candidates:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    return _get


def calculate_r_squared(x_vals: Sequence[float], y_vals: Sequence[float]) -> Tuple[float, float]:
    """Computes R^2 (coefficient of determination) and slope via simple linear regression."""
    assert len(x_vals) == len(y_vals) and len(x_vals) >= 2
    x = np.array(x_vals, dtype=np.float64)
    y = np.array(y_vals, dtype=np.float64)

    cov = np.cov(x, y)[0, 1]
    var_x = np.var(x, ddof=1)
    slope = float(cov / var_x) if var_x > 0 else 0.0

    r = float(np.corrcoef(x, y)[0, 1])
    r2 = r ** 2
    return r2, slope


# ── Adversarial Challenge 1: Short Formula Retention Across Diverse Canvases ─

@pytest.mark.integration
class TestAdversarialShortFormulaRetention:
    """
    Stress-tests formula retention across diverse document canvas sizes:
    800w, 1600w, 2400w, 3200w.
    Verifies that formulas are never dropped by relative width filters (w < 0.15W).
    """

    @pytest.mark.parametrize("canvas_size", [
        (800, 1000),
        (1600, 2000),
        (2400, 3000),
        (3200, 4000),
    ])
    @pytest.mark.parametrize("formula_spec", [
        {"type": "isolated", "text": "f(x) = ax + bx", "sentence": None},
        {"type": "isolated", "text": "a^2 + b^2 = c^2", "sentence": None},
        {"type": "inline", "text": "x \u2208 \u211d", "sentence": "Consider f(x) = ax + bx for all x \u2208 \u211d."},
        {"type": "inline", "text": "x \u2208 [0, 1]", "sentence": "where parameter x \u2208 [0, 1] is strictly bounded."},
    ])
    def test_short_formula_retention_across_canvases(
        self,
        detector_default: FormulaDetector,
        font_loader,
        canvas_size: Tuple[int, int],
        formula_spec: Dict[str, Any],
    ) -> None:
        w, h = canvas_size
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Proportional typography font size matching standard publication scan DPI:
        # 800w (100 DPI) -> 28pt, 1600w (200 DPI) -> 36pt, 2400w (300 DPI) -> 48pt, 3200w (400 DPI) -> 64pt
        pt_map = {800: 28, 1600: 36, 2400: 48, 3200: 64}
        font = font_loader(pt_map[w], lang="en")

        pos_x = int(w * 0.15)
        pos_y = int(h * 0.35)

        rendered_text = formula_spec["sentence"] if formula_spec["sentence"] else formula_spec["text"]
        draw.text((pos_x, pos_y), rendered_text, fill=(0, 0, 0), font=font)

        detections = detector_default.detect(img)

        # 1. Verification: Formula is detected
        assert len(detections) >= 1, (
            f"Adversarial failure: Formula '{rendered_text}' on canvas {w}x{h} dropped! "
            f"Expected detection, got 0."
        )

        # 2. Check each detected formula: verify absolute size threshold and retention
        for det in detections:
            box_w = det.box[2] - det.box[0]
            box_h = det.box[3] - det.box[1]

            # Invariant: absolute size threshold prevents dropping valid formulas
            assert box_w >= 12.0
            assert box_h >= 10.0
            assert det.score >= 0.20


# ── Adversarial Challenge 2: Dynamic Position Shifting Linearity ──────────────

@pytest.mark.integration
class TestAdversarialDynamicPositionShifting:
    """
    Physically shifts formulas across coordinates and verifies that detected
    bounding boxes strictly and linearly track the shift (R^2 >= 0.998, slope ~ 1.0).
    Exposes any static coordinates, mock fixtures, or non-linear letterbox unmapping bugs.
    """

    def test_vertical_shift_linearity(
        self, detector_default: FormulaDetector, font_loader
    ) -> None:
        w, h = 1600, 2400
        font = font_loader(36, lang="en")
        target_formula = "f(x) = ax + bx"

        y_positions = [200, 500, 800, 1100, 1400, 1700, 2000]
        detected_y_centers: List[float] = []

        for y in y_positions:
            img = Image.new("RGB", (w, h), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            draw.text((250, y), target_formula, fill=(0, 0, 0), font=font)

            dets = detector_default.detect(img)
            assert len(dets) >= 1, f"Failed detection at vertical pos y={y}"

            # Pick closest detection in y
            best = min(dets, key=lambda d: abs((d.box[1] + d.box[3]) / 2.0 - (y + 20)))
            y_center = (best.box[1] + best.box[3]) / 2.0
            detected_y_centers.append(y_center)

        r2, slope = calculate_r_squared(y_positions, detected_y_centers)
        print(f"\n[Vertical Linearity] R^2: {r2:.6f}, Slope: {slope:.4f}")

        # Assert near-perfect linearity
        assert r2 >= 0.998, f"Vertical position tracking non-linear: R^2 = {r2:.6f} < 0.998"
        assert 0.95 <= slope <= 1.05, f"Vertical scale distortion: slope = {slope:.4f}"

    def test_horizontal_shift_linearity(
        self, detector_default: FormulaDetector, font_loader
    ) -> None:
        w, h = 2000, 1400
        font = font_loader(36, lang="en")
        target_formula = "a^2 + b^2 = c^2"

        x_positions = [150, 450, 750, 1050, 1350, 1600]
        detected_x_centers: List[float] = []

        for x in x_positions:
            img = Image.new("RGB", (w, h), (255, 255, 255))
            draw = ImageDraw.Draw(img)
            draw.text((x, 500), target_formula, fill=(0, 0, 0), font=font)

            dets = detector_default.detect(img)
            assert len(dets) >= 1, f"Failed detection at horizontal pos x={x}"

            # Pick closest detection in x
            best = min(dets, key=lambda d: abs((d.box[0] + d.box[2]) / 2.0 - (x + 80)))
            x_center = (best.box[0] + best.box[2]) / 2.0
            detected_x_centers.append(x_center)

        r2, slope = calculate_r_squared(x_positions, detected_x_centers)
        print(f"\n[Horizontal Linearity] R^2: {r2:.6f}, Slope: {slope:.4f}")

        # Assert near-perfect linearity
        assert r2 >= 0.998, f"Horizontal position tracking non-linear: R^2 = {r2:.6f} < 0.998"
        assert 0.95 <= slope <= 1.05, f"Horizontal scale distortion: slope = {slope:.4f}"


# ── Adversarial Challenge 3: Negative Controls (0 False Positives) ───────────

@pytest.mark.integration
class TestAdversarialNegativeControls:
    """
    Evaluates detector specificity against blank pages, solid colors, pure text prose,
    and noisy scanned artifacts. Strictly expects 0 false positive detections.
    """

    @pytest.mark.parametrize("color_name,rgb", [
        ("pure_white", (255, 255, 255)),
        ("pure_black", (0, 0, 0)),
        ("neutral_gray", (114, 114, 114)),
        ("light_gray", (230, 230, 230)),
        ("red", (255, 0, 0)),
        ("green", (0, 255, 0)),
        ("blue", (0, 0, 255)),
    ])
    def test_negative_control_solid_colors(
        self, detector_default: FormulaDetector, color_name: str, rgb: Tuple[int, int, int]
    ) -> None:
        img = Image.new("RGB", (1200, 1600), rgb)
        dets = detector_default.detect(img)
        assert len(dets) == 0, f"False positives on solid color {color_name}: {dets}"

    def test_negative_control_dense_english_prose(
        self, detector_default: FormulaDetector, font_loader
    ) -> None:
        """Paragraphs of academic English prose with zero mathematical notation."""
        w, h = 1600, 2200
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = font_loader(32, lang="en")

        paragraphs = [
            "Introduction and Overview of the System Architecture",
            "This document presents a comprehensive study of contemporary distributed software engineering.",
            "The modular design enforces strict separation of concerns between data persistence and presentation.",
            "Each subsystem communicates through clearly defined interfaces, eliminating implicit coupling.",
            "In modern enterprise systems, high availability and horizontal scalability are critical objectives.",
            "Microservices provide independent deployment pipelines, allowing diverse engineering teams to collaborate.",
            "Furthermore, automated integration pipelines ensure continuous delivery without compromising reliability.",
            "Load balancers distribute network traffic evenly across redundant clusters located in multiple regions.",
            "Database transactions adhere strictly to ACID properties, guaranteeing durable state changes.",
            "In conclusion, adopting robust engineering standards mitigates operational friction and enhances velocity.",
        ]
        y = 150
        for line in paragraphs:
            draw.text((100, y), line, fill=(0, 0, 0), font=font)
            y += 65

        dets = detector_default.detect(img)
        assert len(dets) == 0, f"False positives detected on pure English prose: {dets}"

    def test_negative_control_dense_chinese_prose(
        self, detector_default: FormulaDetector, font_loader
    ) -> None:
        """Dense Chinese literary text without mathematical notation."""
        w, h = 1600, 2200
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = font_loader(32, lang="cn")

        lines = [
            "古代文學與史學方法論探討：論司馬遷之敘事藝術與史學筆法",
            "史記以紀傳體開創我國紀傳體史書之先河，其敘事結構宏大而微觀刻畫細膩入微。",
            "司馬遷在描摹人物性格時，善於選取關鍵生活細節，並運用生動之對話彰顯人物內心衝突。",
            "在鴻門宴一章中，項羽之優柔寡斷與劉邦之機變果決形成了鮮明對比，深具戲劇張力。",
            "這種寓褒貶於敘事之中的春秋筆法，對後世散文與古典小說之發展產生了深遠的影響。",
            "清代文論家章學誠在文史通義中提出史德史才史識史學四要素，亦多本於太史公之論述。",
            "歷代學者對於史記之考證注釋層出不窮，形成了蔚為大觀的太史公學研究傳統。",
            "本文旨在通過文本細讀與比較文化學視角，進一步梳理其敘事策略之美學特質與哲理內涵。",
        ]
        y = 150
        for line in lines:
            draw.text((100, y), line, fill=(0, 0, 0), font=font)
            y += 65

        dets = detector_default.detect(img)
        assert len(dets) == 0, f"False positives detected on dense Chinese prose: {dets}"

    def test_negative_control_gaussian_noise(
        self, detector_default: FormulaDetector
    ) -> None:
        """Random Gaussian noise simulating severe sensor noise on blank scan."""
        np.random.seed(42)
        noise = np.random.normal(240, 20, (1200, 1600, 3)).clip(0, 255).astype(np.uint8)
        img = Image.fromarray(noise)

        dets = detector_default.detect(img)
        assert len(dets) == 0, f"False positives on Gaussian noise canvas: {dets}"

    def test_negative_control_scanning_artifacts_and_lines(
        self, detector_default: FormulaDetector
    ) -> None:
        """Simulates physical scanner artifacts: ruler lines, border gutters, margin shadows."""
        w, h = 1600, 2000
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Horizontal separator lines across document
        draw.line([(50, 300), (1550, 300)], fill=(0, 0, 0), width=3)
        draw.line([(50, 800), (1550, 800)], fill=(100, 100, 100), width=1)
        draw.line([(50, 1300), (1550, 1300)], fill=(50, 50, 50), width=5)

        # Scanner edge binding shadow on left
        for i in range(40):
            gray_val = int(50 + i * 4.5)
            draw.line([(i, 0), (i, h)], fill=(gray_val, gray_val, gray_val), width=1)

        dets = detector_default.detect(img)
        assert len(dets) == 0, f"False positives on scanner lines/shadows: {dets}"


# ── Adversarial Challenge 4: Provider Fallback & Output Equivalence ──────────

@pytest.mark.integration
class TestAdversarialProviderEquivalence:
    """
    Validates output parity between CPUExecutionProvider and hardware provider (DML/CUDA).
    Ensures that floating point math, letterboxing, and NMS produce strictly identical
    detections regardless of the active hardware provider.
    """

    def test_cpu_vs_gpu_detection_equivalence(
        self,
        detector_default: FormulaDetector,
        detector_cpu: FormulaDetector,
        font_loader,
    ) -> None:
        w, h = 1600, 2000
        img = Image.new("RGB", (w, h), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        font = font_loader(36, lang="en")

        draw.text((100, 300), "Consider the mapping f(x) = ax + bx.", fill=(0, 0, 0), font=font)
        draw.text((100, 700), "And the identity a^2 + b^2 = c^2.", fill=(0, 0, 0), font=font)
        draw.text((100, 1200), "Where parameter x \u2208 [0, 1] is real.", fill=(0, 0, 0), font=font)

        # Run on both providers
        dets_default = detector_default.detect(img)
        dets_cpu = detector_cpu.detect(img)

        print(f"\n[Provider Parity] Default Provider: {detector_default.active_provider} -> {len(dets_default)} detections")
        print(f"[Provider Parity] CPU Provider: {detector_cpu.active_provider} -> {len(dets_cpu)} detections")

        # 1. Detection count parity
        assert len(dets_default) == len(dets_cpu), (
            f"Provider detection count mismatch: {detector_default.active_provider} found {len(dets_default)}, "
            f"CPUExecutionProvider found {len(dets_cpu)}"
        )
        assert len(dets_default) >= 2, "Expected at least 2 formulas detected"

        # 2. Field-by-field parity check
        for i, (d_def, d_cpu) in enumerate(zip(dets_default, dets_cpu)):
            assert d_def.category == d_cpu.category, f"Category mismatch at index {i}"
            assert d_def.class_id == d_cpu.class_id, f"Class ID mismatch at index {i}"

            # Scores within floating point precision (< 0.05)
            assert abs(d_def.score - d_cpu.score) < 0.05, (
                f"Score divergence at index {i}: {d_def.score} vs {d_cpu.score}"
            )

            # Bounding box coordinates within 3.0px
            for c_def, c_cpu in zip(d_def.box, d_cpu.box):
                assert abs(c_def - c_cpu) <= 3.0, (
                    f"Coordinate divergence at index {i}: {d_def.box} vs {d_cpu.box}"
                )
