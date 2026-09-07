import re

with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# We will extract the inner logic of extract_formulas into a standalone function
worker_code = '''
# =========================================================================
# Multiprocessing Worker for Formula Extraction
# =========================================================================
_worker_mfd = None

def _init_mfd_worker():
    global _worker_mfd
    if _worker_mfd is None:
        from pix2text import MathFormulaDetector
        _worker_mfd = MathFormulaDetector()

def _process_single_page(args):
    page_idx, input_pdf, formula_dir, dpi, max_safe_width = args
    global _worker_mfd
    if _worker_mfd is None:
        _init_mfd_worker()
    
    import fitz, cv2, numpy as np, os, re
    mfd = _worker_mfd
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
        try:
            detections = mfd.detect(img)
        except Exception:
            return generated_files

        if not detections:
            return generated_files

        display_boxes = []
        for item in detections:
            b_type = item.get('type', '')
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

class_idx = content.find('class PDFConversionAgent:')
content = content[:class_idx] + worker_code + '\n' + content[class_idx:]

old_loop_pattern = r'for idx_offset, page_idx in enumerate\(range\(start_page_idx, end_page_idx \+ 1\)\):.*?if eq_idx > 1:\s*log_fn\(f"  \[P\{page_num:03d\}\] AI 找到 \{eq_idx - 1\} 個獨立公式區塊"\)'
new_loop_code = '''
            from multiprocessing import Pool
            import multiprocessing
            
            # Prepare arguments
            tasks = [(p_idx, self.input_pdf, self.formula_dir, dpi, CFG.max_image_width) for p_idx in range(start_page_idx, end_page_idx + 1)]
            
            num_workers = min(multiprocessing.cpu_count(), 4)
            log_fn(f"[SYS] 啟動 Multiprocessing Pool (Workers: {num_workers}) 進行平行公式萃取...")
            
            with Pool(processes=num_workers, initializer=_init_mfd_worker) as pool:
                for idx_offset, result_files in enumerate(pool.imap(_process_single_page, tasks)):
                    if progress_callback:
                        progress_callback(idx_offset + 1, total_to_process, f"提取公式 (P{start_page_idx + idx_offset + 1})")
                    if result_files:
                        generated_files.extend(result_files)
                        count += len(result_files)
                        log_fn(f"  [P{start_page_idx + idx_offset + 1:03d}] AI 找到 {len(result_files)} 個獨立公式區塊")
                    else:
                        skipped_pages += 1
'''

content = re.sub(old_loop_pattern, new_loop_code.strip(), content, flags=re.DOTALL)

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Refactored core_agent.py')
