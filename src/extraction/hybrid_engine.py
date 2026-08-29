#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 數學公式自動裁切工具（V4：語義與視覺混合分析 Hybrid Extraction）
======================================
100% 保留原書折行、矩陣比例與多行標註，絕不橫向拉長。

改進重點：
1. 引入 PyMuPDF 底層文字區塊解析，精準定位「中文正文」與「圖表標題」。
2. 圖表排除：精準排除「图 X.X」上方的圖片與「表 X.X」下方的表格，大幅減少誤抓。
3. 語義合併 (Semantic Merging)：根據「兩個中文段落之間的空白區域」作為公式安全區，
   將該區域內的所有視覺碎塊強制合併，解決多行公式斷裂的問題。
"""

import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import io
import re
from pathlib import Path

# 集中設定中心
from config import PATHS, CFG

# Windows 終端 UTF-8 輸出修正
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import zipfile
import fitz  # PyMuPDF
import cv2
import numpy as np

def estimate_font_height(binary_inv, page_h, top_margin, bottom_margin):
    body_region = binary_inv[top_margin:bottom_margin, :]
    contours, _ = cv2.findContours(body_region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    heights = []
    for c in contours:
        _, _, w, h = cv2.boundingRect(c)
        if 10 <= h <= 80 and 5 <= w <= 200:
            heights.append(h)
    if len(heights) > 10:
        return float(np.median(heights))
    return 42.0

def estimate_body_left_margin(binary_inv, h_font, top_margin, bottom_margin):
    body_region = binary_inv[top_margin:bottom_margin, :]
    left_positions = []
    row_step = max(1, int(h_font * 0.5))
    for row in range(0, body_region.shape[0], row_step):
        row_data = body_region[row, :]
        nonzero = np.nonzero(row_data)[0]
        if len(nonzero) > 10:
            left_positions.append(nonzero[0])
    if left_positions:
        hist, bin_edges = np.histogram(left_positions, bins=50)
        most_common_bin = np.argmax(hist)
        body_left = bin_edges[most_common_bin]
        return int(body_left)
    return 0

def get_page_semantic_blocks(page, scale_factor):
    """
    從 PyMuPDF 獲取文字區塊，並分辨「中文段落」與「圖表標題」
    回傳：
        chinese_paragraphs: list of (x0, y0, x1, y1) in 300DPI scale
        image_captions: list of (x0, y0, x1, y1, text) in 300DPI scale
    """
    blocks = page.get_text("blocks")
    chinese_paragraphs = []
    image_captions = []
    
    for b in blocks:
        x0, y0, x1, y1, text, block_no, block_type = b
        if block_type != 0:
            continue
            
        text = text.strip().replace('\n', '')
        if not text:
            continue
            
        sx0, sy0, sx1, sy1 = x0 * scale_factor, y0 * scale_factor, x1 * scale_factor, y1 * scale_factor
        
        # 標題特徵：「图 2.20」、「图2.3」、「表 1.1」 (包含图、圖、表)
        if re.match(r'^(图|圖|表)\s*\d+(\.\d+)*', text):
            image_captions.append((sx0, sy0, sx1, sy1, text))
            continue
            
        # 中文段落：包含至少 2 個中文字
        if len(re.findall(r'[\u4e00-\u9fff]', text)) >= 2:
            chinese_paragraphs.append((sx0, sy0, sx1, sy1))
            
    return chinese_paragraphs, image_captions

def extract_pdf_formulas_crop(pdf_path, output_dir="extracted_formulas", dpi=300):
    os.makedirs(output_dir, exist_ok=True)
    if not pdf_path.lower().endswith('.pdf'):
        print(f"[ERROR] 輸入檔案必須是 PDF 格式：'{pdf_path}'")
        return
        
    if not os.path.exists(pdf_path):
        print(f"[ERROR] 找不到 PDF 檔案 '{pdf_path}'")
        return

    doc = fitz.open(pdf_path)
    try:
    total_pages = len(doc)
        scale_factor = dpi / 72.0
        
        print(f"[PDF] 開始讀取 PDF：'{os.path.basename(pdf_path)}'，共 {total_pages} 頁...")
        print(f"[CFG] 渲染解析度：{dpi} DPI (混合分析模式)")
        print("=" * 60)

        # ── Guardrail 1: 頁數上限防呆 ──
        from config import CFG
        if total_pages > CFG.max_safe_pages:
            print(f"[WARNING] 請求處理的頁數 ({total_pages}) 超過安全上限 ({CFG.max_safe_pages})！")
            print(f"[WARNING] 已自動截斷為 {CFG.max_safe_pages} 頁，以防止記憶體耗盡。")
            total_pages = CFG.max_safe_pages

        count = 0
        generated_files = []
        skipped_pages = 0

        for page_idx in range(total_pages):
            # ── Guardrail 2: 分批處理與記憶體回收 (Batching & GC) ──
            if page_idx > 0 and page_idx % CFG.batch_size == 0:
                import gc
                gc.collect()
                print(f"[SYS] 已處理 {page_idx} 頁，執行記憶體回收 (Garbage Collection)...")
                
            page = doc[page_idx]
            page_num = page_idx + 1
            
            # ── Guardrail 3: 動態解析度降級 (Dynamic DPI Scaling) ──
            rect = page.rect
            current_dpi = dpi
            expected_width = (rect.width * current_dpi) / 72.0
            if expected_width > CFG.max_image_width:
                current_dpi = int(CFG.max_image_width * 72.0 / rect.width)
                print(f"[WARNING] P{page_num:03d} 尺寸過大 ({expected_width:.0f}px)，為防止 OOM，動態將 DPI 降至 {current_dpi}")
                
            current_scale = current_dpi / 72.0

            # ── 1. 語義分析 (Semantic Analysis) ──
            chinese_paras, image_captions = get_page_semantic_blocks(page, current_scale)
            chinese_paras.sort(key=lambda b: b[1])

            # ── 2. 影像渲染與 OpenCV 前置處理 ──
            pix = page.get_pixmap(dpi=current_dpi)
            img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            if pix.n == 4:
                img = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
            elif pix.n == 3:
                img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
            else:
                img = img_data.copy()

            h, w = img.shape[:2]
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, binary_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            top_margin = int(h * 0.07)
            bottom_margin = int(h * 0.93)
            work_binary = binary_inv.copy()
            work_binary[:top_margin, :] = 0
            work_binary[bottom_margin:, :] = 0

            h_font = estimate_font_height(work_binary, h, top_margin, bottom_margin)
            body_left = estimate_body_left_margin(work_binary, h_font, top_margin, bottom_margin)

            # ── 3. 建立公式安全區 (Formula Safe Zones) ──
            safe_zones = []
            current_y = top_margin
            for b in chinese_paras:
                cy0, cy1 = b[1], b[3]
                if cy0 > current_y + h_font * 1.5:  # 中文段落間有足夠的空隙
                    safe_zones.append((current_y, cy0))
                current_y = max(current_y, cy1)
            if bottom_margin > current_y + h_font * 1.5:
                safe_zones.append((current_y, bottom_margin))

            # 3. OpenCV 處理
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # --- 物理塗白 (White-out Masking) ---
            # 覆蓋「中文正文」與「圖表標題」，切斷 OpenCV 的無效視覺連接
            # 強制規定塗白區域不得超過頁面寬度的 75% (x < 0.75 * w)，保護右側編號 (2.xx) 不被誤刪
            h_font_300 = h_font * scale_factor / 72.0 * 300
            
            # 塗白中文正文 (h_font 本身已經是 300 DPI 的像素值)
            h_font_300 = h_font
            
            for cx0, cy0, cx1, cy1 in chinese_paras:
                x0 = int(cx0)
                x1 = int(cx1)
                center_y = (cy0 + cy1) / 2
                ty0 = int(center_y - h_font_300 * 0.55)
                ty1 = int(center_y + h_font_300 * 0.55)
                cv2.rectangle(gray, (x0, ty0), (x1, ty1), 255, -1)
                
            # 塗白圖表標題
            for cx0, cy0, cx1, cy1, _ in image_captions:
                x0 = int(cx0)
                x1 = int(cx1)
                center_y = (cy0 + cy1) / 2
                ty0 = int(center_y - h_font_300 * 0.55)
                ty1 = int(center_y + h_font_300 * 0.55)
                cv2.rectangle(gray, (x0, ty0), (x1, ty1), 255, -1)

            # 二值化
            _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY_INV)

            # 形態學操作：連接相近的墨水像素
            kw_h = int(2 * h_font)
            kw_v = int(1.0 * h_font)
            kernel_horiz = cv2.getStructuringElement(cv2.MORPH_RECT, (kw_h, 2))
            kernel_vert = cv2.getStructuringElement(cv2.MORPH_RECT, (2, kw_v))

            dilated = cv2.dilate(thresh, kernel_horiz, iterations=1)
            dilated = cv2.dilate(dilated, kernel_vert, iterations=1)

            # 找尋輪廓
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # ── 5. 初步視覺過濾與圖片排除 ──
            visual_candidates = []
            for cnt in contours:
                cx, cy, cw, ch = cv2.boundingRect(cnt)
                
                if cy < top_margin or cy + ch > bottom_margin:
                    continue
                if cw < h_font * 0.8 or ch < h_font * 0.4:
                    continue

                roi = work_binary[cy:cy+ch, cx:cx+cw]
                extent = cv2.countNonZero(roi) / float(cw * ch) if cw * ch > 0 else 0
                
                # 圖片排除邏輯
                is_image = False
                for cap in image_captions:
                    cap_y0, cap_y1 = cap[1], cap[3]
                    cap_text = cap[4]
                    if cap_text.startswith("图") or cap_text.startswith("圖"):
                        # 圖表通常在標題上方
                        if -h_font * 2 < cap_y0 - (cy + ch) < h_font * 6:
                            if cw > w * 0.4 and ch > h_font * 4.0:
                                is_image = True
                                break
                    elif cap_text.startswith("表"):
                        # 表格通常在標題下方
                        if -h_font * 2 < cy - cap_y1 < h_font * 6:
                            if cw > w * 0.4 and ch > h_font * 4.0:
                                is_image = True
                                break
                                
                if is_image:
                    continue
                    
                # 基本的公式特徵判斷 (放寬條件，因為我們有安全區保護)
                left_indent = cx - body_left
                is_indented = left_indent > h_font * 1.5
                is_sparse = extent < 0.28
                is_not_full_width = cw < w * 0.95
                is_wide_enough = cw > h_font * 1.5
                is_tall = ch > h_font * 1.5
                
                # 或者是在頁面右側的小標籤 (2.38)
                is_right_tag = cx > w * 0.75 and cw < w * 0.2 and ch < h_font * 3

                if (is_wide_enough and is_not_full_width and (is_indented or is_sparse or is_tall)) or is_right_tag:
                    visual_candidates.append((cx, cy, cw, ch))

            # ── 6. 語義與 Y 軸投影智慧分群 (Tag-Based Y-Axis Grouping) ──
            final_boxes = []
            for zone in safe_zones:
                z_y0, z_y1 = zone
                zone_boxes = []
                
                for box in visual_candidates:
                    cx, cy, cw, ch = box
                    center_y = cy + ch / 2.0
                    # 如果公式框的中心落在安全區內 (稍微放寬邊界)
                    if z_y0 - h_font <= center_y <= z_y1 + h_font:
                        zone_boxes.append(box)
                        
                if zone_boxes:
                    # 將該安全區內的所有碎塊合併成一個完整的公式
                    min_x = min([b[0] for b in zone_boxes])
                    min_y = min([b[1] for b in zone_boxes])
                    max_x = max([b[0] + b[2] for b in zone_boxes])
                    max_y = max([b[1] + b[3] for b in zone_boxes])
                    
                    # 安全防呆：避免合併出橫跨大半頁的無效區域
                    if max_y - min_y < h * 0.6:
                        final_boxes.append((min_x, min_y, max_x - min_x, max_y - min_y))
                    else:
                        # 如果太大，則不強制合併，保留原狀 (極端情況防護)
                        for b in zone_boxes:
                            final_boxes.append(b)

            # ── 7. 裁切與輸出 ──
            final_boxes = sorted(list(set(final_boxes)), key=lambda b: b[1])
            eq_idx = 1
            for (cx, cy, cw, ch) in final_boxes:
                pad_x = int(h_font * 0.5)
                pad_y = int(h_font * 0.4)
                x1 = max(0, int(cx - pad_x))
                y1 = max(0, int(cy - pad_y))
                x2 = min(w, int(cx + cw + pad_x))
                y2 = min(h, int(cy + ch + pad_y))

                crop = img[y1:y2, x1:x2]
                if crop.shape[0] < h_font * 0.8 or crop.shape[1] < h_font * 1.5:
                    continue

                filename = f"p{page_num:03d}_eq{eq_idx:02d}.png"
                filepath = os.path.join(output_dir, filename)
                # 解決 Windows 中文路徑無法透過 cv2.imwrite 儲存的問題
                ext = os.path.splitext(filepath)[1]
                result, img_encode = cv2.imencode(ext, crop)
                if result:
                    img_encode.tofile(filepath)
                generated_files.append(filepath)
                eq_idx += 1
                count += 1

            if eq_idx > 1:
                print(f"  [P{page_num:03d}] 找到 {eq_idx - 1} 個公式 (文字高度≈{h_font:.0f}px)")
            else:
                skipped_pages += 1

        finally:
    doc.close()

    # ── 8. 打包 ZIP ──
    # ✅ 錨定至 output_dir 的上層（與 output 資料夾並排），不寫入 CWD
    zip_path = Path(output_dir).parent / "all_pdf_formulas_hybrid.zip"
    with zipfile.ZipFile(str(zip_path), 'w', zipfile.ZIP_DEFLATED) as zipf:
        for f in generated_files:
            zipf.write(f, os.path.basename(f))

    print("=" * 60)
    print(f"[DONE] 提取完成！共成功裁切 {count} 張公式圖片。")
    print(f"[STAT] 統計：{total_pages} 頁中有 {total_pages - skipped_pages} 頁包含公式")
    print(f"[ZIP]  已打包儲存於：{zip_path}")


if __name__ == "__main__":
    # ✅ 在腳本旁的「待提取公式檔案」資料夾找 PDF，不受 CWD 影響
    PDF_FILE_PATH = PATHS.input_dir / "101844-01 四足仿生机器人基本原理及开发教程 ZW.pdf"

    if not PDF_FILE_PATH.exists():
        print(f"[ERROR] 找不到 PDF：{PDF_FILE_PATH}")
        print(f"        請將 PDF 放入：{PATHS.input_dir}")
    else:
        extract_pdf_formulas_crop(str(PDF_FILE_PATH))
