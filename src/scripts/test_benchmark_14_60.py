import os
import sys
import time
import json
from pathlib import Path

# 錨定專案根目錄
ROOT = Path(__file__).parent.parent.absolute()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymupdf as fitz
from src.core_agent import PDFConversionAgent
from src.founder_tools.fix_founder_fonts import clean_founder_text
from config import PATHS

PDF_PATH = r"C:\Users\randy\Desktop\應用開發\公式書籍轉檔\database_text\101844-01 四足仿生机器人基本原理及开发教程 ZW.pdf"
START_PAGE = 14  # 1-based
END_PAGE = 60    # 1-based
START_IDX = START_PAGE - 1  # 13 (0-based)
END_IDX = END_PAGE - 1      # 59 (0-based)

import multiprocessing

def run_all_tests():
    report = {
        "pdf_name": Path(PDF_PATH).name,
        "page_range": f"{START_PAGE} - {END_PAGE} (共 {END_PAGE - START_PAGE + 1} 頁)",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tests": {}
    }

    print("=" * 60)
    print(f"🚀 開始全功能自動化測試流程")
    print(f"📄 測試檔案: {Path(PDF_PATH).name}")
    print(f"📑 測試範圍: 第 {START_PAGE} 頁 ~ 第 {END_PAGE} 頁 (共 {END_PAGE - START_PAGE + 1} 頁)")
    print("=" * 60)

# =========================================================================
# 測試 1: PDF 數學公式 AI 萃取 (純 ONNX YOLOv8) 與高清 Word 轉檔
# =========================================================================
print("\n[測試 1/3] 正在執行：PDF 數學公式 AI 萃取與動態裁切轉 Word...")
t0 = time.time()

test1_formula_dir = PATHS.root / "data" / "02_intermediate" / "test_14_60_formulas"
test1_docx_path = PATHS.root / "data" / "03_output" / "test_14_60_已轉檔.docx"
test1_formula_dir.mkdir(parents=True, exist_ok=True)

agent = PDFConversionAgent(
    input_pdf=PDF_PATH,
    output_docx=str(test1_docx_path),
    formula_dir=str(test1_formula_dir),
    header_ratio=0.08,
    footer_ratio=0.08,
    extract_inline=False,
    embed_formulas_in_word=True
)

logs = []
def log_collector(msg):
    logs.append(msg)
    if "進度" in msg or "完成" in msg or "公式" in msg:
        print(f"  [AI Agent] {msg}")

try:
    res = agent.execute_pipeline(
        convert_word=True,
        extract_formulas=True,
        formula_dpi=300,
        start_page_idx=START_IDX,
        end_page_idx=END_IDX,
        log_fn=log_collector
    )
    t1_duration = time.time() - t0
    
    # 統計產出的公式截圖
    formula_files = list(test1_formula_dir.glob("*.png"))
    docx_size_kb = os.path.getsize(res["word_path"]) / 1024 if res.get("word_path") and os.path.exists(res["word_path"]) else 0
    zip_size_kb = os.path.getsize(res["zip_path"]) / 1024 if res.get("zip_path") and os.path.exists(res["zip_path"]) else 0

    report["tests"]["feature_1_formula_extraction"] = {
        "status": "SUCCESS",
        "duration_seconds": round(t1_duration, 2),
        "total_formulas_found": len(formula_files),
        "docx_output": res.get("word_path"),
        "docx_size_kb": round(docx_size_kb, 2),
        "zip_output": res.get("zip_path"),
        "zip_size_kb": round(zip_size_kb, 2),
        "sample_formulas": [f.name for f in formula_files[:10]]
    }
    print(f"  ✅ 測試 1 成功！耗時 {t1_duration:.1f} 秒，共萃取 {len(formula_files)} 個獨立數學公式，Word 檔大小: {docx_size_kb:.1f} KB")
except Exception as e:
    report["tests"]["feature_1_formula_extraction"] = {
        "status": "FAILED",
        "error": str(e)
    }
    print(f"  ❌ 測試 1 失敗: {e}")

# =========================================================================
# 測試 2: 方正排版 (Founder Bookmaker) CMap 標點與字元修復
# =========================================================================
print("\n[測試 2/3] 正在執行：方正排版 CMap 標點與缺字編碼修復...")
t0 = time.time()

try:
    doc = fitz.open(PDF_PATH)
    raw_texts = []
    for p_idx in range(START_IDX, END_IDX + 1):
        raw_texts.append(doc[p_idx].get_text())
    doc.close()

    full_raw_text = "\n".join(raw_texts)
    cleaned_text = clean_founder_text(full_raw_text)
    t2_duration = time.time() - t0

    diff_chars = sum(1 for c1, c2 in zip(full_raw_text, cleaned_text) if c1 != c2)
    diff_chars += abs(len(full_raw_text) - len(cleaned_text))

    out_repaired_txt = PATHS.root / "data" / "03_output" / "test_14_60_founder_repaired.txt"
    with open(out_repaired_txt, "w", encoding="utf-8") as f:
        f.write(cleaned_text)

    report["tests"]["feature_2_founder_repair"] = {
        "status": "SUCCESS",
        "duration_seconds": round(t2_duration, 2),
        "total_characters_processed": len(full_raw_text),
        "repaired_characters_count": diff_chars,
        "output_txt": str(out_repaired_txt),
        "output_txt_size_kb": round(os.path.getsize(out_repaired_txt) / 1024, 2)
    }
    print(f"  ✅ 測試 2 成功！處理 {len(full_raw_text)} 字元，完成修復與標點對齊，儲存至: {out_repaired_txt.name}")
except Exception as e:
    report["tests"]["feature_2_founder_repair"] = {
        "status": "FAILED",
        "error": str(e)
    }
    print(f"  ❌ 測試 2 失敗: {e}")

# =========================================================================
# 測試 3: 文件原始內嵌圖片批次無損提取
# =========================================================================
print("\n[測試 3/3] 正在執行：文件內嵌原始高清圖片無損提取...")
t0 = time.time()

test3_img_dir = PATHS.root / "data" / "02_intermediate" / "test_14_60_extracted_images"
test3_img_dir.mkdir(parents=True, exist_ok=True)

try:
    doc = fitz.open(PDF_PATH)
    extracted_images = []
    
    for p_idx in range(START_IDX, END_IDX + 1):
        page = doc[p_idx]
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            
            img_filename = f"p{p_idx+1:03d}_img{img_idx+1:02d}.{image_ext}"
            img_save_path = test3_img_dir / img_filename
            with open(img_save_path, "wb") as f:
                f.write(image_bytes)
            extracted_images.append(img_save_path)
            
    doc.close()
    t3_duration = time.time() - t0

    report["tests"]["feature_3_embedded_images_extraction"] = {
        "status": "SUCCESS",
        "duration_seconds": round(t3_duration, 2),
        "total_images_extracted": len(extracted_images),
        "output_dir": str(test3_img_dir),
        "sample_images": [p.name for p in extracted_images[:10]]
    }
    print(f"  ✅ 測試 3 成功！耗時 {t3_duration:.1f} 秒，成功提取 {len(extracted_images)} 張原始圖檔")
except Exception as e:
    report["tests"]["feature_3_embedded_images_extraction"] = {
        "status": "FAILED",
        "error": str(e)
    }
    print(f"  ❌ 測試 3 失敗: {e}")

# =========================================================================
# 產生驗證報告 JSON
# =========================================================================
report_path = PATHS.root / "data" / "03_output" / "benchmark_test_report_14_60.json"
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print("\n" + "=" * 60)
print(f"📊 完整測試報告已產出至: {report_path}")
print("=" * 60)
