# -*- coding: utf-8 -*-
import unittest
from src.extraction.symbol_mapper import restore_ocr_symbols
from src.scripts.process_ocr import sort_blocks_2d_reading_order


class TestSymbolMapperAndOcrFixes(unittest.TestCase):
    def test_truncated_bracket_restoration(self):
        """驗證邊緣截斷括號 一)、二) 能自動還原為 （一）、（二）"""
        raw = "一)小妙招详解\n\n**二)组方思路**\n\n> 三)传统施治科普"
        restored, stats = restore_ocr_symbols(raw)
        self.assertIn("（一）小妙招详解", restored)
        self.assertIn("**（二）组方思路**", restored)
        self.assertIn("> （三）传统施治科普", restored)
        self.assertEqual(stats["brackets_restored"], 3)

    def test_circled_number_restoration(self):
        """驗證圓圈數字辨識退化為純阿拉伯數字（如 1外感風寒...）能自動修復為 ①外感風寒..."""
        raw = "1外感风寒者禁用。\n\n2脾胃虚寒者慎用。\n\n3调入川贝粉和冰糖,煮沸即可。"
        restored, stats = restore_ocr_symbols(raw)
        self.assertIn("①外感风寒者禁用。", restored)
        self.assertIn("②脾胃虚寒者慎用。", restored)
        self.assertIn("③调入川贝粉和冰糖,煮沸即可。", restored)
        self.assertEqual(stats["circled_restored"], 3)

    def test_numeric_range_tilde_normalization(self):
        """驗證數字區間波浪號 ~ 能標準化為全形浪紋線 ～，防止 Pandoc 誤判為下標"""
        raw = "快速冲洗2~3次(每次10~15秒)。\n保持药液微沸,继续煎20~25分钟。"
        restored, stats = restore_ocr_symbols(raw)
        self.assertIn("2～3次", restored)
        self.assertIn("10～15秒", restored)
        self.assertIn("20～25分钟", restored)
        self.assertEqual(stats["tildes_normalized"], 3)

    def test_empty_img_tag_cleanup(self):
        """驗證無效或殘留之 ![img]() 標記會被乾淨移除，避免在 Word 中留下 'img' 殘留文字"""
        raw = "段落一\n\n![img]()\n\n段落二\n\n![]()\n\n段落三"
        restored, stats = restore_ocr_symbols(raw)
        self.assertNotIn("![img]()", restored)
        self.assertNotIn("![]()", restored)
        self.assertIn("段落一", restored)
        self.assertIn("段落二", restored)
        self.assertIn("段落三", restored)
        self.assertEqual(stats["empty_imgs_removed"], 2)

    def test_sort_blocks_2d_reading_order_cards(self):
        """驗證多欄卡片（圖片 + 標題說明）依 2D 自然閱讀順序排序，而非圖片全部沉底或浮頂"""
        # 模擬 2 欄卡片：
        # 欄 1: 圖片 [80..130, 100..150], 說明 [80..130, 155..180]
        # 欄 2: 圖片 [200..250, 100..150], 說明 [200..250, 155..180]
        blocks = [
            {"bbox": [200, 100, 250, 150], "original_label": "image", "surya_text": ""},
            {"bbox": [80, 100, 130, 150], "original_label": "image", "surya_text": ""},
            {"bbox": [200, 155, 250, 180], "original_label": "caption", "surya_text": "白茅根 10克"},
            {"bbox": [80, 155, 130, 180], "original_label": "caption", "surya_text": "川贝母5克"}
        ]
        sorted_blocks = sort_blocks_2d_reading_order(blocks, page_w=500, page_h=700)
        
        # 預期順序：
        # 欄 1 圖片 -> 欄 1 說明 (川贝母) -> 欄 2 圖片 -> 欄 2 說明 (白茅根)
        self.assertEqual(sorted_blocks[0]["bbox"][0], 80)
        self.assertEqual(sorted_blocks[1]["surya_text"], "川贝母5克")
        self.assertEqual(sorted_blocks[2]["bbox"][0], 200)
        self.assertEqual(sorted_blocks[3]["surya_text"], "白茅根 10克")

    def test_filter_margin_chapter_header(self):
        """驗證極外側豎向切口章名裝飾標記被自動過濾，不干擾正文流"""
        blocks = [
            {"bbox": [50, 80, 400, 110], "original_label": "text", "surya_text": "正文第一行"},
            {"bbox": [460, 200, 475, 250], "original_label": "text", "surya_text": "第一章"}, # 極右側豎向裝飾
            {"bbox": [50, 260, 400, 290], "original_label": "text", "surya_text": "正文第二行"}
        ]
        sorted_blocks = sort_blocks_2d_reading_order(blocks, page_w=500, page_h=700)
        texts = [b["surya_text"] for b in sorted_blocks]
        self.assertIn("正文第一行", texts)
        self.assertIn("正文第二行", texts)
        self.assertNotIn("第一章", texts)


    def test_merge_wrapping_paragraphs(self):
        """驗證圖文環繞斷行或中途折斷段落（如以《溫結尾）能自動與下一塊正文平滑合併，且不誤合併標題"""
        from src.scripts.process_ocr import _merge_wrapping_paragraphs

        blocks = [
            {"bbox": [100, 100, 300, 130], "original_label": "text", "surya_text": "### （一）组方思路"},
            {"bbox": [150, 140, 250, 160], "original_label": "text", "surya_text": "双参灵百汤"},
            {"bbox": [100, 180, 400, 200], "original_label": "text", "surya_text": "双参灵百汤的配伍思路主要借鉴了清代吴鞠通《温"},
            {"bbox": [100, 210, 400, 300], "original_label": "text", "surya_text": "病条辨》中的沙参麦冬汤。沙参麦冬汤是治疗经典方剂。"}
        ]
        merged = _merge_wrapping_paragraphs(blocks, page_w=500.0)
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0]["surya_text"], "### （一）组方思路")
        self.assertEqual(merged[1]["surya_text"], "双参灵百汤")
        self.assertTrue(merged[2]["surya_text"].startswith("双参灵百汤的配伍思路主要借鉴了清代吴鞠通《温病条辨》中的沙参麦冬汤。"))

    def test_slice_box_into_lines(self):
        """驗證多行段落圖片切片功能能將多行文字依水平投影分割為獨立行切片"""
        from PIL import Image, ImageDraw
        from src.scripts.process_ocr import _slice_box_into_lines

        # 建立 3 行黑字白底圖片
        img = Image.new("RGB", (200, 90), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 190, 25], fill=(0, 0, 0))  # line 1
        draw.rectangle([10, 38, 190, 53], fill=(0, 0, 0))  # line 2
        draw.rectangle([10, 66, 190, 81], fill=(0, 0, 0))  # line 3

        slices = _slice_box_into_lines(img, min_line_h=8)
        self.assertEqual(len(slices), 3)


if __name__ == "__main__":
    unittest.main()
