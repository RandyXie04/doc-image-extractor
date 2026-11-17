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

    def test_join_ocr_line_slices_splices_cjk_lines_smoothly(self):
        """驗證多行切片拼接演算法在 CJK 漢字間無縫拼接且在英文字詞間保留空格"""
        from src.scripts.process_ocr import _join_ocr_line_slices

        lines = ["双参灵百汤的配伍思路主要借鉴了清代吴鞠通《温", "病条辨》中的沙参麦冬汤。", "Clinical trial", "Phase III"]
        joined = _join_ocr_line_slices(lines)
        self.assertEqual(
            joined,
            "双参灵百汤的配伍思路主要借鉴了清代吴鞠通《温病条辨》中的沙参麦冬汤。 Clinical trial Phase III"
        )

    def test_process_page_footnotes_restores_block_without_wiping_headings_and_styles(self):
        """驗證 L1 修復：頁底未匹配之偽腳注區塊（如條列 ①...）退回正文時，不會抹除頁首標題與樣式"""
        from src.scripts.process_ocr import process_page_footnotes

        page_info = {
            "page_idx": 0,
            "page_size": [1000.0, 1400.0],
            "para_blocks": [
                {
                    "original_label": "section-header",
                    "bbox": [100.0, 80.0, 400.0, 120.0],
                    "surya_text": "第一章　组方思路",
                    "type": None,
                },
                {
                    "original_label": "text",
                    "bbox": [100.0, 150.0, 900.0, 300.0],
                    "surya_text": "这是普通正文段落，阐述基本病理机制与药物相互作用关系。",
                    "type": None,
                },
                {
                    "original_label": "text",
                    "bbox": [100.0, 1100.0, 850.0, 1150.0],  # y0 > 1400 * 0.72 = 1008
                    "surya_text": "①将药材洗净后加入清水浸泡三十分钟。",  # 前綴為 ① 但正文無錨點且非文獻引用
                    "type": None,
                },
            ],
        }
        audit_records = []
        style_mapping = {"h1": "heading 1", "h2": "heading 2", "body": "Normal"}

        body_list, final_footnotes, open_fn = process_page_footnotes(
            page_info=page_info,
            page_num=1,
            previous_open_footnote=None,
            audit_records=audit_records,
            style_mapping=style_mapping,
            enable_footnotes=True,
        )

        # 1. 偽腳注 ① 未被誤轉為腳注，而是完整退回正文
        self.assertEqual(len(final_footnotes), 0)
        self.assertIsNone(open_fn)
        self.assertEqual(len(body_list), 3)

        # 2. 標題依然被正確識別為 H1 並套用 custom-style，未被第二度 render_blocks 抹除！
        h_md = body_list[0]["md"]
        self.assertTrue(h_md.startswith("# 第一章　组方思路"))
        self.assertIn('custom-style="heading 1"', h_md)

        # 3. 內文與退回的條列區塊亦正常套用樣式
        self.assertIn('custom-style="Normal"', body_list[1]["md"])
        self.assertIn("①将药材洗净后加入清水浸泡三十分钟。", body_list[2]["md"])

    def test_process_page_footnotes_uses_actual_page_width_for_centered_heading(self):
        """驗證 L3 修復：以實際頁寬（如 1200px）判定置中標題，避免以硬編碼 300px 誤判左對齊短句"""
        from src.scripts.process_ocr import process_page_footnotes

        page_info = {
            "page_idx": 0,
            "page_size": [1200.0, 1600.0],
            "para_blocks": [
                {
                    # 真正置中短標題：x0=450, x1=750, 中心點 600, 距頁面中點 600 偏差 0
                    "original_label": "text",
                    "bbox": [450.0, 100.0, 750.0, 140.0],
                    "surya_text": "中医内科学导论",
                    "type": None,
                },
                {
                    # 左對齊短句：x0=100, x1=500, 中心點 300, 距頁面中點 600 偏差 300 (非置中)
                    "original_label": "text",
                    "bbox": [100.0, 200.0, 500.0, 230.0],
                    "surya_text": "普通靠左對齊說明句",
                    "type": None,
                },
            ],
        }
        audit_records = []
        body_list, _, _ = process_page_footnotes(
            page_info=page_info,
            page_num=1,
            previous_open_footnote=None,
            audit_records=audit_records,
            style_mapping={"h2": "Heading 2"},
            enable_footnotes=False,
        )

        # 左對齊短句不可被誤判為標題
        self.assertFalse(body_list[1]["md"].startswith("#"))
        self.assertIn("普通靠左對齊說明句", body_list[1]["md"])

    def test_extract_pdf_images_target_pages_and_scan_exclusion(self):
        """驗證 M3 修復：extract_from_pdf 傳入 target_pages 僅掃描目標頁，節省 VRAM/磁碟開銷"""
        import tempfile
        import os
        import fitz
        from typing import Any
        from PIL import Image
        from src.scripts.extract_images import extract_from_pdf

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "multi_page.pdf")
            out_dir = os.path.join(tmpdir, "extracted")

            # 建立 2 頁 PDF，每頁插入 60x60 圖片
            doc: Any = fitz.open()
            img_path = os.path.join(tmpdir, "dot.png")
            Image.new("RGB", (60, 60), (255, 0, 0)).save(img_path)

            for _ in range(2):
                page = doc.new_page(width=400, height=600)
                page.insert_image(fitz.Rect(50, 50, 150, 150), filename=img_path)

            doc.save(pdf_path)
            doc.close()

            # 僅指定提取第 2 頁
            count = extract_from_pdf(pdf_path, out_dir, target_pages={2})
            self.assertEqual(count, 1)

            extracted_files = os.listdir(out_dir)
            self.assertEqual(len(extracted_files), 1)
            self.assertTrue(extracted_files[0].startswith("page_0002_"))

    def test_reconcile_layout_and_det_recovers_bottom_orphan_lines(self):
        """驗證雙解析度對帳能救回被版面模型遺漏或截斷的頁底孤兒文字行，並依幾何位置併入上方段落或獨立成塊"""
        from types import SimpleNamespace
        from src.scripts.process_ocr import _reconcile_layout_and_det_lines

        # Case 1: 緊鄰上方段落底部的孤兒行應直接併入該文本塊 (line_bboxes_150 擴張、bbox 下移)
        layout_bboxes = [
            {"bbox": [60.0, 100.0, 440.0, 160.0], "label": "Text"},
        ]
        det_bboxes = [
            {"bbox": [60.0, 102.0, 440.0, 122.0]},
            {"bbox": [60.0, 130.0, 440.0, 150.0]},
            {"bbox": [60.0, 174.0, 440.0, 194.0]},  # 頁底被 layout 截斷的孤兒行 (y_gap=14 <= 1.85*20)
        ]
        blocks = _reconcile_layout_and_det_lines(layout_bboxes, det_bboxes, page_w=500.0, page_h=700.0)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["original_label"], "text")
        self.assertEqual(len(blocks[0]["line_bboxes_150"]), 3)
        self.assertEqual(blocks[0]["bbox"][3], 194.0)

        # Case 2: 遠離上方區塊（或縮排新段 / object 樣式 polygon）之孤兒行應補建為獨立 "text" 區塊，零掉行
        obj_layout = [
            SimpleNamespace(
                polygon=[[60.0, 100.0], [440.0, 100.0], [440.0, 155.0], [60.0, 155.0]],
                label="Text",
            ),
        ]
        det_with_far_orphan = [
            SimpleNamespace(polygon=[[60.0, 102.0], [440.0, 102.0], [440.0, 122.0], [60.0, 122.0]]),
            SimpleNamespace(polygon=[[60.0, 130.0], [440.0, 130.0], [440.0, 150.0], [60.0, 150.0]]),
            SimpleNamespace(polygon=[[60.0, 610.0], [320.0, 610.0], [320.0, 630.0], [60.0, 630.0]]),
        ]
        blocks_far = _reconcile_layout_and_det_lines(
            obj_layout, det_with_far_orphan, page_w=500.0, page_h=700.0
        )
        self.assertEqual(len(blocks_far), 2)
        self.assertEqual(blocks_far[1]["original_label"], "text")
        self.assertEqual(blocks_far[1]["line_bboxes_150"], [[60.0, 610.0, 320.0, 630.0]])
        total_lines = sum(len(b["line_bboxes_150"]) for b in blocks_far)
        self.assertEqual(total_lines, 3)

    def test_reconcile_layout_demotes_pagefooter_and_rescues_text_picture(self):
        """驗證已裁切頁面內之 PageHeader/PageFooter 降級為 text，且無底圖重疊卻含文字行的 Picture 被救回為 text"""
        from src.scripts.process_ocr import _reconcile_layout_and_det_lines

        layout_bboxes = [
            {"bbox": [60.0, 20.0, 440.0, 45.0], "label": "PageHeader"},
            {"bbox": [60.0, 120.0, 440.0, 200.0], "label": "Picture"},
            {"bbox": [60.0, 640.0, 440.0, 670.0], "label": "PageFooter"},
        ]
        det_bboxes = [
            {"bbox": [60.0, 22.0, 440.0, 42.0]},
            {"bbox": [60.0, 125.0, 440.0, 145.0]},
            {"bbox": [60.0, 160.0, 440.0, 180.0]},
            {"bbox": [60.0, 645.0, 440.0, 665.0]},
        ]
        blocks = _reconcile_layout_and_det_lines(
            layout_bboxes,
            det_bboxes,
            page_w=500.0,
            page_h=700.0,
            image_rects_150=[],
        )
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0]["original_label"], "text")
        self.assertEqual(blocks[0]["line_bboxes_150"], [[60.0, 22.0, 440.0, 42.0]])
        self.assertEqual(blocks[1]["original_label"], "text")
        self.assertEqual(
            blocks[1]["line_bboxes_150"],
            [[60.0, 125.0, 440.0, 145.0], [60.0, 160.0, 440.0, 180.0]],
        )
        self.assertEqual(blocks[2]["original_label"], "text")
        self.assertEqual(blocks[2]["line_bboxes_150"], [[60.0, 645.0, 440.0, 665.0]])

        # 若確實與真實點陣底圖重疊，Picture 應維持為 picture 不誤救回
        raster_blocks = _reconcile_layout_and_det_lines(
            [{"bbox": [60.0, 300.0, 300.0, 500.0], "label": "Picture"}],
            [{"bbox": [80.0, 350.0, 260.0, 370.0]}],
            page_w=500.0,
            page_h=700.0,
            image_rects_150=[[60.0, 300.0, 300.0, 500.0]],
        )
        self.assertEqual(len(raster_blocks), 1)
        self.assertEqual(raster_blocks[0]["original_label"], "picture")
        self.assertEqual(raster_blocks[0]["line_bboxes_150"], [])

    def test_scale_bbox_150_to_200_dpi(self):
        """驗證 _scale_bbox 正確依 4/3 倍率將 150 DPI 座標轉換為 200 DPI 並支援邊界夾限"""
        from src.scripts.process_ocr import _scale_bbox

        ratio = 4.0 / 3.0
        scaled = _scale_bbox([30.0, 60.0, 150.0, 300.0], ratio, ratio)
        self.assertAlmostEqual(scaled[0], 40.0)
        self.assertAlmostEqual(scaled[1], 80.0)
        self.assertAlmostEqual(scaled[2], 200.0)
        self.assertAlmostEqual(scaled[3], 400.0)

        clamped = _scale_bbox([-15.0, -6.0, 900.0, 1200.0], ratio, ratio, max_w=1000.0, max_h=1400.0)
        self.assertEqual(clamped, [0.0, 0.0, 1000.0, 1400.0])

    def test_sort_blocks_retains_bottom_numbers_in_cropped_page(self):
        """驗證已裁切頁面底端獨立數字（y0 > page_h * 0.90）不會被誤刪，同時保留右側豎排切口章名過濾"""
        blocks = [
            {"bbox": [50, 80, 450, 120], "original_label": "text", "surya_text": "正文段落内容。"},
            {"bbox": [460, 200, 475, 250], "original_label": "text", "surya_text": "第一章"},
            {"bbox": [230, 650, 270, 675], "original_label": "text", "surya_text": "128"},
        ]
        sorted_blocks = sort_blocks_2d_reading_order(blocks, page_w=500, page_h=700)
        texts = [b["surya_text"] for b in sorted_blocks]
        self.assertIn("正文段落内容。", texts)
        self.assertIn("128", texts)
        self.assertNotIn("第一章", texts)

    def test_merge_cross_page_paragraphs(self):
        """驗證 _merge_cross_page_paragraphs 正確拼接句中截斷與未閉合《之跨頁段落，保留樣式且不誤併句號結尾或標題頁"""
        from src.scripts.process_ocr import _merge_cross_page_paragraphs, build_ocr_layout_contracts

        # Case 1: 句中截斷 + ::: {custom-style="Normal"} 樣式保留
        pages_mid = [
            {
                "page_num": 1,
                "page_size": [500.0, 700.0],
                "body": [
                    {
                        "orig_idx": 0,
                        "md": '::: {custom-style="Normal"}\n本方以清热解毒、健脾益气为主要治疗原则，临床应用时可根据患者体质适当调整\n:::',
                        "block": {
                            "original_label": "text",
                            "bbox": [60.0, 580.0, 440.0, 640.0],
                            "line_bboxes_150": [[60.0, 580.0, 440.0, 600.0], [60.0, 610.0, 380.0, 630.0]],
                            "surya_text": "本方以清热解毒、健脾益气为主要治疗原则，临床应用时可根据患者体质适当调整",
                        },
                    }
                ],
                "footnotes": [],
            },
            {
                "page_num": 2,
                "page_size": [500.0, 700.0],
                "body": [
                    {
                        "orig_idx": 0,
                        "md": '::: {custom-style="Normal"}\n剂量与配伍比例，从而达到标本兼治的理想临床疗效。\n:::',
                        "block": {
                            "original_label": "text",
                            "bbox": [60.0, 60.0, 440.0, 110.0],
                            "line_bboxes_150": [[60.0, 60.0, 440.0, 80.0], [60.0, 90.0, 320.0, 110.0]],
                            "surya_text": "剂量与配伍比例，从而达到标本兼治的理想临床疗效。",
                        },
                    },
                    {
                        "orig_idx": 1,
                        "md": '::: {custom-style="Normal"}\n第二段新起内容，保持独立存在。\n:::',
                        "block": {
                            "original_label": "text",
                            "bbox": [60.0, 130.0, 440.0, 170.0],
                            "line_bboxes_150": [[96.0, 130.0, 440.0, 150.0], [60.0, 152.0, 300.0, 170.0]],
                            "surya_text": "第二段新起内容，保持独立存在。",
                        },
                    },
                ],
                "footnotes": [],
            },
        ]
        merged_mid = _merge_cross_page_paragraphs(pages_mid)
        self.assertEqual(len(merged_mid[0]["body"]), 1)
        self.assertEqual(
            merged_mid[0]["body"][0]["md"],
            '::: {custom-style="Normal"}\n本方以清热解毒、健脾益气为主要治疗原则，临床应用时可根据患者体质适当调整剂量与配伍比例，从而达到标本兼治的理想临床疗效。\n:::',
        )
        self.assertEqual(len(merged_mid[1]["body"]), 1)
        self.assertIn("第二段新起内容，保持独立存在。", merged_mid[1]["body"][0]["md"])
        self.assertTrue(len(build_ocr_layout_contracts(merged_mid)) > 0)

        # Case 2: 未閉合書名號《跨頁續接
        pages_quote = [
            {
                "page_num": 1,
                "page_size": [500.0, 700.0],
                "body": [
                    {
                        "orig_idx": 0,
                        "md": "上述方剂加减化裁规律最早见于清代医家吴鞠通所著《温",
                        "block": {"original_label": "text", "bbox": [60.0, 600.0, 440.0, 630.0]},
                    }
                ],
                "footnotes": [],
            },
            {
                "page_num": 2,
                "page_size": [500.0, 700.0],
                "body": [
                    {
                        "orig_idx": 0,
                        "md": "病条辨》中的经典论述。",
                        "block": {"original_label": "text", "bbox": [60.0, 60.0, 300.0, 80.0]},
                    }
                ],
                "footnotes": [],
            },
        ]
        merged_quote = _merge_cross_page_paragraphs(pages_quote)
        self.assertEqual(
            merged_quote[0]["body"][0]["md"],
            "上述方剂加减化裁规律最早见于清代医家吴鞠通所著《温病条辨》中的经典论述。",
        )
        self.assertEqual(len(merged_quote[1]["body"]), 0)

        # Case 3: 頁底以句號「。」結尾 -> 不得合併
        pages_terminal = [
            {
                "page_num": 1,
                "page_size": [500.0, 700.0],
                "body": [
                    {
                        "orig_idx": 0,
                        "md": "本方临床疗效确切，安全可靠，值得临床推广应用。",
                        "block": {"original_label": "text", "bbox": [60.0, 600.0, 440.0, 630.0]},
                    }
                ],
                "footnotes": [],
            },
            {
                "page_num": 2,
                "page_size": [500.0, 700.0],
                "body": [
                    {
                        "orig_idx": 0,
                        "md": "后续观察病例共六十例，均取得良好预后。",
                        "block": {"original_label": "text", "bbox": [60.0, 60.0, 440.0, 80.0]},
                    }
                ],
                "footnotes": [],
            },
        ]
        not_merged_term = _merge_cross_page_paragraphs(pages_terminal)
        self.assertEqual(len(not_merged_term[0]["body"]), 1)
        self.assertEqual(len(not_merged_term[1]["body"]), 1)

        # Case 4: 次頁以標題 # 開頭 -> 不得合併
        pages_heading = [
            {
                "page_num": 1,
                "page_size": [500.0, 700.0],
                "body": [
                    {
                        "orig_idx": 0,
                        "md": "本方以清热解毒、健脾益气为主要治疗原则，临床应用时可灵活",
                        "block": {"original_label": "text", "bbox": [60.0, 600.0, 440.0, 630.0]},
                    }
                ],
                "footnotes": [],
            },
            {
                "page_num": 2,
                "page_size": [500.0, 700.0],
                "body": [
                    {
                        "orig_idx": 0,
                        "md": "# 第二章 临床应用",
                        "block": {"original_label": "section-header", "bbox": [60.0, 60.0, 300.0, 90.0]},
                    }
                ],
                "footnotes": [],
            },
        ]
        not_merged_head = _merge_cross_page_paragraphs(pages_heading)
        self.assertEqual(len(not_merged_head[0]["body"]), 1)
        self.assertEqual(len(not_merged_head[1]["body"]), 1)
        self.assertEqual(not_merged_head[1]["body"][0]["md"], "# 第二章 临床应用")


if __name__ == "__main__":
    unittest.main()
