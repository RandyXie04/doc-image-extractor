import sys
import argparse
import os
import json
import subprocess
import fitz

def is_vector_pdf(pdf_path, text_threshold=100):
    """
    Check if a PDF is primarily vector/text-based by sampling the first few pages.
    """
    try:
        doc = fitz.open(pdf_path)
        total_text_length = 0
        pages_to_check = min(5, len(doc))
        if pages_to_check == 0:
            return False
            
        for i in range(pages_to_check):
            page = doc[i]
            text = page.get_text("text")
            total_text_length += len(text.strip())
            
        return (total_text_length / pages_to_check) > text_threshold
    except Exception as e:
        print(f"Error checking PDF type: {e}")
        return False

def extract_with_pymupdf(pdf_path, output_dir, style_mapping):
    """
    Fast extraction using PyMuPDF for vector PDFs.
    """
    doc = fitz.open(pdf_path)
    md_content = []
    
    total_pages = len(doc)
    
    for page_num in range(total_pages):
        # Emit progress
        progress = int((page_num / total_pages) * 100)
        print(json.dumps({"progress": progress, "message": f"[INFO] Processing page {page_num+1}/{total_pages} (PyMuPDF)..."}))
        sys.stdout.flush()
        
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if b['type'] == 0:  # text block
                block_text = ""
                for l in b["lines"]:
                    for s in l["spans"]:
                        text = s["text"].strip()
                        if text:
                            # Basic heuristic for title detection
                            if s["size"] > 14:
                                block_text += f"# {text}\n"
                            else:
                                block_text += f"{text} "
                if block_text.strip():
                    md_content.append(block_text.strip())
                    
    out_name = os.path.basename(pdf_path).rsplit(".", 1)[0] + ".md"
    out_path = os.path.join(output_dir, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(md_content))
    
    print(json.dumps({"progress": 100, "message": f"[INFO] PyMuPDF extraction complete."}))
    sys.stdout.flush()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, required=True, help="Specific PDF file to process")
    parser.add_argument("--output_dir", type=str, default="data/03_output", help="Output directory")
    parser.add_argument("--style_mapping", type=str, default="{}", help="JSON string for heading style mapping")
    parser.add_argument("--engine", type=str, default="auto", choices=["auto", "pymupdf", "rapiddoc"], help="Forced engine choice")
    parser.add_argument("--left_ratio", type=float, default=0.0)
    parser.add_argument("--right_ratio", type=float, default=1.0)
    args = parser.parse_args()

    engine_choice = args.engine
    
    print(json.dumps({"progress": 5, "message": "[INFO] Analyzing document format..."}))
    sys.stdout.flush()
    
    if engine_choice == "auto":
        if is_vector_pdf(args.file):
            print(json.dumps({"progress": 10, "message": "[INFO] Auto-detected Vector PDF. Using fast PyMuPDF extraction."}))
            engine_choice = "pymupdf"
        else:
            print(json.dumps({"progress": 10, "message": "[INFO] Auto-detected Scanned PDF. Using RapidDoc Deep OCR."}))
            engine_choice = "rapiddoc"
    sys.stdout.flush()

    if engine_choice == "pymupdf":
        extract_with_pymupdf(args.file, args.output_dir, args.style_mapping)
    else:
        # Fallback to RapidDoc deep OCR process
        # Need to spawn process_ocr.py
        # Wait, if we use subprocess, we can just pipe its stdout.
        # process_ocr.py already prints [INFO] stuff that can be caught.
        script_dir = os.path.dirname(os.path.abspath(__file__))
        process_ocr_path = os.path.join(script_dir, "process_ocr.py")
        
        cmd = [
            sys.executable, process_ocr_path, 
            "--file", args.file, 
            "--output_dir", args.output_dir, 
            "--style_mapping", args.style_mapping
        ]
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        for line in proc.stdout:
            # Wrap regular text output in JSON for SSE progress
            # if it's already JSON from somewhere, we might just pass it
            line = line.strip()
            if line:
                if line.startswith("{") and "progress" in line:
                    print(line)
                else:
                    # heuristic progress mapping
                    progress_val = 50
                    if "[INFO]" in line:
                        print(json.dumps({"progress": progress_val, "message": line}))
                    else:
                        print(json.dumps({"progress": progress_val, "message": line}))
                sys.stdout.flush()
        proc.wait()

if __name__ == "__main__":
    main()
