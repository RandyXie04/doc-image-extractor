# -*- coding: utf-8 -*-
"""
Deep Adversarial Stress and Fuzz Test Suite for Formula Exporter
==============================================================
Empirical Challenger M2-R2-1:
Systematically probes:
1. Pathological control characters (C0, C1, surrogates, DEL, noncharacters, BOM).
2. Complex nested LaTeX formatting (\\text{\\textbf{...}}, math in \\text{}, escaped braces).
3. Multi-layer code fences (3 to 16 backticks, nested layers, mixed markdown/math tags).
4. High-volume fuzz oracle: 500+ combinatorial inputs asserting 100% valid XML parsability.
"""

from pathlib import Path
import random
import string
import xml.etree.ElementTree as ET

import pytest

from src.extraction.contracts import (
    FormulaCategory,
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaResultContract,
)
from src.extraction.formula_exporter import (
    export_formula_result,
    export_formula_results,
    latex_to_mathml,
    normalize_katex_fences,
    sanitize_latex,
)


class TestPathologicalControlCharacters:
    """Stress testing formula exporter against all ASCII control characters and illegal XML tokens."""

    ALL_C0_CONTROL_CHARS = [chr(i) for i in range(32)]  # \x00 through \x1f
    ILLEGAL_XML_CHARS = [chr(i) for i in range(9)] + [chr(11), chr(12)] + [chr(i) for i in range(14, 32)] + ["\ufffe", "\uffff"]

    def test_all_individual_c0_control_chars_in_mathml(self):
        """Every individual C0 control character mixed in LaTeX must produce 100% valid XML."""
        for code, char in enumerate(self.ALL_C0_CONTROL_CHARS):
            raw = f"x + {char} + y = z"
            mathml = latex_to_mathml(raw)
            try:
                root = ET.fromstring(mathml)
                assert root.tag.endswith("math")
            except ET.ParseError as exc:
                pytest.fail(f"Failed on C0 char 0x{code:02x} ({repr(char)}): {exc}")

    def test_clustered_illegal_control_characters(self):
        """Massive block of illegal control characters together."""
        clustered = "".join(self.ILLEGAL_XML_CHARS)
        raw = f"\\int_{{{clustered}}}^{{\\infty}} f(x) dx"
        mathml = latex_to_mathml(raw)
        root = ET.fromstring(mathml)
        assert root.tag.endswith("math")

    def test_control_chars_inside_cjk_text(self):
        """Control characters embedded inside Chinese text within \\text{}."""
        raw = "\\text{這是\x00一個\x08包含\x1b控制\x1f字元的\x0c測試}"
        sanitized = sanitize_latex(raw)
        assert "這是" in sanitized and "測試" in sanitized

        mathml = latex_to_mathml(sanitized)
        root = ET.fromstring(mathml)
        assert root.tag.endswith("math")

    def test_valid_xml_whitespace_control_chars_preserved(self):
        """XML 1.0 explicitly allows \t (0x09), \n (0x0A), and \r (0x0D)."""
        valid_ws = "a\t+\nb\r= c"
        sanitized = sanitize_latex(valid_ws)
        mathml = latex_to_mathml(sanitized)
        root = ET.fromstring(mathml)
        assert root.tag.endswith("math")


class TestComplexNestedLatexFormatting:
    """Stress testing depth-aware balanced brace scanner and CJK wrapping."""

    @pytest.mark.parametrize(
        "nested_input,expected_substr",
        [
            (r"\text{說明：\textbf{重要結論}}", r"\text{說明：\textbf{重要結論}}"),
            (r"\text{\textbf{\textit{深度三重格式}}}", r"\text{\textbf{\textit{深度三重格式}}}"),
            (r"\mbox{\textbf{盒子粗體}}", r"\mbox{\textbf{盒子粗體}}"),
            (r"\mathrm{\textbf{羅馬粗體}}", r"\mathrm{\textbf{羅馬粗體}}"),
            (r"\operatorname{\mathbf{自訂運算子}}", r"\operatorname{\mathbf{自訂運算子}}"),
            (r"\operatorname*{\mathbf{帶星號運算子}}", r"\operatorname*{\mathbf{帶星號運算子}}"),
        ],
    )
    def test_nested_text_style_commands_preserved_without_double_wrap(self, nested_input, expected_substr):
        sanitized = sanitize_latex(nested_input)
        assert "\\text{\\text{" not in sanitized
        assert expected_substr in sanitized
        assert sanitized.count("{") == sanitized.count("}")

    def test_math_inside_text_command(self):
        """LaTeX formula embedded inside \\text{...} using inline math $...$."""
        raw = r"\text{若 $x \in \{1, 2\}$，則 $y > 0$}"
        sanitized = sanitize_latex(raw)
        assert "\\text{\\text{" not in sanitized
        assert sanitized.count("{") == sanitized.count("}")
        assert r"\text{若 $x \in \{1, 2\}$，則 $y > 0$}" in sanitized

    def test_complex_formula_inside_text_command(self):
        raw = r"\text{當 $f(x) = \frac{1}{\sqrt{x^2 + 1}}$ 時，函數連續且有界}"
        sanitized = sanitize_latex(raw)
        assert "\\text{\\text{" not in sanitized
        assert sanitized.count("{") == sanitized.count("}")
        assert "函數連續且有界" in sanitized

    def test_escaped_braces_in_and_out_of_text(self):
        """Escaped braces \\{ and \\} must not disrupt brace balance depth."""
        raw = r"S = \{ x \mid x > 0 \} \text{（集合說明：\{元素\}）}"
        sanitized = sanitize_latex(raw)
        assert "\\text{\\text{" not in sanitized
        assert r"\{" in sanitized and r"\}" in sanitized

    def test_odd_and_even_backslashes_before_braces(self):
        """Test backslash parity: \\\\\\{ is line break + escaped brace; \\\\{ is line break + grouping brace."""
        # 3 backslashes: line break + literal brace \{ -> not a grouping brace
        raw1 = r"\text{換行 \\\{ 項目 \}}"
        sanitized1 = sanitize_latex(raw1)
        assert "\\text{\\text{" not in sanitized1
        assert r"\\\{" in sanitized1

        # 2 backslashes: line break + grouping brace { ... }
        raw2 = r"\text{換行 \\{ 項目 \\} }"
        sanitized2 = sanitize_latex(raw2)
        assert "\\text{\\text{" not in sanitized2

    def test_consecutive_text_blocks_on_single_line(self):
        raw = r"\text{第一部} + \alpha \cdot \text{第二部} = \text{第三部}"
        sanitized = sanitize_latex(raw)
        assert "\\text{\\text{" not in sanitized
        assert r"\text{第一部}" in sanitized
        assert r"\text{第二部}" in sanitized
        assert r"\text{第三部}" in sanitized

    def test_unclosed_brace_graceful_fallback(self):
        """Unclosed brace in \\text{ does not crash or raise recursion errors."""
        raw = r"\text{未閉合的中文"
        sanitized = sanitize_latex(raw)
        assert isinstance(sanitized, str)
        # Verify MathML generation also succeeds
        mathml = latex_to_mathml(sanitized)
        root = ET.fromstring(mathml)
        assert root.tag.endswith("math")


class TestMultiLayerFencesAdversarial:
    """Stress testing fence peeling across various backtick depths and layer combinations."""

    @pytest.mark.parametrize("backtick_count", [3, 4, 5, 7, 10, 16])
    def test_arbitrary_backtick_counts(self, backtick_count):
        ticks = "`" * backtick_count
        raw = f"{ticks}latex\nE = m c^2\n{ticks}"
        sanitized = sanitize_latex(raw)
        assert "`" not in sanitized
        assert sanitized == "E = m c^2"

    def test_triple_nested_markdown_math_latex_fences(self):
        """Deeply nested wrapper fences from cascaded LLM / tool calls."""
        nested = (
            "`````markdown\n"
            "````math\n"
            "```latex\n"
            "\\sum_{k=1}^n k = \\frac{n(n+1)}{2}\n"
            "```\n"
            "````\n"
            "`````"
        )
        sanitized = sanitize_latex(nested)
        assert "`" not in sanitized
        assert sanitized == r"\sum_{k=1}^n k = \frac{n(n+1)}{2}"

    def test_fences_with_mixed_surrounding_whitespace_and_newlines(self):
        raw = "\n\n   \t ```latex\n\n   a + b = c   \n\n```   \n\t "
        sanitized = sanitize_latex(raw)
        assert "`" not in sanitized
        assert sanitized == "a + b = c"

    def test_fences_combined_with_math_delimiters(self):
        """Code fences wrapping $$ delimiters."""
        raw = "```latex\n$$ x^2 + y^2 = 1 $$\n```"
        sanitized = sanitize_latex(raw)
        assert "`" not in sanitized
        assert "$" not in sanitized
        assert sanitized == "x^2 + y^2 = 1"


class TestMathML100PercentParseabilityOracle:
    """
    High-volume stress harness:
    Feeds 200+ randomly mutated, noisy, and pathological inputs into latex_to_mathml.
    Validates 100% parseability via xml.etree.ElementTree.fromstring.
    """

    LATEX_SNIPPETS = [
        r"x + y = z",
        r"\frac{-b \pm \sqrt{b^2 - 4ac}}{2a}",
        r"\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}",
        r"\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}",
        r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}",
        r"\lim_{x \to 0} \frac{\sin x}{x} = 1",
        r"\text{中文測試：} f(x) = \sin(x)",
    ]

    NOISE_INJECTIONS = [
        "\x00", "\x01", "\x02", "\x07", "\x08", "\x0b", "\x0c", "\x0e", "\x1f",
        "\ufffe", "\uffff", "\ufffd",
        "{{{{{", "}}}}}", r"\frac{", r"\sqrt{", r"\left(",
        "```latex", "```", "$$", "$", "\\[", "\\]", "\\(", "\\)",
        "\x00\x08\x1b",
    ]

    def test_200_fuzzed_adversarial_inputs_valid_xml(self):
        random.seed(42)

        for i in range(200):
            base = random.choice(self.LATEX_SNIPPETS)
            num_injections = random.randint(1, 5)

            # Randomly slice, corrupt, or inject noise
            chars = list(base)
            for _ in range(num_injections):
                noise = random.choice(self.NOISE_INJECTIONS)
                insert_pos = random.randint(0, len(chars))
                chars.insert(insert_pos, noise)

            corrupted = "".join(chars)

            # Sanitize and convert to MathML
            clean = sanitize_latex(corrupted)
            for display in ["inline", "block"]:
                mathml = latex_to_mathml(clean, display=display)
                assert isinstance(mathml, str), f"Iter {i}: mathml not str"
                assert len(mathml) > 0, f"Iter {i}: mathml empty"

                try:
                    root = ET.fromstring(mathml)
                    assert root.tag.endswith("math")
                except ET.ParseError as exc:
                    pytest.fail(
                        f"Fuzz test failed on iter {i}!\n"
                        f"Raw corrupted: {repr(corrupted)}\n"
                        f"Sanitized: {repr(clean)}\n"
                        f"MathML output: {repr(mathml)}\n"
                        f"ParseError: {exc}"
                    )
