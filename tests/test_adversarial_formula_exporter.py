# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite for Formula Exporter (Milestone 2)
===============================================================
Adversarially probes:
  1. LaTeX sanitization stress: pathological fences, multi-line nested code blocks,
     complex mixed CJK characters, already protected \\text{} commands.
  2. MathML generation stress: severely malformed LaTeX strings, unclosed brackets,
     raw OCR garbage (including control characters). Verifies 100% valid XML.
  3. 1600px PNG export stress: extreme aspect ratios, edge/out-of-bounds bounding boxes,
     zero 1-pixel rounding errors across vector PDF and raster modes.
  4. Dense surrounding text test: formula cropping and multi-format export within dense
     multi-paragraph Chinese and English text canvases.
"""

from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
import pytest

from src.extraction.contracts import (
    FormulaCategory,
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaResultContract,
)
from src.extraction.formula_cropper import FormulaCropper
from src.extraction.formula_exporter import (
    export_formula_result,
    export_formula_results,
    export_highres_png,
    latex_to_mathml,
    normalize_katex_fences,
    sanitize_latex,
)


# ============================================================================
# 1. LaTeX Sanitization Stress Tests
# ============================================================================
class TestLatexSanitizationAdversarial:
    """Stress tests for LaTeX sanitization against pathological inputs."""

    def test_empty_and_whitespace(self):
        assert sanitize_latex("") == ""
        assert sanitize_latex("   \n\t  ") == ""
        assert sanitize_latex(None) == ""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("```latex\nx+y\n```", "x+y"),
            ("```math\nx+y\n```", "x+y"),
            ("```\nx+y\n```", "x+y"),
            ("`x+y`", "x+y"),
            ("  ```latex\n   a+b   \n```  ", "a+b"),
            ("```LATEX\nx+y\n```", "x+y"),
            ("```Math\nx+y\n```", "x+y"),
        ],
    )
    def test_standard_fences(self, raw, expected):
        assert sanitize_latex(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("$$x+y$$", "x+y"),
            ("$$\n  x+y  \n$$", "x+y"),
            ("\\[ x+y \\]", "x+y"),
            ("\\( x+y \\)", "x+y"),
            ("$x+y$", "x+y"),
            ("$$ x=1 $$ and $$ y=2 $$", "x=1 $$ and $$ y=2"),
        ],
    )
    def test_outer_math_delimiters(self, raw, expected):
        assert sanitize_latex(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("x ^ 2 + y _ 1", "x^2 + y_1"),
            ("x   ^   2", "x^2"),
            ("( x + y ) ^ 2", "( x + y )^2"),
            ("a _ { i + 1 }", "a_{ i + 1 }"),
            ("E = m c ^ 2", "E = m c^2"),
        ],
    )
    def test_whitespace_normalization(self, raw, expected):
        assert sanitize_latex(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("\\text{中文}", "\\text{中文}"),
            ("\\mbox{中文}", "\\mbox{中文}"),
            ("\\mathrm{中文}", "\\mathrm{中文}"),
            ("\\operatorname{中文}", "\\operatorname{中文}"),
            ("\\text{中文1} + \\text{中文2}", "\\text{中文1} + \\text{中文2}"),
            ("\\text{甲} \\quad \\text{乙}", "\\text{甲} \\quad \\text{乙}"),
        ],
    )
    def test_already_protected_cjk_preservation(self, raw, expected):
        """Pre-existing protected blocks must not be double-wrapped."""
        assert sanitize_latex(raw) == expected

    def test_unprotected_cjk_wrapping(self):
        raw = "f(x) = 2x + 1，其中 x 為非負實數。"
        sanitized = sanitize_latex(raw)
        assert "\\text{，其中}" in sanitized or "\\text{，其中 x 為非負實數。}" in sanitized or "\\text{為非負實數。}" in sanitized
        assert "其中" in sanitized and "非負實數" in sanitized
        # Ensure no nested text commands like \text{\text{...}}
        assert "\\text{\\text{" not in sanitized

    def test_mixed_protected_and_unprotected_cjk(self):
        raw = "\\text{已知}變數 x 為實數"
        sanitized = sanitize_latex(raw)
        # \text{已知} should remain protected and not become \text{\text{已知}}
        assert "\\text{已知}" in sanitized
        assert "\\text{\\text{" not in sanitized
        assert "\\text{變數}" in sanitized or "\\text{變數 x 為實數}" in sanitized or "\\text{為實數}" in sanitized

    def test_cjk_with_nested_braces(self):
        """
        Adversarial probe: what happens when \\text{...} contains inner braces or formatting?
        E.g. \\text{中文 \\textbf{粗體}} or \\text{集合 $\\{1, 2\\}$}
        """
        raw = "\\text{中文 \\textbf{粗體}}"
        sanitized = sanitize_latex(raw)
        # Must not produce invalid or unclosed braces
        assert sanitized.count("{") == sanitized.count("}")
        # Must not double-wrap into \text{\text{...}}
        assert "\\text{\\text{" not in sanitized, f"Double wrapped in nested braces: {sanitized}"

    def test_nested_markdown_code_blocks(self):
        """
        Adversarial probe: LLM/OCR output wrapped in multiple nested markdown code blocks:
        ```markdown
        ```latex
        x + y = z
        ```
        ```
        """
        nested = "```markdown\n```latex\nx + y = z\n```\n```"
        sanitized = sanitize_latex(nested)
        assert "```" not in sanitized, f"Fences remained in sanitized output: {sanitized}"
        assert sanitized == "x + y = z"

    def test_four_backtick_fences(self):
        """
        Adversarial probe: 4-backtick code fences ````latex ... ````
        """
        four = "````latex\nx + y = z\n````"
        sanitized = sanitize_latex(four)
        assert "`" not in sanitized, f"Backticks remained in output: {sanitized}"
        assert sanitized == "x + y = z"


# ============================================================================
# 2. MathML Generation Stress Tests
# ============================================================================
class TestMathMLGenerationAdversarial:
    """Stress tests for MathML XML generation and <merror> fallback robustness."""

    @pytest.mark.parametrize(
        "malformed_latex",
        [
            r"\frac{1}{2",  # unclosed fraction
            r"\sqrt{x + \frac{1}{2}",  # unclosed nested sqrt
            r"\left( x + y",  # missing \right)
            r"\notacommand{xyz}",  # invalid / undefined command
            r"x^^2",  # double superscript
            r"x__1",  # double subscript
            r"^2",  # bare superscript
            r"_1",  # bare subscript
            r"\begin{matrix} 1 & 2",  # unclosed environment
            r"\over \over",  # illegal TeX primitives
            r"$$#%@!&*~???///\\",  # raw punctuation noise
            r"\int_{0}^{1 \frac{dx}{x}",  # unclosed sub/sup
            r"\sum_{i=1}^{\infty x_i",  # unclosed limit
            "",  # empty
            "   ",  # spaces
        ],
    )
    def test_malformed_latex_produces_100_percent_valid_xml(self, malformed_latex):
        """
        Every single malformed LaTeX string must either convert or fall back to
        a valid W3C MathML structure that parses cleanly via ElementTree.
        """
        for display in ["inline", "block"]:
            mathml = latex_to_mathml(malformed_latex, display=display)
            assert isinstance(mathml, str)
            assert len(mathml) > 0

            # Must parse cleanly without ParseError
            root = ET.fromstring(mathml)
            assert root.tag.endswith("math")
            assert root.attrib.get("display") == display

    def test_raw_ocr_garbage_and_control_characters(self):
        """
        Raw OCR garbage often contains null bytes or ASCII control codes.
        Verify that latex_to_mathml does not crash and produces valid XML.
        """
        control_chars_garbage = [
            "x + \x00 + y",  # null byte
            "x + \x08 + y",  # backspace
            "x + \x0b + y",  # vertical tab
            "x + \x0c + y",  # form feed
            "x + \x1b + y",  # escape
            "x + \ufffd + y",  # unicode replacement character
            "\\alpha + \\beta + \x07 + \\gamma",  # bell char
        ]

        for garbage in control_chars_garbage:
            # We test how latex_to_mathml currently behaves
            mathml = latex_to_mathml(garbage)
            try:
                root = ET.fromstring(mathml)
                assert root.tag.endswith("math")
            except ET.ParseError as exc:
                # If ElementTree fails, we catch it as a confirmed empirical bug
                pytest.fail(
                    f"MathML XML parsing failed on raw OCR control character string {repr(garbage)}: {exc}"
                )

    def test_merror_fallback_schema_conformance(self):
        """
        Verify that the fallback structure strictly conforms to W3C MathML standard:
        <math display="..."><semantics><merror><mtext>...</mtext></merror><annotation encoding="application/x-tex">...</annotation></semantics></math>
        """
        broken_latex = r"\left( x + y"
        mathml = latex_to_mathml(broken_latex, display="block")

        root = ET.fromstring(mathml)
        assert root.attrib.get("display") == "block"

        # Check semantics child
        semantics = root.find("{http://www.w3.org/1998/Math/MathML}semantics")
        assert semantics is not None, "Missing <semantics> in MathML fallback"

        # Check merror child
        merror = semantics.find("{http://www.w3.org/1998/Math/MathML}merror")
        assert merror is not None, "Missing <merror> in MathML fallback"

        # Check mtext child
        mtext = merror.find("{http://www.w3.org/1998/Math/MathML}mtext")
        assert mtext is not None, "Missing <mtext> in <merror>"
        assert "conversion failed" in mtext.text

        # Check annotation child
        annotation = semantics.find("{http://www.w3.org/1998/Math/MathML}annotation")
        assert annotation is not None, "Missing <annotation> in MathML fallback"
        assert annotation.attrib.get("encoding") == "application/x-tex"
        assert annotation.text == broken_latex


# ============================================================================
# 3. 1600px PNG High-Resolution Export Stress Tests
# ============================================================================
class TestHighResPngExportAdversarial:
    """Stress tests for strict max(w, h) == 1600 constraint across raster and vector modes."""

    EXTREME_ASPECT_RATIOS = [
        (1, 1),
        (1, 2),
        (2, 1),
        (1, 1600),
        (1600, 1),
        (1, 500),
        (500, 1),
        (3, 17),
        (17, 3),
        (7, 13),
        (13, 7),
        (73, 29),
        (29, 73),
        (137, 589),
        (589, 137),
        (31, 97),
        (97, 31),
        (811, 213),
        (213, 811),
        (10, 1599),
        (1599, 10),
        (20, 2000),
        (2000, 20),
        (999, 1001),
        (1001, 999),
        (1600, 1600),
        (1920, 1080),
        (1280, 720),
    ]

    def test_raster_export_extreme_aspect_ratios(self):
        """Verify max(w, h) == 1600 strictly across all extreme aspect ratios in raster mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for w, h in self.EXTREME_ASPECT_RATIOS:
                crop = Image.new("RGB", (w, h), (200, 200, 200))
                out_p = Path(tmpdir) / f"raster_{w}_{h}.png"
                export_highres_png(out_p, crop, (0, 0, w, h), pdf_page=None, imgsz=1600)

                with Image.open(out_p) as im:
                    max_dim = max(im.width, im.height)
                    assert (
                        max_dim == 1600
                    ), f"Raster export failed for {w}x{h}: got {im.size}, max={max_dim}"
                    assert im.width <= 1600
                    assert im.height <= 1600

    def test_vector_export_extreme_aspect_ratios(self):
        """Verify max(w, h) == 1600 strictly across all extreme aspect ratios in vector PDF mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            doc = fitz.open()
            page = doc.new_page(width=3000, height=3000)

            for w, h in self.EXTREME_ASPECT_RATIOS:
                crop = Image.new("RGB", (w, h), (200, 200, 200))
                out_p = Path(tmpdir) / f"vector_{w}_{h}.png"
                export_highres_png(
                    out_p, crop, (50, 50, 50 + w, 50 + h), pdf_page=page, imgsz=1600
                )

                with Image.open(out_p) as im:
                    max_dim = max(im.width, im.height)
                    assert (
                        max_dim == 1600
                    ), f"Vector export failed for {w}x{h}: got {im.size}, max={max_dim}"
                    assert im.width <= 1600
                    assert im.height <= 1600

    def test_vector_export_out_of_bounds_bounding_boxes(self):
        """Test bounding boxes partially or completely outside page boundaries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            doc = fitz.open()
            page = doc.new_page(width=400, height=400)

            oob_cases = [
                (-50, 20, 100, 80, 150, 60, "negative_x1"),
                (20, -50, 80, 100, 60, 150, "negative_y1"),
                (350, 20, 500, 80, 150, 60, "overflow_x2"),
                (20, 350, 80, 500, 60, 150, "overflow_y2"),
                (500, 500, 600, 600, 100, 100, "completely_outside"),
            ]

            for x1, y1, x2, y2, cw, ch, tag in oob_cases:
                crop = Image.new("RGB", (cw, ch), (150, 150, 150))
                out_p = Path(tmpdir) / f"oob_{tag}.png"
                export_highres_png(
                    out_p, crop, (x1, y1, x2, y2), pdf_page=page, imgsz=1600
                )

                with Image.open(out_p) as im:
                    max_dim = max(im.width, im.height)
                    assert (
                        max_dim == 1600
                    ), f"OOB case {tag} failed: got {im.size}, max={max_dim}"

    def test_degenerate_zero_and_negative_size_crops(self):
        """Test zero-area or single-pixel crops without crashes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            crop = Image.new("RGB", (1, 1), (0, 0, 0))
            out_p = Path(tmpdir) / "degenerate.png"
            export_highres_png(out_p, crop, (10, 10, 10, 10), pdf_page=None, imgsz=1600)
            with Image.open(out_p) as im:
                assert max(im.width, im.height) == 1600


# ============================================================================
# 4. Dense Surrounding Text Test
# ============================================================================
class TestDenseSurroundingTextAdversarial:
    """Stress tests formula cropping and multi-format export in dense mixed CJK/English text."""

    def test_dense_text_canvas_cropping_and_export(self):
        """
        Creates a high-density 1200x1600 document canvas filled with dense multi-paragraph
        Chinese and English prose, with an inline formula and an isolated formula embedded.
        Verifies:
          - Safety padding (3-5px) correctly expands bounding boxes
          - Formula cropper extracts crops without bounds error
          - Aspect ratio sorting and mini-batch packaging work
          - Exporter delivers Format 1 (LaTeX), Format 2 (MathML), and Format 3 (1600px PNG)
        """
        img_w, img_h = 1200, 1600
        canvas = Image.new("RGB", (img_w, img_h), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        # Dense paragraph 1 (Chinese)
        y_cursor = 40
        chinese_text = (
            "在現代數學分析與深度學習架構中，最佳化函數之收斂性保證通常需要嚴謹的梯度界限條件。"
            "假設目標函數為凸函數且具備李普希茲連續性，則其二階導數之特徵值必然大於零。"
            "當考慮多變量系統時，我們定義如下之目標損失函數："
        )
        for line_idx in range(6):
            draw.text((60, y_cursor), f"【段落 {line_idx+1}】 {chinese_text}", fill=(30, 30, 30))
            y_cursor += 30

        # Isolated formula between paragraphs
        isolated_box = (350, y_cursor + 15, 850, y_cursor + 75)  # 500x60
        draw.rectangle(isolated_box, outline=(200, 200, 200), fill=(245, 245, 250))
        draw.text((380, y_cursor + 35), r"\int_0^1 x^2 \, dx = \frac{1}{3}", fill=(0, 0, 0))
        y_cursor += 105

        # Dense paragraph 2 (English)
        english_text = (
            "Given a probability space (Omega, F, P), let X be a random variable with finite variance. "
            "The central limit theorem implies that the standardized sample mean converges in distribution "
            "to a standard normal random variable as the sample size tends to infinity."
        )
        for line_idx in range(6):
            draw.text((60, y_cursor), f"[Section {line_idx+1}] {english_text}", fill=(40, 40, 40))
            y_cursor += 28

        # Paragraph 3 with embedded inline formula
        y_cursor += 20
        draw.text(
            (60, y_cursor),
            "為評估非線性激勵函數之性質，我們考慮一維函數 ",
            fill=(30, 30, 30),
        )
        # Inline formula: f(x)=ax+bx inside line
        inline_box = (450, y_cursor - 4, 620, y_cursor + 24)  # 170x28
        draw.rectangle(inline_box, outline=(180, 180, 180), fill=(250, 248, 240))
        draw.text((455, y_cursor), "f(x) = ax + bx", fill=(0, 0, 0))
        draw.text((630, y_cursor), "，此處 a 與 b 為任意實常數。", fill=(30, 30, 30))
        y_cursor += 35

        # Dense paragraph 4 (mixed prose)
        for line_idx in range(8):
            draw.text(
                (60, y_cursor),
                f"隨後的數值實驗表明，該系統在較大擾動下仍維持漸近穩定（Lyapunov 準則），如第 {line_idx+1} 次迭代所示。",
                fill=(30, 30, 30),
            )
            y_cursor += 30

        # Test cropping with FormulaCropper
        cropper = FormulaCropper(pad=4, batch_size=32)
        detections = [
            FormulaDetectionContract(
                box=(float(isolated_box[0]), float(isolated_box[1]), float(isolated_box[2]), float(isolated_box[3])),
                score=0.985,
                category="isolated",
                class_id=1,
            ),
            FormulaDetectionContract(
                box=(float(inline_box[0]), float(inline_box[1]), float(inline_box[2]), float(inline_box[3])),
                score=0.962,
                category="inline",
                class_id=0,
            ),
        ]

        batches, cropped_items = cropper.crop_and_batch(canvas, detections)
        assert len(batches) == 1
        assert len(batches[0]) == 2
        assert len(cropped_items) == 2

        # Verify safe padding
        for item in cropped_items:
            orig_x1, orig_y1, orig_x2, orig_y2 = item.detection.box
            pad_x1, pad_y1, pad_x2, pad_y2 = item.padded_box
            assert pad_x1 <= orig_x1
            assert pad_y1 <= orig_y1
            assert pad_x2 >= orig_x2
            assert pad_y2 >= orig_y2

        # Verify multi-format export
        with tempfile.TemporaryDirectory() as tmpdir:
            predictions = [
                (r"\int_0^1 x^2 \, dx = \frac{1}{3}", 0.99),
                (r"f(x) = ax + bx", 0.97),
            ]
            crops = [b[0] for b in batches[0]]
            results = export_formula_results(
                crops=crops,
                items=cropped_items,
                raw_predictions=predictions,
                output_dir=tmpdir,
                imgsz=1600,
                save_manifest=True,
            )

            assert len(results) == 2
            manifest_path = Path(tmpdir) / "formulas.json"
            assert manifest_path.exists()

            for res in results:
                # 1. LaTeX
                assert len(res.latex) > 0
                # 2. MathML
                assert res.mathml.startswith("<math")
                ET.fromstring(res.mathml)  # Must be valid XML
                # 3. High-res PNG
                img_p = Path(res.image_path)
                assert img_p.exists()
                with Image.open(img_p) as im:
                    assert max(im.width, im.height) == 1600
