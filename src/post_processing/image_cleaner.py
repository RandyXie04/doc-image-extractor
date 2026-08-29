import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 公式截圖文字二次清理與白邊自動裁切工具 (EasyOCR 後處理版)
==========================================================
功能說明：
本腳本為 PDF 公式自動萃取管線的第二階段（後處理）腳本。
針對 extract_with_mfd.py 所輸出的公式截圖，透過 EasyOCR 模型辨識並精準塗白圖片最左側殘留的正文接續詞（如「其中，」、「因此」），
同時嚴格保護公式主體與帶括號的條件說明（如 `(s_3 为正值时)`），最後執行白邊自動裁切 (Auto-Trim)，輸出高品質排版用公式圖檔。

設計原則與維護注意事項：
1. Windows Unicode 相容：使用 OpenCV imdecode/imencode buffer 機制，解決 Windows 系統下包含中文路徑讀寫失敗的問題。
2. 兩段式安全抹除：僅抹除位於圖片最左側 (X < 18% 寬度) 且無括號的中文字；若文字同行含有括號條件句，則強制跳過抹除。
"""

import os
import sys
import zipfile
import re
import cv2
import numpy as np
from glob import glob
from pathlib import Path
from tqdm import tqdm

# 集中設定：路徑由 pathlib 動態計算，API 金鑰/設定值由 .env 載入
from config import PATHS, CFG


def load_image_unicode(path):
    """
    載入含中文或特殊字元路徑的圖片（Windows OpenCV 相容讀取）。

    參數意義：
    -----------
    path : str
        圖片的完整檔案路徑（可包含中文與空白）。

    傳回值：
    --------
    numpy.ndarray 或 None
        成功傳回 BGR 格式影像陣列，失敗傳回 None。
    """
    try:
        # np.fromfile 可避開 OpenCV C++ API 在 Windows 無法解析非 ANSI 路徑的問題
        img_array = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"Error loading image {path}: {e}")
        return None


def save_image_unicode(path, img):
    """
    儲存圖片至含中文或特殊字元的檔案路徑（Windows OpenCV 相容寫入）。

    參數意義：
    -----------
    path : str
        儲存目標的完整檔案路徑。
    img : numpy.ndarray
        欲儲存的 BGR 影像陣列。

    傳回值：
    --------
    bool
        儲存成功傳回 True，失敗傳回 False。
    """
    try:
        ext = os.path.splitext(path)[1]
        # 先在記憶體中編碼，再透過 Python 檔案串流寫入硬碟，避開 Unicode 路徑限制
        result, img_encode = cv2.imencode(ext, img)
        if result:
            img_encode.tofile(path)
            return True
        return False
    except Exception as e:
        print(f"Error saving image {path}: {e}")
        return False


def contains_chinese(text):
    """
    檢查字串中是否包含中文字元 (CJK 統一漢字)。

    參數意義：
    -----------
    text : str
        OCR 辨識出之文字內容。

    傳回值：
    --------
    bool
        包含中文字傳回 True，否則傳回 False。
    """
    if not text:
        return False
    # 涵蓋 CJK 常用漢字與擴充漢字範圍
    pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')
    return bool(pattern.search(text))


def has_brackets(text):
    """
    檢查字串是否包含半形或全形括號。

    參數意義：
    -----------
    text : str
        OCR 辨識出之文字內容。

    傳回值：
    --------
    bool
        若包含任何形式的括號（如 `()`, `（）`, `[]`, `【】`）傳回 True，代表該文字為條件說明或編號，需加以保護。
    """
    bracket_chars = ['(', ')', '（', '）', '[', ']', '【', '】']
    return any(c in text for c in bracket_chars)


def is_left_text_to_erase(bbox, text, img_width):
    """
    判斷 EasyOCR 偵測到的文字區塊是否屬於「最左側需要塗白的正文接續詞」。

    判定邏輯原因：
    1. 必須包含中文字：避免抹除最左側的純數學符號或變數 (如 `x = ...`)。
    2. 絕對不能包含括號：保護如 `(s_3 为正值时)` 等附帶條件說明與公式邊緣註記。
    3. 必須位於圖片最左側 (X 軸前 18% 範圍內)：避免誤抹公式中央或右側出現的中文字。

    參數意義：
    -----------
    bbox : list
        EasyOCR 傳回之四點坐標 `[[x0,y0], [x1,y0], [x1,y1], [x0,y1]]`。
    text : str
        該區域的辨識文字內容。
    img_width : int
        當前公式圖片的總像素寬度。

    傳回值：
    --------
    bool
        符合抹除條件傳回 True，否則傳回 False。
    """
    if not contains_chinese(text):
        return False

    # 若含有括號，屬於公式條件註解說明，100% 保護不抹除
    if has_brackets(text):
        return False

    pts = np.array(bbox, dtype=np.int32)
    x_min = np.min(pts[:, 0])
    x_max = np.max(pts[:, 0])
    x_center = (x_min + x_max) / 2.0

    # 僅抹除起始位置在最左側 (X < 18% 寬度) 且中心點未偏離最左區域 (X < 22%) 的正文詞
    if x_min < img_width * 0.18 and x_center < img_width * 0.22:
        return True

    return False


def auto_trim(img, padding=15, white_threshold=245):
    """
    自動裁切圖片四周過多的白邊 (Auto Trim)。

    參數意義：
    -----------
    img : numpy.ndarray
        輸入之 BGR 影像。
    padding : int, 預設 15
        裁切後在墨水邊界四周保留的白色安全留白像素 (像素單位)。
    white_threshold : int, 預設 245
        判定為白色背景的灰階臨界值 (灰階度 > 245 視為背景白頁)。

    傳回值：
    --------
    numpy.ndarray
        裁切白邊後的新影像。
    """
    if img is None:
        return img
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 尋找所有小於 white_threshold 的非白色墨水點 (公式主體、文字)
    non_white_y, non_white_x = np.where(gray < white_threshold)
    
    if len(non_white_y) == 0 or len(non_white_x) == 0:
        return img
    
    h, w = img.shape[:2]
    
    y_min, y_max = np.min(non_white_y), np.max(non_white_y)
    x_min, x_max = np.min(non_white_x), np.max(non_white_x)
    
    # 加入 Padding 留白 (15px)，防止切邊過度緊貼符號
    y_min = max(0, y_min - padding)
    y_max = min(h, y_max + padding + 1)
    x_min = max(0, x_min - padding)
    x_max = min(w, x_max + padding + 1)
    
    cropped = img[y_min:y_max, x_min:x_max]
    return cropped


def process_formula_images(input_dir, output_dir, zip_path=None, use_gpu=True):
    """
    批次執行公式圖片的 EasyOCR 塗白清理與白邊自動裁切。

    工作流程：
    1. 若輸入資料夾不存在且提供 ZIP 路徑，自動解壓輸入檔。
    2. 使用 EasyOCR 偵測每張圖片中的文字與坐標。
    3. 塗白左側無括號的正文引導詞，保護同行含有括號條件句的字塊。
    4. 執行 auto_trim 重新裁剪白邊。
    5. 儲存清理後圖檔至 output_dir。

    參數意義：
    -----------
    input_dir : str
        包含第一階段輸出截圖的資料夾路徑。
    output_dir : str
        後處理清理完成圖檔的輸出目標資料夾。
    zip_path : str 或 None, 預設 None
        備援 ZIP 檔案路徑。若 input_dir 不存在，自動從此 zip 檔解壓。
    use_gpu : bool, 預設 True
        是否使用 PyTorch GPU 加速 EasyOCR 推論。
    """
    import easyocr

    # 檢查並解壓縮 ZIP 檔 (若解壓目錄不存在時的自動保護機制)
    if not os.path.exists(input_dir) and zip_path and os.path.exists(zip_path):
        print(f"正在解壓縮 {zip_path} 至 {input_dir}...")
        os.makedirs(input_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(os.path.dirname(input_dir))
        print("解壓縮完成！")

    if not os.path.exists(input_dir):
        print(f"錯誤：找不到輸入目錄 {input_dir}")
        return

    os.makedirs(output_dir, exist_ok=True)

    image_paths = sorted(glob(os.path.join(input_dir, "*.png")))
    if not image_paths:
        image_paths = sorted(glob(os.path.join(input_dir, "**", "*.png"), recursive=True))

    total_images = len(image_paths)
    print(f"找到 {total_images} 張公式圖片。初始化 EasyOCR (簡體/繁體中文/英文)...")

    # 嘗試載入 EasyOCR Reader (自動處理 GPU 不可用時回退至 CPU)
    try:
        reader = easyocr.Reader(['ch_sim', 'en'], gpu=use_gpu)
    except Exception as e:
        print(f"GPU 初始化失敗 ({e})，改用 CPU 執行 OCR...")
        reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)

    print("開始執行精準圖片清理與自動裁切...\n")

    erased_count = 0

    for img_path in tqdm(image_paths, desc="清理公式圖片", unit="張"):
        filename = os.path.basename(img_path)
        out_path = os.path.join(output_dir, filename)

        img = load_image_unicode(img_path)
        if img is None:
            continue

        h, w, c = img.shape
        img_cleaned = img.copy()
        has_erased = False

        # 執行 EasyOCR 全圖文字辨識
        ocr_results = reader.readtext(img)

        # 第一階段掃描：紀錄全圖所有帶括號區塊的 Y 軸高度範圍 (擴大保護同行與鄰近的條件說明文字)
        bracket_y_ranges = []
        for bbox, text, prob in ocr_results:
            if has_brackets(text):
                pts = np.array(bbox, dtype=np.int32)
                y_min_b = np.min(pts[:, 1])
                y_max_b = np.max(pts[:, 1])
                bracket_y_ranges.append((y_min_b - 5, y_max_b + 5))

        # 第二階段掃描：進行塗白條件過濾與矩形填充
        for bbox, text, prob in ocr_results:
            pts = np.array(bbox, dtype=np.int32)
            y_min = np.min(pts[:, 1])
            y_max = np.max(pts[:, 1])

            # 檢查是否屬於最左側需抹除的正文詞
            if is_left_text_to_erase(bbox, text, img_width=w):
                # 安全保護機制：若該文字塊與任何帶括號的條件說明處於相同 Y 軸高度，且稍微離開極左邊緣 (X > 10%)，加強保護不抹除
                is_near_bracket_line = any(
                    by1 <= (y_min + y_max)/2 <= by2 for by1, by2 in bracket_y_ranges
                )
                if is_near_bracket_line and (np.min(pts[:, 0]) > w * 0.10):
                    continue

                # 計算塗白矩形並微幅外擴 3px 確保乾淨抹除
                x_min = max(0, int(np.min(pts[:, 0])) - 3)
                y_min_pad = max(0, int(np.min(pts[:, 1])) - 3)
                x_max = min(w, int(np.max(pts[:, 0])) + 3)
                y_max_pad = min(h, int(np.max(pts[:, 1])) + 3)

                # 填滿純白矩形 (RGB: 255, 255, 255)
                cv2.rectangle(img_cleaned, (x_min, y_min_pad), (x_max, y_max_pad), (255, 255, 255), -1)
                has_erased = True

        if has_erased:
            erased_count += 1

        # 自動裁切白邊 (Auto Trim, Padding = 15px)
        final_img = auto_trim(img_cleaned, padding=15, white_threshold=245)

        # 儲存清理後結果檔
        save_image_unicode(out_path, final_img)

    print("\n" + "="*50)
    print(" 批次優化清理完成！")
    print(f" 總處理圖片張數 : {total_images}")
    print(f" 清理左側正文圖片 : {erased_count} 張")
    print(f" 輸出資料夾路徑   : {output_dir}")
    print("="*50)


if __name__ == "__main__":
    # ✅ 所有路徑由 config.PATHS 動態計算，改名/移動專案後自動跟隨
    # ✅ use_gpu 由 .env 的 USE_GPU 控制，不寫死
    PATHS.cleaned_dir.mkdir(parents=True, exist_ok=True)

    process_formula_images(
        input_dir=str(PATHS.formula_dir),
        output_dir=str(PATHS.cleaned_dir),
        zip_path=str(PATHS.zip_mfd),
        use_gpu=CFG.use_gpu
    )


