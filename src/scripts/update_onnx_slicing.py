import re

with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Define the old block that starts from `img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)`
# and ends before `else:` which maps to `_mock_detect`
start_marker = "                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)"
end_marker = "            else:"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker, start_idx)

if start_idx == -1 or end_idx == -1:
    print("Could not find the target block!")
    exit(1)

new_block = """                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                h_orig, w_orig = img_rgb.shape[:2]
                
                target_size = 640
                
                # ==== 切片掃描 (Sliding Window) 解決小公式丟失問題 ====
                n_slices = 3
                overlap = 0.15
                slice_h = int(h_orig / (n_slices - (n_slices - 1) * overlap))
                step = int(slice_h * (1 - overlap))
                slices = []
                for i in range(n_slices):
                    y0 = i * step
                    y1 = min(h_orig, y0 + slice_h)
                    if i == n_slices - 1:
                        y1 = h_orig
                        y0 = max(0, h_orig - slice_h)
                    slices.append((0, y0, w_orig, y1))
                    
                boxes, scores = [], []
                
                for (sx0, sy0, sx1, sy1) in slices:
                    slice_img = img_rgb[sy0:sy1, sx0:sx1]
                    sh, sw = slice_img.shape[:2]
                    
                    scale = min(target_size / sw, target_size / sh)
                    new_w, new_h = int(sw * scale), int(sh * scale)
                    resized = cv2.resize(slice_img, (new_w, new_h))
                    
                    dw = (target_size - new_w) / 2
                    dh = (target_size - new_h) / 2
                    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
                    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
                    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
                    
                    blob = padded.transpose((2, 0, 1))[np.newaxis, ...].astype(np.float32) / 255.0
                    
                    outputs = _onnx_session.run(None, {_onnx_input_name: blob})
                    out = outputs[0][0].transpose()
                    
                    for row in out:
                        classes_scores = row[4:]
                        class_id = np.argmax(classes_scores)
                        score = classes_scores[class_id]
                        if score > 0.20 and class_id in [0, 1, 2, 3]:
                            xc, yc, bw, bh = row[:4]
                            # 計算在切片中的座標
                            bx1 = (xc - bw/2 - left) / scale
                            by1 = (yc - bh/2 - top) / scale
                            bx2 = (xc + bw/2 - left) / scale
                            by2 = (yc + bh/2 - top) / scale
                            
                            # 轉換回整頁的全局座標
                            gx1, gy1 = bx1 + sx0, by1 + sy0
                            gx2, gy2 = bx2 + sx0, by2 + sy0
                            
                            boxes.append([gx1, gy1, gx2 - gx1, gy2 - gy1, class_id])
                            scores.append(float(score))
                            
                if len(boxes) > 0:
                    box_coords = [b[:4] for b in boxes]
                    indices = cv2.dnn.NMSBoxes(box_coords, scores, score_threshold=0.20, nms_threshold=0.45)
                    if len(indices) > 0:
                        for i in np.array(indices).flatten():
                            x, y, bw, bh, cid = boxes[i]
                            box_arr = np.array([[x, y], [x+bw, y], [x+bw, y+bh], [x, y+bh]])
                            b_type = 'isolated' if cid in [1, 2, 3] else 'inline'
                            detections.append({'type': b_type, 'score': scores[i], 'box': box_arr})
"""
content = content[:start_idx] + new_block + content[end_idx:]

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Successfully replaced inference block with Sliding Window implementation!")
