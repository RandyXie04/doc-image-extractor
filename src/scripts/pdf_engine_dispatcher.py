import sys
import argparse
import os
import json
import subprocess
from pathlib import Path
import fitz

# Anchor project root to sys.path
root_dir = Path(__file__).parent.parent.parent.absolute()
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

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

def extract_with_pymupdf(pdf_path, output_dir, style_mapping, output_stem=None):
    """
    High-precision extraction using book_layout_extractor:
    - Header & footer removal
    - Footnotes extraction and dual-way anchor matching
    - Heading style detection (H1, H2, H3)
    - Paragraph line-wrap reflow
    """
    from src.scripts.book_layout_extractor import process_book_vector_pdf
    
    def on_progress(percent, msg):
        print(json.dumps({"progress": percent, "message": msg}))
        sys.stdout.flush()
        
    out_md_path, audit_data = process_book_vector_pdf(
        pdf_path=pdf_path,
        output_dir=output_dir,
        output_stem=output_stem,
        style_mapping=style_mapping,
        progress_callback=on_progress
    )
    
    # Save structured audit tracking file
    audit_txt_path = os.path.join(output_dir, f"{output_stem or 'conversion'}_audit.json")
    with open(audit_txt_path, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, ensure_ascii=False, indent=2)
        
    print(json.dumps({"progress": 90, "message": f"[INFO] 版面分析與文字結構化完成，已消除頁眉頁碼並匹配 {audit_data['footnotes_matched'] + audit_data['footnotes_fallback']} 條腳注。"}))
    sys.stdout.flush()
    return out_md_path, audit_data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, required=True, help="Specific PDF file to process")
    parser.add_argument("--output_dir", type=str, default="data/03_output", help="Output directory")
    parser.add_argument("--output_stem", type=str, default=None, help="Stem name for output files")
    parser.add_argument("--style_mapping", type=str, default="{}", help="JSON string for heading style mapping")
    parser.add_argument("--engine", type=str, default="auto", choices=["auto", "pymupdf", "rapiddoc"], help="Forced engine choice")
    parser.add_argument("--header_ratio", type=float, default=0.1)
    parser.add_argument("--footer_ratio", type=float, default=0.1)
    parser.add_argument("--left_ratio", type=float, default=0.0)
    parser.add_argument("--right_ratio", type=float, default=0.0)
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
        extract_with_pymupdf(args.file, args.output_dir, args.style_mapping, output_stem=args.output_stem)
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
        
        # If output_stem is specified and RapidDoc produced a file based on args.file basename, rename if needed
        if args.output_stem:
            raw_base = os.path.basename(args.file).rsplit(".", 1)[0]
            raw_out = os.path.join(args.output_dir, f"{raw_base}.md")
            target_out = os.path.join(args.output_dir, f"{args.output_stem}.md")
            if os.path.exists(raw_out) and raw_out != target_out:
                import shutil
                shutil.move(raw_out, target_out)

        if proc.returncode != 0:
            raise RuntimeError(f"RapidDoc execution failed with code {proc.returncode}")

if __name__ == "__main__":
    main()
