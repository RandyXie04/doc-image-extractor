#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 轉換與公式萃取自動化管線 (整合版)
======================================
整合「PDF 動態裁切與轉檔 (PDFConversionAgent)」與
「AI 深度學習公式檢測器 (Pix2Text MFD 版)」，
形成一個自動化處理管線 (Pipeline)，讓使用者能一鍵完成：
  - 階段一：動態偵測頁眉/頁尾邊界、預覽驗證、裁切並轉檔為 Word。
  - 階段二：透過 AI MFD 模型，針對原始 PDF 萃取獨立數學公式圖片。

安裝依賴：
  pip install pymupdf pdf2docx tqdm pix2text opencv-python numpy
"""

import os
import sys
import io
import zipfile
import re

# Windows 終端 UTF-8 輸出相容性設定
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import fitz          # PyMuPDF
import cv2
import numpy as np
from pdf2docx import Converter
from tqdm import tqdm
from pix2text import MathFormulaDetector


class PDFConversionAgent:
    """
    PDF 轉換代理物件：負責將包含頁眉/頁尾的 PDF 檔案，
    透過動態邊界偵測與自動裁切，轉換為乾淨的 Word (Docx) 檔案。

    同時整合 AI 深度學習公式檢測器 (Pix2Text MFD 版)，
    可在轉檔後自動萃取 PDF 中的獨立數學公式圖片。

    功能說明：
    - 階段一：動態分析 PDF 頁首/頁尾邊界、進行預覽驗證、裁切並轉檔為 Word。
    - 階段二：利用 Pix2Text MFD 深度學習模型，針對「原始未裁切 PDF」進行
              300 DPI 高解析度渲染，自動偵測並裁切獨立數學公式 (Display Math)。

    關鍵特性與設計原因：
    1. 公式萃取必須針對原始 PDF 進行，確保與 PyMuPDF get_text 的原始座標一致。
    2. 夾縫中文字檢查：垂直合併時，若兩框間有 >= 4 個中文字，代表獨立公式，不合併。
    3. 精準右界控制：偵測到全形/半形公式編號時擴展右界至 97%；遇圖表標題則鎖死。

    Attributes:
        input_pdf (str): 來源 PDF 檔案路徑。
        output_docx (str): 輸出的 Word 檔案路徑。
        preview_dir (str): 存放視覺化對照圖片的資料夾名稱。
        formula_dir (str): 存放公式圖片 PNG 的資料夾路徑。
        temp_cropped_pdf (str): 過程中的暫存裁切 PDF 檔名。
    """

    def __init__(
        self,
        input_pdf: str,
        output_docx: str,
        preview_dir: str = "previews",
        formula_dir: str = "extracted_formulas",
    ):
        self.input_pdf = input_pdf
        self.output_docx = output_docx
        self.preview_dir = preview_dir
        self.formula_dir = formula_dir
        self.temp_cropped_pdf = "temp_cropped_optimized.pdf"
        os.makedirs(preview_dir, exist_ok=True)
        os.makedirs(formula_dir, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────
    # 階段一：動態裁切與 Word 轉檔
    # ──────────────────────────────────────────────────────────────────

    def plan_crop_parameters(self) -> dict:
        """
        讀取 PDF 屬性，規劃初始裁切參數與抽樣策略。

        Returns:
            dict: 包含頁面尺寸、邊界閾值與抽樣頁碼列表的設定字典。
        """
        doc = fitz.open(self.input_pdf)
        first_page = doc[0]
        rect = first_page.rect
        doc.close()

        return {
            "page_width": rect.width,
            "page_height": rect.height,
            "header_threshold": rect.height * 0.08,  # 預設頂部 8% 為頁眉區
            "footer_threshold": rect.height * 0.92,  # 預設底部 8% 為頁尾區
            "sample_pages": [0, 1, -1],               # 抽樣首頁、第二頁與最後一頁
        }

    def _detect_page_boundaries(self, page: fitz.Page, plan: dict):
        """
        [核心] 傳入單一頁面，分析該頁的文字區塊，回傳動態計算的專屬裁切邊界。

        Args:
            page (fitz.Page): 欲分析的 PDF 頁面物件。
            plan (dict): 由 plan_crop_parameters 產生的設定。

        Returns:
            tuple: (頂部裁切Y座標, 底部裁切Y座標, 偵測到的頁眉文字, 偵測到的頁尾文字)
        """
        rect = page.rect
        blocks = page.get_text("blocks")

        detected_header_y = 0.0
        detected_footer_y = rect.height
        header_text = "(無)"
        footer_text = "(無)"

        for b in blocks:
            x0, y0, x1, y1, text, *_ = b
            clean_text = text.strip()
            if not clean_text:
                continue

            # 判斷是否為頁眉 (在頂部閾值內，且字數短)
            if y1 <= plan["header_threshold"] and len(clean_text) < 30:
                detected_header_y = max(detected_header_y, y1)
                header_text = clean_text.replace("\n", " ")
            # 判斷是否為頁尾 (在底部閾值內，且為純數字或字數短)
            elif y0 >= plan["footer_threshold"] and (
                clean_text.isdigit() or len(clean_text) < 15
            ):
                detected_footer_y = min(detected_footer_y, y0)
                footer_text = clean_text.replace("\n", " ")

        # 加上 5pt 安全緩衝，避免裁切太貼近文字
        final_top = detected_header_y + 5 if detected_header_y > 0 else 0.0
        final_bottom = (
            detected_footer_y - 5 if detected_footer_y < rect.height else rect.height
        )

        return final_top, final_bottom, header_text, footer_text

    def generate_verification_report(self, plan: dict):
        """
        針對抽樣頁面產生視覺化對照預覽圖，並評估裁切風險。

        Returns:
            tuple: (報告數據列表, 是否觸發危險閾值警告)
        """
        doc = fitz.open(self.input_pdf)
        report_data = []
        has_any_warning = False
        total_pages = len(doc)

        for page_idx in plan["sample_pages"]:
            actual_idx = total_pages + page_idx if page_idx < 0 else page_idx

            if actual_idx >= total_pages or actual_idx < 0:
                continue

            page = doc[actual_idx]
            rect = page.rect

            final_top, final_bottom, header_text, footer_text = (
                self._detect_page_boundaries(page, plan)
            )

            # 繪製紅線預覽圖並輸出
            crop_rect = fitz.Rect(0, final_top, rect.width, final_bottom)
            page.draw_rect(crop_rect, color=(1, 0, 0), width=2)
            preview_path = os.path.join(
                self.preview_dir, f"preview_page_{actual_idx + 1}.png"
            )
            pix = page.get_pixmap(dpi=150)
            pix.save(preview_path)

            # 異常邊界偵測：若裁切掉超過 15% 頁面，標記警告
            is_edge_case = (final_top / rect.height > 0.15) or (
                (rect.height - final_bottom) / rect.height > 0.15
            )
            if is_edge_case:
                has_any_warning = True

            report_data.append(
                {
                    "page": actual_idx + 1,
                    "header_detected": header_text,
                    "header_cut_y": f"{final_top:.2f} pt",
                    "footer_detected": footer_text,
                    "footer_cut_y": f"{final_bottom:.2f} pt",
                    "preview_img": preview_path,
                    "status": "WARN" if is_edge_case else "PASS",
                }
            )

        doc.close()
        return report_        """
        os.makedirs(self.formula_dir, exist_ok=True)

        # 載入 MFD (Math Formula Detector) 模型 (基於 YOLO / ONNX 辨識架構)
        print("[AI] 正在載入 Pix2Text 開源 MFD 深度學習模型...")
        mfd = MathFormulaDetector()
        print("[AI] MFD 模型載入完成！")

        # 針對原始 PDF（self.input_pdf）進行分析，確保座標系統一致
        doc = fitz.open(self.input_pdf)
        total_pages = len(doc)
        # 計算 72 points (PyMuPDF 預設點數) 到指定 DPI 的放大倍率，用於坐標系轉換
        scale_factor = dpi / 72.0

        print(f"[PDF] 開始公式萃取：'{os.path.basename(self.input_pdf)}'")
        print(f"[CFG] 掃描範圍：全文共 {total_pages} 頁")
        print(f"[CFG] 渲染解析度：{dpi} DPI (AI 深度學習 MFD 分析模式)")
        print("=" * 60)

        count = 0
        generated_files = []
        skipped_pages = 0

        # 使用 tqdm 顯示逐頁分析進度條
        for page_idx in tqdm(range(total_pages), desc="AI 公式偵測進度", unit="頁"):
            page_num = page_idx + 1
            page = doc[page_idx]

            # 渲染 300 DPI 高解析度圖片（高 DPI 能大幅提升小符號與矩陣判讀品質）
            pix = page.get_pixmap(dpi=dpi)
            img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
            else:
                img = img_data.copy()

            h, w = img.shape[:2]

            # 執行 AI 視覺檢測，取得潛在公式邊界框 (bounding boxes)
            try:
                detections = mfd.detect(img)
            except Exception as e:
                tqdm.write(f"  [P{page_num:03d}] MFD 檢測異常跳過：{e}")
                continue

            if not detections:
                skipped_pages += 1
                continue

            # 篩選區塊獨立公式 (isolated math blocks)
            display_boxes = []
            for item in detections:
                b_type = item.get('type', '')
                score = item.get('score', 0.0)
                box = item.get('box', None)

                if box is None or len(box) == 0:
                    continue

                # box 格式為 [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]，取矩形極值邊界
                x0 = int(round(np.min(box[:, 0])))
                y0 = int(round(np.min(box[:, 1])))
                x1 = int(round(np.max(box[:, 0])))
                y1 = int(round(np.max(box[:, 1])))
                box_w = x1 - x0
                box_h = y1 - y0

                # 排除頁頭 (Y < 5%) 與頁尾 (Y > 95%) 區域，避免誤抓頁眉或頁碼
                if y0 < h * 0.05 or y1 > h * 0.95:
                    continue
                # 排除極小雜訊 (寬 < 25px 或 高 < 15px)
                if box_h < 15 or box_w < 25:
                    continue

                # 篩選條件：只取被判定為 isolated (獨立公式區塊) 且置信度 >= 0.45，
                # 或寬高較大的大型公式區塊 (置信度 >= 0.50)，排除純行內符號 (embedding)
                if (b_type == 'isolated' and score >= 0.45) or (box_w > w * 0.25 and box_h > 25 and score >= 0.50):
                    display_boxes.append((x0, y0, x1, y1))

            if not display_boxes:
                skipped_pages += 1
                continue

            # 依照 Y 軸上方座標進行垂直排序，確保自上而下處理
            display_boxes.sort(key=lambda b: b[1])

            # 合併垂直重疊極近的同組公式 (例如多行折行 Display Math)
            # 核心防呆邏輯：若兩框中間夾有 >= 4 個中文字 (如正文說明「矩阵...是稍后确定的矩阵」)，
            # 代表為兩條獨立公式，嚴格不合併！
            merged_boxes = []
            curr_x0, curr_y0, curr_x1, curr_y1 = display_boxes[0]

            for i in range(1, len(display_boxes)):
                nx0, ny0, nx1, ny1 = display_boxes[i]

                # 將 300 DPI 影像座標轉回 PyMuPDF 72 DPI PDF 坐標系，用以提取夾縫內的文字
                gap_y0_pdf = curr_y1 / scale_factor
                gap_y1_pdf = ny0 / scale_factor

                has_chinese_in_gap = False
                if gap_y1_pdf > gap_y0_pdf:
                    gap_rect = fitz.Rect(0, gap_y0_pdf, page.rect.width, gap_y1_pdf)
                    gap_text = page.get_text("text", clip=gap_rect).strip()
                    # 統計夾縫區域內的中文字數
                    chinese_chars = re.findall(r'[\u4e00-\u9fff]', gap_text)
                    if len(chinese_chars) >= 4:
                        has_chinese_in_gap = True

                # 若垂直間距近 (< 35px) 且中間沒有正文中文字，判定為同組多行公式，進行邊界聯集合併
                if ny0 <= curr_y1 + 35 and not has_chinese_in_gap:
                    curr_x0 = min(curr_x0, nx0)
                    curr_y0 = min(curr_y0, ny0)
                    curr_x1 = max(curr_x1, nx1)
                    curr_y1 = max(curr_y1, ny1)
                else:
                    merged_boxes.append((curr_x0, curr_y0, curr_x1, curr_y1))
                    curr_x0, curr_y0, curr_x1, curr_y1 = nx0, ny0, nx1, ny1
            merged_boxes.append((curr_x0, curr_y0, curr_x1, curr_y1))

            pad_x = 20
            pad_y = 12
            eq_idx = 1

            for (x0, y0, x1, y1) in merged_boxes:
                # 檢查公式右側區域 (72%~100% 寬度) 是否帶有公式編號
                # 透過 PyMuPDF 解析右側對應位置的文本，區分「公式編號」與「圖表標題」
                roi_y0_pdf = max(0, y0 - 15) / scale_factor
                roi_y1_pdf = min(h, y1 + 15) / scale_factor
                right_rect = fitz.Rect(page.rect.width * 0.72, roi_y0_pdf, page.rect.width, roi_y1_pdf)
                right_text = page.get_text("text", clip=right_rect).strip().replace('\n', '')

                # 正則表達式判定：是否為圖表標題 (如「图 11.10」、「圖 8.9」) 或公式編號
                # 同時支援全形括號（）與半形括號()，以及連字號 (6-20) 與小數點 (3.12) 格式
                is_figure_caption = bool(re.search(r'(图|圖|表)\s*\d+', right_text))
                has_eq_tag = bool(re.search(r'[(\uff08]\s*\d+([-.\u2013]\d+)*\s*[)\uff09]', right_text))

                # 只有當右側有編號 (X.XX / X-XX / X–XX) 且「不是圖表標題」時，
                # 才向右延伸包覆編號 (延伸至 97% 寬度)
                # 若右側為圖說或插圖，則保留原 MFD 右邊界，絕不拉寬，避免包含雜圖
                if has_eq_tag and not is_figure_caption:
                    x1 = max(x1, int(w * 0.97))

                # 加入適度留白 (padding)
                crop_x0 = max(0, x0 - pad_x)
                crop_y0 = max(0, y0 - pad_y)
                crop_x1 = min(w, x1 + pad_x)
                crop_y1 = min(h, y1 + pad_y)

                crop = img[crop_y0:crop_y1, crop_x0:crop_x1]
                if crop.shape[0] < 20 or crop.shape[1] < 30:
                    continue

                # 以 PDF 絕對頁碼與序號命名 (如 p045_eq01.png)
                filename = f"p{page_num:03d}_eq{eq_idx:02d}.png"
                filepath = os.path.join(self.formula_dir, filename)
                cv2.imwrite(filepath, crop)
                generated_files.append(filepath)
                eq_idx += 1
                count += 1

            tqdm.write(f"  [P{page_num:03d}] AI 找到 {eq_idx - 1} 個獨立公式區塊")

        doc.close()

        # ZIP 打包：以輸出 Word 檔名為基礎命名，方便對應識別
        zip_filename = os.path.splitext(self.output_docx)[0] + "_formulas.zip"��公式，嚴格不合併！
            merged_boxes = []
            curr_x0, curr_y0, curr_x1, curr_y1 = display_boxes[0]

            for i in range(1, len(display_boxes)):
                nx0, ny0, nx1, ny1 = display_boxes[i]

                # 將 300 DPI 影像座標轉回 PyMuPDF 72 DPI PDF 坐標系，用以提取夾縫內的文字
                gap_y0_pdf = curr_y1 / scale_factor
                gap_y1_pdf = ny0 / scale_factor

                has_chinese_in_gap = False
                if gap_y1_pdf > gap_y0_pdf:
                    gap_rect = fitz.Rect(0, gap_y0_pdf, page.rect.width, gap_y1_pdf)
                    gap_text = page.get_text("text", clip=gap_rect).strip()
                    # 統計夾縫區域內的中文字數
                    chinese_chars = re.findall(r'[\u4e00-\u9fff]', gap_text)
                    if len(chinese_chars) >= 4:
                        has_chinese_in_gap = True

                # 若垂直間距近 (< 35px) 且中間沒有正文中文字，判定為同組多行公式，進行邊界聯集合併
                if ny0 <= curr_y1 + 35 and not has_chinese_in_gap:
                    curr_x0 = min(curr_x0, nx0)
                    curr_y0 = min(curr_y0, ny0)
                    curr_x1 = max(curr_x1, nx1)
                    curr_y1 = max(curr_y1, ny1)
                else:
                    merged_boxes.append((curr_x0, curr_y0, curr_x1, curr_y1))
                    curr_x0, curr_y0, curr_x1, curr_y1 = nx0, ny0, nx1, ny1
            merged_boxes.append((curr_x0, curr_y0, curr_x1, curr_y1))

            pad_x = 20
            pad_y = 12
            eq_idx = 1

            for (x0, y0, x1, y1) in merged_boxes:
                # 檢查公式右側區域 (72%~100% 寬度) 是否帶有公式編號 (X.XX)
                # 透過 PyMuPDF 解析右側對應位置的文本，區分「公式編號」與「圖表標題」
                roi_y0_pdf = max(0, y0 - 15) / scale_factor
                roi_y1_pdf = min(h, y1 + 15) / scale_factor
                right_rect = fitz.Rect(page.rect.width * 0.72, roi_y0_pdf, page.rect.width, roi_y1_pdf)
                right_text = page.get_text("text", clip=right_rect).strip().replace('\n', '')

                # 正則表達式判定：是否為圖表標題 (如「图 11.10」、「圖 8.9」) 或公式編號 (如 (3.12)、(6-20))
                is_figure_caption = bool(re.search(r'(图|圖|表)\s*\d+', right_text))
                has_eq_tag = bool(re.search(r'[(\uff08]\s*\d+([-.\u2013]\d+)*\s*[)\uff09]', right_text))

                # 只有當右側有編號 (X.XX / X-XX) 且「不是圖表標題」時，才向右延伸包覆編號 (延伸至 97% 寬度)
                # 若右側為圖說或插圖，則保留原 MFD 右邊界，絕不拉寬，避免包含雜圖
                if has_eq_tag and not is_figure_caption:
                    x1 = max(x1, int(w * 0.97))

                # 加入適度留白 (padding)
                crop_x0 = max(0, x0 - pad_x)
                crop_y0 = max(0, y0 - pad_y)
                crop_x1 = min(w, x1 + pad_x)
                crop_y1 = min(h, y1 + pad_y)

                crop = img[crop_y0:crop_y1, crop_x0:crop_x1]
                if crop.shape[0] < 20 or crop.shape[1] < 30:
                    continue

                # 以 PDF 絕對頁碼與序號命名 (如 p045_eq01.png)
                filename = f"p{page_num:03d}_eq{eq_idx:02d}.png"
                filepath = os.path.join(self.formula_dir, filename)
                cv2.imwrite(filepath, crop)
                generated_files.append(filepath)
                eq_idx += 1
                count += 1

            tqdm.write(f"  [P{page_num:03d}] AI 找到 {eq_idx - 1} 個獨立公式區塊")

        doc.close()

        # NOTE: zip_filename 目前寫死為 "all_pdf_formulas_ai_mfd.zip" 於專案根目錄，不會隨 self.formula_dir 變動。
        zip_filename = "all_pdf_formulas_ai_mfd.zip"
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for f in generated_files:
                zipf.write(f, os.path.basename(f))

        print("=" * 60)
        print(f"[DONE] 提取完成！共使用 AI MFD 成功裁切 {count} 張公式圖片。")
        print(f"[ZIP]  已打包儲存於：{zip_filename}")



    # ──────────────────────────────────────────────────────────────────
    # 主控流程
    # ──────────────────────────────────────────────────────────────────

    def execute_pipeline(self, extract_formulas: bool = True):
        """
        主控流程：執行規劃、驗證、人工確認、動態裁切、轉檔，以及（可選的）公式萃取。

        流程分為兩個階段：
        - 階段一：動態裁切頁眉/頁尾，轉換為 Word 檔案。
        - 階段二（可選）：使用 AI MFD 模型萃取公式圖片（針對原始 PDF 操作）。

        Args:
            extract_formulas (bool): 是否在轉檔後執行公式圖片萃取。預設為 True。
                                     若設為 False，則僅執行階段一的 Word 轉檔。
        """
        # ── 階段一：動態裁切與 Word 轉檔 ──────────────────────────
        plan = self.plan_crop_parameters()
        report, has_warning = self.generate_verification_report(plan)

        print(">>> 驗證步驟完成，產出對照報告中...")
        for r in report:
            print(
                f"抽樣頁面 {r['page']} -> 頂部: {r['header_cut_y']} | "
                f"底部: {r['footer_cut_y']} | 預覽圖: {r['preview_img']}"
            )

        custom_crop = None
        if has_warning:
            user_choice = self.request_human_approval(
                "部分抽樣頁面裁切幅度超出安全閾值（>15% 頁高）", report
            )
            if user_choice == "2":
                top_manual = float(input("請輸入全域強制頂部裁切高度 (pt): "))
                bottom_manual = float(input("請輸入全域強制底部保留高度 (pt): "))
                custom_crop = (top_manual, bottom_manual)
            elif user_choice == "1":
                custom_crop = None
            else:
                print("流程已由人工中止。")
                return

        print("\n>>> 覆核通過，開始執行批次動態裁切...")
        doc = fitz.open(self.input_pdf)

        # 使用 tqdm 顯示單頁裁切進度條
        for page in tqdm(doc, desc="動態計算與裁切進度", unit="頁"):
            rect = page.rect

            if custom_crop:
                apply_top, apply_bottom = custom_crop
            else:
                apply_top, apply_bottom, _, _ = self._detect_page_boundaries(page, plan)

            page.set_cropbox(fitz.Rect(rect.x0, apply_top, rect.x1, apply_bottom))

        doc.save(self.temp_cropped_pdf, deflate=True)
        doc.close()

        print("\n>>> 裁切完成！開始進行 PDF 轉 Word (此步驟耗時較長，請耐心等候)...")
        try:
            cv = Converter(self.temp_cropped_pdf)
            cv.convert(self.output_docx, start=0, end=None)
            cv.close()
        finally:
            # 無論轉檔成功與否，確保安全清理暫存檔
            if os.path.exists(self.temp_cropped_pdf):
                try:
                    os.remove(self.temp_cropped_pdf)
                except OSError:
                    pass

        print(f"\n[SUCCESS] 階段一完成！已產出: {self.output_docx}")

        # ── 階段二：AI 公式萃取（針對原始未裁切 PDF）──────────────
        if extract_formulas:
            print("\n>>> 開始執行階段二：AI 深度學習公式萃取...")
            self._extract_formulas(dpi=300)

        print("\n[PIPELINE COMPLETE] 所有任務已完成。")


# ==========================================
# 導入與執行方式 (How to Import and Run)
# ==========================================
if __name__ == "__main__":
    # 確保你已在終端機安裝套件:
    # pip install pymupdf pdf2docx tqdm pix2text opencv-python numpy

    # 將 "input.pdf" 替換成你的來源檔案名，"output.docx" 替換為想要的檔名
    pipeline = PDFConversionAgent(
        input_pdf="input.pdf",
        output_docx="output.docx",
        preview_dir="previews",
        formula_dir="extracted_formulas",
    )
    # 若不需要萃取公式，可傳入 extract_formulas=False
    pipeline.execute_pipeline(extract_formulas=True)
