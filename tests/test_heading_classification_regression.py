# -*- coding: utf-8 -*-
"""
Phase 3.2 Regression Test Suite: Prevent False Heading Classification
====================================================================
Reproduces and prevents false-positive heading classification where
body text lines (with identical body font and body font size) are
mistakenly classified as H2 headings merely due to loose centering heuristics.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
import fitz

from src.scripts.book_layout_extractor import (
    _parse_pdf_layout_flow,
    extract_book_vector_ast,
)


class TestHeadingClassificationRegression(unittest.TestCase):
    """Tests for heading classification precision and recall."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_heading_reg_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_synthetic_doc(self, body_text_samples, target_lines):
        """Helper to create a PDF with established body profile and target test lines."""
        pdf_path = self.test_dir / "sample.pdf"
        doc = fitz.open()
        p = doc.new_page(width=500, height=700)

        y = 80
        # Establish body profile with 10.5pt china-ss
        for sample in body_text_samples:
            p.insert_text(fitz.Point(60, y), sample, fontname="china-ss", fontsize=10.5)
            y += 25

        y += 20
        # Insert target test lines
        for text, x, font, size in target_lines:
            p.insert_text(fitz.Point(x, y), text, fontname=font, fontsize=size)
            y += 30

        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def test_01_same_font_same_size_centered_body_not_promoted_to_heading(self):
        """
        Regression: A body text line with identical font (china-ss) and size (10.5pt)
        that happens to be visually centered must NOT be promoted to H2 heading.
        """
        body_samples = [
            "這是一段非常標準且足夠長的中文書籍正文段落，用於建立整份文件的正文基準字體與字級統計基準。",
            "第二行正文繼續提供足夠的字數採樣，確保統計出的 body_size 為 10.5pt 且 body_font 為 china-ss。",
            "第三行正文繼續維持統計穩定性，確保單行文字不會影響整體字級與字型分布判定。",
        ]
        target_lines = [
            # Centered line with same font and size (like test_2.pdf p4 line)
            ("础篇第一章主要介绍了小儿发热的基本概念", 120, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc(body_samples, target_lines)

        ast = extract_book_vector_ast(pdf_path)
        section_titles = [s.title for s in ast.sections]

        # The centered body text line MUST NOT become a section title
        self.assertNotIn(
            "础篇第一章主要介绍了小儿发热的基本概念",
            section_titles,
            "Body text with body font and body size must not be promoted to a section heading",
        )

    def test_02_large_centered_heading_correctly_classified(self):
        """
        Recall: A centered line with significantly larger font (e.g. 16pt vs 10.5pt body)
        MUST still be correctly classified as a heading.
        """
        body_samples = [
            "這是一段非常標準且足夠長的中文書籍正文段落，用於建立整份文件的正文基準字體與字級統計基準。",
            "第二行正文繼續提供足夠的字數採樣，確保統計出的 body_size 為 10.5pt 且 body_font 為 china-ss。",
        ]
        target_lines = [
            ("第三章 深度學習與人機對話技術", 110, "china-ss", 16.0),
        ]
        pdf_path = self._create_synthetic_doc(body_samples, target_lines)

        ast = extract_book_vector_ast(pdf_path)
        section_titles = [s.title for s in ast.sections]
        self.assertTrue(
            any("第三章 深度學習與人機對話技術" in t for t in section_titles),
            f"Large centered heading must be recognized as a section. Found: {section_titles}",
        )

    def test_03_numbered_heading_syntax_correctly_classified(self):
        """
        Recall: Explicit chapter / section regex syntax must be classified as heading
        even if font size is close to body.
        """
        body_samples = [
            "這是一段非常標準且足夠長的中文書籍正文段落，用於建立整份文件的正文基準字體與字級統計基準。",
            "第二行正文繼續提供足夠的字數採樣，確保統計出的 body_size 為 10.5pt 且 body_font 為 china-ss。",
        ]
        target_lines = [
            ("第1章 人機對話架構與語意分析", 60, "china-ss", 12.0),
        ]
        pdf_path = self._create_synthetic_doc(body_samples, target_lines)

        ast = extract_book_vector_ast(pdf_path)
        section_titles = [s.title for s in ast.sections]
        self.assertTrue(
            any("第1章 人機對話架構與語意分析" in t for t in section_titles),
            f"Numbered chapter syntax must be recognized as a section. Found: {section_titles}",
        )

    def test_04_centered_poem_or_epigraph_not_promoted_to_heading(self):
        """
        Precision: Centered poem / quotation with same font and size must remain body paragraph.
        """
        body_samples = [
            "這是一段非常標準且足夠長的中文書籍正文段落，用於建立整份文件的正文基準字體與字級統計基準。",
            "第二行正文繼續提供足夠的字數採樣，確保統計出的 body_size 為 10.5pt 且 body_font 為 china-ss。",
        ]
        target_lines = [
            ("人生到處知何似 應似飛鴻踏雪泥", 140, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc(body_samples, target_lines)

        ast = extract_book_vector_ast(pdf_path)
        section_titles = [s.title for s in ast.sections]
        self.assertNotIn(
            "人生到處知何似 應似飛鴻踏雪泥",
            section_titles,
            "Centered poem line with body font and size must remain paragraph, not section",
        )

    def test_05_test_2_pdf_page_4_regression(self):
        """
        Real document regression: data/test_2.pdf page 4 has 10.5pt body sentences
        which were previously misclassified as 3 separate H2 headings.
        """
        test_2_path = Path("data/test_2.pdf")
        if not test_2_path.exists():
            self.skipTest("data/test_2.pdf not found")

        # Extract page 4 only
        doc = fitz.open(str(test_2_path))
        page4_doc = fitz.open()
        page4_doc.insert_pdf(doc, from_page=3, to_page=3) # Page 4 (0-based 3)
        doc.close()

        page4_pdf = self.test_dir / "test_2_p4.pdf"
        page4_doc.save(str(page4_pdf))
        page4_doc.close()

        ast = extract_book_vector_ast(page4_pdf)
        section_titles = [s.title for s in ast.sections]

        # These three body sentences must NOT be section titles!
        disallowed_titles = [
            "础篇第一章主要介绍了小儿发热的基本概念、分类、生理病理、体",
            "重点介绍了常见小儿发热疾病的病因病机、临床表现、临床诊断、",
            "书中吸纳了前贤们对小儿发热的理、法、方、药等经验结晶及我们",
        ]
        for dt in disallowed_titles:
            self.assertNotIn(
                dt,
                section_titles,
                f"Page 4 body sentence '{dt}' must not be a section title",
            )


if __name__ == "__main__":
    unittest.main()
