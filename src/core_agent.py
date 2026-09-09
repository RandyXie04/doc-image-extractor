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


import warnings
warnings.filterwarnings("ignore", message=".*The `fitz` API is deprecated.*")
import pymupdf as fitz  # PyMuPDF
import cv2
import numpy as np
from tqdm import tqdm

# 全域修補 (Monkey Patch) 解決 PyMuPDF 遇到 CMYK/非RGB 圖片時寫入 PNG 崩潰的重大瑕疵 (code=4: pixmap must be grayscale or rgb to write as png)
_orig_pixmap_tobytes = fitz.Pixmap.tobytes
_orig_pixmap_save = fitz.Pixmap.save

def _safe_pixmap_tobytes(self, output="png", *args, **kwargs):
    if str(output).lower() == "png":
        if self.colorspace and self.colorspace.name not in (fitz.csGRAY.name, fitz.csRGB.name):
            try:
                return fitz.Pixmap(fitz.csRGB, self).tobytes(output, *args, **kwargs)
            except Exception:
                pass
        elif self.n >= 5 or (self.alpha and self.n not in (2, 4)):
            try:
                return fitz.Pixmap(fitz.csRGB, self).tobytes(output, *args, **kwargs)
            except Exception:
                pass
    return _orig_pixmap_tobytes(self, output, *args, **kwargs)

def _safe_pixmap_save(self, filename, output=None, *args, **kwargs):
    fmt = output or os.path.splitext(filename)[1].lstrip('.').lower() or "png"
    if fmt == "png":
        if self.colorspace and self.colorspace.name not in (fitz.csGRAY.name, fitz.csRGB.name):
            try:
                return fitz.Pixmap(fitz.csRGB, self).save(filename, output=output, *args, **kwargs)
            except Exception:
                pass
        elif self.n >= 5 or (self.alpha and self.n not in (2, 4)):
            try:
                return fitz.Pixmap(fitz.csRGB, self).save(filename, output=output, *args, **kwargs)
            except Exception:
                pass
    return _orig_pixmap_save(self, filename, output=output, *args, **kwargs)

fitz.Pixmap.tobytes = _safe_pixmap_tobytes
fitz.Pixmap.save = _safe_pixmap_save

# pdf2docx 延遲/防呆載入
try:
    from pdf2docx import Converter
    HAS_PDF2DOCX = True
except ImportError:
    HAS_PDF2DOCX = False




# =========================================================================
# ONNX Runtime Worker for Formula Extraction (YOLOv8 CPU Inference)
# =========================================================================
# Global for multiprocessing worker
_onnx_session = None
_onnx_input_name = None

def _init_mfd_worker(use_gpu=False):
    global _onnx_session, _onnx_input_name
    if _onnx_session is None:
        try:
            import onnxruntime as ort
            from config import PATHS
            import os
            
            model_path = str(PATHS.root / "config" / "yolo_v8_ft.onnx")
            if os.path.exists(model_path):
                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                from src.scripts.hardware_probe import get_best_providers
                _onnx_session = ort.InferenceSession(model_path, sess_options=options, providers=get_best_providers())
                _onnx_input_name = _onnx_session.get_inputs()[0].name
            else:
                _onnx_session = "MOCK"
        except Exception:
            _onnx_session = "MOCK"

def _mock_detect(img):
    # 用於在尚未準備好模型時，測試 Multiprocessing 流程不會崩潰
    return []

def _process_single_page(args):
    import traceback
    if len(args) >= 6:
        page_idx, input_pdf, formula_dir, dpi, max_safe_width, extract_inline = args[:6]
    else:
        page_idx, input_pdf, formula_dir, dpi, max_safe_width = args[:5]
        extract_inline = False
        
    global _onnx_session, _onnx_input_name
    if _onnx_session is None:
        _init_mfd_worker()
    
    import pymupdf as fitz, cv2, numpy as np, os, re
    generated_files = []
    page_bboxes = []
    
    try:
        doc = fitz.open(input_pdf)
    except Exception as e:
        return {"status": "error", "files": [], "error": f"無法開啟 PDF: {str(e)}", "bboxes": []}
        
    try:
        page = doc[page_idx]
        rect = page.rect
        current_dpi = dpi
        expected_width = (rect.width * current_dpi) / 72.0
        
        if expected_width > max_safe_width:
            current_dpi = int(max_safe_width * 72.0 / rect.width)
            
        scale_factor = current_dpi / 72.0
        pix = page.get_pixmap(dpi=current_dpi)
        img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        
        if pix.n == 4:
            img = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
        else:
            img = img_data.copy()

        h, w = img.shape[:2]
        
        # ---------------------------------------------------------
        # ONNX Inference (YOLOv8 example)
        # ---------------------------------------------------------
        detections = []
        try:
            if _onnx_session != "MOCK":
                try:
                    from src.scripts import yolo_onnx_utils
                except ImportError:
                    try:
                        from scripts import yolo_onnx_utils
                    except ImportError:
                        import yolo_onnx_utils
                
                # Preprocess (Dynamic Input Resolution Support)
                inp_shape = _onnx_session.get_inputs()[0].shape
                model_h = inp_shape[2] if isinstance(inp_shape[2], int) else 1888
                model_w = inp_shape[3] if isinstance(inp_shape[3], int) else 1888
                img_padded, ratio, (dw, dh) = yolo_onnx_utils.letterbox(img, new_shape=(model_h, model_w))
                input_tensor = cv2.cvtColor(img_padded, cv2.COLOR_BGR2RGB)
                input_tensor = np.transpose(input_tensor, (2, 0, 1)).astype(np.float32)
                input_tensor /= 255.0
                input_tensor = np.expand_dims(input_tensor, axis=0)
                
                # Inference
                outputs = _onnx_session.run(None, {_onnx_input_name: input_tensor})
                
                # Postprocess
                results = yolo_onnx_utils.postprocess(outputs, conf_threshold=0.15, iou_threshold=0.45)
                
                for res in results:
                    b_type = 'inline' if res["class_id"] == 0 else 'isolated'
                    score = res["score"]
                    x1, y1, x2, y2 = res["box"]
                    x1 = np.clip((x1 - dw) / ratio, 0, w)
                    x2 = np.clip((x2 - dw) / ratio, 0, w)
                    y1 = np.clip((y1 - dh) / ratio, 0, h)
                    y2 = np.clip((y2 - dh) / ratio, 0, h)
                    
                    detections.append({
                        'type': b_type,
                        'score': float(score),
                        'box': np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
                    })
            else:
                detections = _mock_detect(img)
        except Exception as e:
            return {"status": "error", "files": generated_files, "error": str(e), "bboxes": []}

        if not detections:
            return {"status": "success", "files": generated_files, "log_data": {"page": page_idx + 1, "detections": []}, "bboxes": []}

        log_data = {
            "page": page_idx + 1,
            "detections": [{"type": d['type'], "score": float(d['score']), "box": [int(x) for x in d['box'].flatten()]} for d in detections],
            "display_boxes": [],
            "merged_boxes": [],
            "final_crops": []
        }

        # ---------------------------------------------------------
        # 精準後處理：依據 extract_inline 與 智慧延伸編號篩選
        # ---------------------------------------------------------
        final_boxes = []
        for item in detections:
            b_type = item.get('type', 'isolated')
            score = item.get('score', 0.0)
            box = item.get('box', None)
            if box is None or len(box) == 0: continue

            x0, y0 = int(round(np.min(box[:, 0]))), int(round(np.min(box[:, 1])))
            x1, y1 = int(round(np.max(box[:, 0]))), int(round(np.max(box[:, 1])))
            box_w, box_h = x1 - x0, y1 - y0

            if y0 < h * 0.03 or y1 > h * 0.97: continue # 邊緣雜訊
            if box_h < 15 or box_w < 25: continue       # 太小雜點

            # 依據 extract_inline 設定決定篩選條件
            if extract_inline:
                keep = (b_type == 'isolated' and score >= 0.20) or (b_type == 'inline' and box_w > w * 0.15 and box_h > 15 and score >= 0.20)
            else:
                keep = (b_type == 'isolated' and score >= 0.20)

            if keep:
                final_boxes.append([x0, y0, x1, y1])

        # 微小重疊合併（避免同一公式被切開）
        final_boxes.sort(key=lambda b: b[1])
        merged_boxes = []
        if final_boxes:
            curr = final_boxes[0]
            for i in range(1, len(final_boxes)):
                nxt = final_boxes[i]
                if (nxt[1] <= curr[3] + 5) and (max(curr[0], nxt[0]) < min(curr[2], nxt[2])):
                    curr[0] = min(curr[0], nxt[0])
                    curr[1] = min(curr[1], nxt[1])
                    curr[2] = max(curr[2], nxt[2])
                    curr[3] = max(curr[3], nxt[3])
                else:
                    merged_boxes.append(curr)
                    curr = nxt
            merged_boxes.append(curr)

        log_data["display_boxes"] = [list(b) for b in final_boxes]
        log_data["merged_boxes"] = [list(b) for b in merged_boxes]

        chinese_reviews = []
        pad_x, pad_y = 15, 10
        eq_idx = 1
        page_num = page_idx + 1

        for (x0, y0, x1, y1) in merged_boxes:
            orig_x1 = x1
            roi_y0_pdf = max(0, y0 - 10) / scale_factor
            roi_y1_pdf = min(h, y1 + 10) / scale_factor
            trailing_rect = fitz.Rect(x1 / scale_factor, roi_y0_pdf, page.rect.width, roi_y1_pdf)
            trailing_text = page.get_text("text", clip=trailing_rect).strip().replace('\n', ' ')

            is_figure_caption = bool(re.search(r'[\u56fe\u5716\u8868]\s*\d+', trailing_text))
            has_eq_tag = bool(re.search(r'[(（]\s*\d+([-.–]\d+)*\s*[)）]', trailing_text))
            chinese_matches = re.findall(r'[\u4e00-\u9fff]', trailing_text)

            filename = f"p{page_num:03d}_eq{eq_idx:02d}.png"

            if not is_figure_caption and trailing_text:
                words = page.get_text("words", clip=trailing_rect)
                if words:
                    # Check if Chinese explanation or equation tag exists on the right
                    if len(chinese_matches) > 0:
                        max_word_x1 = max([w[2] for w in words]) * scale_factor
                        if max_word_x1 > x1:
                            x1 = max(x1, int(max_word_x1 + 10))
                        chinese_reviews.append({
                            "page": page_num,
                            "filename": filename,
                            "trailing_text": trailing_text,
                            "chinese_chars": "".join(chinese_matches),
                            "orig_box": [x0, y0, orig_x1, y1],
                            "extended_box": [x0, y0, x1, y1]
                        })
                    elif has_eq_tag:
                        max_word_x1 = max([w[2] for w in words]) * scale_factor
                        if max_word_x1 > x1:
                            x1 = max(x1, int(max_word_x1 + 10))

            # Ensure valid bounds
            crop_x0, crop_y0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
            crop_x1, crop_y1 = min(w, x1 + pad_x), min(h, y1 + pad_y)
            crop = img[crop_y0:crop_y1, crop_x0:crop_x1]
            if crop.shape[0] < 20 or crop.shape[1] < 30: continue

            filepath = os.path.join(formula_dir, filename)
            ext = os.path.splitext(filepath)[1]
            result, img_encode = cv2.imencode(ext, crop)
            if result:
                img_encode.tofile(filepath)
            generated_files.append(filepath)

            page_bboxes.append({
                "page_idx": page_idx,
                "rect_pdf": [crop_x0 / scale_factor, crop_y0 / scale_factor, crop_x1 / scale_factor, crop_y1 / scale_factor],
                "image_path": filepath
            })

            log_data["final_crops"].append({"filename": filename, "crop_coords": [crop_x0, crop_y0, crop_x1, crop_y1]})
            eq_idx += 1

    except Exception as e:
        return {"status": "error", "files": generated_files, "error": str(e), "bboxes": [], "chinese_reviews": []}
    finally:
        doc.close()
        
    return {
        "status": "success",
        "files": generated_files,
        "log_data": log_data,
        "bboxes": page_bboxes,
        "chinese_reviews": chinese_reviews
    }

class PDFConversionAgent:
    """
    PDF 轉換與公式萃取代理核心類別
    """
    def __init__(self, input_pdf: str, output_docx: str = None,
                 preview_dir: str = None,
                 formula_dir: str = None,
                 header_ratio: float = None,
                 footer_ratio: float = None,
                 left_ratio: float = None,
                 right_ratio: float = None,
                 extract_inline: bool = None,
                 embed_formulas_in_word: bool = None):
        if not input_pdf.lower().endswith('.pdf'):
            raise ValueError(f"輸入檔案必須是 PDF 格式，但收到了：'{input_pdf}'")
            
        self.input_pdf = input_pdf
        if output_docx:
            self.output_docx = output_docx
        else:
            base_name = os.path.splitext(os.path.basename(input_pdf))[0]
            self.output_docx = str(PATHS.data_dir / "02_intermediate" / f"{base_name}_已轉檔.docx")

        # ✅ 所有目錄預設由 PATHS 提供，不再使用裸字串相對路徑
        self.preview_dir = preview_dir if preview_dir else str(PATHS.preview_dir)
        self.formula_dir = formula_dir if formula_dir else str(PATHS.formula_dir_v2)

        # ✅ 臨時 PDF 錨定至專案根目錄，不再污染 CWD
        self.temp_cropped_pdf = str(PATHS.root / "temp_cropped_optimized.pdf")

        # ✅ 探測比例預設由 CFG 提供（可由 .env 覆寫）
        self.header_ratio = header_ratio if header_ratio is not None else CFG.header_ratio
        self.footer_ratio = footer_ratio if footer_ratio is not None else CFG.footer_ratio
        self.left_ratio = left_ratio if left_ratio is not None else CFG.left_ratio
        self.right_ratio = right_ratio if right_ratio is not None else CFG.right_ratio
        self.extract_inline = extract_inline if extract_inline is not None else CFG.extract_inline
        self.embed_formulas_in_word = embed_formulas_in_word if embed_formulas_in_word is not None else CFG.embed_formulas_in_word

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
            "left_threshold": rect.width * self.left_ratio,
            "right_threshold": rect.width * (1.0 - self.right_ratio),
            "sample_pages": [0, 1, -1]
        }

    def _detect_page_boundaries(self, page: fitz.Page, plan: dict):
        """傳入單一頁面，分析該頁文字區塊，回傳動態計算的專屬裁切邊界 (上下左右)。"""
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
        final_left = plan.get("left_threshold", 0.0)
        final_right = plan.get("right_threshold", rect.width)

        return final_top, final_bottom, final_left, final_right, header_text, footer_text

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
                final_top, final_bottom, final_left, final_right, header_text, footer_text = self._detect_page_boundaries(page, plan)

                crop_rect = fitz.Rect(final_left, final_top, final_right, final_bottom)
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

    def convert_to_word(self, start_page_idx: int = 0, end_page_idx: int = None, bboxes_by_page: dict = None, log_fn=print, progress_callback=None) -> bool:
        """
        [任務一核心] 執行 PDF 動態邊界裁切並轉換為 Word (.docx)
        支援 PDF 預先換圖法 (Redaction & Image Insertion) 消除破碎文字
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
            total_pages = len(doc)
            end_page_idx = min(end_page_idx, total_pages - 1) if end_page_idx is not None else total_pages - 1
            
            # Guardrail 1: Limit max pages
            total_to_process = end_page_idx - start_page_idx + 1
            if total_to_process > CFG.max_safe_pages:
                log_fn(f"[WARNING] Word 轉檔請求頁數 ({total_to_process}) 超過上限 ({CFG.max_safe_pages})，已截斷！")
                end_page_idx = start_page_idx + CFG.max_safe_pages - 1
                
            for page_idx in range(start_page_idx, end_page_idx + 1):
                page = doc[page_idx]
                rect = page.rect
                apply_top, apply_bottom, apply_left, apply_right, _, _ = self._detect_page_boundaries(page, plan)
                page.set_cropbox(fitz.Rect(apply_left, apply_top, apply_right, apply_bottom))

            # 若啟用將公式圖片嵌入 Word：透過 Redaction 抹除破碎文字並貼入高清圖片
            if self.embed_formulas_in_word and bboxes_by_page:
                log_fn(">>> [Word 公式合成] 正在執行 PDF 預先換圖 (Redaction & Image Insertion)...")
                embedded_count = 0
                for page_idx in range(start_page_idx, end_page_idx + 1):
                    page = doc[page_idx]
                    page_items = bboxes_by_page.get(page_idx, [])
                    for item in page_items:
                        r = fitz.Rect(item["rect_pdf"])
                        page.add_redact_annot(r, fill=False)
                    if page_items:
                        page.apply_redactions()
                        for item in page_items:
                            r = fitz.Rect(item["rect_pdf"])
                            img_p = item["image_path"]
                            if os.path.exists(img_p):
                                page.insert_image(r, filename=img_p)
                                embedded_count += 1
                log_fn(f">>> [Word 公式合成] 已成功將 {embedded_count} 個公式替換為高清圖！")

            # Only save the specific pages if we're not doing the whole book
            if start_page_idx > 0 or end_page_idx < total_pages - 1:
                doc.select(list(range(start_page_idx, end_page_idx + 1)))
                
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

    def extract_formulas(self, dpi: int = 300, start_page_idx: int = 0, end_page_idx: int = None, log_fn=print, progress_callback=None) -> dict:
        """
        [任務二核心] 使用 YOLOv8 MFD 模型從原始 PDF 中偵測並擷取獨立公式截圖。
        回傳包含 files, zip_path, bboxes_by_page 的成果字典。
        """
        os.makedirs(self.formula_dir, exist_ok=True)
        if not os.path.exists(self.input_pdf):
            log_fn(f"[ERROR] 找不到 PDF 檔案 '{self.input_pdf}'")
            return {"status": "error", "files": [], "zip_path": None, "bboxes_by_page": {}}

        log_fn("\n" + "=" * 60)

        doc = fitz.open(self.input_pdf)
        bboxes_by_page = {}
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
            log_fn(f"[CFG] 包含行內公式：{'是' if self.extract_inline else '否 (僅獨立塊狀公式)'}")
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
                
            from multiprocessing import Pool
            import multiprocessing
            
            # Prepare arguments
            tasks = [(p_idx, self.input_pdf, self.formula_dir, dpi, CFG.max_image_width, self.extract_inline) for p_idx in range(start_page_idx, end_page_idx + 1)]
            
            import torch
            use_gpu = CFG.use_gpu and torch.cuda.is_available()
            # For GPU, 2-4 workers give max throughput without VRAM contention on 6GB VRAM.
            # For CPU, 4-8 workers avoid overwhelming RAM.
            num_workers = min(3, multiprocessing.cpu_count()) if use_gpu else min(8, multiprocessing.cpu_count())
            device_str = f"GPU: {torch.cuda.get_device_name(0)}" if use_gpu else "CPU"
            log_fn(f"[SYS] 啟動 Multiprocessing Pool (Workers: {num_workers}, 運算裝置: {device_str}) 進行平行公式萃取...")

            import json
            log_file_path = os.path.join(self.formula_dir, "formulas_ai_log.jsonl")
            # Clear log file initially
            with open(log_file_path, "w", encoding="utf-8") as f: pass

            all_chinese_reviews = []
            with Pool(processes=num_workers, initializer=_init_mfd_worker, initargs=(use_gpu,)) as pool:
                for idx_offset, res in enumerate(pool.imap(_process_single_page, tasks)):
                    current_p = start_page_idx + idx_offset + 1
                    if progress_callback:
                        progress_callback(idx_offset + 1, total_to_process, f"提取公式 (P{current_p})")
                        
                    if res.get("status") == "error":
                        log_fn(f"[ERROR] 第 {current_p} 頁處理發生例外：{res.get('error')}")
                        skipped_pages += 1
                        continue
                        
                    log_data = res.get("log_data")
                    if log_data:
                        with open(log_file_path, "a", encoding="utf-8") as lf:
                            lf.write(json.dumps(log_data, ensure_ascii=False) + "\n")

                    if res.get("chinese_reviews"):
                        all_chinese_reviews.extend(res["chinese_reviews"])

                    result_files = res.get("files", [])
                    if result_files:
                        generated_files.extend(result_files)
                        count += len(result_files)
                        log_fn(f"  [P{current_p:03d}] AI 找到 {len(result_files)} 個獨立公式區塊")
                    else:
                        skipped_pages += 1

                    for b in res.get("bboxes", []):
                        p_i = b["page_idx"]
                        if p_i not in bboxes_by_page:
                            bboxes_by_page[p_i] = []
                        bboxes_by_page[p_i].append(b)
        finally:
            doc.close()

        import datetime
        review_txt_path = os.path.join(self.formula_dir, "formula_right_boundary_chinese_review.txt")
        time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(review_txt_path, "w", encoding="utf-8") as rf:
            rf.write("=" * 80 + "\n")
            rf.write("公式右界中文說明判定覆核清單 (Formula Right-Boundary Chinese Review)\n")
            rf.write(f"生成時間: {time_str}\n")
            rf.write(f"來源文件: {os.path.basename(self.input_pdf)}\n")
            rf.write("說明:\n")
            rf.write("  以下獨立公式在水平右側檢測到中文文字/條件註記（例如「(s_3 為正值時)」、「式中：」、「單位：米」等）。\n")
            rf.write("  系統已【預設包入】截圖中以確保語意完整。請人工比對確認是否需要保留於截圖，或應作為獨立正文段落。\n")
            rf.write("=" * 80 + "\n\n")

            if all_chinese_reviews:
                for idx_r, item in enumerate(all_chinese_reviews, 1):
                    rf.write(f"[項目 {idx_r}]\n")
                    rf.write(f"  - 頁碼: 第 {item['page']} 頁 (P{item['page']:03d})\n")
                    rf.write(f"  - 檔案名稱: {item['filename']}\n")
                    rf.write(f"  - 右側延伸文字: {item['trailing_text']}\n")
                    rf.write(f"  - 包含中文字元: {item['chinese_chars']}\n")
                    rf.write(f"  - 原始公式框 (X, Y): [{item['orig_box'][0]}, {item['orig_box'][1]} -> {item['orig_box'][2]}, {item['orig_box'][3]}]\n")
                    rf.write(f"  - 延伸包含框 (X, Y): [{item['extended_box'][0]}, {item['extended_box'][1]} -> {item['extended_box'][2]}, {item['extended_box'][3]}]\n")
                    rf.write("  - 狀態標註: [已預設包入截圖，待人工覆核]\n\n")
                rf.write("-" * 80 + "\n")
                rf.write(f"總計待覆核項目: {len(all_chinese_reviews)} 筆\n")
            else:
                rf.write("未檢測到公式右界包含中文說明之特殊案例，所有公式編號均為純數字符號標籤。\n")
            rf.write("=" * 80 + "\n")

        if all_chinese_reviews:
            log_fn(f"[REVIEW] ⚠️ 檢測到 {len(all_chinese_reviews)} 處公式右界包含中文說明！已預設包入截圖，覆核清單儲存於：\n    {review_txt_path}")

        import zipfile
        zip_filename = os.path.join(self.formula_dir, "all_pdf_formulas_ai_mfd.zip")
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for f in generated_files:
                zipf.write(f, os.path.basename(f))
            if os.path.exists(log_file_path):
                zipf.write(log_file_path, os.path.basename(log_file_path))
            if os.path.exists(review_txt_path):
                zipf.write(review_txt_path, os.path.basename(review_txt_path))

        log_fn("=" * 60)
        log_fn(f"[DONE] 公式提取完成！共使用 AI MFD 成功裁切 {count} 張公式圖片。")
        log_fn(f"[ZIP]  已打包儲存於：{zip_filename}")
        log_fn("=" * 60)

        return {
            "status": "success",
            "files": generated_files,
            "zip_path": zip_filename,
            "bboxes_by_page": bboxes_by_page
        }

    def execute_pipeline(self, convert_word: bool = True, extract_formulas: bool = True, formula_dpi: int = 300, start_page_idx: int = 0, end_page_idx: int = None, log_fn=print, progress_callback=None) -> dict:
        """
        端到端執行流程：支援優先提取公式後進行 Word 公式高清替換，並分流產出。
        """
        bboxes_by_page = {}
        formula_result = None

        # 若需要提取公式，或需要轉 Word 且啟用了公式圖片替換，則先執行公式偵測與擷取
        if extract_formulas or (convert_word and self.embed_formulas_in_word):
            formula_result = self.extract_formulas(
                dpi=formula_dpi,
                start_page_idx=start_page_idx,
                end_page_idx=end_page_idx,
                log_fn=log_fn,
                progress_callback=progress_callback
            )
            if formula_result and "bboxes_by_page" in formula_result:
                bboxes_by_page = formula_result["bboxes_by_page"]

        word_success = False
        if convert_word:
            word_success = self.convert_to_word(
                start_page_idx=start_page_idx,
                end_page_idx=end_page_idx,
                bboxes_by_page=bboxes_by_page,
                log_fn=log_fn,
                progress_callback=progress_callback
            )

        # ── 統整輸出包裝與分流 ──
        log_fn("\n>>> 正在統整輸出產物...")
        import shutil
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(os.path.basename(self.input_pdf))[0]
        delivery_folder = PATHS.root / "data" / "03_output" / f"{base_name}_{timestamp}"
        
        delivery_word_path = None
        delivery_zip_path = None
        has_moved = False
        
        try:
            os.makedirs(delivery_folder, exist_ok=True)
            
            # 複製 Word 檔
            if convert_word and os.path.exists(self.output_docx):
                dest_word = delivery_folder / os.path.basename(self.output_docx)
                shutil.copy(self.output_docx, dest_word)
                delivery_word_path = str(dest_word)
                has_moved = True
                
            # 複製公式 ZIP 檔
            zip_filename = os.path.join(self.formula_dir, "all_pdf_formulas_ai_mfd.zip")
            if extract_formulas and os.path.exists(zip_filename):
                dest_zip = delivery_folder / f"{base_name}_formulas.zip"
                shutil.copy(zip_filename, dest_zip)
                delivery_zip_path = str(dest_zip)
                has_moved = True

            # 複製公式右界中文覆核清單
            review_txt = os.path.join(self.formula_dir, "formula_right_boundary_chinese_review.txt")
            if os.path.exists(review_txt):
                shutil.copy(review_txt, delivery_folder / "formula_right_boundary_chinese_review.txt")
                has_moved = True
                
            if has_moved:
                log_fn(f"[SUCCESS] 📦 任務成果已保存至：\n    {delivery_folder}")
        except Exception as e:
            log_fn(f"[WARNING] 打包輸出檔案時發生錯誤：{e}")

        return {
            "delivery_folder": str(delivery_folder) if has_moved else None,
            "word_path": delivery_word_path,
            "zip_path": delivery_zip_path
        }
# =========================================================================
# Tkinter 全功能視覺化工作站 (GUI 介面)
# =========================================================================
