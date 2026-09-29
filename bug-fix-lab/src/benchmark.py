import os
# Set environment variables for 6GB VRAM limit BEFORE importing surya
os.environ["RECOGNITION_BATCH_SIZE"] = "2"
os.environ["DETECTOR_BATCH_SIZE"] = "2"

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import fitz
import time
from PIL import Image
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

def get_all_pdf_images(pdf_path):
    doc = fitz.open(pdf_path)
    images = []
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    doc.close()
    return images

def native_pdf_extraction(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text += page.get_text()
    doc.close()
    return text

def run_benchmark():
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "01_input"))
    pdf_path = os.path.join(data_dir, "text01.pdf")
    
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        return

    print("=== Channel 2: Native PDF Text Extraction ===")
    start_time = time.time()
    native_text = native_pdf_extraction(pdf_path)
    end_time = time.time()
    
    print(f"Time taken: {end_time - start_time:.2f} seconds")
    print(f"Extracted {len(native_text)} characters.")
    print("Preview:\n" + native_text[:200] + "...\n")

    print("=== Channel 1: Pure OCR (Surya) ===")
    print("Loading models...")
    det_processor, det_model = load_det_processor(), load_det_model()
    rec_model, rec_processor = load_rec_model(), load_rec_processor()
    
    start_time = time.time()
    images = get_all_pdf_images(pdf_path)
    print(f"Converted {len(images)} pages to images.")
    
    predictions = run_ocr(
        images,
        langs=[["zh"]] * len(images),
        det_model=det_model,
        det_processor=det_processor,
        rec_model=rec_model,
        rec_processor=rec_processor
    )
    
    total_lines = sum(len(pred.text_lines) for pred in predictions if pred.text_lines)
    end_time = time.time()
    print(f"Time taken: {end_time - start_time:.2f} seconds")
    print(f"Found {total_lines} lines.")
    if total_lines > 0 and predictions[0].text_lines:
        print("Preview:\n" + "\n".join([line.text for line in predictions[0].text_lines[:5]]) + "...\n")

if __name__ == "__main__":
    run_benchmark()
