# // ==============================================================================
# // pdf_font_analyzer.py: PDF 字體掃描與樣式對應工具
# // - 掃描 PDF 中所有字體名稱、字級與代表性範例文字
# // - 讀取 template.docx 中的段落樣式清單
# // - 讀取 / 寫入 fonts.json 字體角色對應表
# // ==============================================================================

import os
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

# pyrefly: ignore [missing-import]
import fitz


def scan_pdf_fonts(pdf_path: str, max_samples: int = 3, max_sample_len: int = 60) -> list[dict]:
    """
    掃描 PDF，回傳每種字體的：
      - name      : 字體名稱（去掉 PDF 子集前綴，如 ABCDEF+FontName → FontName）
      - full_name : 原始完整字體名
      - size_pt   : 該字體最常見的字級（取眾數四捨五入至 0.5pt）
      - sample_texts : 最多 max_samples 句代表性文字
    """
    doc = fitz.open(pdf_path)

    # font_name → {sizes: [], texts: set()}
    font_data: dict[str, dict] = {}

    for page in doc:
        blocks = page.get_text("dict").get("blocks", [])
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    raw_font = span.get("font", "") or ""
                    text = (span.get("text") or "").strip()
                    size = round(span.get("size", 0) * 2) / 2  # round to nearest 0.5

                    if not raw_font or not text:
                        continue

                    # 去掉 PDF 子集前綴（格式：XXXXXX+FontName）
                    clean_name = raw_font.split("+", 1)[-1] if "+" in raw_font else raw_font

                    if clean_name not in font_data:
                        font_data[clean_name] = {
                            "full_name": raw_font,
                            "sizes": [],
                            "texts": [],
                        }

                    entry = font_data[clean_name]
                    entry["sizes"].append(size)

                    # 積累非重複的樣本句子
                    if text not in entry["texts"] and len(text) >= 3:
                        entry["texts"].append(text)

    doc.close()

    result = []
    for clean_name, data in font_data.items():
        # 眾數字級
        if data["sizes"]:
            size_mode = max(set(data["sizes"]), key=data["sizes"].count)
        else:
            size_mode = 0.0

        samples = []
        texts = data["texts"]
        if texts:
            step = max(1, len(texts) // max_samples)
            for i in range(0, len(texts), step):
                if len(samples) >= max_samples:
                    break
                samples.append(texts[i][:max_sample_len])

        result.append({
            "name": clean_name,
            "full_name": data["full_name"],
            "size_pt": size_mode,
            "sample_texts": samples,
        })

    # 依字級由大到小排序，方便人工從標題到內文對應
    result.sort(key=lambda x: x["size_pt"], reverse=True)
    return result


def read_docx_styles(template_path: str) -> list[str]:
    """
    從 template.docx 讀取所有段落樣式名稱。
    回傳清單（保留原始順序）。
    """
    styles = []
    W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(template_path, "r") as z:
            if "word/styles.xml" in z.namelist():
                tree = ET.fromstring(z.read("word/styles.xml"))
                for s in tree.findall(f"{W_NS}style"):
                    if s.get(f"{W_NS}type") == "paragraph":
                        name_el = s.find(f"{W_NS}name")
                        if name_el is not None:
                            val = name_el.get(f"{W_NS}val")
                            if val:
                                styles.append(val)
    except Exception as e:
        print(f"[FontAnalyzer] 讀取 template.docx 樣式失敗: {e}")
    return styles


def load_fonts_json(fonts_json_path: str) -> dict:
    """
    讀取 fonts.json。
    同時支援舊格式（字體名 → 純字串值）與新格式（字體名 → {role, docx_style, ...}）。
    統一回傳新格式 dict。
    """
    if not os.path.exists(fonts_json_path):
        return {}
    try:
        with open(fonts_json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}

    normalized = {}
    for key, val in raw.items():
        if isinstance(val, dict):
            normalized[key] = val
        elif isinstance(val, str):
            # 舊格式：值為範例文字，保留為 sample，role 未設定
            normalized[key] = {
                "role": None,
                "docx_style": None,
                "sample": val,
                "mapped_by": "legacy",
            }
    return normalized


def save_fonts_json(fonts_json_path: str, mapping: dict) -> None:
    """將字體角色對應表寫入 fonts.json（保留現有未更動的 key）。"""
    existing = load_fonts_json(fonts_json_path)
    existing.update(mapping)
    with open(fonts_json_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def get_font_role_map(fonts_json_path: str) -> dict[str, dict]:
    """
    供 book_layout_extractor 呼叫：
    回傳 {font_name: {role, docx_style}} 的對應表，
    僅包含已由人工設定 role 的項目。
    """
    raw = load_fonts_json(fonts_json_path)
    result = {}
    for name, data in raw.items():
        if isinstance(data, dict) and data.get("role") and data.get("mapped_by") != "legacy":
            result[name] = data
    return result


def analyze_pdf_for_ui(pdf_path: str, template_path: Optional[str], fonts_json_path: str) -> dict:
    """
    整合入口：掃描 PDF 字體、讀取 docx 樣式、讀取已存的對應表，
    回傳供前端 Modal 使用的 JSON。
    """
    fonts = scan_pdf_fonts(pdf_path)
    docx_styles = read_docx_styles(template_path) if template_path else []
    existing_mapping = load_fonts_json(fonts_json_path)

    # 合併現有對應（讓已設定過的字體在 UI 中預選）
    for font in fonts:
        name = font["name"]
        if name in existing_mapping:
            existing = existing_mapping[name]
            font["current_role"] = existing.get("role") if isinstance(existing, dict) else None
            font["current_docx_style"] = existing.get("docx_style") if isinstance(existing, dict) else None
        else:
            font["current_role"] = None
            font["current_docx_style"] = None

    # 固定預設角色清單（作為 fallback，若 docx 無樣式時使用）
    default_roles = ["H1", "H2", "H3", "圖說", "楷體", "正文", "忽略"]

    return {
        "fonts": fonts,
        "docx_styles": docx_styles,
        "default_roles": default_roles,
    }


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="掃描 PDF 字體並輸出 JSON")
    parser.add_argument("pdf_path", help="PDF 檔案路徑")
    parser.add_argument("--template", help="template.docx 路徑（選用）", default=None)
    parser.add_argument("--fonts_json", help="fonts.json 路徑", default="fonts.json")
    args = parser.parse_args()

    result = analyze_pdf_for_ui(
        pdf_path=args.pdf_path,
        template_path=args.template,
        fonts_json_path=args.fonts_json,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
