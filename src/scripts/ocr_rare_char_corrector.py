#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR 生僻字後處理與可疑字元偵測模組
=============================================================================
功能說明：
1. 套用 founder_correction_dict.json 靜態校正字典，修復已知的 OCR 錯字。
2. 套用 clean_founder_text()，修復方正排版 CMap 編碼亂碼。
3. 偵測 OCR 輸出中的可疑字元（PUA 區、彝文區、CJK 相容區、替換字元 U+FFFD、
   零寬字元、罕見控制字元等），產出頁級覆核報告。
4. 產出格式化的 rare_char_review_report.txt 人工覆核清單。
"""

import os
import re
import json
import datetime
import unicodedata
from pathlib import Path


def load_correction_dict(data_dir: str) -> dict:
    """載入 founder_correction_dict.json 靜態校正字典。"""
    dict_path = Path(data_dir) / 'Json' / 'founder_correction_dict.json'
    if dict_path.exists():
        try:
            with open(dict_path, 'r', encoding='utf-8') as f:
                corrections = json.load(f)
            return corrections
        except Exception as e:
            print(f"[Warning] 讀取 founder_correction_dict.json 失敗: {e}")
    return {}


def apply_corrections(text: str, corrections: dict) -> tuple:
    """
    套用靜態校正字典，回傳 (修正後文字, 替換記錄列表)。
    每筆替換記錄: {"bad": str, "good": str, "count": int}
    """
    if not corrections or not text:
        return text, []

    records = []
    for bad_char, good_char in corrections.items():
        if not bad_char or bad_char.startswith('_'):  # 跳過空鍵和 _ 開頭的說明欄位
            continue
        count = text.count(bad_char)
        if count > 0:
            text = text.replace(bad_char, good_char)
            records.append({"bad": bad_char, "good": good_char, "count": count})
    return text, records


def apply_founder_cleanup(text: str) -> str:
    """
    套用 clean_founder_text() 修復方正排版 CMap 編碼亂碼。
    若模組不可用則略過。
    """
    try:
        from src.founder_tools.fix_founder_fonts import clean_founder_text
        return clean_founder_text(text)
    except ImportError:
        try:
            from founder_tools.fix_founder_fonts import clean_founder_text
            return clean_founder_text(text)
        except ImportError:
            return text


# ────────────────────────────────────────────────────────────────
# 可疑字元偵測規則
# ────────────────────────────────────────────────────────────────

# Unicode 範圍定義
_SUSPICIOUS_RANGES = [
    # PUA (Private Use Area) — 方正排版殘留
    (0xE000, 0xF8FF, "PUA 私用區 (方正排版殘留)"),
    # Supplementary PUA
    (0xF0000, 0xFFFFF, "PUA 補充區-A"),
    (0x100000, 0x10FFFF, "PUA 補充區-B"),
    # 彝文音節區 — 常見方正 GBK 映射錯誤
    (0xA000, 0xA4CF, "彝文音節區 (疑似方正 GBK 映射錯誤)"),
    # CJK 相容表意文字 — 可能是 OCR 誤判
    (0xF900, 0xFAFF, "CJK 相容表意文字區"),
]

# 單個特殊字元
_SUSPICIOUS_CHARS = {
    '\uFFFD': '替換字元 U+FFFD (OCR 無法辨識)',
    '\u200B': '零寬空格 U+200B',
    '\u200C': '零寬非連接符 U+200C',
    '\u200D': '零寬連接符 U+200D',
    '\uFEFF': 'BOM 標記 U+FEFF',
    '\u00AD': '軟連字號 U+00AD',
}


def _classify_char(ch: str):
    """判斷字元是否為可疑字元，回傳分類說明或 None。"""
    # 先檢查特殊單字元
    if ch in _SUSPICIOUS_CHARS:
        return _SUSPICIOUS_CHARS[ch]

    code = ord(ch)
    for start, end, desc in _SUSPICIOUS_RANGES:
        if start <= code <= end:
            return desc

    return None


def detect_suspicious_chars(text: str, page_num: int = 0, context_radius: int = 15) -> list:
    """
    掃描文字中的可疑字元，回傳偵測記錄列表。
    每筆記錄: {
        "page": int,
        "char": str,
        "unicode": str (e.g. "U+E81F"),
        "char_name": str (Unicode 名稱),
        "category": str (分類說明),
        "position": int (字元在文字中的位置),
        "context": str (前後文片段)
    }
    """
    findings = []
    if not text:
        return findings

    for i, ch in enumerate(text):
        category = _classify_char(ch)
        if category:
            # 取得前後文
            start = max(0, i - context_radius)
            end = min(len(text), i + context_radius + 1)
            context = text[start:end].replace('\n', '↵')

            # 標記可疑字元位置
            marker_pos = i - start
            context_marked = context[:marker_pos] + f"【{ch}】" + context[marker_pos + 1:]

            # 取得 Unicode 名稱
            try:
                char_name = unicodedata.name(ch, "UNKNOWN")
            except ValueError:
                char_name = "UNKNOWN"

            findings.append({
                "page": page_num,
                "char": ch,
                "unicode": f"U+{ord(ch):04X}",
                "char_name": char_name,
                "category": category,
                "position": i,
                "context": context_marked,
            })

    return findings


def generate_rare_char_review_report(
    pdf_name: str,
    all_findings: list,
    correction_records: list,
    output_path: str
):
    """
    產出格式化的生僻字/可疑字元人工覆核報告。

    Args:
        pdf_name: 來源 PDF 檔名
        all_findings: 所有頁面的可疑字元偵測記錄
        correction_records: 靜態字典已修正的記錄
        output_path: 報告輸出路徑
    """
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 統計
    total_suspicious = len(all_findings)
    total_corrected = sum(r["count"] for r in correction_records) if correction_records else 0
    pages_with_issues = len(set(f["page"] for f in all_findings)) if all_findings else 0

    # 按分類統計
    category_counts = {}
    for f in all_findings:
        cat = f["category"]
        category_counts[cat] = category_counts.get(cat, 0) + 1

    lines = [
        "=" * 80,
        "OCR 生僻字與可疑字元人工覆核報告",
        f"生成時間：{now_str}",
        f"來源文件：{pdf_name}",
        "=" * 80,
        "",
        "【統計總覽】",
        f"  靜態字典已自動修正 ：{total_corrected} 處",
        f"  待人工覆核可疑字元 ：{total_suspicious} 處",
        f"  涉及頁數           ：{pages_with_issues} 頁",
        "",
    ]

    # 已修正記錄
    if correction_records:
        lines.append("【靜態字典自動修正明細】")
        lines.append("-" * 60)
        for r in correction_records:
            lines.append(f"  「{r['bad']}」 → 「{r['good']}」 （共 {r['count']} 處）")
        lines.append("")

    # 按分類列出
    if category_counts:
        lines.append("【可疑字元分類統計】")
        lines.append("-" * 60)
        for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: {cnt} 處")
        lines.append("")

    # 逐頁列出可疑字元
    if all_findings:
        lines.append("【逐頁可疑字元明細】")
        lines.append("說明：以下字元可能是 OCR 無法正確辨識的生僻字或方正殘留亂碼。")
        lines.append("      請人工比對原始 PDF 後，將正確對應新增至")
        lines.append("      data/Json/founder_correction_dict.json 字典中。")
        lines.append("-" * 60)
        lines.append("")

        current_page = -1
        for f in all_findings:
            if f["page"] != current_page:
                current_page = f["page"]
                lines.append(f"  ── 第 {current_page} 頁 ──")

            lines.append(
                f"    [{f['unicode']}] 「{f['char']}」"
                f" ({f['char_name']})"
                f" | 分類: {f['category']}"
            )
            lines.append(f"    上下文: ...{f['context']}...")
            lines.append("")
    else:
        lines.append("【結果】本次 OCR 未偵測到可疑字元，文字品質良好。")
        lines.append("")

    # 使用指南
    lines.extend([
        "=" * 80,
        "【如何修正生僻字？】",
        "",
        "步驟 1：比對原始 PDF 確認正確的字元。",
        "步驟 2：打開 data/Json/founder_correction_dict.json",
        '步驟 3：新增一行，格式為 "錯字": "正確字"',
        "        範例：",
        '          {',
        '            "颃嗓": "頏顙",',
        '            "〇": "零",',
        '            "﨏": "缺字的正確字"',
        '          }',
        "步驟 4：重新執行 OCR 管線，字典會自動套用。",
        "",
        "提示：字典支援多字元對應（如「颃嗓」→「頏顙」），",
        "      也支援單字對應（如「〇」→「零」）。",
        "=" * 80,
        ""
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def postprocess_ocr_markdown(
    markdown_text: str,
    data_dir: str,
    pdf_name: str = "",
    output_dir: str = "",
    page_separator: str = "\n\n",
) -> tuple:
    """
    OCR Markdown 文字的完整後處理流程：
    1. 載入並套用靜態校正字典
    2. 套用方正亂碼修復
    3. 偵測可疑字元
    4. 產出覆核報告

    Args:
        markdown_text: OCR 輸出的原始 Markdown 文字
        data_dir: 專案 data 目錄路徑 (用於讀取字典)
        pdf_name: 來源 PDF 檔名 (用於報告)
        output_dir: 報告輸出目錄
        page_separator: 頁面分隔符號 (用於估算頁碼)

    Returns:
        (修正後的 Markdown 文字, 修正統計 dict)
    """
    # 1. 載入並套用靜態校正字典
    corrections = load_correction_dict(data_dir)
    markdown_text, correction_records = apply_corrections(markdown_text, corrections)

    # 2. 套用方正亂碼修復
    markdown_text = apply_founder_cleanup(markdown_text)

    # 3. 偵測可疑字元 (逐頁)
    # 嘗試按雙換行分頁來估算頁碼
    pages = markdown_text.split(page_separator) if page_separator in markdown_text else [markdown_text]
    all_findings = []
    for page_idx, page_text in enumerate(pages):
        page_num = page_idx + 1
        findings = detect_suspicious_chars(page_text, page_num=page_num)
        all_findings.extend(findings)

    # 4. 產出覆核報告
    if output_dir:
        report_path = os.path.join(output_dir, "rare_char_review_report.txt")
        generate_rare_char_review_report(pdf_name, all_findings, correction_records, report_path)

    stats = {
        "corrections_applied": sum(r["count"] for r in correction_records) if correction_records else 0,
        "suspicious_chars_found": len(all_findings),
        "correction_details": correction_records,
        "report_path": os.path.join(output_dir, "rare_char_review_report.txt") if output_dir else None,
    }

    return markdown_text, stats
