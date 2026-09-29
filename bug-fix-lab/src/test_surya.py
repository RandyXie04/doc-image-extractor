import os
import fitz
from PIL import Image
from surya.ocr import run_ocr
from surya.model.detection.model import load_model as load_det_model, load_processor as load_det_processor
from surya.model.recognition.model import load_model as load_rec_model
from surya.model.recognition.processor import load_processor as load_rec_processor

# Monkey-patch SuryaOCRConfig for Python 3.13 / transformers compatibility
import surya.model.recognition.config
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

def test_surya_on_pdfs():
    print("Loading models...")
    det_processor, det_model = load_det_processor(), load_det_model()
    rec_model, rec_processor = load_rec_model(), load_rec_processor()
    
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "01_input"))
    pdf_files = ["text01.pdf"]
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(data_dir, pdf_file)
        if not os.path.exists(pdf_path):
            print(f"File not found: {pdf_path}")
            continue
            
        print(f"\nProcessing ENTIRE {pdf_file} via Python API...")
        try:
            images = get_all_pdf_images(pdf_path)
            print(f"Extracted {len(images)} pages.")
            
            # Note: langs must be a list of lists, one for each image
            predictions = run_ocr(
                images,
                langs=[["zh"]] * len(images),
                det_model=det_model,
                det_processor=det_processor,
                rec_model=rec_model,
                rec_processor=rec_processor
            )
            
            total_lines = sum(len(pred.text_lines) for pred in predictions if pred.text_lines)
            print(f"Result for {pdf_file}: Found {total_lines} lines across {len(images)} pages.")
            
            if total_lines > 0:
                first_pred = predictions[0]
                if first_pred.text_lines:
                    print("Snippet from page 1:")
                    for i, line in enumerate(first_pred.text_lines[:3]):
                        print(f"  [{line.confidence:.2f}] {line.text}")
                    
        except Exception as e:
            print(f"Error processing {pdf_file}: {type(e).__name__} - {e}")

if __name__ == "__main__":
    test_surya_on_pdfs()
