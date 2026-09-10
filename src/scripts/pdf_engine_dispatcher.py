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

def extract_with_pymupdf(pdf_path, output_dir, style_mapping, left_ratio=0.0, right_ratio=1.0):
    """
    Fast extraction using PyMuPDF for vector PDFs with margin filtering.
    """
    doc = fitz.open(pdf_path)
    md_content = []
    
    total_pages = len(doc)
    
    for page_num in range(total_pages):
        progress = int(((page_num + 1) / total_pages) * 85)
        print(json.dumps({"progress": progress, "message": f"[INFO] 正在解析第 {page_num+1}/{total_pages} 頁 (PyMuPDF 高速引擎)..."}))
        sys.stdout.flush()
        
        page = doc[page_num]
        p_width = page.rect.width
        min_x = p_width * left_ratio
        max_x = p_width * right_ratio
        
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if b['type'] == 0:  # text block
                # Bounding box filter: (x0, y0, x1, y1)
                bbox = b.get("bbox", (0, 0, 0, 0))
                if bbox[2] < min_x or bbox[0] > max_x:
                    continue
                
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
    
    print(json.dumps({"progress": 90, "message": "[INFO] PyMuPDF 向量文字提取完成，產出 Markdown 檔案。"}))
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
    
    print(json.dumps({"progress": 5, "message": "[INFO] 正在分析文件類型與文字密度..."}))
    sys.stdout.flush()
    
    if engine_choice == "auto":
        if is_vector_pdf(args.file):
            print(json.dumps({"progress": 10, "message": "[INFO] 自動辨識為原生向量 PDF，切換至 PyMuPDF 高速引擎。"}))
            engine_choice = "pymupdf"
        else:
            print(json.dumps({"progress": 10, "message": "[INFO] 自動辨識為掃描檔/圖片型 PDF，切換至 RapidDoc 深度 OCR 引擎。"}))
            engine_choice = "rapiddoc"
    sys.stdout.flush()

    if engine_choice == "pymupdf":
        extract_with_pymupdf(args.file, args.output_dir, args.style_mapping, args.left_ratio, args.right_ratio)
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        process_ocr_path = os.path.join(script_dir, "process_ocr.py")
        
        cmd = [
            sys.executable, process_ocr_path, 
            "--file", args.file, 
            "--output_dir", args.output_dir, 
            "--style_mapping", args.style_mapping
        ]
        
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            line = line.strip()
            if line:
                if line.startswith("{") and "progress" in line:
                    print(line)
                else:
                    progress_val = 50
                    if "[INFO]" in line:
                        print(json.dumps({"progress": progress_val, "message": line}))
                    else:
                        print(json.dumps({"progress": progress_val, "message": line}))
                sys.stdout.flush()
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"RapidDoc execution failed with code {proc.returncode}")

if __name__ == "__main__":
    main()
