import re

with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Define the new post-processing block
start_marker = "        # 原本的後處理與邊界合併邏輯"
end_marker = "    except Exception as e:\n        return {\"status\": \"error\", \"files\": generated_files, \"error\": str(e)}"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker, start_idx)

if start_idx == -1 or end_idx == -1:
    print("Could not find markers")
    exit(1)

new_logic = """        # ---------------------------------------------------------
        # 精準後處理：無腦合併取消，套用中文字途白 (White-out) 邏輯
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
            if box_h < 15 or box_w < 25: continue # 太小

            # 只保留獨立公式 (isolated) 或 夠大的行內公式
            if (b_type == 'isolated' and score >= 0.20) or (b_type == 'inline' and box_w > w * 0.15 and box_h > 15 and score >= 0.20):
                final_boxes.append([x0, y0, x1, y1])

        # 這裡不進行暴力的垂直合併，因為 YOLOv8 已經非常精準
        # 僅進行微小的重疊合併（如果兩個框幾乎重疊或上下緊貼）
        final_boxes.sort(key=lambda b: b[1])
        merged_boxes = []
        if final_boxes:
            curr = final_boxes[0]
            for i in range(1, len(final_boxes)):
                nxt = final_boxes[i]
                # 如果 Y 軸重疊且 X 軸也重疊，或者上下距離極近 (<5px) 且 X 軸有交集
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

        pad_x, pad_y = 15, 10
        eq_idx = 1
        page_num = page_idx + 1

        for (x0, y0, x1, y1) in merged_boxes:
            # 公式編號擴展：如果右側有 (2.5) 之類的編號，我們把它包進來
            roi_y0_pdf = max(0, y0 - 10) / scale_factor
            roi_y1_pdf = min(h, y1 + 10) / scale_factor
            right_rect = fitz.Rect(max(x1 / scale_factor, page.rect.width * 0.6), roi_y0_pdf, page.rect.width, roi_y1_pdf)
            right_text = page.get_text("text", clip=right_rect).strip().replace('\\n', '')
            
            is_figure_caption = bool(re.search(r'(图|圖|表)\\s*\\d+', right_text))
            has_eq_tag = bool(re.search(r'[(（]\\s*\\d+([-.–]\\d+)*\\s*[)）]', right_text))

            if has_eq_tag and not is_figure_caption:
                words = page.get_text("words", clip=right_rect)
                if words:
                    max_word_x1 = max([w[2] for w in words]) * scale_factor
                    if max_word_x1 > x1:
                        x1 = max(x1, int(max_word_x1 + 10))

            # 確保邊界正確
            crop_x0, crop_y0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
            crop_x1, crop_y1 = min(w, x1 + pad_x), min(h, y1 + pad_y)
            crop = img[crop_y0:crop_y1, crop_x0:crop_x1]
            if crop.shape[0] < 20 or crop.shape[1] < 30: continue

            # ==== 途白邏輯 (White-out Chinese Characters) ====
            # 在 crop 區域內尋找中文字的 bounding boxes，並塗白
            crop_rect_pdf = fitz.Rect(crop_x0 / scale_factor, crop_y0 / scale_factor, crop_x1 / scale_factor, crop_y1 / scale_factor)
            words = page.get_text("words", clip=crop_rect_pdf)
            for word in words:
                text = word[4]
                # 如果包含中文字
                if re.search(r'[一-鿿]', text):
                    wx0, wy0, wx1, wy1 = word[:4]
                    # 轉換回圖片座標 (相對 crop_x0, crop_y0)
                    px0 = max(0, int(wx0 * scale_factor) - crop_x0)
                    py0 = max(0, int(wy0 * scale_factor) - crop_y0)
                    px1 = min(crop.shape[1], int(wx1 * scale_factor) - crop_x0)
                    py1 = min(crop.shape[0], int(wy1 * scale_factor) - crop_y0)
                    # 途白
                    cv2.rectangle(crop, (px0, py0), (px1, py1), (255, 255, 255), -1)
            # ===============================================

            filename = f"p{page_num:03d}_eq{eq_idx:02d}.png"
            filepath = os.path.join(formula_dir, filename)
            ext = os.path.splitext(filepath)[1]
            result, img_encode = cv2.imencode(ext, crop)
            if result:
                img_encode.tofile(filepath)
            generated_files.append(filepath)
            log_data["final_crops"].append({"filename": filename, "crop_coords": [crop_x0, crop_y0, crop_x1, crop_y1]})
            eq_idx += 1\n\n"""

content = content[:start_idx] + new_logic + content[end_idx:]

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Post-processing replaced successfully!")
