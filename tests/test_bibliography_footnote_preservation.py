# -*- coding: utf-8 -*-
"""
Tests for bibliography citation and footnote preservation:
R1. Fix Footnote False-Positive in Bibliography Citations:
    Citation page numbers (e.g. "上海: 上海文化出版社,2008:283.") must not be misidentified
    or converted into footnote references like "[^p191_283]".
R2. Prevent Text Loss in Footnote/Citation Entries:
    Preceding citation text must not disappear leaving only the page number.
R3. Preserve Legitimate Footnote Processing:
    Legitimate footnote markers and definitions continue to be identified, extracted, and linked.
Reproduction Document:
    data/01_input/元明文学经典研究-内文.pdf
"""
import os
import unittest
import fitz

from src.scripts.book_layout_extractor import (
    extract_book_vector_ast,
    process_book_vector_pdf,
    _replace_fn_markers_in_text,
    _FN_MARKER_SPLIT_RE,
    is_strong_citation_text,
)
from src.scripts.process_ocr import (
    process_page_footnotes,
    parse_footnote_entries,
)


class TestBibliographyFootnotePreservation(unittest.TestCase):
    """Test suite ensuring bibliography citations and legitimate footnotes are correctly handled."""

    def setUp(self):
        self.reproduction_pdf = os.path.join(
            os.path.dirname(__file__), "..", "data", "01_input", "元明文学经典研究-内文.pdf"
        )

    def test_citation_page_number_not_split_in_book_layout(self):
        """Verify _FN_MARKER_SPLIT_RE does not split bibliography citation page numbers like '2008:283.'."""
        text = "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283."
        parts = _FN_MARKER_SPLIT_RE.split(text)
        # Should not split into '2008:' and marker '283.'
        self.assertNotIn("283.", parts)
        self.assertEqual(parts, [text])

    def test_citation_page_number_with_space_not_split(self):
        """Verify citation page numbers with spaces (e.g. '2008: 283.') are not split."""
        text = "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社, 2008: 283."
        parts = _FN_MARKER_SPLIT_RE.split(text)
        self.assertNotIn("283.", parts)
        self.assertEqual(parts, [text])

    def test_citation_page_abbreviations_and_delimiters_not_split(self):
        """Verify p., pp., Vol., semicolons, and 第 X. are not split into phantom footnotes."""
        cases = [
            "See p. 283.",
            "See p.283.",
            "See pp. 283.",
            "See pp.283.",
            "See P. 283.",
            "See PP. 283.",
            "See Vol. 1.",
            "See vol. 1.",
            "上海文化出版社,2008; 283.",
            "上海文化出版社,2008;283.",
            "见第 15. 页",
            "见第15. 页",
        ]
        for c in cases:
            parts = _FN_MARKER_SPLIT_RE.split(c)
            self.assertNotIn("283.", parts, f"Failed on case: {c}")
            self.assertNotIn("1.", parts, f"Failed on case: {c}")
            self.assertNotIn("15.", parts, f"Failed on case: {c}")

    def test_replace_fn_markers_does_not_convert_page_abbreviations_or_semicolons(self):
        """Verify _replace_fn_markers_in_text guards p., pp., Vol., and semicolons."""
        fake_page_footnotes = [
            {"id": 283, "marker": "283.", "content": ""},
            {"id": 1, "marker": "1.", "content": ""},
        ]
        body = "See p. 283. and pp. 283. and Vol. 1. and 2008; 283. here."
        replaced = _replace_fn_markers_in_text(body, fake_page_footnotes, page_num=1)
        self.assertIn("p. 283.", replaced)
        self.assertIn("pp. 283.", replaced)
        self.assertIn("Vol. 1.", replaced)
        self.assertIn("2008; 283.", replaced)
        self.assertNotIn("[^p1_283]", replaced)
        self.assertNotIn("[^p1_1]", replaced)

    def test_footnote_header_label_does_not_swallow_bracket_marker(self):
        """Verify footnote block prefix like '注释：' does not swallow [1] as citation part."""
        text = "注释：\n[1] 第一条文献\n[2] 第二条文献"
        entries = parse_footnote_entries(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["id"], 1)
        self.assertEqual(entries[0]["raw_marker"], "[1]")
        self.assertEqual(entries[0]["content"], "第一条文献")
        self.assertEqual(entries[1]["id"], 2)
        self.assertEqual(entries[1]["raw_marker"], "[2]")
        self.assertEqual(entries[1]["content"], "第二条文献")

    def test_is_strong_citation_text_rejects_running_headers(self):
        """Verify is_strong_citation_text does not misclassify running part headers like '中编：《水浒传》'."""
        self.assertFalse(is_strong_citation_text("中编：《水浒传》"))
        self.assertFalse(is_strong_citation_text("上编：《红楼梦》"))
        self.assertTrue(is_strong_citation_text("曹雪芹著，高鹗续.《红楼梦》"))
        self.assertTrue(is_strong_citation_text("袁行霈主编.《中国文学史》"))

    def test_footnote_with_bracket_and_citation_parsed_intact(self):
        """Verify footnote starting with [1] containing citation preserves full text including page number."""
        text = "[1] 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283."
        parts = _FN_MARKER_SPLIT_RE.split(text)
        self.assertEqual(parts, ["", "[1]", " 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283."])

    def test_replace_fn_markers_does_not_convert_citation_page_number(self):
        """Verify _replace_fn_markers_in_text does not turn '2008:283.' into '2008:[^p191_283]'."""
        body = "关于这一观点，可见潘知常在其著作（上海: 上海文化出版社,2008:283.）中的详述。"
        # Even if a footnote with id 283 existed on page, it must never corrupt citation
        fake_page_footnotes = [{"id": 283, "marker": "283.", "content": ""}]
        replaced = _replace_fn_markers_in_text(body, fake_page_footnotes, page_num=191)
        self.assertIn("2008:283.", replaced)
        self.assertNotIn("[^p191_283]", replaced)

    def test_parse_footnote_entries_preserves_preceding_text_on_newline(self):
        """Verify parse_footnote_entries does not lose preceding text when citation wraps across newline."""
        text = "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:\n283."
        entries = parse_footnote_entries(text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], 1)
        self.assertIn("潘知常", entries[0]["content"])
        self.assertIn("2008:\n283.", entries[0]["content"])

    def test_parse_footnote_entries_with_bracket_and_wrapped_citation(self):
        """Verify parse_footnote_entries with bracket marker and wrapped citation preserves page number."""
        text = "[1] 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:\n283."
        entries = parse_footnote_entries(text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], 1)
        self.assertEqual(entries[0]["raw_marker"], "[1]")
        self.assertIn("2008:\n283.", entries[0]["content"])

    def test_ocr_process_page_footnotes_preserves_citation(self):
        """Verify OCR pipeline process_page_footnotes preserves citation text without phantom tags."""
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 350.0],
                    "surya_text": "人们痛斥孙二娘“最不堪为妻”[1]，但她亦有三不杀。另外引文见2008:283.处。",
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": "[1] 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283.",
                    "type": None,
                },
            ],
        }
        audit_records = []
        body_list, final_footnotes, _ = process_page_footnotes(
            page_info=page_info,
            page_num=191,
            previous_open_footnote=None,
            audit_records=audit_records,
            enable_footnotes=True,
        )

        body_md = body_list[0]["md"]
        # Legitimate footnote linked
        self.assertIn("“最不堪为妻”[^p191_1]", body_md)
        # Citation page number in body preserved without corruption
        self.assertIn("2008:283.", body_md)
        self.assertNotIn("[^p191_283]", body_md)

        # Footnote definition preserved intact
        self.assertEqual(len(final_footnotes), 1)
        self.assertEqual(final_footnotes[0]["id"], 1)
        self.assertEqual(
            final_footnotes[0]["content"],
            "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283.",
        )

    def test_reproduction_pdf_page_191_extraction(self):
        """
        Verify reproduction document 元明文学经典研究-内文.pdf on page 191:
        1. Outputs '2008:283.' without converting into '[^p191_283]'.
        2. Footnote [1] has full intact content '潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283.'.
        3. Preceding body text '痛斥孙二娘...' is completely preserved in the body.
        4. Footnote anchor '“最不堪为妻” [^p191_1]' is correctly linked.
        5. No phantom [^p191_283] exists anywhere.
        """
        if not os.path.exists(self.reproduction_pdf):
            self.skipTest(f"Reproduction PDF not found at {self.reproduction_pdf}")

        ast = extract_book_vector_ast(
            self.reproduction_pdf, page_range=(191, 191), enable_footnotes=True
        )
        ast_dict = ast.to_dict()

        # 1. Exactly 1 footnote matched, 0 fallbacks
        self.assertEqual(ast_dict["audit_data"]["footnotes_matched"], 1)
        self.assertEqual(ast_dict["audit_data"]["footnotes_fallback"], 0)

        # 2. Footnote detail content contains 2008:283.
        fn_detail = ast_dict["audit_data"]["footnotes_detail"]
        self.assertEqual(len(fn_detail), 1)
        self.assertEqual(fn_detail[0]["id"], 1)
        self.assertIn("2008:283.", fn_detail[0]["content"])
        self.assertNotIn("283", [str(f["id"]) for f in fn_detail if f["id"] == 283])

        raw_content = ast.sections[0].raw_content

        # 3. Footnote definition is intact
        self.assertIn(
            "[^p191_1]: 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283.",
            raw_content,
        )

        # 4. No phantom tag [^p191_283]
        self.assertNotIn("[^p191_283]", raw_content)
        self.assertNotIn("2008:[^p", raw_content)

        # 5. Preceding citation text in body is preserved
        self.assertIn("痛斥孙二娘的穷凶极恶、心狠手辣", raw_content)
        self.assertIn("“最不堪为妻”", raw_content)
        self.assertIn("[^p191_1]", raw_content)

    def test_reproduction_pdf_page_10_extraction(self):
        """
        Verify reproduction document 元明文学经典研究-内文.pdf on page 10:
        Citation '李占鹏. 关汉卿评传[M]. 南京: 南京大学出版社,2000:158.' is intact without phantom [^p10_158].
        """
        if not os.path.exists(self.reproduction_pdf):
            self.skipTest(f"Reproduction PDF not found at {self.reproduction_pdf}")

        ast = extract_book_vector_ast(
            self.reproduction_pdf, page_range=(10, 10), enable_footnotes=True
        )
        ast_dict = ast.to_dict()

        self.assertEqual(ast_dict["audit_data"]["footnotes_matched"], 1)
        self.assertEqual(ast_dict["audit_data"]["footnotes_fallback"], 0)

        fn_detail = ast_dict["audit_data"]["footnotes_detail"]
        self.assertEqual(len(fn_detail), 1)
        self.assertEqual(fn_detail[0]["id"], 1)
        self.assertIn("2000:158.", fn_detail[0]["content"])

        all_content = "\n".join(s.raw_content for s in ast.sections)
        self.assertIn(
            "[^p10_1]: 李占鹏. 关汉卿评传[M]. 南京: 南京大学出版社,2000:158.",
            all_content,
        )
        self.assertNotIn("[^p10_158]", all_content)
        self.assertNotIn("2000:[^p", all_content)

    def test_reproduction_pdf_full_pipeline_process_book_vector_pdf(self):
        """Verify full process_book_vector_pdf pipeline on reproduction PDF preserves citations and body text."""
        import tempfile
        if not os.path.exists(self.reproduction_pdf):
            self.skipTest(f"Reproduction PDF not found at {self.reproduction_pdf}")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_md, audit = process_book_vector_pdf(
                pdf_path=self.reproduction_pdf,
                output_dir=tmpdir,
                enable_footnotes=True,
                fonts_json_path=os.path.join(tmpdir, "fonts.json"),
            )
            with open(out_md, "r", encoding="utf-8") as f:
                content = f.read()

            # Page 191 citation and body checks
            self.assertIn(
                "[^p191_1]: 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283.",
                content,
            )
            self.assertNotIn("[^p191_283]", content)
            self.assertNotIn("2008:[^p", content)
            self.assertIn("痛斥孙二娘的穷凶极恶、心狠手辣", content)

            # Page 10 citation check
            self.assertIn(
                "[^p10_1]: 李占鹏. 关汉卿评传[M]. 南京: 南京大学出版社,2000:158.",
                content,
            )
            self.assertNotIn("[^p10_158]", content)
            self.assertNotIn("2000:[^p", content)

            # Page 13 [J] and issue number citation check
            self.assertIn(
                "[^p13_1]: 陈颀. 司法冤案与儒家礼法：以《窦娥冤》为例[J]. 中外法学,2014(5):1264.",
                content,
            )
            self.assertNotIn("[^p13_10]", content)
            self.assertNotIn("[^p13_5]", content)

    def test_journal_and_dissertation_document_tags_not_split(self):
        """Verify [J], [D], [C], [M] and issue numbers (5) are not split as phantom footnotes."""
        text_j = "[1] 陈颀. 司法冤案与儒家礼法：以《窦娥冤》为例[J]. 中外法学,2014(5):1264."
        parts_j = _FN_MARKER_SPLIT_RE.split(text_j)
        self.assertEqual(parts_j, ["", "[1]", " 陈颀. 司法冤案与儒家礼法：以《窦娥冤》为例[J]. 中外法学,2014(5):1264."])

        text_d = "[1] 李某. 关汉卿研究[D]. 南京: 南京大学, 2005: 12."
        parts_d = _FN_MARKER_SPLIT_RE.split(text_d)
        self.assertEqual(parts_d, ["", "[1]", " 李某. 关汉卿研究[D]. 南京: 南京大学, 2005: 12."])

    def test_english_citations_with_alphabet_characters_not_shredded(self):
        """Verify English citations with words ending in a-j do not produce phantom footnote splits."""
        text1 = "[1] Published by Oxford University Press, 2008: 283."
        parts1 = _FN_MARKER_SPLIT_RE.split(text1)
        self.assertEqual(parts1, ["", "[1]", " Published by Oxford University Press, 2008: 283."])

        text2 = "[1] The Oxford History of English Literature, vol. 1."
        parts2 = _FN_MARKER_SPLIT_RE.split(text2)
        self.assertEqual(parts2, ["", "[1]", " The Oxford History of English Literature, vol. 1."])

    def test_volume_and_page_prefixes_not_split(self):
        """Verify Chinese volume, page, and book division prefixes are preserved."""
        text1 = "引文见《明史》卷283.以及《清史稿》卷 283.处。"
        parts1 = _FN_MARKER_SPLIT_RE.split(text1)
        self.assertNotIn("283.", parts1)

        fake_page_footnotes = [{"id": 283, "marker": "283.", "content": ""}]
        replaced = _replace_fn_markers_in_text(text1, fake_page_footnotes, page_num=1)
        self.assertNotIn("[^p1_283]", replaced)
        self.assertIn("卷283.", replaced)
        self.assertIn("卷 283.", replaced)

    def test_bracketed_legitimate_footnote_after_volume_not_blocked(self):
        """Verify legitimate bracketed footnotes attached to volume/page words (e.g. 第3卷[1]) are linked."""
        fns = [{"id": 1, "marker": "[1]", "content": "注释内容"}]
        res = _replace_fn_markers_in_text("见第3卷[1]的论述", fns, page_num=1)
        self.assertEqual(res, "见第3卷[^p1_1]的论述")

    def test_reproduction_pdf_page_13_extraction(self):
        """
        Verify reproduction document 元明文学经典研究-内文.pdf on page 13:
        1. Footnote [1] has full intact content '陈颀. 司法冤案与儒家礼法：以《窦娥冤》为例[J]. 中外法学,2014(5):1264.'.
        2. Zero fallback phantom footnotes ([^p13_10], [^p13_5]).
        """
        if not os.path.exists(self.reproduction_pdf):
            self.skipTest(f"Reproduction PDF not found at {self.reproduction_pdf}")

        ast = extract_book_vector_ast(
            self.reproduction_pdf, page_range=(13, 13), enable_footnotes=True
        )
        ast_dict = ast.to_dict()

        self.assertEqual(ast_dict["audit_data"]["footnotes_matched"], 1)
        self.assertEqual(ast_dict["audit_data"]["footnotes_fallback"], 0)

        fn_detail = ast_dict["audit_data"]["footnotes_detail"]
        self.assertEqual(len(fn_detail), 1)
        self.assertEqual(fn_detail[0]["id"], 1)
        self.assertIn("2014(5):1264.", fn_detail[0]["content"])
        self.assertIn("[J].", fn_detail[0]["content"])

        all_content = "\n".join(s.raw_content for s in ast.sections)
        self.assertIn(
            "[^p13_1]: 陈颀. 司法冤案与儒家礼法：以《窦娥冤》为例[J]. 中外法学,2014(5):1264.",
            all_content,
        )
        self.assertNotIn("[^p13_10]", all_content)
        self.assertNotIn("[^p13_5]", all_content)

    def test_multispace_and_newline_citations_in_replace_fn_markers(self):
        """Verify _replace_fn_markers_in_text handles multiple spaces, newlines, and ranges without corrupting page numbers."""
        cases = [
            "上海: 上海文化出版社,2008:  283. 另见下文",
            "上海: 上海文化出版社,2008:\n283. 另见下文",
            "上海: 上海文化出版社,2008:  1. 另见下文",
            "上海: 上海文化出版社,2008:\n1. 另见下文",
            "引文见《明史》卷  283.处。",
            "See Oxford Press, p.  283.",
            "See Oxford Press, pp.  283-285.",
        ]
        fake_fns = [
            {"id": 283, "marker": "283.", "content": ""},
            {"id": 1, "marker": "1.", "content": ""},
        ]
        for c in cases:
            res = _replace_fn_markers_in_text(c, fake_fns, page_num=100)
            self.assertNotIn("[^p100_", res, f"Erroneous footnote substitution on case: {c}")

    def test_multispace_citation_in_ocr_process_page_footnotes(self):
        """Verify process_page_footnotes links legitimate anchor without hijacking multi-space citation page number."""
        page_info = {
            "page_idx": 0,
            "page_size": [1000, 1400],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [0, 0, 100, 100],
                    "surya_text": "另外引文见2008:  1. 处，正文在此[1]。",
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [0, 900, 100, 1000],
                    "surya_text": "1. 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283.",
                    "type": None,
                },
            ],
        }
        body_list, fns, _ = process_page_footnotes(
            page_info, 100, None, [], style_mapping={}, enable_footnotes=True
        )
        body_md = body_list[0]["md"]
        # Legitimate anchor linked
        self.assertIn("正文在此[^p100_1]。", body_md)
        # Citation page number intact
        self.assertIn("2008:  1.", body_md)
        self.assertNotIn("2008:  [^p", body_md)

    def test_citation_page_ranges_not_split_or_converted(self):
        """Verify citation page ranges (e.g. 2008: 283-285. or 2008: 283～285.) remain intact."""
        text = "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008: 283-285."
        entries = parse_footnote_entries(text)
        self.assertEqual(len(entries), 1)
        self.assertIn("283-285.", entries[0]["content"])

    def test_reproduction_pdf_page_209_extraction(self):
        """
        Verify reproduction document 元明文学经典研究-内文.pdf on page 209:
        1. URLs containing embedded numbers ('book118.com', 'doc88.com') are NOT split.
        2. Exactly 3 footnotes matched, 0 fallback phantom footnotes ([^p209_118], [^p209_88]).
        3. Footnote definitions contain full intact URLs.
        4. Preceding and body text anchors are preserved.
        """
        if not os.path.exists(self.reproduction_pdf):
            self.skipTest(f"Reproduction PDF not found at {self.reproduction_pdf}")

        ast = extract_book_vector_ast(
            self.reproduction_pdf, page_range=(209, 209), enable_footnotes=True
        )
        ast_dict = ast.to_dict()

        self.assertEqual(ast_dict["audit_data"]["footnotes_matched"], 3)
        self.assertEqual(ast_dict["audit_data"]["footnotes_fallback"], 0)

        fn_detail = ast_dict["audit_data"]["footnotes_detail"]
        self.assertEqual(len(fn_detail), 3)
        fn_ids = [f["id"] for f in fn_detail]
        self.assertEqual(fn_ids, [1, 2, 3])
        self.assertNotIn(118, fn_ids)
        self.assertNotIn(88, fn_ids)

        all_content = "\n".join(s.raw_content for s in ast.sections)
        self.assertIn("https://max.book118.com/html/2020/0703/6234114100002214.shtm.", all_content)
        self.assertIn("https://www.doc88.com/p-1078449955416.html.", all_content)
        self.assertNotIn("[^p209_118]", all_content)
        self.assertNotIn("[^p209_88]", all_content)

    def test_url_domains_and_ip_addresses_not_split(self):
        """Verify URL domains and alphanumeric numbers are not split into phantom footnotes."""
        cases = [
            "https://max.book118.com/html/2020/0703/6234114100002214.shtm.",
            "https://www.doc88.com/p-1078449955416.html.",
            "http://192.168.1.1/index.html",
            "See website www.win7.org for details.",
        ]
        for c in cases:
            parts = _FN_MARKER_SPLIT_RE.split(c)
            self.assertNotIn("118.", parts)
            self.assertNotIn("88.", parts)
            self.assertNotIn("1.", parts)

    def test_line_wrapped_citation_with_preceding_context(self):
        """Verify _replace_fn_markers_in_text guards line-wrapped citation with preceding_context."""
        fake_page_footnotes = [{"id": 283, "marker": "283.", "content": ""}]
        line1 = "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:"
        line2 = "283. 另见下文。"
        res1 = _replace_fn_markers_in_text(line1, fake_page_footnotes, 100)
        res2 = _replace_fn_markers_in_text(line2, fake_page_footnotes, 100, preceding_context=line1)
        self.assertNotIn("[^p100_283]", res2)
        self.assertIn("283. 另见下文。", res2)

    def test_gbt_7714_electronic_tags_recognized(self):
        """Verify GB/T 7714 literature types like [EB/OL], [DB/OL], [M/CD] are recognized."""
        self.assertTrue(is_strong_citation_text("[1] 冉婷婷. 女性观[EB/OL].（2020-07-06）"))
        self.assertTrue(is_strong_citation_text("[1] 中国学术期刊数据库[DB/OL]."))
        self.assertTrue(is_strong_citation_text("[1] 中国大百科全书[M/CD]. 北京: 中国大百科全书出版社"))

    def test_adversarial_year_dot_and_chinese_year_citations_not_split(self):
        """Verify citations with dot year, Chinese year, edition, and non-numeric volumes are not split."""
        cases = [
            "潘知常. 说《水浒》人物[M]. 2008. 283.",
            "潘知常. 说《水浒》人物[M]. 2008年 283.",
            "潘知常. 说《水浒》人物[M]. 2008年版 283.",
            "王阳明全集·上册: 283.",
            "王阳明全集·卷五: 1.",
            "潘知常. 说《水浒》人物[M]. [M]. 283.",
            "潘知常. 女性观[EB/OL]. [EB/OL]. 283.",
            "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社, 2008:  283.",
            "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社, 2008:\u3000283.",
            "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社, 2008:\t283.",
        ]
        for c in cases:
            parts = _FN_MARKER_SPLIT_RE.split(c)
            self.assertNotIn("283.", parts, f"Erroneous marker split on: {c}")
            self.assertNotIn("1.", parts, f"Erroneous marker split on: {c}")

    def test_adversarial_replace_fn_markers_year_dot_and_chinese_year(self):
        """Verify _replace_fn_markers_in_text guards dot year, Chinese year, and volume citations."""
        fake_fns = [
            {"id": 283, "marker": "283.", "content": ""},
            {"id": 1, "marker": "1.", "content": ""},
        ]
        cases = [
            "长沙：湖南科学技术出版社，2009. 283. 另见后文。",
            "上海文化出版社，2008年 283. 另见下文。",
            "上海文化出版社，2008年版 283. 另见下文。",
            "引文见王阳明全集上册: 1. 另见下文。",
            "引文见王阳明全集卷五: 283. 另见下文。",
            "潘知常. 说《水浒》人物[M]. [M]. 283. 另见下文。",
        ]
        for c in cases:
            res = _replace_fn_markers_in_text(c, fake_fns, page_num=100)
            self.assertNotIn("[^p100_283]", res, f"Erroneously converted on: {c}")
            self.assertNotIn("[^p100_1]", res, f"Erroneously converted on: {c}")

    def test_dot_number_footnote_entries_with_wrapped_citations(self):
        """Verify parse_footnote_entries with dot_number markers does not fracture wrapped citations."""
        cases = [
            "1. 潘知常. 说《水浒》人物[M]. 2008. \n283.",
            "1. 潘知常. 说《水浒》人物[M]. 2008年 \n283.",
            "1. 潘知常. 说《水浒》人物[M]. 上册: \n283.",
            "1. 潘知常. 说《水浒》人物[M]. [M]. \n283.",
        ]
        for c in cases:
            entries = parse_footnote_entries(c)
            self.assertEqual(len(entries), 1, f"Expected 1 entry, got {len(entries)} for: {c}")
            self.assertEqual(entries[0]["id"], 1)
            self.assertIn("283.", entries[0]["content"])

    def test_multi_dot_numbered_footnotes_with_wrapped_citations(self):
        """Verify multiple dot-numbered footnotes with wrapped citations are correctly parsed as separate entries."""
        text = (
            "1. 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:\n"
            "283.\n"
            "2. 聂绀弩. 中国古典小说论集[M]. 上海: 上海古籍出版社,1981:\n"
            "3."
        )
        entries = parse_footnote_entries(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["id"], 1)
        self.assertIn("2008:\n283.", entries[0]["content"])
        self.assertEqual(entries[1]["id"], 2)
        self.assertIn("1981:\n3.", entries[1]["content"])

    def test_citation_page_number_with_three_and_four_spaces_not_split(self):
        """Verify citations with 3 or 4 spaces before page numbers are not split into phantom footnotes."""
        cases = [
            "上海文化出版社,2008:   283.",
            "上海文化出版社,2008:    283.",
            "上海文化出版社, 2008:   283.",
            "见第   15. 页",
            "引文见《明史》卷   283.处。",
            "See p.   283.",
            "See pp.   283.",
        ]
        for c in cases:
            parts = _FN_MARKER_SPLIT_RE.split(c)
            self.assertNotIn("283.", parts, f"Failed on case: {c}")
            self.assertNotIn("15.", parts, f"Failed on case: {c}")

    def test_ocr_process_page_footnotes_wrapped_across_para_blocks(self):
        """Verify OCR pipeline does not hijack page numbers wrapped across blocks."""
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 250.0],
                    "surya_text": "潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:",
                    "type": None,
                },
                {
                    "original_label": "text",
                    "bbox": [100.0, 260.0, 900.0, 310.0],
                    "surya_text": "283. 另见说明[1]。",
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": "1. 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283.",
                    "type": None,
                },
            ],
        }
        body_list, final_footnotes, _ = process_page_footnotes(
            page_info=page_info,
            page_num=191,
            previous_open_footnote=None,
            audit_records=[],
            enable_footnotes=True,
        )
        self.assertNotIn("[^p191_283]", body_list[1]["md"])
        self.assertIn("[^p191_1]", body_list[1]["md"])
        self.assertEqual(len(final_footnotes), 1)
        self.assertEqual(final_footnotes[0]["id"], 1)

    def test_book_layout_flow_wrapped_across_para_blocks(self):
        """Verify vector PDF layout pipeline preserves cross-block citation page numbers without phantom tags."""
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        page.insert_text((50, 70), "这是正文第一段，包含足够字数的正文内容以确立正文字体大小为标准十磅。", fontsize=10)
        page.insert_text((50, 100), "关于此问题，见潘知常先生著作。上海: 上海文化出版社,2008:", fontsize=10)
        page.insert_text((50, 150), "283. 另见详细阐述[1]。", fontsize=10)
        page.insert_text((50, 550), "1. 潘知常. 说《水浒》人物[M]. 上海: 上海文化出版社,2008:283.", fontsize=8)
        page.insert_text((50, 600), "283. 假注脚定义。", fontsize=8)

        from src.scripts.book_layout_extractor import _parse_pdf_layout_flow
        pages, _, audit, _ = _parse_pdf_layout_flow(doc, enable_footnotes=True)
        self.assertTrue(len(pages) > 0)
        page_md = pages[0]
        self.assertIn("2008:", page_md)
        self.assertIn("283. ", page_md)
        self.assertIn("[^p1_1]", page_md)

    def test_ocr_process_page_footnotes_with_weak_dot_marker_commentary(self):
        """Verify OCR pipeline correctly links weak dot markers on commentary footnotes and preserves citations."""
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 300.0],
                    "surya_text": "关汉卿评传（南京大学出版社,2000: 1.）论述深刻，学者在此处附注 1. 予以详细说明。",
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": "1. 此处曲白互见，为全剧高潮所在，见王国维考证。",
                    "type": None,
                },
            ],
        }
        body_list, final_footnotes, _ = process_page_footnotes(
            page_info=page_info,
            page_num=10,
            previous_open_footnote=None,
            audit_records=[],
            enable_footnotes=True,
        )
        self.assertEqual(len(final_footnotes), 1)
        self.assertEqual(final_footnotes[0]["id"], 1)
        self.assertEqual(final_footnotes[0]["content"], "此处曲白互见，为全剧高潮所在，见王国维考证。")
        body_md = body_list[0]["md"]
        self.assertIn("2000: 1.", body_md)
        self.assertNotIn("2000: [^p", body_md)
        self.assertIn("此处附注 [^p10_1] 予以详细说明。", body_md)

    def test_ocr_process_page_footnotes_with_paren_marker_commentary(self):
        """Verify OCR pipeline correctly links paren markers on commentary footnotes and preserves journal citations."""
        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 900.0, 300.0],
                    "surya_text": "引文见《中外法学》,2014(5):1264. 另有关汉卿戏曲评论在此处附注 (5) 备考。",
                    "type": None,
                },
                {
                    "original_label": "footnote",
                    "bbox": [100.0, 1150.0, 900.0, 1250.0],
                    "surya_text": "(5) 此处考证依据北京图书馆藏孤本。",
                    "type": None,
                },
            ],
        }
        body_list, final_footnotes, _ = process_page_footnotes(
            page_info=page_info,
            page_num=13,
            previous_open_footnote=None,
            audit_records=[],
            enable_footnotes=True,
        )
        self.assertEqual(len(final_footnotes), 1)
        self.assertEqual(final_footnotes[0]["id"], 5)
        self.assertEqual(final_footnotes[0]["content"], "此处考证依据北京图书馆藏孤本。")
        body_md = body_list[0]["md"]
        self.assertIn("2014(5):1264.", body_md)
        self.assertNotIn("2014[^p", body_md)
        self.assertIn("此处附注 [^p13_5] 备考。", body_md)


if __name__ == "__main__":
    unittest.main()
