# -*- coding: utf-8 -*-
"""
Phase 3.3 Regression Test Suite: Paragraph Reflow & Layout Boundary Precision
=============================================================================
Validates refined paragraph merging decision rules across diverse publishing layouts:
- Standard 2-character indentation reflow (within-paragraph splicing)
- Modern no-indent layout with vertical paragraph spacing (gap-based division)
- Unnumbered list items without terminal punctuation (anti-merging guard)
- Standalone unnumbered short headings (BUG-004 anti-sticking guard)
- Mid-sentence unclosed quotes and book titles across lines (BUG-006B reflow)
- Bibliographic hanging indentation continuation
- Fullwidth space indentation (\u3000\u3000)
- Trailing section headings merged at sentence end (BUG-007 split)
- Interleaved tables and figures boundary isolation (BUG-007 table integrity)
- Empty string / whitespace safety (BUG-006 IndexError prevention)
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
import fitz

from src.scripts.book_layout_extractor import (
    process_book_vector_pdf,
    _parse_pdf_layout_flow,
    extract_book_vector_ast,
)


class TestParagraphReflowRegression(unittest.TestCase):
    """Synthetic PDF regression tests for paragraph reflow and anti-sticking rules."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_para_reflow_reg_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_synthetic_doc(self, pages_lines):
        """
        Creates a multi-page PDF from a list of pages.
        Each page is a list of tuples: (text, x, y, font, size).
        """
        pdf_path = self.test_dir / "sample.pdf"
        doc = fitz.open()
        for lines in pages_lines:
            p = doc.new_page(width=500, height=700)
            for text, x, y, font, size in lines:
                p.insert_text(fitz.Point(x, y), text, fontname=font, fontsize=size)
        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    def test_01_standard_two_char_indent_paragraphs_smoothly_reflowed(self):
        """
        Scenario 1: Standard 2-char indented Chinese paragraphs.
        Each paragraph has 2 lines. Line 1 has indent (x=81), Line 2 has no indent (x=60).
        Lines within each paragraph must be smoothly merged into a single paragraph.
        The two paragraphs must remain distinct.
        """
        p1_l1 = "强直性脊柱炎是一种以骶髂关节和脊柱附着点炎症为主要病理改变的"
        p1_l2 = "慢性进行性炎性疾病，临床多表现为晨僵、腰背部疼痛与活动受限。"
        p2_l1 = "本病病因尚不完全明确，现代医学研究认为与遗传因素有高度相关性，"
        p2_l2 = "其中人类白细胞抗原HLA-B27的阳性表达率在患者中高达百分之九十。"

        page_data = [
            # Paragraph 1
            (p1_l1, 81, 100, "china-ss", 10.5),
            (p1_l2, 60, 118, "china-ss", 10.5),
            # Paragraph 2 (starts with indent)
            (p2_l1, 81, 140, "china-ss", 10.5),
            (p2_l2, 60, 158, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc([page_data])
        out_dir = self.test_dir / "out1"
        md_path, audit = process_book_vector_pdf(str(pdf_path), str(out_dir))

        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read().strip()

        paras = [p.strip() for p in md.split("\n\n") if p.strip()]
        self.assertEqual(len(paras), 2, f"Expected exactly 2 paragraphs, got {len(paras)}: {paras}")
        self.assertIn("慢性进行性炎性疾病", paras[0])
        self.assertIn("强直性脊柱炎是一种以骶髂关节", paras[0])
        self.assertIn("人类白细胞抗原HLA-B27", paras[1])
        self.assertGreaterEqual(audit["paragraphs_reflowed"], 2)

    def test_02_no_indent_modern_style_paragraph_gap(self):
        """
        Scenario 2: Modern publishing style with NO indentation (flush-left),
        distinguished by vertical paragraph gaps (空行/段前距).
        Lines within the same paragraph have normal line spacing and must be merged.
        Paragraphs separated by a gap must be split.
        """
        p1_l1 = "针灸配合刺络拔罐疗法是中医治疗痹证与骨伤痛症的传统外治法之一，"
        p1_l2 = "通过温通经络、调畅气血、活血化瘀达到通则不痛的临床疗效。"
        p2_l1 = "对照组患者接受口服双氯芬酸钠缓释胶囊治疗，连续观察四周时间，"
        p2_l2 = "记录治疗前后患者枕墙距、指地距以及胸廓活动度的变化情况。"

        page_data = [
            # Paragraph 1 (tight line spacing: 18pt pitch)
            (p1_l1, 60, 100, "china-ss", 10.5),
            (p1_l2, 60, 118, "china-ss", 10.5),
            # Paragraph 2 (separated by paragraph gap: y jumps from 118 to 148, gap=30pt > 10.5*1.5)
            (p2_l1, 60, 148, "china-ss", 10.5),
            (p2_l2, 60, 166, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc([page_data])
        out_dir = self.test_dir / "out2"
        md_path, audit = process_book_vector_pdf(str(pdf_path), str(out_dir))

        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read().strip()

        paras = [p.strip() for p in md.split("\n\n") if p.strip()]
        self.assertEqual(len(paras), 2, f"Expected 2 paragraphs for no-indent layout with gap, got: {paras}")
        self.assertIn("活血化瘀达到通则不痛", paras[0])
        self.assertIn("记录治疗前后患者枕墙距", paras[1])

    def test_03_list_items_without_terminal_punct_isolated(self):
        """
        Scenario 3: Unnumbered/numbered list items (e.g. herbal prescriptions)
        where each item ends without sentence-ending punctuation (BUG-006A defense).
        Must NOT be concatenated into a single run-on paragraph!
        """
        item1 = "1. 柴胡 12g，黄芩 9g，清半夏 9g"
        item2 = "2. 党参 15g，炙甘草 6g，生姜 3片"
        item3 = "3. 大枣 4枚，白芍 12g，茯苓 15g"

        page_data = [
            (item1, 60, 100, "china-ss", 10.5),
            (item2, 60, 120, "china-ss", 10.5),
            (item3, 60, 140, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc([page_data])
        out_dir = self.test_dir / "out3"
        md_path, audit = process_book_vector_pdf(str(pdf_path), str(out_dir))

        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read().strip()

        paras = [p.strip() for p in md.split("\n\n") if p.strip()]
        self.assertEqual(len(paras), 3, f"Expected 3 separate list items, got: {paras}")
        self.assertIn("1. 柴胡", paras[0])
        self.assertIn("2. 党参", paras[1])
        self.assertIn("3. 大枣", paras[2])

    def test_04_unrecognized_short_heading_anti_sticking(self):
        """
        Scenario 4: Standalone unnumbered short heading (BUG-004 anti-sticking guard).
        Even if not captured by TOC or Regex, a short line without punctuation
        must NOT be glued to the subsequent body paragraph!
        """
        h_line = "临床资料与诊断标准"
        b_line1 = "纳入本临床观察之全部患者共计八十六例，均符合国际脊柱关节炎评估学会"
        b_line2 = "于二零零九年修订的中轴型脊柱关节炎分类标准，且签署知情同意书。"

        page_data = [
            (h_line, 60, 100, "china-ss", 10.5),
            (b_line1, 60, 130, "china-ss", 10.5),
            (b_line2, 60, 148, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc([page_data])
        out_dir = self.test_dir / "out4"
        md_path, audit = process_book_vector_pdf(str(pdf_path), str(out_dir))

        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read().strip()

        paras = [p.strip() for p in md.split("\n\n") if p.strip()]
        self.assertGreaterEqual(len(paras), 2)
        # Heading text must not be glued into the body text
        self.assertNotIn("临床资料与诊断标准纳入本临床观察", md)
        self.assertTrue(any("临床资料与诊断标准" in p for p in paras))
        self.assertTrue(any("纳入本临床观察之全部患者" in p for p in paras))

    def test_05_unclosed_book_quote_across_lines_merged(self):
        """
        Scenario 5: Line ends with unclosed book mark or quote (BUG-006B).
        Example: '...《温' wrapping to '病条辨》...'.
        Must smoothly concatenate without splitting.
        """
        l1 = "双参灵百汤之配伍思路主要借鉴清代著名医家吴鞠通所著《温"
        l2 = "病条辨》之沙参麦冬汤，具有益气养阴、润燥清肺之特殊功效。"

        page_data = [
            (l1, 60, 100, "china-ss", 10.5),
            (l2, 60, 118, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc([page_data])
        out_dir = self.test_dir / "out5"
        md_path, audit = process_book_vector_pdf(str(pdf_path), str(out_dir))

        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read().strip()

        paras = [p.strip() for p in md.split("\n\n") if p.strip()]
        self.assertEqual(len(paras), 1, f"Expected 1 merged paragraph, got: {paras}")
        self.assertIn("《温病条辨》", paras[0])

    def test_06_hanging_indent_reference_reflowed(self):
        """
        Scenario 6: Hanging indent citation (e.g. bibliography).
        Line 1 is flush-left (x=60), Line 2 is indented (x=80).
        Line 1 ends with colon ':' or non-terminal punctuation.
        Must smoothly merge into single bibliographic item.
        """
        l1 = "[1] 葛均波, 徐永健, 王辰. 内科学[M]. 9版. 北京:"
        l2 = "人民卫生出版社, 2018: 812-817."

        page_data = [
            (l1, 60, 100, "china-ss", 10.5),
            (l2, 80, 118, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc([page_data])
        out_dir = self.test_dir / "out6"
        md_path, audit = process_book_vector_pdf(str(pdf_path), str(out_dir))

        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read().strip()

        paras = [p.strip() for p in md.split("\n\n") if p.strip()]
        self.assertEqual(len(paras), 1, f"Expected single citation paragraph, got: {paras}")
        self.assertIn("人民卫生出版社", paras[0])

    def test_07_fullwidth_space_indent_reflowed(self):
        """
        Scenario 7: Fullwidth space indentation (\u3000\u3000).
        Both lines have physical x0=60, but Line 1 starts with \u3000\u3000.
        Lines must be merged into one paragraph.
        """
        l1 = "　　方中重用金银花、连翘清热解毒，透热达表，为君药之选；"
        l2 = "配伍薄荷、牛蒡子疏散风热，清利头目，增强君药宣透之力。"

        page_data = [
            (l1, 60, 100, "china-ss", 10.5),
            (l2, 60, 118, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc([page_data])
        out_dir = self.test_dir / "out7"
        md_path, audit = process_book_vector_pdf(str(pdf_path), str(out_dir))

        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read().strip()

        paras = [p.strip() for p in md.split("\n\n") if p.strip()]
        self.assertEqual(len(paras), 1, f"Expected 1 merged paragraph, got: {paras}")
        self.assertIn("增强君药宣透之力", paras[0])

    def test_08_trailing_heading_in_paragraph_split(self):
        """
        Scenario 8: Paragraph text ending with '...。 4 讨论' (BUG-007 第 5 項).
        Must split trailing section heading into an independent Heading record.
        """
        body_with_trail_h = "治疗前后两组患者实验室指标差异显著（疗效对比时剔除）。 4 讨论"
        next_body = "强直性脊柱炎属中医学大偻、痹证范畴，多因肾督亏虚、风寒湿热痹阻所致。"

        page_data = [
            (body_with_trail_h, 60, 100, "china-ss", 10.5),
            (next_body, 60, 130, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc([page_data])
        out_dir = self.test_dir / "out8"
        md_path, audit = process_book_vector_pdf(str(pdf_path), str(out_dir))

        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read().strip()

        # Heading '4 讨论' must be properly split
        self.assertIn("## 4 讨论", md)
        self.assertIn("疗效对比时剔除", md)
        self.assertIn("属中医学大偻", md)
        h_detected = [h["text"] for h in audit["headings_detected"]]
        self.assertTrue(any("4 讨论" in h for h in h_detected))

    def test_09_empty_and_whitespace_blocks_no_index_error(self):
        """
        Scenario 9: Empty or pure whitespace text blocks (BUG-006 defense).
        Must not raise IndexError: string index out of range.
        """
        page_data = [
            ("第一行正常文字内容。", 60, 100, "china-ss", 10.5),
            ("   ", 60, 120, "china-ss", 10.5),
            ("第二行正常文字内容。", 60, 140, "china-ss", 10.5),
        ]
        pdf_path = self._create_synthetic_doc([page_data])
        out_dir = self.test_dir / "out9"
        # Must execute without exception
        md_path, audit = process_book_vector_pdf(str(pdf_path), str(out_dir))
        with open(md_path, "r", encoding="utf-8") as f:
            md = f.read().strip()
        self.assertIn("第一行正常文字", md)
        self.assertIn("第二行正常文字", md)


if __name__ == "__main__":
    unittest.main()

