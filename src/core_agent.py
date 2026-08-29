#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 智慧轉換與 AI 公式萃取全功能工作站 (PDFConversionAgent Pipeline & GUI)
=============================================================================
整合功能說明：
1. 【任務一：動態裁切與轉檔 Word】
   透過 PyMuPDF 動態分析頁首與頁尾邊界、自動裁切掉頁眉頁碼雜訊，並轉換為排版乾淨的 Word (.docx) 文件。

2. 【任務二：AI 深度學習數學公式萃取】
   利用 Pix2Text 開源之 MathFormulaDetector (MFD) 深度學習模型，針對原始未裁切 PDF 以 300 DPI 高解析度渲染，
   自動偵測獨立公式，具備「夾縫中文字檢查 (防誤合併)」與「全形/半形括號編號右界自適應擴展 (防雜圖)」雙重防呆機制，
   最後裁切為高畫質 PNG 公式截圖並自動封裝為 ZIP 壓縮檔。

3. 【雙模啟動介面】
   - 雙擊執行 / 無參數呼叫：開啟 Tkinter 原生全功能視窗介面 (GUI)，可自由勾選任務一、任務二或一鍵雙開。
   - 命令列模式 (CLI)：支援帶參數背景自動化批次執行。
"""

import os
import sys
import io
import glob
import re
import zipfile
import threading
from pathlib import Path

# 集中設定中心：路徑由 pathlib 動態計算，API 金鑰/設定值由 .env 載入
from config import PATHS, AI, CFG

# Windows 終端 UTF-8 輸出相容性設定
if sys.platform == 'win32':
    try:
        if isinstance(sys.stdout, io.TextIOWrapper) and sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if isinstance(sys.stderr, io.TextIOWrapper) and sys.stderr.encoding.lower() != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import fitz  # PyMuPDF
import cv2
import numpy as np
from tqdm import tqdm
from pix2text import MathFormulaDetector

# pdf2docx 延遲/防呆載入
try:
    from pdf2docx import Converter
    HAS_PDF2DOCX = True
except ImportError:
    HAS_PDF2DOCX = False


class PDFConversionAgent:
    """
    PDF 轉換與公式萃取代理核心類別
    """
    _mfd_model = None  # 類別共用快取

    @classmethod
    def get_mfd_model(cls, log_fn=print):
        if cls._mfd_model is None:
            log_fn("[AI] 正在載入 Pix2Text 開源 MFD 深度學習模型 (初次載入，請稍候)...")
            cls._mfd_model = MathFormulaDetector()
            log_fn("[AI] MFD 模型載入完成！")
        else:
            log_fn("[AI] 使用已快取的 MFD 深度學習模型 (秒速啟動)。")
        return cls._mfd_model

    def __init__(self, input_pdf: str, output_docx: str = None,
                 preview_dir: str = None,
                 formula_dir: str = None,
                 header_ratio: float = None,
                 footer_ratio: float = None):
        if not input_pdf.lower().endswith('.pdf'):
            raise ValueError(f"輸入檔案必須是 PDF 格式，但收到了：'{input_pdf}'")
            
        self.input_pdf = input_pdf
        if output_docx:
            self.output_docx = output_docx
        else:
            base_name = os.path.splitext(os.path.basename(input_pdf))[0]
            self.output_docx = f"{base_name}_已轉檔.docx"

        # ✅ 所有目錄預設由 PATHS 提供，不再使用裸字串相對路徑
        self.preview_dir = preview_dir if preview_dir else str(PATHS.preview_dir)
        self.formula_dir = formula_dir if formula_dir else str(PATHS.formula_dir_v2)

        # ✅ 臨時 PDF 錨定至專案根目錄，不再污染 CWD
        self.temp_cropped_pdf = str(PATHS.root / "temp_cropped_optimized.pdf")

        # ✅ 探測比例預設由 CFG 提供（可由 .env 覆寫）
        self.header_ratio = header_ratio if header_ratio is not None else CFG.header_ratio
        self.footer_ratio = footer_ratio if footer_ratio is not None else CFG.footer_ratio

        os.makedirs(self.preview_dir, exist_ok=True)
        os.makedirs(self.formula_dir, exist_ok=True)

    def plan_crop_parameters(self) -> dict:
        """讀取 PDF 屬性，規劃初始裁切參數與抽樣策略。"""
        with fitz.open(self.input_pdf) as doc:
            first_page = doc[0]
            rect = first_page.rect

        return {
            "page_width": rect.width,
            "page_height": rect.height,
            "header_threshold": rect.height * self.header_ratio,
            "footer_threshold": rect.height * self.footer_ratio,
            "sample_pages": [0, 1, -1]
        }

    def _detect_page_boundaries(self, page: fitz.Page, plan: dict):
        """傳入單一頁面，分析該頁文字區塊，回傳動態計算的專屬裁切邊界。"""
        rect = page.rect
        blocks = page.get_text("blocks")
        
        # 使用者指定的探測極限 (由滑桿控制)
        header_search_limit = plan["header_threshold"]
        footer_search_limit = plan["footer_threshold"]
        
        detected_header_y = 0.0
        detected_footer_y = rect.height
        header_text = "(無)"
        footer_text = "(無)"

        # 將 blocks 依照 Y 座標排序，方便判斷上下區塊的間距
        blocks.sort(key=lambda b: b[1])

        for i, b in enumerate(blocks):
            x0, y0, x1, y1, text, *_ = b
            clean_text = text.strip()
            if not clean_text:
                continue

            # 限制長度小於 25，真正的頁眉都很短，這能有效防止把正文第一行 (長句子) 誤認為頁眉
            if y1 <= header_search_limit and len(clean_text) < 25:
                # 尋找真正「下一行」文字的 y0 (解決左右並排文字干擾的問題)
                next_y0 = rect.height
                for next_b in blocks:
                    if next_b[4].strip():
                        # 只要另一個區塊的頂部 (y0) 高於我們底部的容錯值 (-2pt)，就認定它在我們「下方」
                        if next_b[1] >= y1 - 2:
                            next_y0 = min(next_y0, next_b[1])
                            
                gap_to_next_line = next_y0 - y1
                
                # 1. 絕對頂部安全區 (5%)
                # 2. 或者與「下一行」有明顯間距 (大於 10pt)
                if y1 <= (rect.height * 0.05) or gap_to_next_line > 10:
                    detected_header_y = max(detected_header_y, y1)
                    header_text = clean_text.replace("\n", " ")
                    
            # 頁尾判定：在下方探測區內，且為數字(頁碼)或短文字
            elif y0 >= footer_search_limit and (clean_text.isdigit() or len(clean_text) < 25):
                detected_footer_y = min(detected_footer_y, y0)
                footer_text = clean_text.replace("\n", " ")

        final_top = detected_header_y + 5 if detected_header_y > 0 else 0.0
        final_bottom = detected_footer_y - 5 if detected_footer_y < rect.height else rect.height

        return final_top, final_bottom, header_text, footer_text

    def generate_verification_report(self, plan: dict, log_fn=print):
        """針對抽樣頁面產生視覺化對照預覽圖，並評估裁切風險。"""
        doc = fitz.open(self.input_pdf)
        try:
            report_data = []
            has_any_warning = False
            total_pages = len(doc)

            for page_idx in plan["sample_pages"]:
                actual_idx = total_pages + page_idx if page_idx < 0 else page_idx
                if actual_idx >= total_pages or actual_idx < 0:
                    continue

                page = doc[actual_idx]
                rect = page.rect
                final_top, final_bottom, header_text, footer_text = self._detect_page_boundaries(page, plan)

                crop_rect = fitz.Rect(0, final_top, rect.width, final_bottom)
                page.draw_rect(crop_rect, color=(1, 0, 0), width=2)
                preview_path = os.path.join(self.preview_dir, f"preview_page_{actual_idx + 1}.png")
                pix = page.get_pixmap(dpi=150)
                pix.save(preview_path)

                is_edge_case = (final_top / rect.height > 0.15) or ((rect.height - final_bottom) / rect.height > 0.15)
                if is_edge_case:
                    has_any_warning = True

                report_data.append({
                    "page": actual_idx + 1,
                    "header_detected": header_text,
                    "header_cut_y": f"{final_top:.2f} pt",
                    "footer_detected": footer_text,
                    "footer_cut_y": f"{final_bottom:.2f} pt",
                    "preview_img": preview_path,
                    "status": "WARN" if is_edge_case else "PASS"
                })

            return report_data, has_any_warning
        finally:
            doc.close()

    def convert_to_word(self, log_fn=print, progress_callback=None) -> bool:
        """
        [任務一核心] 執行 PDF 動態邊界裁切並轉換為 Word (.docx)
        """
        if not HAS_PDF2DOCX:
            log_fn("[ERROR] 尚未安裝 pdf2docx 套件！請在終端機執行：pip install pdf2docx")
            return False

        if not os.path.exists(self.input_pdf):
            log_fn(f"[ERROR] 找不到 PDF 檔案 '{self.input_pdf}'")
            return False

        log_fn("\n" + "=" * 60)
        log_fn(">>> [階段一] 開始執行 PDF 動態裁切與 Word 轉檔...")
        plan = self.plan_crop_parameters()
        report, has_warning = self.generate_verification_report(plan, log_fn=log_fn)

        log_fn(">>> 抽樣驗證報告完成：")
        for r in report:
            log_fn(f"  * 抽樣頁面 {r['page']} | 頂部: {r['header_cut_y']} | 底部: {r['footer_cut_y']} | 狀態: {r['status']}")

        log_fn(">>> 正在批次動態計算每頁裁切邊界...")
        with fitz.open(self.input_pdf) as doc:
            for page in doc:
                rect = page.rect
                apply_top, apply_bottom, _, _ = self._detect_page_boundaries(page, plan)
                page.set_cropbox(fitz.Rect(rect.x0, apply_top, rect.x1, apply_bottom))

            doc.save(self.temp_cropped_pdf, deflate=True)

        log_fn(f">>> 邊界裁切完成！開始轉檔至 Word: '{self.output_docx}' (轉檔較耗時，請稍候)...")
        try:
            cv = Converter(self.temp_cropped_pdf)
            try:
                cv.convert(self.output_docx, start=0, end=None)
            finally:
                cv.close()
            log_fn(f"[SUCCESS] 🎉 Word 轉檔成功！已產出：{self.output_docx}")
            return True
        except Exception as e:
            log_fn(f"[ERROR] Word 轉檔失敗：{e}")
            return False
        finally:
            if os.path.exists(self.temp_cropped_pdf):
                try:
                    os.remove(self.temp_cropped_pdf)
                except OSError:
                    pass

    def extract_formulas(self, dpi: int = 300, start_page_idx: int = 0, end_page_idx: int = None, log_fn=print, progress_callback=None) -> list:
        """
        [任務二核心] 使用 Pix2Text MFD 模型從未裁切原始 PDF 中偵測並擷取獨立公式截圖。
        """
        os.makedirs(self.formula_dir, exist_ok=True)
        if not os.path.exists(self.input_pdf):
            log_fn(f"[ERROR] 找不到 PDF 檔案 '{self.input_pdf}'")
            return []

        log_fn("\n" + "=" * 60)
        mfd = self.get_mfd_model(log_fn=log_fn)

        doc = fitz.open(self.input_pdf)
        try:
            total_pages = len(doc)
            scale_factor = dpi / 72.0

            if end_page_idx is None:
                end_page_idx = total_pages - 1

            start_page_idx = max(0, min(start_page_idx, total_pages - 1))
            end_page_idx = max(start_page_idx, min(end_page_idx, total_pages - 1))

            scan_start_page = start_page_idx + 1
            scan_end_page = end_page_idx + 1
            is_full_scan = (start_page_idx == 0 and end_page_idx == total_pages - 1)
            scan_label = "全文" if is_full_scan else "自訂範圍"

            log_fn(f"[PDF] 開始讀取原始 PDF：'{os.path.basename(self.input_pdf)}'")
            log_fn(f"[CFG] 掃描範圍：第 {scan_start_page} 頁 ～ 第 {scan_end_page} 頁（{scan_label}，共 {total_pages} 頁）")
            log_fn(f"[CFG] 渲染解析度：{dpi} DPI (AI 深度學習 MFD 分析模式)")
            log_fn(f"[CFG] 公式輸出目錄：{self.formula_dir}")
            log_fn("=" * 60)

            count = 0
            generated_files = []
            skipped_pages = 0

            total_to_process = end_page_idx - start_page_idx + 1
            
            # ── Guardrail 1: 頁數上限防呆 ──
            if total_to_process > CFG.max_safe_pages:
                log_fn(f"[WARNING] 請求處理的頁數 ({total_to_process}) 超過安全上限 ({CFG.max_safe_pages})！")
                log_fn(f"[WARNING] 已自動截斷為 {CFG.max_safe_pages} 頁，以防止記憶體耗盡。")
                end_page_idx = start_page_idx + CFG.max_safe_pages - 1
                total_to_process = CFG.max_safe_pages
                
            for idx_offset, page_idx in enumerate(range(start_page_idx, end_page_idx + 1)):
                if progress_callback:
                    progress_callback(idx_offset + 1, total_to_process, f"提取公式 (P{page_idx + 1})")
                
                # ── Guardrail 2: 分批處理與記憶體回收 (Batching & GC) ──
                if idx_offset > 0 and idx_offset % CFG.batch_size == 0:
                    import gc
                    gc.collect()
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except ImportError:
                        pass
                    log_fn(f"[SYS] 已處理 {idx_offset} 頁，執行記憶體回收 (Garbage Collection)...")
                    
                page_num = page_idx + 1
                page = doc[page_idx]

                # ── Guardrail 3: 動態解析度降級 (Dynamic DPI Scaling) ──
                rect = page.rect
                current_dpi = dpi
                expected_width = (rect.width * current_dpi) / 72.0
                if expected_width > CFG.max_image_width:
                    current_dpi = int(CFG.max_image_width * 72.0 / rect.width)
                    log_fn(f"[WARNING] P{page_num:03d} 尺寸過大 ({expected_width:.0f}px)，為防止 OOM，動態將 DPI 降至 {current_dpi}")
                
                current_scale = current_dpi / 72.0
                pix = page.get_pixmap(dpi=current_dpi)
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                if pix.n == 4:
                    img = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
                elif pix.n == 3:
                    img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
                else:
                    img = img_data.copy()

                h, w = img.shape[:2]

                try:
                    detections = mfd.detect(img)
                except Exception as e:
                    log_fn(f"[WARN: MFD_SKIP] [P{page_num:03d}] MFD 檢測異常跳過：{e}")
                    continue

                if not detections:
                    skipped_pages += 1
                    continue

                display_boxes = []
                for item in detections:
                    b_type = item.get('type', '')
                    score = item.get('score', 0.0)
                    box = item.get('box', None)
                    if box is None or len(box) == 0:
                        continue

                    x0 = int(round(np.min(box[:, 0])))
                    y0 = int(round(np.min(box[:, 1])))
                    x1 = int(round(np.max(box[:, 0])))
                    y1 = int(round(np.max(box[:, 1])))
                    box_w = x1 - x0
                    box_h = y1 - y0

                    if y0 < h * 0.05 or y1 > h * 0.95:
                        continue
                    if box_h < 15 or box_w < 25:
                        continue

                    if (b_type == 'isolated' and score >= 0.45) or (box_w > w * 0.25 and box_h > 25 and score >= 0.50):
                        display_boxes.append((x0, y0, x1, y1))

                if not display_boxes:
                    skipped_pages += 1
                    continue

                display_boxes.sort(key=lambda b: b[1])

                merged_boxes = []
                curr_x0, curr_y0, curr_x1, curr_y1 = display_boxes[0]

                for i in range(1, len(display_boxes)):
                    nx0, ny0, nx1, ny1 = display_boxes[i]
                    gap_y0_pdf = curr_y1 / scale_factor
                    gap_y1_pdf = ny0 / scale_factor

                    has_chinese_in_gap = False
                    if gap_y1_pdf > gap_y0_pdf:
                        gap_rect = fitz.Rect(0, gap_y0_pdf, page.rect.width, gap_y1_pdf)
                        gap_text = page.get_text("text", clip=gap_rect).strip()
                        chinese_chars = re.findall(r'[\u4e00-\u9fff]', gap_text)
                        if len(chinese_chars) >= 4:
                            has_chinese_in_gap = True

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
                    roi_y0_pdf = max(0, y0 - 15) / scale_factor
                    roi_y1_pdf = min(h, y1 + 15) / scale_factor
                    right_rect = fitz.Rect(page.rect.width * 0.72, roi_y0_pdf, page.rect.width, roi_y1_pdf)
                    right_text = page.get_text("text", clip=right_rect).strip().replace('\n', '')

                    is_figure_caption = bool(re.search(r'(图|圖|表)\s*\d+', right_text))
                    has_eq_tag = bool(re.search(r'[(\uff08]\s*\d+([-.\u2013]\d+)*\s*[)\uff09]', right_text))

                    if has_eq_tag and not is_figure_caption:
                        # 使用 PyMuPDF 抓出這個區域的所有文字塊，取得最右側的邊界，避免產生過多留白或切到雜訊
                        words = page.get_text("words", clip=right_rect)
                        if words:
                            max_word_x1 = max([w[2] for w in words]) * scale_factor
                            if max_word_x1 > x1:
                                x1 = max(x1, int(max_word_x1 + 10))

                    crop_x0 = max(0, x0 - pad_x)
                    crop_y0 = max(0, y0 - pad_y)
                    crop_x1 = min(w, x1 + pad_x)
                    crop_y1 = min(h, y1 + pad_y)

                    crop = img[crop_y0:crop_y1, crop_x0:crop_x1]
                    if crop.shape[0] < 20 or crop.shape[1] < 30:
                        continue

                    filename = f"p{page_num:03d}_eq{eq_idx:02d}.png"
                    filepath = os.path.join(self.formula_dir, filename)
                    # 解決 Windows 中文路徑無法透過 cv2.imwrite 儲存的問題
                    ext = os.path.splitext(filepath)[1]
                    result, img_encode = cv2.imencode(ext, crop)
                    if result:
                        img_encode.tofile(filepath)
                    generated_files.append(filepath)
                    eq_idx += 1
                    count += 1

                if eq_idx > 1:
                    log_fn(f"  [P{page_num:03d}] AI 找到 {eq_idx - 1} 個獨立公式區塊")
        finally:
            doc.close()

        zip_filename = os.path.join(self.formula_dir, "all_pdf_formulas_ai_mfd.zip")
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for f in generated_files:
                zipf.write(f, os.path.basename(f))

        log_fn("=" * 60)
        log_fn(f"[DONE] 公式提取完成！共使用 AI MFD 成功裁切 {count} 張公式圖片。")
        log_fn(f"[ZIP]  已打包儲存於：{zip_filename}")
        log_fn("=" * 60)

        return generated_files

    def execute_pipeline(self, convert_word: bool = True, extract_formulas: bool = True, formula_dpi: int = 300, start_page_idx: int = 0, end_page_idx: int = None, log_fn=print, progress_callback=None):
        if convert_word:
            self.convert_to_word(log_fn=log_fn, progress_callback=progress_callback)
            
        if extract_formulas:
            self.extract_formulas(
                dpi=formula_dpi,
                start_page_idx=start_page_idx,
                end_page_idx=end_page_idx,
                log_fn=log_fn,
                progress_callback=progress_callback
            )
            
        # ── Guardrail 4: 統整輸出包裝 ──
        log_fn("\n>>> 正在統整輸出產物...")
        import shutil
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(os.path.basename(self.input_pdf))[0]
        delivery_folder = PATHS.root / "data" / "03_output" / f"{base_name}_{timestamp}"
        
        try:
            os.makedirs(delivery_folder, exist_ok=True)
            has_moved = False
            
            # 移動 Word 檔
            if convert_word and os.path.exists(self.output_docx):
                shutil.copy(self.output_docx, delivery_folder / os.path.basename(self.output_docx))
                has_moved = True
                
            # 移動公式 ZIP 檔
            zip_filename = os.path.join(self.formula_dir, "all_pdf_formulas_ai_mfd.zip")
            if extract_formulas and os.path.exists(zip_filename):
                shutil.copy(zip_filename, delivery_folder / "formulas.zip")
                has_moved = True
                
            if has_moved:
                log_fn(f"[SUCCESS] 📦 任務輸出已打包至資料夾：\n    {delivery_folder}")
                return str(delivery_folder)
        except Exception as e:
            log_fn(f"[WARNING] 打包輸出檔案時發生錯誤：{e}")
        return None
# =========================================================================
# Tkinter 全功能視覺化工作站 (GUI 介面)
# =========================================================================
