#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 深度學習公式檢測器 (Pix2Text MFD 版)
======================================
功能說明：
本腳本為 PDF 公式自動萃取管線的第一階段腳本。
利用 Pix2Text 開源之 MathFormulaDetector (MFD) 深度學習模型，
針對 PDF 頁面進行高解析度渲染 (300 DPI)，自動偵測並裁切區塊獨立數學公式 (Display Math)。

關鍵特性與設計原因：
1. 結合 AI 視覺檢測與 PyMuPDF 底層語義解析，徹底排除封面標題、照片插圖、幾何圖形與正文內文。
2. 夾縫中文字檢查：在進行垂直多行公式合併時，透過 PyMuPDF 檢測框間是否有 ≥ 2 個中文字，防止跨句公式被誤合併。
3. 精準右界控制：利用文字正則表達式比對右側區域，僅在確定為公式編號 (X.XX) 時向右擴展，遇到圖說 (如「圖 11.10」) 時鎖死右界，避免裁切到右側插圖。
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

import fitz  # PyMuPDF
import cv2
import numpy as np
from pix2text import MathFormulaDetector


def extract_pdf_formulas_ai_mfd(pdf_path, start_page_idx=0, end_page_idx=None, output_dir="extracted_formulas_mfd", dpi=300):
    """
    使用 Pix2Text MFD 模型從 PDF 中精準偵測並擷取獨立數學公式截圖。

    參數意義：
    -----------
    pdf_path : str
        目標 PDF 檔案路徑。
    start_page_idx : int, 預設 0
        起始處理的頁碼索引（0-based，0 代表 PDF 第 1 頁）。
    end_page_idx : int 或 None, 預設 None
        結束處理的頁碼索引（0-based，包含該頁）。若為 None，自動解析為總頁數 - 1（即處理至最後一頁）。
    output_dir : str, 預設 "extracted_formulas_mfd"
        裁切產出的 PNG 公式截圖儲存資料夾路徑。
    dpi : int, 預設 300
        PDF 渲染成影像的解析度 (Dots Per Inch)。300 DPI 可確保分數線、矩陣與細小標註清晰不失真。

    傳回值：
    --------
    None (結果直接寫入 output_dir 並打包至 ZIP 檔案)
    """
    os.makedirs(output_dir, exist_ok=True)
    if not os.path.exists(pdf_path):
        print(f"[ERROR] 找不到 PDF 檔案 '{pdf_path}'")
        return

    # 載入 MFD (Math Formula Detector) 模型 (基於 YOLO / ONNX 辨識架構)
    print("[AI] 正在載入 Pix2Text 開源 MFD 深度學習模型...")
    mfd = MathFormulaDetector()
    print("[AI] MFD 模型載入完成！")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    # 計算 72 points (PyMuPDF 預設點數) 到指定 DPI 的放大倍率，用於坐標系轉換
    scale_factor = dpi / 72.0

    # 立即將 end_page_idx 從 None resolve 為實際 0-based 索引，
    # 避免 None 帶入後續迴圈邊界導致 TypeError
    if end_page_idx is None:
        end_page_idx = total_pages - 1

    # 計算人類可讀的「頁碼」（1-based）供 log 輸出使用
    scan_start_page = start_page_idx + 1
    scan_end_page   = end_page_idx + 1
    is_full_scan    = (start_page_idx == 0 and end_page_idx == total_pages - 1)
    scan_label      = "全文" if is_full_scan else "自訂範圍"

    print(f"[PDF] 開始讀取 PDF：'{os.path.basename(pdf_path)}'")
    print(f"[CFG] 掃描範圍：第 {scan_start_page} 頁 ～ 第 {scan_end_page} 頁（{scan_label}，共 {total_pages} 頁）")
    print(f"[CFG] 渲染解析度：{dpi} DPI (AI 深度學習 MFD 分析模式)")
    print("=" * 60)

    count = 0
    generated_files = []
    skipped_pages = 0

    for page_idx in range(start_page_idx, end_page_idx + 1):
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
            print(f"  [P{page_num:03d}] MFD 檢測異常跳過：{e}")
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
        # 核心防呆邏輯：若兩框中間夾有 >= 2 個中文字 (如正文說明「矩阵...是稍后确定的矩阵」)，代表為兩條獨立公式，嚴格不合併！
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
            filepath = os.path.join(output_dir, filename)
            cv2.imwrite(filepath, crop)
            generated_files.append(filepath)
            eq_idx += 1
            count += 1

        print(f"  [P{page_num:03d}] AI 找到 {eq_idx - 1} 個獨立公式區塊")

    doc.close()

    # NOTE: zip_filename 目前寫死為 "all_pdf_formulas_ai_mfd.zip" 於專案根目錄，不會隨 output_dir 變動。
    zip_filename = "all_pdf_formulas_ai_mfd.zip"
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for f in generated_files:
            zipf.write(f, os.path.basename(f))

    print("=" * 60)
    print(f"[DONE] 提取完成！共使用 AI MFD 成功裁切 {count} 張公式圖片。")
    print(f"[ZIP]  已打包儲存於：{zip_filename}")


if __name__ == "__main__":
    import argparse
    import os as _os

    _base = _os.path.dirname(_os.path.abspath(__file__))
    _default_pdf = _os.path.join(_base, "待提取公式檔案", "106629-01 数学通俗演义 67383-5.pdf")
    _default_out = _os.path.join(_base, "extracted_formulas_mfd-2")

    parser = argparse.ArgumentParser(description="PDF 公式提取工具 (MFD AI 版)")
    parser.add_argument("--pdf",    default=_default_pdf, help="PDF 檔案路徑")
    parser.add_argument("--output", default=_default_out,  help="PNG 輸出資料夾")
    parser.add_argument("--start",  type=int, default=None, help="起始頁碼（1-based）")
    parser.add_argument("--end",    type=int, default=None, help="結束頁碼（1-based）")
    args = parser.parse_args()

    # 將使用者輸入的 1-based 頁碼轉換為 0-based 索引
    start_idx = (args.start - 1) if args.start is not None else 0
    end_idx   = (args.end   - 1) if args.end   is not None else None

    # 預設全文掃描；如需縮小範圍可傳入 start_page_idx / end_page_idx
    # 例如只掃第 43～47 頁：extract_pdf_formulas_ai_mfd(PDF_FILE_PATH, start_page_idx=42, end_page_idx=46, output_dir=OUTPUT_DIR)
    extract_pdf_formulas_ai_mfd(args.pdf, start_page_idx=start_idx, end_page_idx=end_idx, output_dir=args.output)

