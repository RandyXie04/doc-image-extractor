# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from PIL import Image
import fitz

from src.scripts.book_layout_extractor import process_book_vector_pdf


class TestInterleavedTablesAndFigures(unittest.TestCase):
    """
    驗證自動整稿通道中，表格與圖片依垂直幾何位置（y0）交錯流式插入，
    確保不會被強制堆疊在頁面最尾端。
    """
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_interleaved_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_interleaved_reading_order_image_and_table(self):
        pdf_path = os.path.join(self.temp_dir, "test_doc.pdf")
        doc = fitz.open()
        page = doc.new_page(width=500, height=800)

        # 1. 頁首正文
        page.insert_text(fitz.Point(60, 80), "段落一：出現在圖片之前。", fontname="china-ts", fontsize=11.0)

        # 2. 插入圖片 (y: 120 ~ 200)
        img = Image.new("RGB", (80, 80), color=(0, 128, 255))
        img_path = os.path.join(self.temp_dir, "sample.png")
        img.save(img_path)
        page.insert_image(fitz.Rect(60, 120, 200, 200), filename=img_path)

        # 3. 中間正文 (y: 250)
        page.insert_text(fitz.Point(60, 250), "段落二：位於圖片之後、表格之前。", fontname="china-ts", fontsize=11.0)

        # 4. 繪製向量表格 (y: 300 ~ 400)
        page.draw_rect(fitz.Rect(60, 300, 400, 400), color=(0, 0, 0), width=1)
        page.draw_line(fitz.Point(60, 350), fitz.Point(400, 350), color=(0, 0, 0), width=1)
        page.draw_line(fitz.Point(230, 300), fitz.Point(230, 400), color=(0, 0, 0), width=1)
        page.insert_text(fitz.Point(80, 330), "欄位甲", fontname="china-ts", fontsize=10.0)
        page.insert_text(fitz.Point(250, 330), "欄位乙", fontname="china-ts", fontsize=10.0)
        page.insert_text(fitz.Point(80, 380), "數據A", fontname="china-ts", fontsize=10.0)
        page.insert_text(fitz.Point(250, 380), "數據B", fontname="china-ts", fontsize=10.0)

        # 5. 頁尾正文 (y: 450)
        page.insert_text(fitz.Point(60, 450), "段落三：位於表格之後。", fontname="china-ts", fontsize=11.0)

        doc.save(pdf_path)
        doc.close()

        out_md, audit = process_book_vector_pdf(pdf_path, self.temp_dir, ai_kaiti=False)
        with open(out_md, encoding="utf-8") as f:
            content = f.read()

        # 驗證輸出 Markdown 內容存在各元素
        self.assertIn("段落一：出現在圖片之前。", content)
        self.assertIn("![](images/image_p1_0.png){width=80%}", content)
        self.assertIn("段落二：位於圖片之後、表格之前。", content)
        self.assertIn("| 欄位甲 | 欄位乙 |", content)
        self.assertIn("段落三：位於表格之後。", content)

        # 驗證相對順序完全符合自然閱讀流（非沉底排版）
        idx_p1 = content.index("段落一：出現在圖片之前。")
        idx_img = content.index("![](images/image_p1_0.png)")
        idx_p2 = content.index("段落二：位於圖片之後、表格之前。")
        idx_tbl = content.index("| 欄位甲 | 欄位乙 |")
        idx_p3 = content.index("段落三：位於表格之後。")

        self.assertLess(idx_p1, idx_img, "圖片應在段落一之後")
        self.assertLess(idx_img, idx_p2, "段落二應在圖片之後")
        self.assertLess(idx_p2, idx_tbl, "表格應在段落二之後")
        self.assertLess(idx_tbl, idx_p3, "段落三應在表格之後，表格不應沉底到段落三之後")


if __name__ == "__main__":
    unittest.main()
