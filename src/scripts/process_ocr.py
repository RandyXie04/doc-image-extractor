import os
import sys
import json
import argparse
from PIL import Image

# Apply batch size limits for GPU OOM prevention (ADR-006)
os.environ["RECOGNITION_BATCH_SIZE"] = "2"
os.environ["DETECTOR_BATCH_SIZE"] = "2"

def main(args):
    print(json.dumps({"progress": 15, "message": "[INFO] 正在載入 Surya OCR 模型..."}))
    sys.stdout.flush()
    
    import fitz
    from surya.ocr import run_ocr
    from surya.model.detection.model import load_model as load_det_model, load_processor as load_det_processor
    from surya.model.recognition.model import load_model as load_rec_model
    from surya.model.recognition.processor import load_processor as load_rec_processor
    import surya.model.recognition.config

    # Monkey-patch SuryaOCRConfig for Python 3.13 / transformers compatibility
    _original_init = surya.model.recognition.config.SuryaOCRConfig.__init__
    def _patched_init(self, **kwargs):
        if "encoder" not in kwargs:
            kwargs["encoder"] = {}
        _original_init(self, **kwargs)
    surya.model.recognition.config.SuryaOCRConfig.__init__ = _patched_init

    det_processor, det_model = load_det_processor(), load_det_model()
    rec_model, rec_processor = load_rec_model(), load_rec_processor()
    
    print(json.dumps({"progress": 30, "message": "[INFO] 模型載入完成，正在轉換 PDF 為圖片..."}))
    sys.stdout.flush()
    
    doc = fitz.open(args.file)
    images = []
    total_pages = len(doc)
    for page_num in range(total_pages):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    doc.close()
    
    print(json.dumps({"progress": 50, "message": f"[INFO] 開始對 {total_pages} 頁圖片進行深度 OCR 辨識..."}))
    sys.stdout.flush()
    
    predictions = run_ocr(
        images,
        langs=[["zh"]] * len(images),
        det_model=det_model,
        det_processor=det_processor,
        rec_model=rec_model,
        rec_processor=rec_processor
    )
    
    print(json.dumps({"progress": 85, "message": "[INFO] OCR 辨識完成，正在重組文字排版..."}))
    sys.stdout.flush()
    
    full_text = ""
    for pred in predictions:
        if pred.text_lines:
            full_text += "\n".join([line.text for line in pred.text_lines]) + "\n\n"
            
    # For Auto compatibility, check if output_stem is provided
    output_stem = getattr(args, "output_stem", None)
    if not output_stem:
        output_stem = os.path.splitext(os.path.basename(args.file))[0]
        
    os.makedirs(args.output_dir, exist_ok=True)
    out_md_path = os.path.join(args.output_dir, f"{output_stem}.md")
    
    with open(out_md_path, "w", encoding="utf-8") as f:
        f.write(full_text)
        
    print(json.dumps({"progress": 90, "message": "[INFO] 文字提取完成，正在儲存文件..."}))
    sys.stdout.flush()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--style_mapping", default="{}")
    parser.add_argument("--output_stem", default=None)
    args = parser.parse_args()
    main(args)
