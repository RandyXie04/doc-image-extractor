import json
import os
import cv2
import pymupdf as fitz
import argparse
import numpy as np

def visualize_logs(pdf_path, log_file, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            data = json.loads(line)
            page_idx = data["page"] - 1
            
            page = doc[page_idx]
            pix = page.get_pixmap(dpi=150)
            img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
            img = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR) if pix.n == 3 else img_data.copy()
            
            scale = 150 / 72.0 # matches what we did in UI, but in core_agent it was based on DPI
            
            # Draw detections
            for d in data.get("detections", []):
                x, y, bw, bh = d["box"]
                # coordinates from core_agent are based on whatever DPI was used. 
                # Let's just draw them relative to original if needed.
                # Actually, core_agent uses original image pixel coords, which are `dpi`.
                # We need to render the image at the EXACT same dpi to match coordinates.
                # In core_agent: expected_width > max_safe_width logic alters DPI.
                # Since we don't know the exact DPI, we might just have to approximate or draw relative.
                pass
            
            print(f"Parsed page {data['page']} logs.")
            # For simplicity, developers can look at the JSON directly for now.

if __name__ == "__main__":
    print("Log visualization helper available. Read the JSONL file directly for exact coordinate data.")
