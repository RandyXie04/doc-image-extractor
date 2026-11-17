# -*- coding: utf-8 -*-
"""
tests/e2e/fixtures/generate_fixtures.py
=======================================
Deterministic, offline synthesis of all E2E test fixtures (Tiers 1-4).
Generates vector PDFs and rendered PNGs using PyMuPDF (fitz) and Pillow (PIL).

Features:
- 100% offline and reproducible: Zero external network requests.
- Surrounds formulas with dense, realistic Chinese and English prose paragraphs
  to simulate real publications and verify that surrounding text is not falsely detected.
- Supports both Windows system fonts and fallback PyMuPDF built-in fonts for portability.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple
import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

FIXTURES_DIR = Path(__file__).resolve().parent

def get_font_file(name: str = "times.ttf") -> Optional[str]:
    """Returns local Windows font path if available, or None for PyMuPDF fallback."""
    candidate = Path("C:/Windows/Fonts") / name
    if candidate.is_file():
        return str(candidate)
    return None

def get_pil_font(name: str = "times.ttf", size: int = 24) -> ImageFont.ImageFont:
    """Loads PIL ImageFont safely with fallback."""
    font_path = get_font_file(name)
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


# ============================================================================
# TIER 1: Feature Coverage Fixture Generation
# ============================================================================

def generate_tier1_fixtures(base_dir: Path) -> None:
    t1_dir = base_dir / "tier1"
    t1_dir.mkdir(parents=True, exist_ok=True)
    font_times = get_font_file("times.ttf")
    font_zh = get_font_file("msyh.ttc") or get_font_file("simsun.ttc")

    # 1. Isolated Formula with Dense Surrounding Text
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    p1 = (
        "In theoretical mathematics, continuous mappings and their analytical properties form "
        "the bedrock of functional analysis. When analyzing second-order polynomial operators on "
        "a Banach space, we frequently examine quadratic functional expressions. Specifically, let "
        "f be a scalar-valued function defined on the real field satisfying the standard differentiability "
        "conditions across the entire domain."
    )
    page.insert_textbox(fitz.Rect(54, 54, 558, 140), p1, fontsize=11, fontfile=font_times)
    # Centered isolated formula
    page.insert_text(fitz.Point(180, 190), "f(x) = ax^2 + bx + c", fontsize=20, fontfile=font_times)
    p2 = (
        "Here the coefficients a, b, and c are arbitrary real constants with a non-zero. The stationary "
        "points of this parabolic distribution can be obtained via straightforward differential evaluation. "
        "Notice that the curvature remains constant across all values of the parameter x."
    )
    page.insert_textbox(fitz.Rect(54, 230, 558, 320), p2, fontsize=11, fontfile=font_times)
    doc.save(str(t1_dir / "t1_isolated.pdf"))
    page.get_pixmap(dpi=150).save(str(t1_dir / "t1_isolated.png"))
    doc.close()

    # 2. Inline Formula Embedded in Dense Prose
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    p_inline = (
        "Consider an affine transformation on the Euclidean line. Suppose that f(x) = 2x + 1 is continuous "
        "and monotonically increasing on the unit interval [0, 1]. In such a configuration, the mapping maps "
        "every open subset into an open subset, satisfying the open mapping theorem for finite-dimensional spaces. "
        "We denote the inverse operator accordingly as the reciprocal gradient function."
    )
    page.insert_textbox(fitz.Rect(54, 60, 558, 160), p_inline, fontsize=11, fontfile=font_times)
    doc.save(str(t1_dir / "t1_inline.pdf"))
    page.get_pixmap(dpi=150).save(str(t1_dir / "t1_inline.png"))
    doc.close()

    # 3. Short Formula (f(x)=ax+bx) Surrounded by Dense Academic Text
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    p_short = (
        "In modern linear algebra, decomposing operations into elementary linear forms is of paramount importance. "
        "We define the elementary combination f(x) = ax + bx for all real values of x, where the coefficients a and b "
        "represent arbitrary scalar multipliers. This short algebraic form must be retained by formula extraction "
        "pipelines without being erroneously filtered out by aspect-ratio or minimum-width heuristics."
    )
    page.insert_textbox(fitz.Rect(54, 60, 558, 160), p_short, fontsize=11, fontfile=font_times)
    p_short_zh = (
        "在线性代数与函数方程中，我们经常研究由基础单项式组合而成的紧凑代数形式。对于任意实数变量 x，"
        "我们定义线性组合 f(x) = ax + bx 。在出版物排版中，此类短小公式往往紧凑嵌入于中文或英文段落内部，"
        "模型必须能够在密集文本背景下准确捕捉该短公式，且不误判周围的文字内容。"
    )
    page.insert_textbox(fitz.Rect(54, 180, 558, 280), p_short_zh, fontsize=11, fontfile=font_zh)
    doc.save(str(t1_dir / "t1_short_formula.pdf"))
    page.get_pixmap(dpi=150).save(str(t1_dir / "t1_short_formula.png"))
    doc.close()

    # 4. Multi-format Deliverables Target (E = mc^2)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    p_emc = (
        "Special relativity establishes the equivalence of inertial mass and resting energy. The fundamental "
        "postulate states that energy and relativistic momentum transform as components of a four-vector."
    )
    page.insert_textbox(fitz.Rect(54, 60, 558, 120), p_emc, fontsize=11, fontfile=font_times)
    page.insert_text(fitz.Point(220, 180), "E = mc^2", fontsize=24, fontfile=font_times)
    page.insert_textbox(
        fitz.Rect(54, 230, 558, 300),
        "Where c denotes the speed of light in vacuum and m is the invariant mass of the physical system.",
        fontsize=11,
        fontfile=font_times,
    )
    doc.save(str(t1_dir / "t1_multiformat.pdf"))
    page.get_pixmap(dpi=150).save(str(t1_dir / "t1_multiformat.png"))
    doc.close()

    # 5. Greek Letter Inline Formula
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_textbox(
        fitz.Rect(54, 60, 558, 160),
        "In differential geometry, angular coordinates on the Riemann sphere satisfy alpha + beta = gamma. "
        "This metric ensures that the conformal structure is preserved under Möbius transformations.",
        fontsize=11,
        fontfile=font_times,
    )
    doc.save(str(t1_dir / "t1_greek.pdf"))
    page.get_pixmap(dpi=150).save(str(t1_dir / "t1_greek.png"))
    doc.close()

    # 6. Pre-rendered Crop Snippets for Stage 2 & 3
    crops_dir = t1_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    font_pil_times = get_pil_font("times.ttf", 26)
    font_pil_zh = get_pil_font("msyh.ttc", 22)

    crop_specs = [
        ("crop_01_poly.png", "f(x) = ax^2 + bx + c", (350, 60), font_pil_times),
        ("crop_02_short.png", "f(x) = ax + bx", (240, 50), font_pil_times),
        ("crop_03_integral.png", "∫ exp(-x^2) dx = √π / 2", (300, 55), font_pil_times),
        ("crop_04_fraction.png", "(a + b) / (c - d)", (240, 50), font_pil_times),
        ("crop_05_chinese.png", "y = kx + b (其中 k 为斜率)", (320, 50), font_pil_zh),
        ("crop_06_sqrt.png", "√(b^2 - 4ac)", (220, 50), font_pil_times),
        ("crop_07_sum.png", "∑ x_i^2 = 1", (200, 50), font_pil_times),
        ("crop_08_limit.png", "lim (sin x) / x = 1", (250, 50), font_pil_times),
        ("crop_wide.png", "f(x) = a0 + a1 x + a2 x^2 + a3 x^3 + a4 x^4", (600, 45), font_pil_times),
        ("crop_tall.png", "E = mc^2", (80, 200), font_pil_times),
        ("crop_square.png", "x^2 + y^2 = r^2", (160, 160), font_pil_times),
        ("crop_tiny.png", "x", (25, 20), font_pil_times),
        ("crop_huge.png", "f(x, y, z) = ∫∫∫ Ω (x^2 + y^2 + z^2) dx dy dz", (700, 150), font_pil_times),
    ]

    for filename, text, size, font in crop_specs:
        im = Image.new("RGB", size, (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.text((10, 10), text, fill=(0, 0, 0), font=font)
        im.save(str(crops_dir / filename))


# ============================================================================
# TIER 2: Boundary & Corner Cases Fixture Generation
# ============================================================================

def generate_tier2_fixtures(base_dir: Path) -> None:
    t2_dir = base_dir / "tier2"
    t2_dir.mkdir(parents=True, exist_ok=True)
    font_times = get_font_file("times.ttf")

    # 1. Blank Pages & Canvas
    doc_blank = fitz.open()
    page_b = doc_blank.new_page(width=612, height=792)
    doc_blank.save(str(t2_dir / "t2_blank_page.pdf"))
    page_b.get_pixmap(dpi=150).save(str(t2_dir / "t2_blank_page.png"))
    doc_blank.close()

    # Neutral gray blank
    im_gray = Image.new("RGB", (1200, 1600), (128, 128, 128))
    im_gray.save(str(t2_dir / "t2_blank_gray.png"))

    # Noise only canvas
    arr_noise = np.random.normal(250, 2.0, (1600, 1200, 3)).clip(0, 255).astype(np.uint8)
    Image.fromarray(arr_noise).save(str(t2_dir / "t2_blank_noise.png"))

    # 1x1 pixel image
    Image.new("RGB", (1, 1), (255, 255, 255)).save(str(t2_dir / "t2_blank_1x1.png"))

    # 2. Border-Touching Formulas (0,0) and (W, H)
    font_pil_large = get_pil_font("times.ttf", 30)

    # Top-Left (0, 0)
    im_tl = Image.new("RGB", (1200, 1600), (255, 255, 255))
    ImageDraw.Draw(im_tl).text((0, 0), "f(x) = ax + b", fill=(0, 0, 0), font=font_pil_large)
    im_tl.save(str(t2_dir / "t2_border_top_left.png"))

    # Bottom-Right (1040, 1560, 1200, 1600)
    im_br = Image.new("RGB", (1200, 1600), (255, 255, 255))
    ImageDraw.Draw(im_br).text((980, 1550), "g(x) = cx + d", fill=(0, 0, 0), font=font_pil_large)
    im_br.save(str(t2_dir / "t2_border_bottom_right.png"))

    # Left border
    im_left = Image.new("RGB", (1200, 1600), (255, 255, 255))
    ImageDraw.Draw(im_left).text((0, 600), "y = mx + b", fill=(0, 0, 0), font=font_pil_large)
    im_left.save(str(t2_dir / "t2_border_left.png"))

    # Top border
    im_top = Image.new("RGB", (1200, 1600), (255, 255, 255))
    ImageDraw.Draw(im_top).text((500, 0), "z = x + y", fill=(0, 0, 0), font=font_pil_large)
    im_top.save(str(t2_dir / "t2_border_top.png"))

    # Bottom border
    im_bot = Image.new("RGB", (1200, 1600), (255, 255, 255))
    ImageDraw.Draw(im_bot).text((500, 1560), "u = v + w", fill=(0, 0, 0), font=font_pil_large)
    im_bot.save(str(t2_dir / "t2_border_bottom.png"))

    # 3. Extreme Aspect Ratio Banners
    im_wide = Image.new("RGB", (2400, 300), (255, 255, 255))
    ImageDraw.Draw(im_wide).text((40, 120), "f(x) = a0 + a1 x + a2 x^2 + a3 x^3 + a4 x^4 + a5 x^5", fill=(0, 0, 0), font=font_pil_large)
    im_wide.save(str(t2_dir / "t2_extreme_wide.png"))

    im_tall = Image.new("RGB", (300, 2400), (255, 255, 255))
    ImageDraw.Draw(im_tall).text((20, 1000), "E = mc^2", fill=(0, 0, 0), font=font_pil_large)
    im_tall.save(str(t2_dir / "t2_extreme_tall.png"))

    # 4. Tiny Single Variables embedded in text
    doc_var = fitz.open()
    page_var = doc_var.new_page(width=612, height=792)
    p_var = (
        "In standard notation, let x denote the independent variable and y denote the response. "
        "Here c is an arbitrary integration constant. These single symbols must be handled safely."
    )
    page_var.insert_textbox(fitz.Rect(54, 60, 558, 160), p_var, fontsize=11, fontfile=font_times)
    doc_var.save(str(t2_dir / "t2_single_variable.pdf"))
    page_var.get_pixmap(dpi=150).save(str(t2_dir / "t2_single_variable.png"))
    doc_var.close()

    # 5. Massive Formula Spanning >75% of Page
    doc_huge = fitz.open()
    page_huge = doc_huge.new_page(width=612, height=792)
    huge_eq_text = (
        "H(x, y) = \n"
        "  [ (d^2 f / dx^2)     (d^2 f / dx dy)     (d^2 f / dx dz) ]\n"
        "  [ (d^2 f / dy dx)     (d^2 f / dy^2)     (d^2 f / dy dz) ]\n"
        "  [ (d^2 f / dz dx)     (d^2 f / dz dy)     (d^2 f / dz^2) ]\n\n"
        "where the determinant det(H) = sum_(sigma in S_3) sgn(sigma) prod_(i=1)^3 H_(i, sigma(i))\n"
        "satisfies the positive definiteness condition for every local minimum."
    )
    page_huge.insert_textbox(fitz.Rect(54, 80, 558, 700), huge_eq_text, fontsize=16, fontfile=font_times)
    doc_huge.save(str(t2_dir / "t2_huge_equation.pdf"))
    page_huge.get_pixmap(dpi=150).save(str(t2_dir / "t2_huge_equation.png"))
    doc_huge.close()

    # 6. Batch Chunk Boundaries: Exactly 33 formulas (testing 32 + 1 chunking)
    doc_33 = fitz.open()
    page_33 = doc_33.new_page(width=612, height=792)
    for idx in range(33):
        col = idx % 3
        row = idx // 3
        x_pt = 50 + col * 180
        y_pt = 60 + row * 62
        page_33.insert_text(fitz.Point(x_pt, y_pt), f"y_{idx} = a_{idx} x + b_{idx}", fontsize=10, fontfile=font_times)
    doc_33.save(str(t2_dir / "t2_batch_chunk_33.pdf"))
    page_33.get_pixmap(dpi=150).save(str(t2_dir / "t2_batch_chunk_33.png"))
    doc_33.close()

    # Exactly 65 formulas across 2 pages (testing 32 + 32 + 1 chunking)
    doc_65 = fitz.open()
    p_idx = 0
    for page_num in range(2):
        pg = doc_65.new_page(width=612, height=792)
        count = 33 if page_num == 0 else 32
        for _ in range(count):
            col = p_idx % 3
            row = (p_idx % 33) // 3
            x_pt = 50 + col * 180
            y_pt = 60 + row * 62
            pg.insert_text(fitz.Point(x_pt, y_pt), f"eq_{p_idx} : z_{p_idx} = c_{p_idx} w", fontsize=10, fontfile=font_times)
            p_idx += 1
    doc_65.save(str(t2_dir / "t2_batch_chunk_65.pdf"))
    doc_65.close()

    # 7. Tiny 8x6 pixel noise artifact (filtered by min bounds w>=12, h>=10)
    im_speck = Image.new("RGB", (1200, 1600), (255, 255, 255))
    ImageDraw.Draw(im_speck).rectangle((500, 500, 508, 506), fill=(10, 10, 10))
    im_speck.save(str(t2_dir / "t2_tiny_artifact.png"))

    # 8. Malformed LaTeX for MathML fallback
    malformed_dir = t2_dir / "malformed"
    malformed_dir.mkdir(parents=True, exist_ok=True)
    (malformed_dir / "malformed_01.txt").write_text("\\frac{1}{", encoding="utf-8")
    (malformed_dir / "malformed_02.txt").write_text("\\sqrt", encoding="utf-8")
    (malformed_dir / "malformed_03.txt").write_text("^", encoding="utf-8")
    (malformed_dir / "malformed_04.txt").write_text("\\text{unclosed", encoding="utf-8")
    (malformed_dir / "malformed_05.txt").write_text("#@!$*&^%", encoding="utf-8")


# ============================================================================
# TIER 3: Cross-Feature Combinations Fixture Generation
# ============================================================================

def generate_tier3_fixtures(base_dir: Path) -> None:
    t3_dir = base_dir / "tier3"
    t3_dir.mkdir(parents=True, exist_ok=True)
    font_times = get_font_file("times.ttf")
    font_zh = get_font_file("msyh.ttc") or get_font_file("simsun.ttc")

    # 1. Mixed Page (3 inline + 2 isolated formulas surrounded by academic text)
    doc_mixed = fitz.open()
    page_m = doc_mixed.new_page(width=612, height=792)
    page_m.insert_textbox(
        fitz.Rect(54, 50, 558, 120),
        "Section 3.1: Combined Analytical Expressions. We begin with a continuous variable x in R "
        "and consider the linear form f(x) = ax + b where the slope satisfies a > 0.",
        fontsize=11,
        fontfile=font_times,
    )
    page_m.insert_text(fitz.Point(160, 170), "int_0^1 ( ax^2 + bx + c ) dx = 1", fontsize=18, fontfile=font_times)
    page_m.insert_textbox(
        fitz.Rect(54, 210, 558, 280),
        "Furthermore, calculating the second variation yields f''(x) = 2a. Under the stated regularity assumptions, "
        "the total dissipated energy can be formulated as an isolated sum:",
        fontsize=11,
        fontfile=font_times,
    )
    page_m.insert_text(fitz.Point(200, 330), "E = sum_{i=1}^n x_i^2", fontsize=18, fontfile=font_times)
    doc_mixed.save(str(t3_dir / "t3_mixed_page.pdf"))
    page_m.get_pixmap(dpi=150).save(str(t3_dir / "t3_mixed_page.png"))
    doc_mixed.close()

    # 2. Chinese Math Textbook Excerpt (Dense Chinese + Formulas)
    doc_zh = fitz.open()
    page_zh = doc_zh.new_page(width=612, height=792)
    page_zh.insert_textbox(
        fitz.Rect(54, 50, 558, 140),
        "第二章：平面解析几何与微积分初步。在平面直角坐标系中，设直线 l 的方程为 y = kx + b ，"
        "其中实数 k 为直线的斜率，b 为纵截距。当直线与曲线 y = f(x) 相切于点 P 时，切线斜率等于导数值。",
        fontsize=11,
        fontfile=font_zh,
    )
    page_zh.insert_text(fitz.Point(180, 190), "S = int_a^b ( f(x) - g(x) ) dx", fontsize=16, fontfile=font_times)
    page_zh.insert_textbox(
        fitz.Rect(54, 230, 558, 320),
        "上式表达了两条连续曲线之间所围成的封闭图形面积。计算时需注意积分上下限的确定，"
        "并确保被积函数在积分区间上处处有界且满足单调性条件。",
        fontsize=11,
        fontfile=font_zh,
    )
    doc_zh.save(str(t3_dir / "t3_chinese_math.pdf"))
    page_zh.get_pixmap(dpi=150).save(str(t3_dir / "t3_chinese_math.png"))
    doc_zh.close()

    # 3. Vector PDF and Raster targets for 1600px verification
    doc_vec = fitz.open()
    page_vec = doc_vec.new_page(width=400, height=100)
    page_vec.insert_text(fitz.Point(50, 60), "H psi = E psi", fontsize=28, fontfile=font_times)
    doc_vec.save(str(t3_dir / "t3_highres_vector.pdf"))
    doc_vec.close()

    im_ras = Image.new("RGB", (400, 100), (255, 255, 255))
    ImageDraw.Draw(im_ras).text((50, 30), "H psi = E psi", fill=(0, 0, 0), font=get_pil_font("times.ttf", 28))
    im_ras.save(str(t3_dir / "t3_highres_raster.png"))


# ============================================================================
# TIER 4: Real-World Scenarios Fixture Generation
# ============================================================================

def generate_tier4_fixtures(base_dir: Path) -> None:
    t4_dir = base_dir / "tier4"
    t4_dir.mkdir(parents=True, exist_ok=True)
    font_times = get_font_file("times.ttf")
    font_zh = get_font_file("msyh.ttc") or get_font_file("simsun.ttc")

    # 1. Chinese GaoKao Exam Simulation
    doc_exam = fitz.open()
    page_exam = doc_exam.new_page(width=612, height=792)
    page_exam.insert_text(fitz.Point(160, 45), "绝密★启用前 | 高等学校招生全国统一考试数学试卷", fontsize=13, fontfile=font_zh)
    p_q1 = (
        "一、选择题：本大题共 4 小题，每小题 5 分，共 20 分。\n"
        "1. 已知集合 A = { x | x^2 - 3x + 2 = 0 }，B = { x | 0 < x < 3 }，则 A ∩ B = （    ）\n"
        "   A. {1}         B. {2}         C. {1, 2}         D. ∅\n\n"
        "2. 设一次函数 f(x) = ax + b 满足 f(1) = 3 且 f(0) = 1 ，则斜率 k 的值为（    ）\n"
        "   A. 1           B. 2           C. 3              D. 4\n\n"
        "二、解答题：解答应写出文字说明、证明过程或演算步骤。\n"
        "3. 已知二次函数图象经过点 (0, 1)，其对称轴为直线 x = 1 ，求函数解析式："
    )
    page_exam.insert_textbox(fitz.Rect(54, 75, 558, 290), p_q1, fontsize=10, fontfile=font_zh)
    page_exam.insert_text(fitz.Point(180, 330), "f(x) = ax^2 + bx + c", fontsize=16, fontfile=font_times)
    page_exam.insert_textbox(
        fitz.Rect(54, 360, 558, 440),
        "4. 设抛物线与 x 轴交于两点 A 与 B ，计算由抛物线与 x 轴所围成的平面区域面积：",
        fontsize=10,
        fontfile=font_zh,
    )
    page_exam.insert_text(fitz.Point(180, 470), "S = int_0^2 ( -x^2 + 2x ) dx", fontsize=16, fontfile=font_times)
    doc_exam.save(str(t4_dir / "t4_exam_paper.pdf"))
    pix_exam = page_exam.get_pixmap(dpi=150)
    pix_exam.save(str(t4_dir / "t4_exam_paper.png"))
    doc_exam.close()

    # 2. Academic Journal Article (Two-Column Layout)
    doc_twocol = fitz.open()
    page_tc = doc_twocol.new_page(width=612, height=792)
    page_tc.insert_text(fitz.Point(140, 45), "Nonlinear Dynamics of Relativistic Wave Equations", fontsize=15, fontfile=font_times)
    # Abstract
    page_tc.insert_textbox(
        fitz.Rect(54, 65, 558, 120),
        "Abstract—We investigate the global existence and asymptotic stability of nonlinear wave equations on Lorentzian manifolds. "
        "By applying energy conservation invariants, we prove that classical Cauchy data leads to smooth global solutions.",
        fontsize=9,
        fontfile=font_times,
    )
    # Column 1
    p_col1 = (
        "I. INTRODUCTION\n\n"
        "Consider the scalar field equation on curved spacetime. The evolution of the geodesic deviation is governed by the curvature tensor. "
        "We introduce the classical field action:"
    )
    page_tc.insert_textbox(fitz.Rect(54, 130, 290, 220), p_col1, fontsize=9.5, fontfile=font_times)
    page_tc.insert_text(fitz.Point(60, 240), "S = int ( R - 2 Lambda ) d^4 x", fontsize=11, fontfile=font_times)
    page_tc.insert_text(fitz.Point(265, 240), "(1)", fontsize=9, fontfile=font_times)
    # Column 2
    p_col2 = (
        "II. CONSERVATION LAWS\n\n"
        "The stress-energy tensor satisfies the continuity equation. For any time-like Killing vector field, "
        "the conserved Hamiltonian charge is given by the spatial integral:"
    )
    page_tc.insert_textbox(fitz.Rect(315, 130, 558, 220), p_col2, fontsize=9.5, fontfile=font_times)
    page_tc.insert_text(fitz.Point(325, 240), "H = int_Sigma T_{00} d^3 x", fontsize=11, fontfile=font_times)
    page_tc.insert_text(fitz.Point(530, 240), "(2)", fontsize=9, fontfile=font_times)
    doc_twocol.save(str(t4_dir / "t4_academic_twocol.pdf"))
    page_tc.get_pixmap(dpi=150).save(str(t4_dir / "t4_academic_twocol.png"))
    doc_twocol.close()

    # 3. Calculus Textbook Chapter
    doc_calc = fitz.open()
    page_calc = doc_calc.new_page(width=612, height=792)
    page_calc.insert_text(fitz.Point(54, 50), "Chapter 7: Techniques of Integration and Limits", fontsize=15, fontfile=font_times)
    p_c1 = (
        "We establish the standard l'Hôpital rule for indeterminate forms of type 0/0. "
        "Let f and g be differentiable functions on an open interval containing c. If the limit of f(x) and g(x) "
        "as x approaches c both equal zero, then the quotient limit satisfies:"
    )
    page_calc.insert_textbox(fitz.Rect(54, 75, 558, 145), p_c1, fontsize=10.5, fontfile=font_times)
    page_calc.insert_text(fitz.Point(180, 175), "lim_{x -> 0} ( sin x ) / x = 1", fontsize=16, fontfile=font_times)
    page_calc.insert_textbox(
        fitz.Rect(54, 205, 558, 270),
        "Next, we consider improper Gaussian integrals over the entire real line. By transforming to polar coordinates "
        "via x = r cos theta and y = r sin theta, the double integral evaluates directly:",
        fontsize=10.5,
        fontfile=font_times,
    )
    page_calc.insert_text(fitz.Point(160, 305), "iint_{R^2} e^{-(x^2 + y^2)} dx dy = pi", fontsize=16, fontfile=font_times)
    doc_calc.save(str(t4_dir / "t4_calculus_chapter.pdf"))
    page_calc.get_pixmap(dpi=150).save(str(t4_dir / "t4_calculus_chapter.png"))
    doc_calc.close()

    # 4. Physics Paper (Vectors, Tensors, Radicals)
    doc_phys = fitz.open()
    page_phys = doc_phys.new_page(width=612, height=792)
    page_phys.insert_text(fitz.Point(54, 50), "Electrodynamics and Relativistic Kinematics", fontsize=15, fontfile=font_times)
    p_p1 = (
        "In relativistic kinematics, the Lorentz force equation describes the trajectory of a charged particle "
        "in an external electromagnetic field. With velocity vector v and field tensor F^{mu nu}:"
    )
    page_phys.insert_textbox(fitz.Rect(54, 75, 558, 140), p_p1, fontsize=10.5, fontfile=font_times)
    page_phys.insert_text(fitz.Point(160, 170), "F = q ( E + v x B )", fontsize=16, fontfile=font_times)
    page_phys.insert_textbox(
        fitz.Rect(54, 200, 558, 260),
        "The relativistic gamma factor depends inversely on the radical of normalized velocity:",
        fontsize=10.5,
        fontfile=font_times,
    )
    page_phys.insert_text(fitz.Point(180, 290), "gamma = 1 / sqrt(1 - v^2 / c^2)", fontsize=16, fontfile=font_times)
    doc_phys.save(str(t4_dir / "t4_physics_paper.pdf"))
    page_phys.get_pixmap(dpi=150).save(str(t4_dir / "t4_physics_paper.png"))
    doc_phys.close()

    # 5. Multi-Page High-Throughput Document (3 pages, 45+ formulas total)
    doc_multi = fitz.open()
    eq_counter = 0
    for page_idx in range(3):
        pg = doc_multi.new_page(width=612, height=792)
        pg.insert_text(fitz.Point(54, 45), f"Multi-Page Scientific Report — Page {page_idx + 1}", fontsize=13, fontfile=font_times)
        pg.insert_textbox(
            fitz.Rect(54, 60, 558, 110),
            f"This section details batch experimental dataset #{page_idx + 1}. All formulas must be recognized "
            "with precise index association and batch preservation across page boundaries.",
            fontsize=10,
            fontfile=font_times,
        )
        for row in range(5):
            for col in range(3):
                eq_counter += 1
                x_pos = 54 + col * 170
                y_pos = 140 + row * 110
                pg.insert_text(fitz.Point(x_pos, y_pos), f"E_{eq_counter} = m_{eq_counter} c^2", fontsize=11, fontfile=font_times)
    doc_multi.save(str(t4_dir / "t4_multipage_report.pdf"))
    doc_multi.close()

    # 6. Simulated Scanned Photocopy (300 DPI, 0.35 deg rotation, sensor noise, contrast)
    img_exam = Image.open(str(t4_dir / "t4_exam_paper.png")).convert("RGB")
    img_rot = img_exam.rotate(0.35, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(250, 250, 250))
    arr_rot = np.array(img_rot).astype(np.float32)
    noise = np.random.normal(0, 3.5, arr_rot.shape)
    img_noisy = Image.fromarray(np.clip(arr_rot + noise, 0, 255).astype(np.uint8))
    img_scanned = ImageEnhance.Contrast(img_noisy).enhance(1.06)
    img_scanned.save(str(t4_dir / "t4_scanned_photocopy.png"))


# ============================================================================
# Main Fixture Orchestrator
# ============================================================================

def build_all_fixtures() -> None:
    print(f"Generating deterministic E2E test fixtures under: {FIXTURES_DIR}")
    generate_tier1_fixtures(FIXTURES_DIR)
    print("  ✓ Tier 1 (Feature Coverage) fixtures generated.")
    generate_tier2_fixtures(FIXTURES_DIR)
    print("  ✓ Tier 2 (Boundary & Corner Cases) fixtures generated.")
    generate_tier3_fixtures(FIXTURES_DIR)
    print("  ✓ Tier 3 (Cross-Feature Combinations) fixtures generated.")
    generate_tier4_fixtures(FIXTURES_DIR)
    print("  ✓ Tier 4 (Real-World Scenarios) fixtures generated.")
    print("All fixtures generated successfully!")

if __name__ == "__main__":
    build_all_fixtures()
