with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_init = """def _init_mfd_worker(use_gpu=False):
    global _mfd_analyzer
    if _mfd_analyzer is None:
        try:
            from cnstd.yolov7.layout_analyzer import LayoutAnalyzer
            import torch
            device = 'cuda' if use_gpu and torch.cuda.is_available() else 'cpu'
            _mfd_analyzer = LayoutAnalyzer('mfd', device=device)
        except ImportError:
            _mfd_analyzer = "MOCK\""""

new_init = """def _init_mfd_worker(use_gpu=False):
    global _mfd_analyzer
    if _mfd_analyzer is None:
        try:
            from ultralytics import YOLO
            from config import PATHS
            import os
            
            model_path = str(PATHS.root / "config" / "yolo_v8_ft.pt")
            if os.path.exists(model_path):
                _mfd_analyzer = YOLO(model_path)
            else:
                _mfd_analyzer = "MOCK"
        except ImportError:
            _mfd_analyzer = "MOCK\""""

content = content.replace(old_init, new_init)

# The inference block using ultralytics YOLO
import re
start_marker = "                # cnstd LayoutAnalyzer Inference (Official MFD)"
end_marker = "            else:\n                detections = _mock_detect(img)"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker, start_idx)

new_inference = """                # ultralytics YOLO Inference (PDF-Extract-Kit)
                # ---------------------------------------------------------
                if _mfd_analyzer != 'MOCK':
                    import torch
                    from config import CFG
                    device = 'cuda' if CFG.use_gpu and torch.cuda.is_available() else 'cpu'
                    
                    results = _mfd_analyzer(img, imgsz=1280, conf=0.15, device=device, verbose=False)
                    for r in results:
                        for box in r.boxes:
                            cls = int(box.cls[0])
                            score = float(box.conf[0])
                            x1, y1, x2, y2 = box.xyxy[0].tolist()
                            
                            # 'embedding' -> inline, 'isolated' -> isolated
                            b_type = 'inline' if cls == 0 else 'isolated'
                            
                            # Add back to our detections format
                            detections.append({
                                'type': b_type,
                                'score': score,
                                'box': __import__('numpy').array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
                            })
"""

content = content[:start_idx] + new_inference + content[end_idx:]

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Replaced cnstd with ultralytics YOLO!")
