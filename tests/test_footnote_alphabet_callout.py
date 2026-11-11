# -*- coding: utf-8 -*-
"""
Unit tests for alphabet footnote callouts ('a', 'b', 'c' from custom symbol fonts like RopeSequenceNumber)
and non-regression across MarkerDetector, book_layout_extractor, and process_ocr.
"""
import re
import unittest

from src.founder_tools.core.marker_detector import MarkerDetector
from src.scripts.book_layout_extractor import (
    _circled_to_int,
    _replace_fn_markers_in_text,
    _normalize_symbol_font_spans,
    FN_MARKER_PATTERN,
    _FN_MARKER_SPLIT_RE,
    _STARTS_WITH_FN_MARKER_RE,
    is_strong_citation_text as ble_is_strong_citation,
)
from src.scripts.process_ocr import (
    process_page_footnotes,
    parse_footnote_entries,
    _FOOTNOTE_PREFIX_RE,
    is_strong_citation_text as ocr_is_strong_citation,
)


class TestMarkerDetectorAlphaCallout(unittest.TestCase):
    """Test MarkerDetector alpha_callout detection and boundary enforcement."""

    def test_alpha_callout_after_cjk_punctuation(self):
        text = "他可能做梦也没有想过自己和芝诺之间有什么联系。”他所说的德国教授是康托尔，集合论的创始人。a"
        matches = MarkerDetector.detect(text, "auto")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].text, "a")
        self.assertEqual(matches[0].number, 1)
        self.assertEqual(matches[0].start_char, len(text) - 1)
        self.assertEqual(matches[0].end_char, len(text))

    def test_alpha_callout_multiple_letters(self):
        text = "集合论的创始人。a 另一位数学家也提出了该猜想。b"
        matches = MarkerDetector.detect(text, "auto")
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0].text, "a")
        self.assertEqual(matches[0].number, 1)
        self.assertEqual(matches[1].text, "b")
        self.assertEqual(matches[1].number, 2)

    def test_alpha_callout_various_cjk_delimiters(self):
        cases = [
            ("这是引文。”a", "a", 1),
            ("这是单引。’b", "b", 2),
            ("逗号分句，c", "c", 3),
            ("感叹句！d", "d", 4),
            ("问句？e", "e", 5),
            ("顿号、f", "f", 6),
            ("分号；g", "g", 7),
            ("括号）h", "h", 8),
            ("方括号】i", "i", 9),
            ("汉字直接接字j", "j", 10),
        ]
        for txt, expected_char, expected_num in cases:
            matches = MarkerDetector.detect(txt, "auto")
            self.assertEqual(len(matches), 1, f"Failed on text: {txt}")
            self.assertEqual(matches[0].text, expected_char)
            self.assertEqual(matches[0].number, expected_num)

    def test_alpha_callout_negative_english_text(self):
        negative_cases = [
            "This is a test of Plan a and factor a in English.",
            "Chapter 1: A brief introduction to algebra.",
            "DNA replication requires enzyme A and protein B.",
            "We have a plan a to solve factor a.",
            "这是一个关于 Plan a 的测试。",
            "在英文单词 cat 和 apple 中不应触发。",
        ]
        for txt in negative_cases:
            matches = MarkerDetector.detect(txt, "alpha_callout")
            self.assertEqual(len(matches), 0, f"False positive on text: {txt}")


class TestBookLayoutExtractorAlphabetCallout(unittest.TestCase):
    """Test book_layout_extractor alphabet footnote conversion and year guard."""

    def test_circled_to_int_alphabet_mapping(self):
        self.assertEqual(_circled_to_int("a"), 1)
        self.assertEqual(_circled_to_int("b"), 2)
        self.assertEqual(_circled_to_int("j"), 10)
        self.assertEqual(_circled_to_int("z"), 26)
        self.assertEqual(_circled_to_int("A"), 1)
        self.assertEqual(_circled_to_int("B"), 2)
        self.assertEqual(_circled_to_int("a."), 1)
        self.assertEqual(_circled_to_int("b、"), 2)
        self.assertEqual(_circled_to_int("[a]"), 1)
        # Existing formats still work
        self.assertEqual(_circled_to_int("①"), 1)
        self.assertEqual(_circled_to_int("⑩"), 10)
        self.assertEqual(_circled_to_int("¹"), 1)
        self.assertEqual(_circled_to_int("2."), 2)

    def test_replace_fn_markers_in_text_with_alpha(self):
        text = "他所说的德国教授是康托尔，集合论的创始人。a"
        page_footnotes = [{"id": 1, "marker": "a", "content": "华莱士...", "matched": False}]
        replaced = _replace_fn_markers_in_text(text, page_footnotes, page_num=1)
        self.assertIn("创始人。[^p1_1]", replaced)
        self.assertNotIn("创始人。a", replaced)
        self.assertTrue(page_footnotes[0]["matched"])

    def test_replace_fn_markers_in_text_negative_english(self):
        text = "This is a test of Plan a and factor a in English."
        page_footnotes = [{"id": 1, "marker": "a", "content": "华莱士...", "matched": False}]
        replaced = _replace_fn_markers_in_text(text, page_footnotes, page_num=1)
        self.assertEqual(replaced, text)
        self.assertFalse(page_footnotes[0]["matched"])

    def test_publication_year_not_split_as_footnote(self):
        fb_text = "a 华莱士. 跳跃的无穷：无穷大简史. 胡凯衡译. 长沙：湖南科学技术出版社，2009. 35"
        parts = _FN_MARKER_SPLIT_RE.split(fb_text)
        # Should NOT split on '2009.'
        matched_markers = [parts[i].strip() for i in range(1, len(parts), 2)]
        self.assertNotIn("2009.", matched_markers)
        self.assertIn("a ", parts[1])

    def test_normalize_symbol_font_spans(self):
        spans = [
            {"text": "集合论的创始人。", "font": "SongTi", "size": 10.5},
            {"text": "a", "font": "JTEQUF+RopeSequenceNumberST-R", "size": 5.8},
            {"text": "b", "font": "XYZ+SequenceNumber-Regular", "size": 5.8},
            {"text": "Plan a", "font": "TimesNewRoman", "size": 10.5},
        ]
        norm = _normalize_symbol_font_spans(spans)
        self.assertEqual(norm[0]["text"], "集合论的创始人。")
        self.assertEqual(norm[1]["text"], "①")
        self.assertEqual(norm[2]["text"], "②")
        self.assertEqual(norm[3]["text"], "Plan a")


class TestProcessOcrAlphabetCallout(unittest.TestCase):
    """Test process_ocr alphabet footnote pipeline and clean callout replacement."""

    def test_footnote_alphabet_callout_extraction_and_clean_replacement(self):
        """
        Explorer 3 Case 1: Body ending in 'a' and footnote labeled 'footnote'.
        Asserts [^p1_1] linked and 'a' cleanly consumed without leaving '。a[^p1_1]'.
        """
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 350.0],
                    "surya_text": "他可能做梦也没有想过自己和芝诺之间有什么联系。”他所说的德国教授是康托尔，集合论的创始人。a",
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": "华莱士. 跳跃的无穷：无穷大简史. 胡凯衡译. 长沙：湖南科学技术出版社，2009. 35",
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

        # 1. Footnote properly extracted and parsed
        self.assertEqual(len(final_footnotes), 1)
        self.assertEqual(final_footnotes[0]["id"], 1)
        self.assertIn("华莱士", final_footnotes[0]["content"])

        # 2. Body contains Pandoc footnote tag [^p1_1]
        self.assertEqual(len(body_list), 1)
        body_md = body_list[0]["md"]
        self.assertIn("[^p1_1]", body_md)

        # 3. Raw callout marker 'a' MUST be consumed/replaced, NOT left as '。a[^p1_1]'
        self.assertNotIn("创始人。a", body_md)
        self.assertIn("创始人。[^p1_1]", body_md.replace(" ", ""))

    def test_footnote_alphabet_multiple_notes_with_text_label_at_page_bottom(self):
        """
        Explorer 3 Case 2: Multiple sequential alphabet callouts ('a', 'b')
        when Surya OCR labels bottom citation blocks as 'text' instead of 'footnote'.
        """
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 350.0],
                    "surya_text": "德国教授是康托尔，集合论的创始人。a 另一位学者发表了新的观点。b",
                    "type": None,
                },
                {
                    "original_label": "text",  # Classified as 'text' by Surya OCR at page bottom
                    "bbox": [100.0, 1100.0, 900.0, 1180.0],
                    "surya_text": "a 华莱士. 跳跃的无穷：无穷大简史. 湖南科学技术出版社，2009. 35",
                    "type": None,
                },
                {
                    "original_label": "text",
                    "bbox": [100.0, 1200.0, 900.0, 1280.0],
                    "surya_text": "b 康托尔. 集合论基础. 人民邮电出版社，2015. 12",
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

        self.assertEqual(len(final_footnotes), 2)
        self.assertEqual(final_footnotes[0]["id"], 1)
        self.assertEqual(final_footnotes[1]["id"], 2)

        body_md = body_list[0]["md"]
        self.assertIn("[^p1_1]", body_md)
        self.assertIn("[^p1_2]", body_md)
        self.assertNotIn("创始人。a", body_md)
        self.assertNotIn("观点。b", body_md)

    def test_english_sentence_negative_test_in_ocr_pipeline(self):
        """
        Verify that English words ("a", "Plan a", "factor a") are NEVER mistakenly replaced
        even when a footnote exists on the page.
        """
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 350.0],
                    "surya_text": "This is a test of Plan a and factor a in English text.",
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": "华莱士. 跳跃的无穷：无穷大简史. 2009. 35",
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

        # Body text should retain "a", "Plan a", "factor a" without mutilation
        body_md = body_list[0]["md"]
        self.assertIn("This is a test of Plan a and factor a in English text.", body_md)
        self.assertNotIn("Plan [^p", body_md)
        self.assertNotIn("factor [^p", body_md)


if __name__ == "__main__":
    unittest.main()
