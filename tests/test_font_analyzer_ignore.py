# -*- coding: utf-8 -*-
import os
import json
import tempfile
import unittest
from pathlib import Path

import fitz

from src.scripts.pdf_font_analyzer import (
    get_font_role_map,
    analyze_pdf_for_ui,
    save_fonts_json,
    load_fonts_json,
)
from src.scripts.book_layout_extractor import process_book_vector_pdf as process_normal
from src.scripts.book_layout_extractor_no_footnote import process_book_vector_pdf as process_no_fn


class TestFontAnalyzerIgnore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_font_ignore_")
        self.fonts_json = os.path.join(self.temp_dir, "fonts.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_font_role_map_includes_ignored_and_docx_styles(self):
        mapping = {
            "CustomFontA (14.0pt)": {"role": "忽略", "docx_style": None, "mapped_by": "user"},
            "CustomFontB (16.0pt)": {"role": "H1", "docx_style": None, "mapped_by": "user"},
            "CustomFontC (10.5pt)": {"role": None, "docx_style": "表說", "mapped_by": "user"},
            "LegacyFont": {"role": None, "docx_style": None, "sample": "legacy text", "mapped_by": "legacy"},
        }
        with open(self.fonts_json, "w", encoding="utf-8") as f:
            json.dump(mapping, f)

        res = get_font_role_map(self.fonts_json)
        self.assertIn("CustomFontA (14.0pt)", res)
        self.assertEqual(res["CustomFontA (14.0pt)"]["role"], "忽略")
        self.assertIn("CustomFontB (16.0pt)", res)
        self.assertIn("CustomFontC (10.5pt)", res)
        self.assertNotIn("LegacyFont", res)

    def test_analyze_pdf_defaults_to_auto(self):
        pdf_path = os.path.join(self.temp_dir, "sample.pdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text(fitz.Point(100, 100), "測試正文內容，這是一段普通的說明文字。", fontsize=12)
        doc.save(pdf_path)
        doc.close()

        with open(self.fonts_json, "w", encoding="utf-8") as f:
            json.dump({}, f)

        data = analyze_pdf_for_ui(pdf_path, template_path=None, fonts_json_path=self.fonts_json)
        self.assertTrue(len(data["fonts"]) > 0)
        for font_info in data["fonts"]:
            self.assertEqual(font_info["current_role"], "auto")
            self.assertIsNone(font_info["current_docx_style"])

    def test_ignored_font_prevents_heading_and_kaiti_in_extractors(self):
        pdf_path = os.path.join(self.temp_dir, "test_heading.pdf")
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        page.insert_text(fitz.Point(100, 150), "第一章 測試標題", fontname="helv", fontsize=14)
        page.insert_text(fitz.Point(100, 200), "這是正常內文第一行內容敘述。", fontname="helv", fontsize=10)
        doc.save(pdf_path)
        doc.close()

        # Case 1: Without ignore mapping (default regex rules apply)
        out_dir_1 = os.path.join(self.temp_dir, "out1")
        md_path_1, audit_1 = process_normal(pdf_path, out_dir_1)
        with open(md_path_1, "r", encoding="utf-8") as f:
            content_1 = f.read()
        self.assertIn("#", content_1)

        # Case 2: Map 'Helvetica' to '忽略'
        real_config_fonts = Path("config/fonts.json")
        backup_content = None
        if real_config_fonts.exists():
            backup_content = real_config_fonts.read_text(encoding="utf-8")

        try:
            test_mapping = {
                "Helvetica": {"role": "忽略", "docx_style": None, "mapped_by": "user"},
                "Helvetica (14.0pt)": {"role": "忽略", "docx_style": None, "mapped_by": "user"},
                "Helvetica_14.0": {"role": "忽略", "docx_style": None, "mapped_by": "user"},
            }
            real_config_fonts.write_text(json.dumps(test_mapping, ensure_ascii=False), encoding="utf-8")

            # Normal extractor
            out_dir_2 = os.path.join(self.temp_dir, "out2")
            md_path_2, audit_2 = process_normal(pdf_path, out_dir_2)
            with open(md_path_2, "r", encoding="utf-8") as f:
                content_2 = f.read()

            self.assertNotIn("#", content_2)

            # No-footnote extractor
            out_dir_3 = os.path.join(self.temp_dir, "out3")
            md_path_3, audit_3 = process_no_fn(pdf_path, out_dir_3)
            with open(md_path_3, "r", encoding="utf-8") as f:
                content_3 = f.read()

            self.assertNotIn("#", content_3)

        finally:
            if backup_content is not None:
                real_config_fonts.write_text(backup_content, encoding="utf-8")

    def test_kaiti_custom_style_not_intercepted_by_heading_heuristic(self):
        """測試字體分析指定楷體樣式 (如 '楷體（小標）') 時，不會被 MD 標題啟發式規則誤判為 H2，且精確套用指定 Word 樣式"""
        pdf_path = os.path.join(self.temp_dir, "test_kaiti_heading.pdf")
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        # Short text, size 14pt (normally triggers Rule 2 for H2 if unmapped)
        page.insert_text(fitz.Point(100, 150), "Short Section Title", fontname="helv", fontsize=14)
        doc.save(pdf_path)
        doc.close()

        real_config_fonts = Path("config/fonts.json")
        backup_content = None
        if real_config_fonts.exists():
            backup_content = real_config_fonts.read_text(encoding="utf-8")

        try:
            # Map Helvetica 14pt to KaiTi with custom docx_style "楷體（小標）"
            test_mapping = {
                "Helvetica": {"role": "楷體", "docx_style": "楷體（小標）", "mapped_by": "user"},
                "Helvetica (14.0pt)": {"role": "楷體", "docx_style": "楷體（小標）", "mapped_by": "user"},
            }
            real_config_fonts.write_text(json.dumps(test_mapping, ensure_ascii=False), encoding="utf-8")

            # Normal extractor
            out_dir = os.path.join(self.temp_dir, "out_kaiti_normal")
            md_path, _ = process_normal(pdf_path, out_dir)
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Must NOT be formatted as heading
            self.assertNotIn("#", content)
            # Must be formatted with custom-style="楷體（小標）"
            self.assertIn('::: {custom-style="楷體（小標）"}', content)
            self.assertIn("Short Section Title", content)

            # No-footnote extractor
            out_dir_no_fn = os.path.join(self.temp_dir, "out_kaiti_no_fn")
            md_path_no_fn, _ = process_no_fn(pdf_path, out_dir_no_fn)
            with open(md_path_no_fn, "r", encoding="utf-8") as f:
                content_no_fn = f.read()

            self.assertNotIn("#", content_no_fn)
            self.assertIn('::: {custom-style="楷體（小標）"}', content_no_fn)

        finally:
            if backup_content is not None:
                real_config_fonts.write_text(backup_content, encoding="utf-8")

    def test_arbitrary_docx_style_for_paragraph(self):
        """測試字體分析指定的任意 Word 樣式 (例如 '屬名') 在正文段落中正確套用"""
        pdf_path = os.path.join(self.temp_dir, "test_custom_style.pdf")
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        page.insert_text(fitz.Point(100, 150), "Author Byline Text Here", fontname="helv", fontsize=11)
        doc.save(pdf_path)
        doc.close()

        real_config_fonts = Path("config/fonts.json")
        backup_content = None
        if real_config_fonts.exists():
            backup_content = real_config_fonts.read_text(encoding="utf-8")

        try:
            test_mapping = {
                "Helvetica (11.0pt)": {"role": None, "docx_style": "屬名", "mapped_by": "user"},
            }
            real_config_fonts.write_text(json.dumps(test_mapping, ensure_ascii=False), encoding="utf-8")

            out_dir = os.path.join(self.temp_dir, "out_custom_normal")
            md_path, _ = process_normal(pdf_path, out_dir)
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn('::: {custom-style="屬名"}', content)
            self.assertIn("Author Byline Text Here", content)

        finally:
            if backup_content is not None:
                real_config_fonts.write_text(backup_content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
