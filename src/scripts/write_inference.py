import re

with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the ONNX Inference block
old_block = '''        # ---------------------------------------------------------
        # ONNX Inference (YOLOv8 example)
        # ---------------------------------------------------------
        detections = []
        try:
            if _onnx_session != "MOCK":
                # 這裡放置純 NumPy 的 YOLOv8 前處理 (Letterbox, Normalize, HWC->CHW)
                # input_tensor = preprocess(img)
                # outputs = _onnx_session.run(None, {_onnx_input_name: input_tensor})
                # detections = postprocess(outputs) # NMS, Scale coords back
                pass
            else:
                detections = _mock_detect(img)
        except Exception as e:
            return {"status": "error", "files": generated_files, "error": str(e)}'''

new_block = '''        # ---------------------------------------------------------
        # ONNX Inference (YOLOv8)
        # ---------------------------------------------------------
        detections = []
        try:
            if _onnx_session != "MOCK":
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                h_orig, w_orig = img_rgb.shape[:2]
                
                target_size = 640
                scale = min(target_size / w_orig, target_size / h_orig)
                new_w, new_h = int(w_orig * scale), int(h_orig * scale)
                resized = cv2.resize(img_rgb, (new_w, new_h))
                
                dw = (target_size - new_w) / 2
                dh = (target_size - new_h) / 2
                top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
                left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
                padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
                
                blob = padded.transpose((2, 0, 1))[np.newaxis, ...].astype(np.float32) / 255.0
                
                outputs = _onnx_session.run(None, {_onnx_input_name: blob})
                out = outputs[0][0]
                out = out.transpose()
                
                boxes = []
                scores = []
                for row in out:
                    classes_scores = row[4:]
                    class_id = np.argmax(classes_scores)
                    score = classes_scores[class_id]
                    if score > 0.45:
                        xc, yc, bw, bh = row[:4]
                        x1 = (xc - bw/2 - left) / scale
                        y1 = (yc - bh/2 - top) / scale
                        x2 = (xc + bw/2 - left) / scale
                        y2 = (yc + bh/2 - top) / scale
                        boxes.append([x1, y1, x2 - x1, y2 - y1])
                        scores.append(float(score))
                        
                if len(boxes) > 0:
                    indices = cv2.dnn.NMSBoxes(boxes, scores, score_threshold=0.45, nms_threshold=0.45)
                    if len(indices) > 0:
                        for i in indices.flatten():
                            x, y, bw, bh = boxes[i]
                            box_arr = np.array([[x, y], [x+bw, y], [x+bw, y+bh], [x, y+bh]])
                            detections.append({'type': 'isolated', 'score': scores[i], 'box': box_arr})
            else:
                detections = _mock_detect(img)
        except Exception as e:
            return {"status": "error", "files": generated_files, "error": str(e)}'''

if old_block in content:
    content = content.replace(old_block, new_block)
else:
    print("Could not find the exact old_block. Regex fallback...")
    # Just to be safe if indentation differs slightly
    content = re.sub(
        r'# ---------------------------------------------------------\n\s*# ONNX Inference.*?(?=if not detections:)',
        new_block + '\n\n        ',
        content,
        flags=re.DOTALL
    )

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Updated ONNX inference block.')
