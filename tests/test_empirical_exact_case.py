# -*- coding: utf-8 -*-
"""
Empirical verification harness for user's exact footnote alphabet callout case:
Body: "他可能做梦也没有想过自己和芝诺之间有什么联系。”他所说的德国教授是康托尔，集合论的创始人。a"
Footnote: "华莱士. 跳跃的无穷：无穷大简史. 胡凯衡译. 长沙：湖南科学技术出版社，2009. 35"

Verifies:
1. Vector PDF extraction pipeline (book_layout_extractor)
2. OCR pipeline (process_ocr)
3. Pandoc footnote tag [^p1_1] generation
4. Footnote definition creation
5. Complete consumption of raw 'a' callout (no "。a[^p1_1]" residue)
6. Publication year preservation (no phantom [^p1_2009])
7. English false-positive protection ("Plan a", "factor a")
"""
import os
import sys
import unittest
import tempfile
import fitz  # PyMuPDF

from src.scripts.book_layout_extractor import (
    process_book_vector_pdf,
    _parse_pdf_layout_flow,
    _replace_fn_markers_in_text,
    _circled_to_int,
    _normalize_symbol_font_spans,
    FN_MARKER_PATTERN,
    _FN_MARKER_SPLIT_RE,
)
from src.scripts.process_ocr import (
    process_page_footnotes,
    parse_footnote_entries,
    _FOOTNOTE_PREFIX_RE,
)
from src.founder_tools.core.marker_detector import MarkerDetector


class TestEmpiricalExactUserCase(unittest.TestCase):
    """Rigorous empirical tests covering the exact user scenario."""

    def setUp(self):
        self.body_text = '他可能做梦也没有想过自己和芝诺之间有什么联系。”他所说的德国教授是康托尔，集合论的创始人。a'
        self.footnote_text = '华莱士. 跳跃的无穷：无穷大简史. 胡凯衡译. 长沙：湖南科学技术出版社，2009. 35'
        self.footnote_with_prefix = 'a 华莱士. 跳跃的无穷：无穷大简史. 胡凯衡译. 长沙：湖南科学技术出版社，2009. 35'

    # =========================================================================
    # PIPELINE 1: OCR Pipeline Verification
    # =========================================================================

    def test_ocr_pipeline_exact_case_with_footnote_label(self):
        """Test OCR pipeline when Surya labels bottom block as 'footnote'."""
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 350.0],
                    "surya_text": self.body_text,
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": self.footnote_text,
                    "type": None,
                },
            ],
        }
        audit_records = []
        body_list, final_footnotes, open_fn = process_page_footnotes(
            page_info=page_info,
            page_num=1,
            previous_open_footnote=None,
            audit_records=audit_records,
            style_mapping={"body": "Normal"},
            enable_footnotes=True,
        )

        # 1. Footnote definition extracted
        self.assertEqual(len(final_footnotes), 1)
        self.assertEqual(final_footnotes[0]["id"], 1)
        self.assertIn("华莱士", final_footnotes[0]["content"])
        self.assertIn("2009. 35", final_footnotes[0]["content"])

        # 2. Body markdown verification
        self.assertEqual(len(body_list), 1)
        body_md = body_list[0]["md"]

        # 3. Tag generated
        self.assertIn("[^p1_1]", body_md)

        # 4. Raw 'a' completely consumed
        self.assertNotIn("创始人。a", body_md)
        self.assertIn("创始人。[^p1_1]", body_md)

        # 5. Full page rendering verification
        page_str = "\n\n".join(item["md"] for item in body_list)
        defs = [f"[^p1_{fn['id']}]: {fn['content']}" for fn in final_footnotes]
        page_str += "\n\n" + "\n\n".join(defs)

        self.assertIn("[^p1_1]: 华莱士", page_str)
        self.assertNotIn("[^p1_2009]", page_str)

    def test_ocr_pipeline_exact_case_with_text_label_and_citation_heuristic(self):
        """Test OCR pipeline when Surya mislabels bottom block as 'text'."""
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 350.0],
                    "surya_text": self.body_text,
                    "type": None,
                },
                {
                    "original_label": "text",  # Mislabeled as 'text'
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],  # Bottom region (> 0.72 page_h)
                    "surya_text": self.footnote_text,
                    "type": None,
                },
            ],
        }
        audit_records = []
        body_list, final_footnotes, open_fn = process_page_footnotes(
            page_info=page_info,
            page_num=1,
            previous_open_footnote=None,
            audit_records=audit_records,
            style_mapping={"body": "Normal"},
            enable_footnotes=True,
        )

        self.assertEqual(len(final_footnotes), 1)
        self.assertEqual(final_footnotes[0]["id"], 1)
        self.assertIn("华莱士", final_footnotes[0]["content"])
        body_md = body_list[0]["md"]
        self.assertIn("[^p1_1]", body_md)
        self.assertNotIn("创始人。a", body_md)

    def test_ocr_pipeline_exact_case_with_explicit_a_prefix(self):
        """Test OCR pipeline when footnote starts with 'a '."""
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 350.0],
                    "surya_text": self.body_text,
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": self.footnote_with_prefix,
                    "type": None,
                },
            ],
        }
        audit_records = []
        body_list, final_footnotes, open_fn = process_page_footnotes(
            page_info=page_info,
            page_num=1,
            previous_open_footnote=None,
            audit_records=audit_records,
            style_mapping={"body": "Normal"},
            enable_footnotes=True,
        )

        self.assertEqual(len(final_footnotes), 1)
        self.assertEqual(final_footnotes[0]["id"], 1)
        body_md = body_list[0]["md"]
        self.assertIn("[^p1_1]", body_md)
        self.assertNotIn("创始人。a", body_md)
        self.assertIn("创始人。[^p1_1]", body_md)

    # =========================================================================
    # PIPELINE 2: Vector PDF Extraction Pipeline Verification
    # =========================================================================

    def test_vector_pipeline_synthetic_pdf_end_to_end(self):
        """Create a real synthetic PDF with PyMuPDF and run process_book_vector_pdf."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test_book.pdf")
            out_dir = os.path.join(tmpdir, "output")
            os.makedirs(out_dir, exist_ok=True)

            # Generate synthetic PDF
            doc = fitz.open()
            page = doc.new_page(width=595, height=842)  # A4

            # Use CJK font so Chinese text is properly encoded in PDF text stream
            cjk_font_path = "C:/Windows/Fonts/simsun.ttc"
            page.insert_font(fontname="simsun", fontfile=cjk_font_path)

            # Insert body text with sufficient length so 10.5pt is detected as dominant body size
            full_body_text = (
                "在十九世纪末，数学界发生了一场深刻的思想变革。" * 3 + "\n" +
                self.body_text
            )
            rect_body = fitz.Rect(50, 100, 545, 450)
            page.insert_textbox(rect_body, full_body_text, fontname="simsun", fontsize=10.5)

            # Insert footnote text at bottom (> 842 * 0.65 = 547)
            rect_fn = fitz.Rect(50, 650, 545, 750)
            page.insert_textbox(rect_fn, self.footnote_with_prefix, fontname="simsun", fontsize=8.0)

            doc.save(pdf_path)
            doc.close()

            # Execute vector PDF pipeline
            audit_data = process_book_vector_pdf(
                pdf_path=pdf_path,
                output_dir=out_dir,
                output_stem="test_result",
                enable_footnotes=True,
            )

            # Check markdown output
            result_md_path = os.path.join(out_dir, "test_result.md")
            self.assertTrue(os.path.exists(result_md_path))

            with open(result_md_path, "r", encoding="utf-8") as f:
                md_content = f.read()

            # 1. Tag [^p1_1] generated
            self.assertIn("[^p1_1]", md_content)

            # 2. Footnote definition generated
            self.assertIn("[^p1_1]:", md_content)
            self.assertIn("华莱士", md_content)

            # 3. Raw callout marker 'a' consumed
            self.assertNotIn("创始人。a", md_content)
            self.assertIn("创始人。[^p1_1]", md_content.replace(" ", ""))

            # 4. Publication year 2009. not split into phantom footnote
            self.assertNotIn("[^p1_2009]", md_content)

    def test_vector_pipeline_with_symbol_font_normalization(self):
        """Test symbol font span normalization (RopeSequenceNumberST-R)."""
        spans = [
            {"text": "集合论的创始人。", "font": "SongTi", "size": 10.5},
            {"text": "a", "font": "XYZ+RopeSequenceNumberST-R", "size": 5.5},
        ]
        norm = _normalize_symbol_font_spans(spans)
        self.assertEqual(norm[1]["text"], "①")

        # Now test that _replace_fn_markers_in_text handles the normalized circled number
        text = "".join(s["text"] for s in norm)
        self.assertEqual(text, "集合论的创始人。①")
        page_footnotes = [{"id": 1, "marker": "①", "content": "华莱士...", "matched": False}]
        res = _replace_fn_markers_in_text(text, page_footnotes, page_num=1)
        self.assertIn("创始人。[^p1_1]", res)
        self.assertNotIn("①", res)
        self.assertTrue(page_footnotes[0]["matched"])

    # =========================================================================
    # FALSE POSITIVES & ADVERSARIAL STRESS
    # =========================================================================

    def test_english_false_positives_guard(self):
        """Assert English words and formulas containing 'a' are never converted."""
        english_texts = [
            "This is a paragraph discussing Plan a and factor a in detail.",
            "As stated in step a, we calculate variable a + b = c.",
            "Chapter 1: A brief note on method a.",
        ]
        for t in english_texts:
            fn = [{"id": 1, "marker": "a", "content": "华莱士...", "matched": False}]
            res = _replace_fn_markers_in_text(t, fn, page_num=1)
            self.assertEqual(res, t)
            self.assertFalse(fn[0]["matched"])

    def test_mixed_english_and_cjk_callout(self):
        """When English words ('Plan a') and CJK callout ('创始人。a') coexist in same text."""
        text = "Under Plan a, 我们得出了新的结论，这是集合论的创始人。a"
        fn = [{"id": 1, "marker": "a", "content": "华莱士...", "matched": False}]
        res = _replace_fn_markers_in_text(text, fn, page_num=1)

        # Plan a must stay Plan a
        self.assertIn("Under Plan a", res)
        # CJK callout must become [^p1_1]
        self.assertIn("创始人。[^p1_1]", res)
        self.assertNotIn("创始人。a", res)
        self.assertTrue(fn[0]["matched"])


if __name__ == "__main__":
    unittest.main()
