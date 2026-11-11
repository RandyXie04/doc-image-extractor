# -*- coding: utf-8 -*-
"""
Empirical stress tests and adversarial edge cases for footnote alphabet callout conversion.
Tests challenge dimensions:
1. Dense English text with letters 'a', 'b', 'c' alongside CJK sentences.
2. Punctuation variants: quotes, brackets, semicolons, commas attached to 'a', 'b'.
3. Multi-character letter words (e.g. 'DNA', 'at', 'as') to verify they are never corrupted.
4. Complex citation lines at page bottom (citations with dates, editions, page ranges).
5. Mixed footnote formats (circled numbers and alphabet callouts in the same document).
6. Vulnerability & edge case probes:
   - Punctuation coverage (book title mark 》, colon ：, brackets ］, 〕, em-dash ——, ellipsis ……).
   - CJK words ending in Latin letters (维生素a, 方案a).
   - Alphabetic markers exceeding 'j' (e.g. 'k').
"""
import unittest

from src.founder_tools.core.marker_detector import MarkerDetector
from src.scripts.book_layout_extractor import (
    _circled_to_int,
    _replace_fn_markers_in_text,
    _normalize_symbol_font_spans,
    FN_MARKER_PATTERN,
    _FN_MARKER_SPLIT_RE,
)
from src.scripts.process_ocr import (
    process_page_footnotes,
    parse_footnote_entries,
    _FOOTNOTE_PREFIX_RE,
)


class TestStressDenseEnglishAndMultiCharWords(unittest.TestCase):
    """Stress testing: English text, multi-character words, mixed CJK/English contexts."""

    def test_english_standalone_articles_and_words_never_detected_as_markers(self):
        sentences = [
            "This is a book about a boy and a dog.",
            "Take a look at option a, then b, and finally c in Section A.",
            "A quick brown fox jumps over a lazy dog.",
            "It is a well-known fact that factor a and parameter b determine c.",
            "Plan a succeeded, while Plan b failed.",
            "Step a: initialize. Step b: process. Step c: finalize.",
        ]
        for s in sentences:
            matches = MarkerDetector.detect(s, "auto")
            self.assertEqual(len(matches), 0, f"False positive marker detected in English: {s}")

    def test_multi_char_words_and_acronyms_never_corrupted(self):
        multi_char_cases = [
            ("关于DNA和RNA的转录机制研究", 0),
            ("在as和at等介词用法中，a常作为不定冠词", 0),
            ("C语言中的malloc和free函数a", 1),  # trailing 'a' attached to CJK char '数'
            ("使用BERT和GPT模型进行NLP评测", 0),
            ("根据IEEE 802.11ac协议标准b", 1),  # trailing 'b' attached to CJK char '准'
            ("采用YOLOv8a模型进行目标检测", 0),
        ]
        for text, exp_count in multi_char_cases:
            matches = MarkerDetector.detect(text, "auto")
            self.assertEqual(len(matches), exp_count, f"Mismatch on {text!r}")
            if exp_count == 1:
                self.assertIn(matches[0].text, ("a", "b"))

    def test_replace_fn_markers_preserves_dense_english_surroundings(self):
        text = (
            "During the experiment, we observed that factor a had a significant impact on group b. "
            "特别是在对照组实验中，这一现象尤为显著。a "
            "Furthermore, as reported by Watson and Crick regarding DNA structure, model a fits well."
        )
        page_footnotes = [{"id": 1, "marker": "a", "content": "华莱士...", "matched": False}]
        replaced = _replace_fn_markers_in_text(text, page_footnotes, page_num=1)

        # The CJK marker at the end of the Chinese sentence should be replaced
        self.assertIn("这一现象尤为显著。[^p1_1]", replaced)
        # The English "factor a", "had a", "group b", "DNA", "model a" must NOT be corrupted
        self.assertIn("factor a had a significant impact on group b.", replaced)
        self.assertIn("regarding DNA structure, model a fits well.", replaced)
        self.assertTrue(page_footnotes[0]["matched"])


class TestStressPunctuationVariants(unittest.TestCase):
    """Stress testing: Quotes, brackets, colons, book title marks, fullwidth/halfwidth variants."""

    def test_supported_cjk_punctuation_callout_detection(self):
        supported_cases = [
            ("这是引文。”a", "a", 1),
            ("这是单引。’b", "b", 2),
            ("后引号a”", "a", 1),
            ("后括号a）", "a", 1),
            ("后逗号a，", "a", 1),
            ("后分号a；", "a", 1),
            ("后句号a。", "a", 1),
            ("半角后括号a)", "a", 1),
        ]
        for text, exp_char, exp_num in supported_cases:
            matches = MarkerDetector.detect(text, "auto")
            self.assertEqual(len(matches), 1, f"Failed detecting {text!r}")
            self.assertEqual(matches[0].text, exp_char)
            self.assertEqual(matches[0].number, exp_num)

            fn = [{"id": exp_num, "marker": exp_char, "content": "note", "matched": False}]
            res = _replace_fn_markers_in_text(text, fn, 1)
            self.assertTrue(fn[0]["matched"], f"Failed replacing {text!r}")
            self.assertIn(f"[^p1_{exp_num}]", res)

    def test_punctuation_edge_cases_and_coverage_gaps(self):
        """
        Adversarial probe: Uncovered CJK punctuation delimiters in regex lookaround:
        - Book title marks: 《...》a
        - Chinese colons: ：a
        - Em-dash / ellipsis: ——a, ……a
        - Fullwidth / tortoise brackets: ］a, 〕a
        - ASCII double quotes: "a"
        """
        gaps = [
            ("书名号》a", "》"),
            ("冒号：a", "："),
            ("破折号——a", "——"),
            ("省略号……a", "……"),
            ("全角方括号］a", "］"),
            ("龟壳括号〕a", "〕"),
        ]
        detected_gaps = []
        for text, punct in gaps:
            matches = MarkerDetector.detect(text, "auto")
            if len(matches) == 0:
                detected_gaps.append(punct)
        # Verify that these edge case punctuations currently fail detection
        self.assertIn("》", detected_gaps)
        self.assertIn("：", detected_gaps)
        self.assertIn("］", detected_gaps)
        self.assertIn("〕", detected_gaps)


class TestStressComplexCitations(unittest.TestCase):
    """Stress testing: Complex citations with publication years, editions, page ranges."""

    def test_multiple_complex_citations_bottom_block(self):
        fb_text = (
            "a 华莱士. 跳跃的无穷：无穷大简史. 胡凯衡译. 长沙：湖南科学技术出版社，2009. 35\n"
            "b 康托尔. 超穷数理论基础. 1895. 第2版. 北京：商务印书馆，1983. 112-115页.\n"
            "c Smith, J. D. (2020). Quantum Foundations, 3rd ed., pp. 45-50."
        )
        entries = parse_footnote_entries(fb_text)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["id"], 1)
        self.assertEqual(entries[1]["id"], 2)
        self.assertEqual(entries[2]["id"], 3)
        self.assertIn("2009. 35", entries[0]["content"])
        self.assertIn("1895.", entries[1]["content"])
        self.assertIn("1983.", entries[1]["content"])
        self.assertIn("(2020).", entries[2]["content"])

    def test_citation_with_various_delimiters(self):
        cases = [
            ("a. 参考文献一，2019. 45", "2019. 45"),
            ("b、参考文献二，2021. 88", "2021. 88"),
            ("[c] 参考文献三，2015. 12-14", "2015. 12-14"),
            ("(d) 参考文献四，2018. 99", "2018. 99"),
        ]
        for c, exp_sub in cases:
            entries = parse_footnote_entries(c)
            self.assertEqual(len(entries), 1, f"Failed parsing: {c}")
            self.assertIn(exp_sub, entries[0]["content"])


class TestStressMixedFootnoteFormats(unittest.TestCase):
    """Stress testing: Mixed footnote formats across document pages and within pipelines."""

    def test_mixed_formats_across_pages(self):
        # Page 1: Circled numbers ①, ②
        p1_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 350.0],
                    "surya_text": "第一页内容含有传统圆圈注标①，以及第二项②。",
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": "① 第一页注释一内容。\n② 第一页注释二内容。",
                    "type": None,
                },
            ],
        }
        # Page 2: Alphabet callouts a, b
        p2_info = {
            "page_idx": 1,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 350.0],
                    "surya_text": "第二页内容采用英文字母标记。a 以及下一个论点。b",
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": "a 第二页字母注释一。\nb 第二页字母注释二。",
                    "type": None,
                },
            ],
        }

        records1 = []
        body1, fn1, open1 = process_page_footnotes(
            p1_info, page_num=1, previous_open_footnote=None, audit_records=records1, enable_footnotes=True
        )
        self.assertEqual(len(fn1), 2)
        self.assertEqual(fn1[0]["id"], 1)
        self.assertEqual(fn1[1]["id"], 2)
        self.assertIn("[^p1_1]", body1[0]["md"])
        self.assertIn("[^p1_2]", body1[0]["md"])

        records2 = []
        body2, fn2, open2 = process_page_footnotes(
            p2_info, page_num=2, previous_open_footnote=None, audit_records=records2, enable_footnotes=True
        )
        self.assertEqual(len(fn2), 2)
        self.assertEqual(fn2[0]["id"], 1)
        self.assertEqual(fn2[1]["id"], 2)
        self.assertIn("[^p2_1]", body2[0]["md"])
        self.assertIn("[^p2_2]", body2[0]["md"])
        self.assertNotIn("标记。a", body2[0]["md"])
        self.assertNotIn("论点。b", body2[0]["md"])


class TestAdversarialFalsePositivesAndLimits(unittest.TestCase):
    """Adversarial testing: False positive collisions and index limitations."""

    def test_cjk_term_ending_in_latin_letter_collides_with_callout(self):
        """
        Adversarial probe: When a CJK noun ending with a Latin letter (like '维生素a', '方案a')
        appears in the same paragraph before a real footnote callout '。a',
        the regex replaces the noun rather than the actual callout.
        """
        text = "人体需要补充维生素a。另外，康托尔是集合论的创始人。a"
        page_footnotes = [{"id": 1, "marker": "a", "content": "华莱士...", "matched": False}]
        res = _replace_fn_markers_in_text(text, page_footnotes, page_num=1)
        # Note: res is '人体需要补充维生素[^p1_1]。另外，康托尔是集合论的创始人。a'
        # The true callout '创始人。a' is left unreplaced!
        has_misplaced_tag = "维生素[^p1_1]" in res
        self.assertTrue(has_misplaced_tag, "Confirmed collision vulnerability: '维生素a' matched before '。a'")

    def test_marker_range_limit_j_vs_k(self):
        """
        Adversarial probe: MarkerDetector and regex patterns only support a-j (1-10).
        Letter 'k' (11th footnote) fails detection.
        """
        matches_j = MarkerDetector.detect("这是第十个注释。j", "auto")
        self.assertEqual(len(matches_j), 1)
        self.assertEqual(matches_j[0].number, 10)

        matches_k = MarkerDetector.detect("这是第十一个注释。k", "auto")
        self.assertEqual(len(matches_k), 0, "Confirmed limit: 'k' (11) is excluded by [a-jA-J]")


if __name__ == "__main__":
    unittest.main()
