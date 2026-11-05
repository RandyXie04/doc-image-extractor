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

from src.utils.docx_style_profiles import read_docx_style_profiles


def scan_pdf_fonts(pdf_path: str, max_samples: int = 3, max_sample_len: int = 60) -> list[dict]:
    """
    掃描 PDF，回傳每種字體的：
      - name      : 字體名稱（去掉 PDF 子集前綴，如 ABCDEF+FontName → FontName）
      - full_name : 原始完整字體名
      - size_pt   : 該字體最常見的字級（取眾數四捨五入至 0.5pt）
      - occurrence_count : 出現次數（span 數）
      - page_count : 涵蓋頁數
      - position_summary : 頁面位置分布（top/middle/bottom 比例與置中比例）
      - sample_texts : 最多 max_samples 句代表性文字
    """
    doc = fitz.open(pdf_path)

    font_data: dict[str, dict] = {}

    for page_idx, page in enumerate(doc):
        page_h = max(1.0, float(page.rect.height))
        page_w = max(1.0, float(page.rect.width))
        blocks = page.get_text("dict").get("blocks", [])
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_bbox = line.get("bbox", block.get("bbox", [0, 0, 0, 0]))
                for span in line.get("spans", []):
                    raw_font = span.get("font", "") or ""
                    text = (span.get("text") or "").strip()
                    size = round(span.get("size", 0) * 2) / 2  # round to nearest 0.5

                    if not raw_font or not text:
                        continue

                    # 去掉 PDF 子集前綴（格式：XXXXXX+FontName）
                    clean_name = raw_font.split("+", 1)[-1] if "+" in raw_font else raw_font

                    font_key = f"{clean_name}_{size}"

                    if font_key not in font_data:
                        font_data[font_key] = {
                            "clean_name": clean_name,
                            "full_name": raw_font,
                            "size": size,
                            "texts": [],
                            "occurrence_count": 0,
                            "pages": set(),
                            "pos_counts": {"top": 0, "middle": 0, "bottom": 0},
                            "centered_count": 0,
                        }

                    entry = font_data[font_key]
                    entry["occurrence_count"] += 1
                    entry["pages"].add(page_idx + 1)

                    span_bbox = span.get("bbox") or line_bbox
                    if span_bbox and len(span_bbox) >= 4:
                        y_center = (float(span_bbox[1]) + float(span_bbox[3])) / 2.0
                        x_center = (float(span_bbox[0]) + float(span_bbox[2])) / 2.0
                        y_ratio = y_center / page_h
                        if y_ratio < 0.25:
                            entry["pos_counts"]["top"] += 1
                        elif y_ratio > 0.75:
                            entry["pos_counts"]["bottom"] += 1
                        else:
                            entry["pos_counts"]["middle"] += 1
                        if abs(x_center - (page_w / 2.0)) < (page_w * 0.12):
                            entry["centered_count"] += 1
                    else:
                        entry["pos_counts"]["middle"] += 1

                    # 積累非重複的樣本句子
                    if text not in entry["texts"] and len(text) >= 2:
                        entry["texts"].append(text)

    doc.close()

    result = []
    for font_key, data in font_data.items():
        clean_name = data["clean_name"]
        size_mode = data["size"]
        occ_count = data["occurrence_count"]
        page_count = len(data["pages"])
        pos_counts = data["pos_counts"]
        total_pos = max(1, sum(pos_counts.values()))
        dominant_zone = max(pos_counts.items(), key=lambda kv: kv[1])[0]
        position_summary = {
            "top_ratio": round(pos_counts["top"] / total_pos, 2),
            "middle_ratio": round(pos_counts["middle"] / total_pos, 2),
            "bottom_ratio": round(pos_counts["bottom"] / total_pos, 2),
            "centered_ratio": round(data["centered_count"] / total_pos, 2),
            "dominant_zone": dominant_zone,
        }

        samples = []
        texts = data["texts"]
        if texts:
            step = max(1, len(texts) // max_samples)
            for i in range(0, len(texts), step):
                if len(samples) >= max_samples:
                    break
                samples.append(texts[i][:max_sample_len])

        result.append({
            "name": f"{clean_name} ({size_mode}pt)",  # Combine name and size for the identifier
            "full_name": data["full_name"],
            "size_pt": size_mode,
            "occurrence_count": occ_count,
            "page_count": page_count,
            "position_summary": position_summary,
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
        print(f"[FontAnalyzer] 讀取 template.docx 樣式失敗 ({type(e).__name__})")
    return styles


def load_fonts_json(fonts_json_path: str) -> dict:
    """
    讀取 fonts.json。
    同時支援舊格式（字體名 → 純字串值）與新格式（字體名 → {role, docx_style, ...}）。
    統一回傳新格式 dict。
    """
    if not os.path.exists(fonts_json_path):
        for alt in ["config/fonts.json", "fonts.json"]:
            if os.path.exists(alt):
                fonts_json_path = alt
                break
        else:
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


def save_fonts_json(fonts_json_path: str, mapping: dict, remove_keys: Optional[list] = None) -> None:
    """將字體角色對應表寫入 fonts.json（保留現有未更動的 key，可選移除 remove_keys）。"""
    existing = load_fonts_json(fonts_json_path)
    if remove_keys:
        for k in remove_keys:
            existing.pop(k, None)
    existing.update(mapping)
    with open(fonts_json_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def get_font_role_map(fonts_json_path: str) -> dict[str, dict]:
    """
    供 book_layout_extractor 呼叫：
    回傳 {font_name: {role, docx_style}} 的對應表，
    包含已由人工設定 role 或 docx_style 的項目。
    """
    raw = load_fonts_json(fonts_json_path)
    result = {}
    for name, data in raw.items():
        if isinstance(data, dict) and (data.get("role") or data.get("docx_style")) and data.get("mapped_by") != "legacy":
            result[name] = data
    return result


def derive_style_mapping_from_fonts(
    fonts_json_path: str,
    base_style_mapping: Optional[dict] = None,
    active_font_names: Optional[list | set] = None,
) -> dict:
    """
    從 fonts.json 的字體審閱確認值推導通用角色樣式對應表 (h1, h2, h3, body, image_caption, kaiti)，
    作為獨立 Word 樣式角色對應 UI 收斂後的內部相容 fallback。
    若呼叫端已明確傳入 base_style_mapping 的非空欄位，優先保留呼叫端設定。
    若提供 active_font_names，僅從當前 PDF 出現的字體群組推導。
    """
    import re
    merged: dict = {}
    if isinstance(base_style_mapping, dict):
        for k, v in base_style_mapping.items():
            if isinstance(v, str) and v.strip():
                merged[k] = v.strip()

    role_to_key = {
        "h1": "h1",
        "h2": "h2",
        "h3": "h3",
        "正文": "body",
        "內文": "body",
        "body": "body",
        "圖說": "image_caption",
        "图说": "image_caption",
        "caption": "image_caption",
        "image_caption": "image_caption",
        "楷體": "kaiti",
        "楷体": "kaiti",
        "kaiti": "kaiti",
        "blockquote": "kaiti",
    }

    active_set = {str(x) for x in active_font_names} if active_font_names is not None else None
    font_map = get_font_role_map(fonts_json_path)
    for font_name, entry in font_map.items():
        if active_set is not None and font_name not in active_set:
            continue
        if not isinstance(entry, dict):
            continue
        docx_style = (entry.get("docx_style") or "").strip()
        if not docx_style:
            continue
        raw_role = (entry.get("role") or "").strip()
        target_key = role_to_key.get(raw_role.lower()) if raw_role else None
        if not target_key:
            if re.search(r"標題\s*1|heading\s*1", docx_style, re.I):
                target_key = "h1"
            elif re.search(r"標題\s*2|heading\s*2", docx_style, re.I):
                target_key = "h2"
            elif re.search(r"標題\s*3|heading\s*3", docx_style, re.I):
                target_key = "h3"
            elif re.search(r"圖說|图说|caption", docx_style, re.I):
                target_key = "image_caption"
            elif re.search(r"楷|kai", docx_style, re.I):
                target_key = "kaiti"
            elif re.search(r"正文|內文|normal|body", docx_style, re.I):
                target_key = "body"
        if target_key and not merged.get(target_key):
            merged[target_key] = docx_style

    return merged


def analyze_pdf_for_ui(pdf_path: str, template_path: Optional[str], fonts_json_path: str) -> dict:
    """
    整合入口：掃描 PDF 字體、讀取 docx 樣式、讀取已存的對應表，
    回傳供前端 Modal 使用的 JSON。
    掃描階段不自動呼叫 Gemma（Gemma 採按需觸發）。
    """
    fonts = scan_pdf_fonts(pdf_path)
    docx_styles = read_docx_styles(template_path) if template_path else []
    docx_style_profiles = []
    if template_path:
        try:
            docx_style_profiles = read_docx_style_profiles(template_path)
        except Exception:
            docx_style_profiles = []
    existing_mapping = load_fonts_json(fonts_json_path)

    # 合併現有對應（讓已設定過的字體在 UI 中預選，未設定者預設為「auto」）
    for font in fonts:
        name = font["name"]
        if name in existing_mapping:
            existing = existing_mapping[name]
            role = existing.get("role") if isinstance(existing, dict) else None
            docx_style = existing.get("docx_style") if isinstance(existing, dict) else None
            font["current_role"] = role if (role or docx_style) else "auto"
            font["current_docx_style"] = docx_style
        else:
            font["current_role"] = "auto"
            font["current_docx_style"] = None
        font_str = font["name"].lower()
        if any(k in font_str for k in ["kaiti", "kai_ti", "fzkt", "fzkai", "stkaiti", "kai", "楷"]):
            font["suggested_role"] = "楷體"
        elif any(k in font_str for k in ["fangsong", "fang_song", "fzfs", "stfangsong", "仿宋"]):
            font["suggested_role"] = "楷體"
        elif any(k in font_str for k in ["songti", "song_ti", "fzss", "fzsong", "stsong", "simsun", "nsimsun", "mingliu", "宋"]):
            font["suggested_role"] = "正文"
        elif any(k in font_str for k in ["heiti", "hei_ti", "fzht", "fzhei", "stheiti", "simhei", "yahei", "黑"]):
            font["suggested_role"] = "H2" if font.get("size_pt", 0) >= 12.0 else "正文"
        else:
            font["suggested_role"] = None
        font["gemma_status"] = "not_run"

    # 固定預設角色清單（作為 fallback，若 docx 無樣式時使用）
    default_roles = ["H1", "H2", "H3", "圖說", "楷體", "正文", "忽略"]

    return {
        "fonts": fonts,
        "docx_styles": docx_styles,
        "docx_style_profiles": docx_style_profiles,
        "default_roles": default_roles,
    }


if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="掃描 PDF 字體並輸出 JSON")
    parser.add_argument("pdf_path", help="PDF 檔案路徑")
    parser.add_argument("--template", help="template.docx 路徑（選用）", default=None)
    parser.add_argument("--fonts_json", help="fonts.json 路徑", default="config/fonts.json")
    args = parser.parse_args()

    result = analyze_pdf_for_ui(
        pdf_path=args.pdf_path,
        template_path=args.template,
        fonts_json_path=args.fonts_json,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
