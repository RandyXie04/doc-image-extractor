# -*- coding: utf-8 -*-
"""
特殊符號與全形編號對應模組 (Symbol Mapper & Typographic Restorer)
==============================================================
負責修復 OCR 階段因裁切邊界、字形退化所導致的符號異常：
1. 邊緣截斷括號修復：將 一)、二) 等還原為 （一）、（二）
2. 圓圈數字辨識修復：將 OCR 遺失外圈的純數字 1、2、3... 還原為 ①、②、③...
3. 連接號/範圍號正規化：將數字區間中的半形波浪號 ~ 轉換為全形浪紋線 ～，防止 Pandoc 誤判為下標 (subscript)
4. 殘留無效圖片標記清理：移除未連結實體圖檔之 ![img]() 空白預留標記
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, Any, Optional

DEFAULT_CIRCLED_MAP: Dict[str, str] = {
    "1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤",
    "6": "⑥", "7": "⑦", "8": "⑧", "9": "⑨", "10": "⑩",
    "11": "⑪", "12": "⑫", "13": "⑬", "14": "⑭", "15": "⑮",
    "16": "⑯", "17": "⑰", "18": "⑱", "19": "⑲", "20": "⑳"
}

DEFAULT_CHINESE_NUMERALS: Dict[str, str] = {
    "一": "（一）", "二": "（二）", "三": "（三）", "四": "（四）", "五": "（五）",
    "六": "（六）", "七": "（七）", "八": "（八）", "九": "（九）", "十": "（十）"
}

_TRUNCATED_BRACKET_RE = re.compile(
    r'(?m)^(\s*(?:>|\*|#)*\s*[*#]{0,3}\s*)([一二三四五六七八九十]+)[)）]'
)

_BARE_DIGIT_LIST_RE = re.compile(
    r'(?m)^(\s*(?:>|\*)*\s*)([1-9]|1[0-9]|20)(?=[\u4e00-\u9fa5])'
)

_NUMERIC_RANGE_TILDE_RE = re.compile(
    r'(?<=\d)\s*~\s*(?=\d)'
)

_EMPTY_IMG_TAG_RE = re.compile(
    r'(?m)^\s*!\[[^\]]*\]\(\s*\)(?:\{[^\n}]*\})?\s*\n?'
)


def load_symbol_mapping(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """載入符號對應設定，若不存在則使用預設值。"""
    if config_path is None:
        try:
            from config import PATHS
            config_path = PATHS.root / "config" / "symbol_mapping.json"
        except Exception:
            config_path = Path(__file__).resolve().parents[2] / "config" / "symbol_mapping.json"

    if config_path and Path(config_path).exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {
        "circled_numbers": DEFAULT_CIRCLED_MAP,
        "chinese_numerals": DEFAULT_CHINESE_NUMERALS,
        "numeric_range_tilde": "～"
    }


def restore_ocr_symbols(text: str, config: Optional[Dict[str, Any]] = None) -> tuple[str, Dict[str, int]]:
    """
    對 Markdown 文字執行特殊符號還原與排版修復。
    
    Returns:
        (restored_text, stats_dict)
    """
    if not text:
        return "", {"brackets_restored": 0, "circled_restored": 0, "tildes_normalized": 0, "empty_imgs_removed": 0}

    if config is None:
        config = load_symbol_mapping()

    circled_map = config.get("circled_numbers", DEFAULT_CIRCLED_MAP)
    range_tilde = config.get("numeric_range_tilde", "～")

    stats = {
        "brackets_restored": 0,
        "circled_restored": 0,
        "tildes_normalized": 0,
        "empty_imgs_removed": 0
    }

    # 1. 邊緣截斷中文括號還原：例如 一)小妙招 -> （一）小妙招、**二)组方思路** -> **（二）组方思路**
    def _repl_bracket(m):
        stats["brackets_restored"] += 1
        prefix = m.group(1)
        num = m.group(2)
        return f"{prefix}（{num}）"

    text = _TRUNCATED_BRACKET_RE.sub(_repl_bracket, text)

    # 2. 圓圈數字辨識退化還原：行首純數字直接緊接中文時（如 1外感風寒... -> ①外感風寒...）
    def _repl_circled(m):
        prefix = m.group(1)
        digit_str = m.group(2)
        if digit_str in circled_map:
            stats["circled_restored"] += 1
            return f"{prefix}{circled_map[digit_str]}"
        return m.group(0)

    text = _BARE_DIGIT_LIST_RE.sub(_repl_circled, text)

    # 3. 數字範圍 ~ 符號轉換為全形浪紋線 ～，防止 Pandoc 轉化為下標 (subscript)
    def _repl_tilde(m):
        stats["tildes_normalized"] += 1
        return range_tilde

    text = _NUMERIC_RANGE_TILDE_RE.sub(_repl_tilde, text)

    # 4. 殘留無效圖片標記清理：移除空的 ![img]() 或 ![]()
    empty_matches = len(_EMPTY_IMG_TAG_RE.findall(text))
    if empty_matches > 0:
        stats["empty_imgs_removed"] = empty_matches
        text = _EMPTY_IMG_TAG_RE.sub("", text)

    return text, stats
