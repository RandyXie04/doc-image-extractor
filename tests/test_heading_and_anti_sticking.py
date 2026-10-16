# -*- coding: utf-8 -*-
import os
import json
import tempfile
import unittest
from pathlib import Path

import fitz

from src.scripts.book_layout_extractor import (
    build_document_profile,
    _match_toc_heading,
    _normalize_title,
    _simple_similarity,
    process_book_vector_pdf,
)


class TestHeadingAndAntiSticking(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_heading_anti_stick_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_normalize_title_and_similarity(self):
        """測試標題標準化與相似度比對"""
        self.assertEqual(_normalize_title("  第一章  導論 ① "), "第一章導論")
        self.assertEqual(_normalize_title("１．２　背景與緣起"), "1.2背景與緣起")
        
        sim = _simple_similarity("文化與自然的交織", "文化與自然的交織")
        self.assertEqual(sim, 1.0)
        
        sim_partial = _simple_similarity("文化與自然", "文化與自然的交織")
        self.assertGreater(sim_partial, 0.5)

    def test_match_toc_heading_exact_and_offset(self):
        """測試 TOC 標題匹配與動態頁碼偏移校準"""
        toc_index = {
            "導論": {"level": 1, "page": 1},
            "文化與自然的交織": {"level": 2, "page": 15},
            "春之祭": {"level": 2, "page": 40},
        }

        # Case 1: 原生書籤 (無頁碼偏移)
        offset_native = [0]
        lvl = _match_toc_heading("導論", page_num=1, toc_index=toc_index, offset_holder=offset_native)
        self.assertEqual(lvl, 1)

        lvl2 = _match_toc_heading("文化與自然的交織", page_num=15, toc_index=toc_index, offset_holder=offset_native)
        self.assertEqual(lvl2, 2)

        # Case 2: 目錄文字解析 (存在 10 頁的頁碼偏移：印刷頁 1 -> PDF 實體頁 11)
        offset_parsed = [None]
        lvl_ch1 = _match_toc_heading("導論", page_num=11, toc_index=toc_index, offset_holder=offset_parsed)
        self.assertEqual(lvl_ch1, 1)
        self.assertEqual(offset_parsed[0], 10, "第一筆命中應校準出 10 頁偏移量")

        # 後續章節帶入已校準的偏移量 (印刷頁 15 + 偏移 10 = PDF 頁 25)
        lvl_ch2 = _match_toc_heading("文化與自然的交織", page_num=25, toc_index=toc_index, offset_holder=offset_parsed)
        self.assertEqual(lvl_ch2, 2)

    def test_build_document_profile_native_toc_and_font(self):
        """測試全書基準字體、字級探測與 PDF 原生書籤提取"""
        pdf_path = os.path.join(self.temp_dir, "profile_sample.pdf")
        doc = fitz.open()

        # Page 1: 封面與簡介
        p1 = doc.new_page(width=500, height=700)
        p1.insert_text(fitz.Point(50, 100), "這是第一頁的簡介內文內容，用以測試正文統計。", fontname="china-ts", fontsize=11.0)
        p1.insert_text(fitz.Point(50, 150), "這是一段比較長的中文正文段落，長度足夠被採樣納入基準統計。", fontname="china-ts", fontsize=11.0)

        # Page 2: 內文
        p2 = doc.new_page(width=500, height=700)
        p2.insert_text(fitz.Point(50, 100), "這是第二頁的標準中文正文段落，繼續使用 11pt 的主文字級進行排版測試。", fontname="china-ts", fontsize=11.0)

        # 設定原生書籤 (第一層級從 1 開始)
        doc.set_toc([
            [1, "導論", 1],
            [2, "文化與自然的交織", 2],
        ])
        doc.save(pdf_path)
        doc.close()

        # 檢驗 profile
        doc_test = fitz.open(pdf_path)
        profile = build_document_profile(doc_test)
        doc_test.close()

        self.assertEqual(profile["body_size"], 11.0)
        self.assertTrue(profile["is_native_toc"])
        self.assertIn("導論", profile["toc_index"])
        self.assertIn("文化與自然的交織", profile["toc_index"])
        self.assertEqual(profile["toc_index"]["導論"]["level"], 1)

    def test_unnumbered_heading_detected_via_toc(self):
        """測試完全無編號、無正則規律的標題，能透過 TOC 成功辨識為 Markdown 標題"""
        pdf_path = os.path.join(self.temp_dir, "unnumbered_toc.pdf")
        doc = fitz.open()

        # Page 1: 標題「文化與自然的交織」+ 緊接一般內文
        p1 = doc.new_page(width=500, height=700)
        p1.insert_text(fitz.Point(50, 100), "文化與自然的交織", fontname="china-ts", fontsize=14.0)
        p1.insert_text(fitz.Point(50, 150), "在人類歷史的長河中，自然環境與人文發展始終保持著緊密的相互作用關係。", fontname="china-ts", fontsize=11.0)

        # 書籤註冊 (層級 1 或 2)
        doc.set_toc([
            [1, "第一部 歷史長河", 1],
            [2, "文化與自然的交織", 1],
        ])
        doc.save(pdf_path)
        doc.close()

        out_dir = os.path.join(self.temp_dir, "out_toc")
        md_path, audit = process_book_vector_pdf(pdf_path, out_dir)

        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        # 必須被辨識為 ## 標題
        self.assertIn("## 文化與自然的交織", md_content)
        # 標題與內文絕不能黏在一起
        self.assertNotIn("## 文化與自然的交織在人類", md_content)
        self.assertIn("在人類歷史的長河中", md_content)

    def test_anti_sticking_guards_isolate_unrecognized_short_heading(self):
        """
        極端測試：即使完全沒有目錄書籤、字體大小與正文完全相同、左對齊，
        防黏連幾何保護機制（前段未滿行短行 / 垂直空隙）也能確保標題與內文強制斷開，絕不硬接成同一行！
        """
        pdf_path = os.path.join(self.temp_dir, "anti_stick.pdf")
        doc = fitz.open()

        p1 = doc.new_page(width=500, height=700)
        # 短行標題 (y=100)，未滿行 (寬度短)
        p1.insert_text(fitz.Point(50, 100), "無編號獨立小標", fontname="china-ts", fontsize=11.0)
        # 一般正文 (y=140)，垂直段距跳躍 > 1.45 倍字高
        p1.insert_text(fitz.Point(50, 140), "這是緊隨其後的內文第一段長句子，用來驗證不會與上方的小標題黏貼在一起。", fontname="china-ts", fontsize=11.0)
        doc.save(pdf_path)
        doc.close()

        out_dir = os.path.join(self.temp_dir, "out_anti_stick")
        md_path, audit = process_book_vector_pdf(pdf_path, out_dir)

        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()

        # 絕不能發生字串直接拼接黏合（如 "無編號獨立小標這是緊隨其後"）
        self.assertNotIn("無編號獨立小標這是緊隨其後", md_content)
        # 兩者必須是分開的獨立段落或區塊
        lines = [line.strip() for line in md_content.splitlines() if line.strip()]
        self.assertTrue(any("無編號獨立小標" in line for line in lines))
        self.assertTrue(any("這是緊隨其後的內文第一段長句子" in line for line in lines))
        # 兩者不在同一個 Markdown 行內
        for line in lines:
            if "無編號獨立小標" in line:
                self.assertNotIn("這是緊隨其後", line)


if __name__ == "__main__":
    unittest.main()
