# // ==============================================================================
# // toc_parser.py: 目錄驅動的全域標題索引校正模組
# // - 自動定位目錄頁
# // - 解析目錄條目（標題 + 頁碼 + 層級）
# // - 建立反向校正索引表
# // ==============================================================================

import re
from typing import Optional


def find_toc_pages_ocr(pages_data: list) -> tuple:
    """
    在 OCR 管線的 pages_data 中定位目錄頁範圍。
    pages_data: list of dicts, each with "page_num", "para_blocks" from RapidDoc.

    Returns:
        (toc_start_page, toc_end_page) — 1-indexed page numbers.
        若未找到目錄頁，回傳 (None, None)。
    """
    toc_keywords = re.compile(r'^(?:目\s*錄|目\s*录|CONTENTS|Table\s+of\s+Contents)\s*$',
                              re.IGNORECASE)
    toc_start = None
    toc_end = None

    for page_info in pages_data:
        page_num = page_info.get("page_idx", page_info.get("page_num", 0))
        if isinstance(page_num, int) and page_num < 1:
            page_num += 1  # convert 0-indexed to 1-indexed

        para_blocks = page_info.get("para_blocks", [])

        for block in para_blocks:
            text = _extract_block_text_ocr(block).strip()
            if toc_keywords.match(text):
                toc_start = page_num
                break

        # If we've started the TOC, keep going until we find a non-TOC page
        if toc_start and toc_start != page_num:
            # Check if this page still looks like TOC
            has_toc_entry = False
            for block in para_blocks:
                text = _extract_block_text_ocr(block).strip()
                if _is_toc_entry_line(text):
                    has_toc_entry = True
                    break
            if has_toc_entry:
                toc_end = page_num
            else:
                break

    if toc_start and not toc_end:
        toc_end = toc_start

    return (toc_start, toc_end)


def find_toc_pages_vector(doc, max_search_pages: int = 20) -> tuple:
    """
    在向量 PDF (PyMuPDF fitz.Document) 中定位目錄頁範圍。

    Returns:
        (toc_start_idx, toc_end_idx) — 0-indexed page indices.
        若未找到目錄頁，回傳 (None, None)。
    """
    toc_keywords = re.compile(r'^(?:目\s*錄|目\s*录|CONTENTS|Table\s+of\s+Contents)\s*$',
                              re.IGNORECASE)
    toc_start = None
    toc_end = None
    total = min(len(doc), max_search_pages)

    for page_idx in range(total):
        page = doc[page_idx]
        blocks = page.get_text("dict").get("blocks", [])

        for b in blocks:
            if b.get("type") != 0:
                continue
            text = "".join(
                s.get("text", "")
                for l in b.get("lines", [])
                for s in l.get("spans", [])
            ).strip()
            if toc_keywords.match(text):
                toc_start = page_idx
                break

        if toc_start is not None and page_idx > toc_start:
            page = doc[page_idx]
            page_text = page.get_text("text")
            if any(_is_toc_entry_line(line.strip()) for line in page_text.split('\n') if line.strip()):
                toc_end = page_idx
            else:
                break

    if toc_start is not None and toc_end is None:
        toc_end = toc_start

    return (toc_start, toc_end)


def parse_toc_entries_from_text(toc_text_lines: list, base_x0_values: list = None) -> list:
    """
    從目錄文字行中解析條目。

    Parameters:
        toc_text_lines: list of str (每行目錄文字)
        base_x0_values: list of float (每行的 x0 座標，用於推斷層級)

    Returns:
        list of {"title": str, "page": int, "level": int, "raw": str}
    """
    entries = []

    # 目錄條目模式 1: 標題 + 省略號/圓點 + 頁碼
    pattern_dotted = re.compile(r'^(.+?)\s*[…·\.]{2,}\s*(\d+)\s*$')
    # 目錄條目模式 2: 標題 + 制表符/多空格 + 頁碼
    pattern_tabbed = re.compile(r'^(.+?)\s{3,}(\d+)\s*$')
    # 目錄條目模式 3: 標題 + 頁碼（在行末，無分隔符但頁碼獨立）
    pattern_tail_num = re.compile(r'^(.{2,}?)\s+(\d{1,4})\s*$')

    for idx, line in enumerate(toc_text_lines):
        line = line.strip()
        if not line:
            continue

        title = None
        page_num = None

        # 嘗試匹配
        for pattern in [pattern_dotted, pattern_tabbed, pattern_tail_num]:
            m = pattern.match(line)
            if m:
                title = m.group(1).strip()
                page_num = int(m.group(2))
                break

        if title and page_num:
            # 排除純頁碼行
            if len(title) < 2:
                continue
            # 排除已包含完整省略號但標題本身太短的垃圾行
            clean_title = re.sub(r'[…·\.\s]', '', title)
            if len(clean_title) < 2:
                continue

            level = _infer_level_from_title(title)

            # 如果有 x0 縮進資訊，用縮進深度微調層級
            if base_x0_values and idx < len(base_x0_values):
                level = _adjust_level_by_indent(level, base_x0_values, idx)

            entries.append({
                "title": clean_title,
                "page": page_num,
                "level": level,
                "raw": line
            })

    return entries


def parse_toc_entries_from_blocks_ocr(para_blocks: list) -> list:
    """
    從 OCR 管線的 para_blocks 中解析目錄條目。
    """
    lines = []
    x0_values = []
    for block in para_blocks:
        text = _extract_block_text_ocr(block)
        if text.strip():
            bbox = block.get("bbox", [0, 0, 0, 0])
            for sub_line in text.split('\n'):
                if sub_line.strip():
                    lines.append(sub_line.strip())
                    x0_values.append(bbox[0] if len(bbox) >= 1 else 0)
    return parse_toc_entries_from_text(lines, x0_values)


def parse_toc_entries_from_blocks_vector(blocks: list) -> list:
    """
    從向量 PDF 的 fitz blocks 中解析目錄條目。
    """
    lines = []
    x0_values = []
    for b in blocks:
        if b.get("type") != 0:
            continue
        text = "".join(
            s.get("text", "")
            for l in b.get("lines", [])
            for s in l.get("spans", [])
        ).strip()
        bbox = b.get("bbox", [0, 0, 0, 0])
        for sub_line in text.split('\n'):
            if sub_line.strip():
                lines.append(sub_line.strip())
                x0_values.append(bbox[0])
    return parse_toc_entries_from_text(lines, x0_values)


def build_toc_index(entries: list) -> dict:
    """
    從解析後的目錄條目建立校正索引表。

    Returns:
        dict: {normalized_title: {"level": int, "page": int}}
    """
    index = {}
    for entry in entries:
        normalized = _normalize_title(entry["title"])
        if normalized:
            index[normalized] = {
                "level": entry["level"],
                "page": entry["page"]
            }
    return index


# ==============================================================================
# Private Helpers
# ==============================================================================

def _extract_block_text_ocr(block: dict) -> str:
    """從 OCR 管線 layout block 提取文字。"""
    parts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            content = span.get("content", "")
            if content:
                parts.append(content)
    return "".join(parts)


def _is_toc_entry_line(text: str) -> bool:
    """判斷一行文字是否看起來像目錄條目。"""
    if not text:
        return False
    # 含省略號/圓點序列 + 數字
    if re.search(r'[…·\.]{2,}\s*\d+', text):
        return True
    # 含制表符 + 數字
    if re.search(r'\t\s*\d+\s*$', text):
        return True
    # 章節格式 + 數字結尾
    if re.match(r'^第[一二三四五六七八九十百]+[章節条條篇卷]', text) and re.search(r'\d+\s*$', text):
        return True
    return False


def _infer_level_from_title(title: str) -> int:
    """根據標題文字內容推斷層級。"""
    # H1: 篇/章/卷 或特殊結構標題
    if (re.match(r'^[上下中]\s*篇', title) or
            re.match(r'^第[一二三四五六七八九十百零]+[章卷篇編]', title) or
            re.match(r'^(?:目錄|目录|序|結語|结语|後記|后记|前言|附錄|附录|主要參考文獻|主要参考文献)', title)):
        return 1

    # H2: 節 或短標題（無子標題格式）
    if re.match(r'^第[一二三四五六七八九十百零]+[節条條]', title):
        return 2

    # H3: 子節格式
    if (re.match(r'^[(（][一二三四五六七八九十\d]+[)）]', title) or
            re.match(r'^\d+\.\d+\.\d+', title)):
        return 3

    # Default: 根據位置推斷，暫時設為 H2
    return 2


def _adjust_level_by_indent(base_level: int, x0_values: list, idx: int) -> int:
    """根據 x0 縮進深度微調層級。"""
    if not x0_values or len(x0_values) < 3:
        return base_level

    # 計算所有 x0 的最小值作為基準
    min_x0 = min(x0_values)
    current_x0 = x0_values[idx]
    indent = current_x0 - min_x0

    # 縮進越深，層級越深
    if indent < 5:
        return max(1, base_level)  # 無縮進 → 保持或提升
    elif indent < 25:
        return max(2, base_level)  # 輕微縮進 → 至少 H2
    else:
        return max(3, base_level)  # 深度縮進 → 至少 H3


def _normalize_title(text: str) -> str:
    """正規化標題文字。"""
    text = text.strip()
    text = re.sub(r'\s+', '', text)
    text = text.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    return text
