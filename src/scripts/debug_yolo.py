import onnxruntime as ort
import cv2
import numpy as np
import sys
import pymupdf as fitz
from pathlib import Path

def debug_detect(pdf_path, page_num):
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    pix = page.get_pixmap(dpi=150)
    img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
    if pix.n == 4: img = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
    elif pix.n == 3: img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
    else: img = img_data.copy()
    
    model_path = "config/formula_yolov8.onnx"
    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    
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
    
    outputs = session.run(None, {"images": blob})
    out = outputs[0][0].transpose()
    
    boxes, scores, class_ids = [], [], []
    for row in out:
        classes_scores = row[4:]
        class_id = np.argmax(classes_scores)
        score = classes_scores[class_id]
        if score > 0.1:  # Very low threshold for debugging
            xc, yc, bw, bh = row[:4]
            x1 = (xc - bw/2 - left) / scale
            y1 = (yc - bh/2 - top) / scale
            x2 = (xc + bw/2 - left) / scale
            y2 = (yc + bh/2 - top) / scale
            boxes.append([x1, y1, x2 - x1, y2 - y1])
            scores.append(float(score))
            class_ids.append(class_id)
            
    indices = cv2.dnn.NMSBoxes(boxes, scores, score_threshold=0.1, nms_threshold=0.45)
    
    for i in indices.flatten():
        x, y, bw, bh = boxes[i]
        cid = class_ids[i]
        score = scores[i]
        
        color = (0, 255, 0)
        if cid == 0: color = (255, 0, 0) # Inline
        if cid in [1, 3]: color = (0, 0, 255) # Display
        if cid == 2: color = (0, 255, 255) # Number
        if cid == 4: color = (255, 255, 0) # Table
        if cid == 5: color = (255, 0, 255) # Figure
        
        cv2.rectangle(img, (int(x), int(y)), (int(x+bw), int(y+bh)), color, 2)
        label = f"C:{cid} S:{score:.2f}"
        cv2.putText(img, label, (int(x), int(y)-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        
    cv2.imwrite("debug_yolo_output.jpg", img)
    print("Debug image saved to debug_yolo_output.jpg")
    
if __name__ == "__main__":
    import glob
    pdfs = glob.glob("data/01_input/*.pdf")
    if pdfs:
        debug_detect(pdfs[0], 0)
