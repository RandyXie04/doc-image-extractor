# -*- coding: utf-8 -*-
import unittest
from src.founder_tools.core.heading_detector import HeadingDetector


class TestHeadingDetector(unittest.TestCase):
    def test_surya_ocr_block_detection(self):
        """測試 Surya OCR 輸出的 block (僅含 surya_text 與 bbox，無 lines) 能正確辨識標題"""
        blk_ch1 = {
            "original_label": "section-header",
            "bbox": [100, 100, 300, 130],
            "surya_text": "第一章 中医基本理念与辨证方法",
            "type": None
        }
        level = HeadingDetector.detect_block_level(blk_ch1, page_width=600.0)
        self.assertEqual(level, 1)

        blk_sec = {
            "original_label": "section-header",
            "bbox": [100, 150, 250, 175],
            "surya_text": "第一节 天人合一",
            "type": None
        }
        level_sec = HeadingDetector.detect_block_level(blk_sec, page_width=600.0)
        self.assertEqual(level_sec, 2)

    def test_arabic_numeral_and_english_chapters(self):
        """測試阿拉伯數字章節與英文 Chapter 辨識"""
        blk_ar = {
            "surya_text": "第1章 機器人運動學",
            "bbox": [50, 80, 250, 110]
        }
        self.assertEqual(HeadingDetector.detect_block_level(blk_ar, page_width=600.0), 1)

        blk_en = {
            "surya_text": "Chapter 2 Kinematics",
            "bbox": [50, 80, 250, 110]
        }
        self.assertEqual(HeadingDetector.detect_block_level(blk_en, page_width=600.0), 1)

    def test_body_text_exclusion(self):
        """測試一般內文不會被誤判為標題"""
        blk_body = {
            "surya_text": "本書是河南省名中醫、全國基層名老中醫藥專家經驗總結。",
            "bbox": [50, 100, 500, 120]
        }
        self.assertEqual(HeadingDetector.detect_block_level(blk_body, page_width=600.0), 0)

        # 包含句號的短句也不應作為標題
        blk_short_punct = {
            "surya_text": "第一章內容。",
            "bbox": [50, 100, 150, 120]
        }
    def test_whitespace_and_empty_blocks(self):
        """測試空白字元或空字串之 OCR 區塊不會拋出 IndexError 且正確回傳 0"""
        blk_spaces = {
            "surya_text": "    \t\n  ",
            "bbox": [50, 100, 150, 120]
        }
        self.assertEqual(HeadingDetector.detect_block_level(blk_spaces, page_width=600.0), 0)

        blk_empty = {
            "surya_text": "",
            "bbox": [50, 100, 150, 120]
        }
        self.assertEqual(HeadingDetector.detect_block_level(blk_empty, page_width=600.0), 0)

        blk_no_text = {
            "bbox": [50, 100, 150, 120]
        }
        self.assertEqual(HeadingDetector.detect_block_level(blk_no_text, page_width=600.0), 0)


if __name__ == "__main__":
    unittest.main()
