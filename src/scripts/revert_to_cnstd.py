import re

with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update _init_mfd_worker
old_init = """def _init_mfd_worker():
    global _onnx_session, _onnx_input_name
    if _onnx_session is None:
        try:
            import onnxruntime as ort
            from config import PATHS
            model_path = str(PATHS.root / 'config' / 'formula_yolov8.onnx')
            if os.path.exists(model_path):
                options = ort.SessionOptions()
                options.intra_op_num_threads = 1
                _onnx_session = ort.InferenceSession(model_path, sess_options=options, providers=['CPUExecutionProvider'])
                _onnx_input_name = _onnx_session.get_inputs()[0].name
            else:
                _onnx_session = 'MOCK'
        except ImportError:
            pass"""

new_init = """_mfd_analyzer = None

def _init_mfd_worker(use_gpu=False):
    global _mfd_analyzer
    if _mfd_analyzer is None:
        try:
            from cnstd.yolov7.layout_analyzer import LayoutAnalyzer
            import torch
            device = 'cuda' if use_gpu and torch.cuda.is_available() else 'cpu'
            _mfd_analyzer = LayoutAnalyzer('mfd', device=device)
        except ImportError:
            _mfd_analyzer = 'MOCK'
"""
content = content.replace(old_init, new_init)

# 2. Update num_workers and Pool init
old_pool = """            num_workers = multiprocessing.cpu_count()
            log_fn(f"[SYS] 啟動 Multiprocessing Pool (Workers: {num_workers}) 進行平行公式萃取...")
            
            import json
            log_file_path = os.path.join(self.formula_dir, "formulas_ai_log.jsonl")
            # Clear log file initially
            with open(log_file_path, "w", encoding="utf-8") as f: pass

            with Pool(processes=num_workers, initializer=_init_mfd_worker) as pool:"""

new_pool = """            import torch
            use_gpu = CFG.use_gpu and torch.cuda.is_available()
            # If using GPU, limit workers to 2 to prevent OOM. Otherwise use CPU count.
            num_workers = min(2, multiprocessing.cpu_count()) if use_gpu else multiprocessing.cpu_count()
            log_fn(f"[SYS] 啟動 Multiprocessing Pool (Workers: {num_workers}, GPU: {use_gpu}) 進行平行公式萃取...")
            
            import json
            log_file_path = os.path.join(self.formula_dir, "formulas_ai_log.jsonl")
            # Clear log file initially
            with open(log_file_path, "w", encoding="utf-8") as f: pass

            with Pool(processes=num_workers, initializer=_init_mfd_worker, initargs=(use_gpu,)) as pool:"""
content = content.replace(old_pool, new_pool)

# 3. Replace the inference block
start_marker = "                # ---------------------------------------------------------\n                # ONNX Inference (YOLOv8) - Slicing / Sliding Window"
end_marker = "            else:\n                detections = _mock_detect(img)"

start_idx = content.find(start_marker)
end_idx = content.find(end_marker, start_idx)

if start_idx == -1 or end_idx == -1:
    print("Could not find inference block markers.")
else:
    new_inference = """                # ---------------------------------------------------------
                # cnstd LayoutAnalyzer Inference (Official MFD)
                # ---------------------------------------------------------
                if _mfd_analyzer != 'MOCK':
                    # cnstd LayoutAnalyzer expects BGR image (OpenCV default) or RGB.
                    # It handles resizing, slicing, and NMS internally and robustly!
                    out = _mfd_analyzer(img)
                    
                    for res in out:
                        # res is dict: {'type': 'isolated'|'embedding', 'box': array(4x2), 'score': float}
                        b_type = res['type']
                        score = res['score']
                        box_arr = res['box']
                        
                        # Apply minimal thresholding just to be safe, cnstd already filters mostly
                        if score > 0.15:
                            # Map 'embedding' to 'inline' to match our downstream logic
                            mapped_type = 'inline' if b_type == 'embedding' else 'isolated'
                            detections.append({'type': mapped_type, 'score': score, 'box': box_arr})
"""
    content = content[:start_idx] + new_inference + content[end_idx:]
    with open('src/core_agent.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Successfully replaced ONNX logic with cnstd LayoutAnalyzer!")

