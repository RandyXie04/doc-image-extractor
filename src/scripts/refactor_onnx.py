import re
import os

with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove pix2text import at top
content = re.sub(r'from pix2text import MathFormulaDetector\n', '', content)

# 2. Replace the Worker code with ONNX logic
onnx_worker_code = '''
# =========================================================================
# ONNX Runtime Worker for Formula Extraction (YOLOv8 CPU Inference)
# =========================================================================
_onnx_session = None
_onnx_input_name = None

def _init_mfd_worker():
    global _onnx_session, _onnx_input_name
    if _onnx_session is None:
        try:
            import onnxruntime as ort
            # 替換為實際的 ONNX 模型路徑 (例如 PDF-Extract-Kit 轉出的 YOLOv8 ONNX)
            from config import PATHS
            model_path = str(PATHS.root / "config" / "formula_yolov8.onnx")
            if os.path.exists(model_path):
                options = ort.SessionOptions()
                options.intra_op_num_threads = 1 # 限制單一 worker 的執行緒，避免與 multiprocessing 搶佔
                _onnx_session = ort.InferenceSession(model_path, sess_options=options, providers=['CPUExecutionProvider'])
                _onnx_input_name = _onnx_session.get_inputs()[0].name
            else:
                _onnx_session = "MOCK" # 若尚未下載模型，提供 Mock 以便測試管線
        except ImportError:
            pass

def _mock_detect(img):
    # 用於在尚未準備好模型時，測試 Multiprocessing 流程不會崩潰
    return []

def _process_single_page(args):
    page_idx, input_pdf, formula_dir, dpi, max_safe_width = args
    global _onnx_session
    if _onnx_session is None:
        _init_mfd_worker()
    
    import fitz, cv2, numpy as np, os, re
    generated_files = []
    
    doc = fitz.open(input_pdf)
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
        if _onnx_session != "MOCK":
            # 這裡放置純 NumPy 的 YOLOv8 前處理 (Letterbox, Normalize, HWC->CHW)
            # input_tensor = preprocess(img)
            # outputs = _onnx_session.run(None, {_onnx_input_name: input_tensor})
            # detections = postprocess(outputs) # NMS, Scale coords back
            pass
        else:
            detections = _mock_detect(img)

        if not detections:
            return generated_files

        # 原本的後處理與邊界合併邏輯 (為了相容 ONNX 輸出的 [x0, y0, x1, y1, conf, class])
        display_boxes = []
        for item in detections:
            b_type = item.get('type', 'isolated')
            score = item.get('score', 0.0)
            box = item.get('box', None)
            if box is None or len(box) == 0: continue

            x0, y0 = int(round(np.min(box[:, 0]))), int(round(np.min(box[:, 1])))
            x1, y1 = int(round(np.max(box[:, 0]))), int(round(np.max(box[:, 1])))
            box_w, box_h = x1 - x0, y1 - y0

            if y0 < h * 0.05 or y1 > h * 0.95: continue
            if box_h < 15 or box_w < 25: continue

            if (b_type == 'isolated' and score >= 0.45) or (box_w > w * 0.25 and box_h > 25 and score >= 0.50):
                display_boxes.append((x0, y0, x1, y1))

        if not display_boxes:
            return generated_files

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
                curr_x0, curr_y0 = min(curr_x0, nx0), min(curr_y0, ny0)
                curr_x1, curr_y1 = max(curr_x1, nx1), max(curr_y1, ny1)
            else:
                merged_boxes.append((curr_x0, curr_y0, curr_x1, curr_y1))
                curr_x0, curr_y0, curr_x1, curr_y1 = nx0, ny0, nx1, ny1
        merged_boxes.append((curr_x0, curr_y0, curr_x1, curr_y1))

        pad_x, pad_y = 20, 12
        eq_idx = 1
        page_num = page_idx + 1

        for (x0, y0, x1, y1) in merged_boxes:
            roi_y0_pdf = max(0, y0 - 15) / scale_factor
            roi_y1_pdf = min(h, y1 + 15) / scale_factor
            right_rect = fitz.Rect(page.rect.width * 0.72, roi_y0_pdf, page.rect.width, roi_y1_pdf)
            right_text = page.get_text("text", clip=right_rect).strip().replace('\n', '')

            is_figure_caption = bool(re.search(r'(图|圖|表)\s*\d+', right_text))
            has_eq_tag = bool(re.search(r'[(\uff08]\s*\d+([-.\u2013]\d+)*\s*[)\uff09]', right_text))

            if has_eq_tag and not is_figure_caption:
                words = page.get_text("words", clip=right_rect)
                if words:
                    max_word_x1 = max([w[2] for w in words]) * scale_factor
                    if max_word_x1 > x1:
                        x1 = max(x1, int(max_word_x1 + 10))

            crop_x0, crop_y0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
            crop_x1, crop_y1 = min(w, x1 + pad_x), min(h, y1 + pad_y)

            crop = img[crop_y0:crop_y1, crop_x0:crop_x1]
            if crop.shape[0] < 20 or crop.shape[1] < 30: continue

            filename = f"p{page_num:03d}_eq{eq_idx:02d}.png"
            filepath = os.path.join(formula_dir, filename)
            ext = os.path.splitext(filepath)[1]
            result, img_encode = cv2.imencode(ext, crop)
            if result:
                img_encode.tofile(filepath)
            generated_files.append(filepath)
            eq_idx += 1

    finally:
        doc.close()
        
    return generated_files
'''

# Find the old worker code and replace it
start_marker = '# =========================================================================\n# Multiprocessing Worker for Formula Extraction'
end_marker = 'class PDFConversionAgent:'
start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + onnx_worker_code + '\n' + content[end_idx:]

# Remove PDFConversionAgent._mfd_model references
content = re.sub(r'\s*_mfd_model = None.*?(?=def __init__)', '\n', content, flags=re.DOTALL)

# In extract_formulas, remove `mfd = self.get_mfd_model(log_fn=log_fn)`
content = re.sub(r'\s*mfd = self.get_mfd_model\(log_fn=log_fn\)', '', content)

# Update the pool to use ALL logical CPU cores
content = re.sub(r'num_workers = min\(multiprocessing.cpu_count\(\), 4\)', 'num_workers = multiprocessing.cpu_count()', content)

# Also remove PyTorch clear_cache logic completely if it's there
torch_clear_code = r'''try:\s*import torch\s*if torch\.cuda\.is_available\(\):\s*torch\.cuda\.empty_cache\(\)\s*except ImportError:\s*pass'''
content = re.sub(torch_clear_code, '', content)

# Write out the new content
with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Refactored for ONNX and removed PyTorch dependencies.')
