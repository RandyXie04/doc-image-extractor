import sys
import argparse
import os
import json
import subprocess
from pathlib import Path
import fitz

# Anchor project root to sys.path
try:
    from src.utils.path_helper import is_frozen
except ImportError:
    _fallback_root = Path(__file__).parent.parent.parent.resolve()
    if str(_fallback_root) not in sys.path:
        sys.path.insert(0, str(_fallback_root))
    from src.utils.path_helper import is_frozen

if not is_frozen():
    root_dir = Path(__file__).parent.parent.parent.resolve()
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
            text = getattr(page, "get_text")("text")
            total_text_length += len(text.strip())
            
        return (total_text_length / pages_to_check) > text_threshold
    except Exception as e:
        print(f"Error checking PDF type: {e}")
        return False

def extract_with_pymupdf(pdf_path, output_dir, style_mapping, output_stem=None, no_footnote=True, ai_kaiti=False, ai_kaiti_threshold=0.65):
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
        progress_callback=on_progress,
        enable_footnotes=not no_footnote,
        ai_kaiti=ai_kaiti,
        ai_kaiti_threshold=ai_kaiti_threshold
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
    parser.add_argument("--style_mapping_file", type=str, default=None, help="Path to JSON file for heading style mapping")
    parser.add_argument("--engine", type=str, default="auto", choices=["auto", "pymupdf", "suryaocr", "rapiddoc"], help="Forced engine choice")
    parser.add_argument("--header_ratio", type=float, default=0.1)
    parser.add_argument("--footer_ratio", type=float, default=0.1)
    parser.add_argument("--left_ratio", type=float, default=0.0)
    parser.add_argument("--right_ratio", type=float, default=0.0)
    parser.add_argument("--no_footnote", action="store_true", help="Disable footnote extraction and matching")
    parser.add_argument("--ai_kaiti", action="store_true", help="Enable Gemini Vision AI Kaiti detection")
    parser.add_argument("--ai_kaiti_threshold", type=float, default=0.65, help="Confidence threshold for AI Kaiti detection")
    args = parser.parse_args()

    if args.style_mapping_file and os.path.exists(args.style_mapping_file):
        try:
            with open(args.style_mapping_file, "r", encoding="utf-8") as smf:
                args.style_mapping = smf.read()
        except Exception as sm_err:
            print(f"[WARN] Failed to read style_mapping_file {args.style_mapping_file}: {sm_err}")

    engine_choice = "suryaocr" if args.engine == "rapiddoc" else args.engine
    
    print(json.dumps({"progress": 5, "message": "[INFO] 正在分析文件類型與文字密度..."}))
    sys.stdout.flush()
    
    if engine_choice == "auto":
        if is_vector_pdf(args.file):
            print(json.dumps({"progress": 10, "message": "[INFO] 自動辨識為原生向量 PDF，切換至 PyMuPDF 高速引擎。"}))
            engine_choice = "pymupdf"
        else:
            print(json.dumps({"progress": 10, "message": "[INFO] 自動辨識為掃描檔/圖片型 PDF，切換至 Surya OCR 深度 OCR 引擎。"}))
            engine_choice = "suryaocr"
    sys.stdout.flush()

    if engine_choice == "pymupdf":
        extract_with_pymupdf(
            args.file, args.output_dir, args.style_mapping,
            output_stem=args.output_stem, no_footnote=args.no_footnote,
            ai_kaiti=args.ai_kaiti, ai_kaiti_threshold=args.ai_kaiti_threshold
        )
    else:
        # v2.1 修正：避免使用 subprocess 啟動不存在於 _MEIPASS 的 process_ocr.py
        try:
            from src.scripts import process_ocr as _process_ocr; process_ocr = _process_ocr
            # 優先嘗試透過 module import 執行
            ocr_args = argparse.Namespace(
                file=args.file,
                output_dir=args.output_dir,
                output_stem=args.output_stem,
                style_mapping=args.style_mapping,
                style_mapping_file=args.style_mapping_file,
                no_footnote=args.no_footnote,
                image_dir=None
            )
            if hasattr(process_ocr, "main"):
                process_ocr.main(ocr_args)
            else:
                pass
        except ImportError as e:
            # 開發環境下，若仍需 subprocess，則作為 Fallback
            from src.utils.path_helper import is_frozen, get_project_dir
            if not is_frozen():
                process_ocr_path = str(get_project_dir() / "src" / "scripts" / "process_ocr.py")
                cmd = [
                    sys.executable, process_ocr_path, 
                    "--file", args.file, 
                    "--output_dir", args.output_dir, 
                    "--style_mapping", args.style_mapping
                ]
                if args.style_mapping_file:
                    cmd.extend(["--style_mapping_file", args.style_mapping_file])
                if args.output_stem:
                    cmd.extend(["--output_stem", args.output_stem])
                if args.no_footnote:
                    cmd.append("--no_footnote")
                import subprocess
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                for line in (proc.stdout or []):
                    line = line.strip()
                    if line:
                        if line.startswith("{") and "progress" in line:
                            print(line)
                        else:
                            progress_val = 50
                            print(json.dumps({"progress": progress_val, "message": line}))
                        sys.stdout.flush()
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError(f"process_ocr.py subprocess failed with exit code {proc.returncode}")
            else:
                raise RuntimeError("Frozen environment 中無法獨立啟動 process_ocr.py 子程序，請確認模組能被 import") from e
        
        # If output_stem is specified and Surya OCR produced a file based on args.file basename, rename if needed
        raw_base = os.path.basename(args.file).rsplit(".", 1)[0]
        raw_out = os.path.join(args.output_dir, f"{raw_base}.md")
        target_out = os.path.join(args.output_dir, f"{args.output_stem}.md") if args.output_stem else raw_out

        if args.output_stem and os.path.exists(raw_out) and raw_out != target_out:
            import shutil
            shutil.move(raw_out, target_out)

        proc = locals().get("proc"); process_ocr = locals().get("process_ocr")
        if proc is not None and proc.returncode != 0:
            raise RuntimeError(f"Surya OCR execution failed with code {proc.returncode}")
        elif 'proc' not in locals() and not hasattr(process_ocr, "main"):
            raise RuntimeError("process_ocr.py is missing or empty, cannot execute Surya OCR.")

        if not os.path.exists(target_out):
            raise RuntimeError(f"Surya OCR 執行未生成預期之輸出檔案: {target_out}")

if __name__ == "__main__":
    main()
