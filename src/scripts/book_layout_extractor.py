# // ==============================================================================
# // book_layout_extractor.py: High-precision Book Vector Layout Extractor
# // - Header / Footer stripping
# // - Footnote extraction, bidirectional anchor matching, and Pandoc syntax
# // - Heading level detection (H1, H2, H3) with custom Word style mapping
# // - Chinese line wrap reflow (smooth paragraph splicing without intra-break)
# // - Comprehensive conversion auditing and tracking
# // ==============================================================================

import os
import re
import json
from pathlib import Path
from collections import Counter
from typing import Optional, Dict, Any, List, Tuple, Callable, Sequence, TYPE_CHECKING

# pyrefly: ignore [missing-import]
import fitz
from src.scripts.gemma_layout_assistant import DEFAULT_GEMMA_MODEL, gemma_available, review_uncertain_layout

if TYPE_CHECKING:
    from src.pod_studio.section_ast import BookAST, SectionAdapter, SectionUnit, ParagraphUnit
else:
    try:
        from src.pod_studio.section_ast import BookAST, SectionAdapter, SectionUnit, ParagraphUnit
    except ImportError:
        try:
            from pod_studio.section_ast import BookAST, SectionAdapter, SectionUnit, ParagraphUnit
        except ImportError:
            BookAST = Any
            SectionAdapter = Any
            SectionUnit = Any
            ParagraphUnit = Any

try:
    from src.founder_tools.core.toc_parser import (
        find_toc_pages_vector,
        parse_toc_entries_from_blocks_vector,
        build_toc_index,
    )
except ImportError:
    try:
        from founder_tools.core.toc_parser import (
            find_toc_pages_vector,
            parse_toc_entries_from_blocks_vector,
            build_toc_index,
        )
    except ImportError:
        find_toc_pages_vector = None
        parse_toc_entries_from_blocks_vector = None
        build_toc_index = None

try:
    from src.founder_tools.core.ai_kaiti_classifier import AIKaitiClassifier
except ImportError:
    AIKaitiClassifier = None

try:
    from src.extraction.table_reconstructor import (
        is_valid_pymupdf_table,
        extract_reconstructed_tables_from_page,
    )
except ImportError:
    try:
        from extraction.table_reconstructor import (
            is_valid_pymupdf_table,
            extract_reconstructed_tables_from_page,
        )
    except ImportError:
        is_valid_pymupdf_table = None
        extract_reconstructed_tables_from_page = None

try:
    from src.scripts.paragraph_reconstruction import update_delimiter_stack
except ImportError:
    try:
        from paragraph_reconstruction import update_delimiter_stack
    except ImportError:
        update_delimiter_stack = None

CIRCLED_MAP = {
    '①': 1, '②': 2, '③': 3, '④': 4, '⑤': 5,
    '⑥': 6, '⑦': 7, '⑧': 8, '⑨': 9, '⑩': 10,
    # Extended circled numbers ⑪–⑳ (U+246A–U+2473)
    '⑪': 11, '⑫': 12, '⑬': 13, '⑭': 14, '⑮': 15,
    '⑯': 16, '⑰': 17, '⑱': 18, '⑲': 19, '⑳': 20,
}

# Regex pattern matching any recognised footnote marker (circled / bracketed / numbered-dot / bare number with space)
# Added expanded unicode ranges for circled numbers > 10 and dingbats.
# Extended to support [1], ［1］, 〔1〕, 【1】, [ 1 ], (1), （1）, 1., 1、, and Unicode superscripts ⁰¹²³⁴⁵⁶⁷⁸⁹
FN_MARKER_PATTERN = r'([\u2460-\u24ff\u2780-\u2793\u3251-\u325f]|[\[［〔【]\s*\d+\s*[\]］〕】]|[\(（]\s*\d+\s*[\)）]|[\u2070\u00b9\u00b2\u00b3\u2074-\u2079]+|\d+[.、])'
_WEAK_MARKER_RE = re.compile(r'^[\d.、\s()（）]+$')
_DIGITS_RE = re.compile(r'\d+')
_FN_MARKER_SPLIT_RE = re.compile(FN_MARKER_PATTERN)
_STARTS_WITH_FN_MARKER_RE = re.compile(r'^\s*(' + FN_MARKER_PATTERN + r')\s*')
_FN_MARKER_PARSE_RE = re.compile(r'^\s*([①-⑩\u2460-\u24ff\u2780-\u2793\u3251-\u325f]|[\[［〔【]\s*\d+\s*[\]］〕】]|[\(（]\s*\d+\s*[\)）]|[\u2070\u00b9\u00b2\u00b3\u2074-\u2079]+|\d+[.、])\s*')

_PAGE_HEADER_PATTERNS = [
    re.compile(r'^[上下中]篇[:：|｜]'),
    re.compile(r'第[一二三四五六七八九十百]+章'),
    re.compile(r'^/\s*\d+'),
    re.compile(r'^\d+\s*/'),
    re.compile(r'^\d{1,4}$'),
    re.compile(r'^(?:目\s*录|目录|序|结语|主要参考文献|后\s*记|后记)\s*/'),
    re.compile(r'/\s*(?:目\s*录|目录|序|结语|主要参考文献|后\s*记|后记)')
]
_HEADER_DIGITS_RE = re.compile(r'^\d+$')
_FOOTER_PAGE_NUM_RE = re.compile(r'^\s*\d{1,4}\s*$')

_CJK_END_RE = re.compile(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]$')
_CJK_START_RE = re.compile(r'^[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]')
_TOC_LINE_RE = re.compile(r'[\.…·\u0107\x08\-_]{2,}\s*\d+$')
_CLEAN_FOR_HEADING_RE = re.compile(r'[①-⑩\u2460-\u2473\s]')
_HEADING_PREFIX_CLEAN_RE = re.compile(r'^(?:第[一二三四五六七八九十百零\d]+[章节條条回讲講篇卷]|(?:Chapter|Part)\s*\d+|[一二三四五六七八九十百\d]+[、. \u3000]+|[（(][一二三四五六七八九十\d]+[)）]|\d+\.\d+(?:\.\d+)?)\s*', re.I)
_SENTENCE_PUNCT_RE = re.compile(r'[。，；？！“”‘’：:]')
_STYLE_HEADING1_RE = re.compile(r'標題\s*1|heading\s*1', re.I)
_STYLE_HEADING2_RE = re.compile(r'標題\s*2|heading\s*2', re.I)
_STYLE_HEADING3_RE = re.compile(r'標題\s*3|heading\s*3', re.I)
_STYLE_CAPTION_RE = re.compile(r'圖說|图说|caption', re.I)
_STYLE_KAI_RE = re.compile(r'楷|kai', re.I)

_H1_PART_RE = re.compile(r'^(?:[上下中]\s*篇(?:\s+[^\n]+)?)$')
_H1_SPECIAL_RE = re.compile(r'^(?:目\s*录|目录|序|后\s*记|后记|结\s*语|结语|主要参考文献)$')
_H1_CHAPTER_RE = re.compile(r'^(?:第[一二三四五六七八九十百零\d]+[章卷篇]|(?:Chapter|Part)\s*\d+)(?:\s+[^\n]+)?$', re.I)
_H2_SECTION_RE = re.compile(r'^第[一二三四五六七八九十百零\d]+[节節回讲講](?:\s+[^\n]+)?$')
_H2_NUM_RE = re.compile(r'^[一二三四五六七八九十百]+[、.· ][^\n]{2,30}$')
_H2_INT_SPACE_RE = re.compile(r'^\d+[\s\u3000]+[\u4e00-\u9fff]{2,15}$')
_H2_DECIMAL_RE = re.compile(r'^\d+\.\d+(?:[\s\u3000]+[^\n]{1,40})?$')
_H3_DECIMAL_RE = re.compile(r'^\d+\.\d+\.\d+(?:[\s\u3000]+[^\n]{1,40})?$')
_LIST_NUM_PREFIX_RE = re.compile(r'^\d+[、.·](?!\d)')
_H3_SUB_RE1 = re.compile(r'^[（(][一二三四五六七八九十\d]+[)）]')
_CHART_TABLE_END_RE = re.compile(r'示意图|表$')
_CIRCLED_START_RE = re.compile(r'^[①-⑩]')
_IMG_PLACEHOLDER_RE = re.compile(r'!\[__IMG_PLACEHOLDER_(\d+)_(\d+)__\]\(\)')
_STANDALONE_HEADING_LINE_RE = re.compile(
    r'^(?:\d+[\s\u3000]+[\u4e00-\u9fff]{2,15}|\d+\.\d+(?:\.\d+)?[\s\u3000]+[\u4e00-\u9fff]{2,25}|第[一二三四五六七八九十百零\d]+[章节節篇卷][\s\u3000]*[^\n]{0,25})$'
)
_TRAILING_HEADING_SPLIT_RE = re.compile(
    r'^(.+[。！？）\)”’])\s*(\d+[\s\u3000]+[\u4e00-\u9fff]{2,15}|\d+\.\d+(?:\.\d+)?[\s\u3000]+[\u4e00-\u9fff]{2,25})$'
)
_TERMINAL_PUNCT_RE = re.compile(r'[。！？!?…]+[”’」』）)\]】]*$')
_TRAILING_MARK_RE = re.compile(r'(?:\[\d+(?:[-–,，]\d+)*\]|[①-⑳]|\^\[\d+\])+$')
_PARA_START_PREFIX_RE = re.compile(r'^(?:[（(]?[一二三四五六七八九十\d]+[)）、.．]|[①-⑳]|[•●◆■※★\-])')
_OPEN_PUNCT_RE = re.compile(r'[《“（(\[〈]$')



def _split_merged_heading_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Splits multi-line text blocks when PyMuPDF merges a standalone heading line
    (e.g. '1　临床资料' or '4 　讨论' whose tall font ascender touches the previous paragraph's bottom)
    into an adjacent body text block.
    """
    expanded: List[Dict[str, Any]] = []
    for b in blocks:
        if b.get("type") != 0:
            expanded.append(b)
            continue
        lines = b.get("lines", [])
        if len(lines) <= 1:
            expanded.append(b)
            continue

        has_heading_line = any(
            _STANDALONE_HEADING_LINE_RE.match(
                "".join(s.get("text", "") for s in ln.get("spans", [])).strip()
            )
            for ln in lines
        )
        if not has_heading_line:
            expanded.append(b)
            continue

        cur_group: List[Dict[str, Any]] = []
        for ln in lines:
            ln_txt = "".join(s.get("text", "") for s in ln.get("spans", [])).strip()
            if _STANDALONE_HEADING_LINE_RE.match(ln_txt):
                if cur_group:
                    grp_bbox = _union_bboxes([g.get("bbox") for g in cur_group if g.get("bbox")]) or b.get("bbox", [0, 0, 0, 0])
                    expanded.append({"type": 0, "bbox": grp_bbox, "lines": cur_group})
                    cur_group = []
                ln_bbox = list(ln.get("bbox", b.get("bbox", [0, 0, 0, 0])))
                expanded.append({"type": 0, "bbox": ln_bbox, "lines": [ln]})
            else:
                cur_group.append(ln)
        if cur_group:
            grp_bbox = _union_bboxes([g.get("bbox") for g in cur_group if g.get("bbox")]) or b.get("bbox", [0, 0, 0, 0])
            expanded.append({"type": 0, "bbox": grp_bbox, "lines": cur_group})

    return expanded


def _normalize_title(text: str) -> str:
    """Normalize heading/TOC text for matching: strip whitespace, full-width digits, marker symbols."""
    text = re.sub(r'[\s①-⑩\u2460-\u2473]+', '', text.strip())
    text = text.translate(str.maketrans('０１２３４５６７８９．：', '0123456789.:'))
    return text


def _simple_similarity(a: str, b: str) -> float:
    """Character-level Jaccard similarity between two normalized strings."""
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _union_bboxes(bboxes: Sequence[Optional[Sequence[float]]]) -> Optional[List[float]]:
    """Computes the minimal bounding box enclosing all valid non-empty bboxes."""
    valid_boxes = [b for b in bboxes if b and len(b) == 4 and b[2] > b[0] and b[3] > b[1]]
    if not valid_boxes:
        return None
    x0 = min(b[0] for b in valid_boxes)
    y0 = min(b[1] for b in valid_boxes)
    x1 = max(b[2] for b in valid_boxes)
    y1 = max(b[3] for b in valid_boxes)
    return [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]


def _compute_dominant_font_and_size(
    blocks: Sequence[Dict[str, Any]],
    fallback_font: str = "",
    fallback_size: float = 10.5,
) -> Tuple[str, float]:
    """
    Computes dominant font name (by character count) and character-weighted average font size
    from contributing blocks and their spans.
    """
    font_counter: Counter = Counter()
    total_chars = 0
    size_weighted_sum = 0.0

    for b in blocks:
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                txt = span.get("text", "")
                if not txt:
                    continue
                char_len = len(txt)
                total_chars += char_len
                raw_font = (span.get("font") or "").split("+", 1)[-1]
                if raw_font:
                    font_counter[raw_font] += char_len
                span_size = float(span.get("size", 0.0))
                if span_size > 0:
                    size_weighted_sum += span_size * char_len

    dominant_font = font_counter.most_common(1)[0][0] if font_counter else fallback_font
    if not dominant_font:
        dominant_font = fallback_font or "SimSun"

    avg_size = round(size_weighted_sum / total_chars, 2) if total_chars > 0 else fallback_size
    if avg_size <= 0.0:
        avg_size = fallback_size or 10.5

    return dominant_font, avg_size


def build_document_profile(doc: fitz.Document) -> dict:
    """
    毫秒級全書特徵探勘：
    1. 統計正文基準字級 (body_size)、主字體 (body_font)
    2. 結合 PDF 原生書籤 (doc.get_toc()) 與目錄頁解析 (toc_parser) 建立全書標題索引
    """
    font_counter = Counter()
    size_counter = Counter()
    toc_index = {}
    is_native_toc = False

    # 1A. 優先提取 PDF 內建書籤 (若有內建書籤，準確率 100% 且耗時 0ms)
    try:
        raw_toc = getattr(doc, "get_toc", lambda: [])()
    except Exception:
        raw_toc = []

    if raw_toc:
        for item in raw_toc:
            if len(item) >= 3:
                level, title, page_num = item[0], item[1], item[2]
                norm_t = _normalize_title(str(title))
                if norm_t:
                    toc_index[norm_t] = {"level": min(int(level), 3), "page": int(page_num)}
        if toc_index:
            is_native_toc = True

    # 1B. 若無內建書籤，呼叫專案既有的 toc_parser 解析目錄頁
    if not toc_index and find_toc_pages_vector and parse_toc_entries_from_blocks_vector and build_toc_index:
        try:
            toc_start, toc_end = find_toc_pages_vector(doc)
            if toc_start is not None:
                toc_entries = []
                for p_idx in range(toc_start, (toc_end or toc_start) + 1):
                    blocks = getattr(doc[p_idx], "get_text")("dict").get("blocks", [])
                    toc_entries.extend(parse_toc_entries_from_blocks_vector(blocks))
                if toc_entries:
                    parsed_idx = build_toc_index(toc_entries)
                    if parsed_idx:
                        toc_index = parsed_idx
        except Exception:
            pass

    # 2. 抽樣前 35 頁統計「正文基準字體與字級」
    sample_indices = range(min(len(doc), 35))
    for p_idx in sample_indices:
        try:
            page_dict = getattr(doc[p_idx], "get_text")("dict")
        except Exception:
            continue
        for b in page_dict.get("blocks", []):
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    txt = span.get("text", "").strip()
                    if len(txt) >= 5:  # 以長句統計正文特徵
                        sz = round(span.get("size", 10.5) * 2) / 2
                        fn = (span.get("font") or "").split("+", 1)[-1].lower()
                        size_counter[sz] += len(txt)
                        font_counter[fn] += len(txt)

    body_size = size_counter.most_common(1)[0][0] if size_counter else 10.5
    body_font = font_counter.most_common(1)[0][0] if font_counter else ""

    return {
        "body_size": body_size,
        "body_font": body_font,
        "toc_index": toc_index,
        "is_native_toc": is_native_toc,
    }


def _match_toc_heading(text: str, page_num: int, toc_index: dict, offset_holder: list) -> int:
    """
    將候選標題文字與 TOC 索引表做匹配，支援動態頁碼偏移量校準。
    offset_holder: [calibrated_offset] (None or int)
    """
    if not toc_index:
        return 0
    norm_t = _normalize_title(text)
    if not norm_t or len(norm_t) < 2:
        return 0

    # 1. 精確匹配
    if norm_t in toc_index:
        entry = toc_index[norm_t]
        expected_p = entry.get("page", 0)
        lvl = entry.get("level", 2)

        if offset_holder[0] is not None:
            if abs((expected_p + offset_holder[0]) - page_num) <= 3:
                return lvl
        else:
            if abs(expected_p - page_num) <= 2:
                offset_holder[0] = 0
                return lvl
            elif page_num >= expected_p:
                offset_holder[0] = page_num - expected_p
                return lvl

    # 2. Fuzzy 匹配 (針對標題有微小空白或符號差異)
    for toc_title, entry in toc_index.items():
        expected_p = entry.get("page", 0)
        lvl = entry.get("level", 2)
        if offset_holder[0] is not None:
            if abs((expected_p + offset_holder[0]) - page_num) > 3:
                continue
        elif abs(expected_p - page_num) > 3 and page_num < expected_p:
            continue

        sim = _simple_similarity(norm_t, toc_title)
        if sim >= 0.82:
            if offset_holder[0] is None and page_num >= expected_p:
                offset_holder[0] = page_num - expected_p
            return lvl

    return 0


_SUPERSCRIPT_CHAR_MAP = {
    '⁰': 0, '¹': 1, '²': 2, '³': 3, '⁴': 4,
    '⁵': 5, '⁶': 6, '⁷': 7, '⁸': 8, '⁹': 9
}

def _circled_to_int(marker_str: str) -> int:
    """Convert any footnote marker string to its integer index."""
    if marker_str in CIRCLED_MAP:
        return CIRCLED_MAP[marker_str]
    if any(c in _SUPERSCRIPT_CHAR_MAP for c in marker_str):
        digits = "".join(str(_SUPERSCRIPT_CHAR_MAP[c]) for c in marker_str if c in _SUPERSCRIPT_CHAR_MAP)
        if digits:
            return int(digits)
    digs = _DIGITS_RE.findall(marker_str)
    return int(digs[0]) if digs else 1


def _replace_fn_markers_in_text(text: str, page_footnotes: list, page_num: int) -> str:
    """Replace all recognised footnote marker occurrences in *text* with Pandoc ref-tags.
    Works for both body paragraphs and table cells."""
    for fn in page_footnotes:
        m_str = fn.get('marker', '')
        fn_id = fn.get('id', 1)
        if not m_str and not fn_id:
            continue
        fn_tag = f"[^p{page_num}_{fn_id}]"

        matched = False
        # 1. 優先嘗試原始標記完全匹配
        if m_str:
            if _WEAK_MARKER_RE.match(m_str):
                # 針對弱標記（如 '1.' 或 '(1)'），要求前後不能是數字以防止誤傷小數點（如 31.5%）或正文數值
                safe_pat = re.compile(r'(?<!\d)' + re.escape(m_str) + r'(?!\d)')
                new_text, n_subs = safe_pat.subn(fn_tag, text, count=1)
                if n_subs > 0:
                    text = new_text
                    fn['matched'] = True
                    matched = True
            elif m_str in text:
                text = text.replace(m_str, fn_tag, 1)
                fn['matched'] = True
                matched = True

        # 2. 次優先：若原始標記未能命中（例如頁底標記為 "1." 或 "[1]"，而正文為 "[1]"、"［1］"、"〔1〕" 等變體），
        # 檢查該 fn_id 對應的強括號/圓圈標記變體
        if not matched and fn_id is not None:
            variants = [
                f"[{fn_id}]",
                f"［{fn_id}］",
                f"〔{fn_id}〕",
                f"【{fn_id}】",
                f"[ {fn_id} ]",
                f"［ {fn_id} ］",
            ]
            rev_circled = [k for k, v in CIRCLED_MAP.items() if v == fn_id]
            if rev_circled:
                variants.append(rev_circled[0])

            for var in variants:
                if var in text:
                    text = text.replace(var, fn_tag, 1)
                    fn['matched'] = True
                    break
    return text


def _table_to_markdown(table, page_footnotes: list, page_num: int) -> str:
    """Convert a PyMuPDF Table object to a GFM Markdown table string.
    Footnote markers inside cells are replaced with Pandoc ref-tags."""
    try:
        rows = table.extract()  # list[list[str|None]]
    except Exception:
        return ""
    if not rows:
        return ""

    md_rows = []
    for r_idx, row in enumerate(rows):
        cells = []
        for cell in row:
            cell_text = (cell or "").replace("\n", " ").strip()
            # Replace footnote markers inside cells
            cell_text = _replace_fn_markers_in_text(cell_text, page_footnotes, page_num)
            # Escape pipe characters inside cells
            cell_text = cell_text.replace("|", "\\|")
            cells.append(cell_text)
        md_rows.append("| " + " | ".join(cells) + " |")
        if r_idx == 0:
            # Insert separator row after header
            md_rows.append("|" + "|".join([" --- " for _ in cells]) + "|")

    return "\n".join(md_rows)

def clean_span_duplicates(spans):
    """Filter out duplicate spans caused by PDF shadow/fake-bold text rendering."""
    clean = []
    seen = set()
    for s in spans:
        txt = s.get('text', '')
        if not txt:
            continue
        bbox = tuple(round(v, 1) for v in s.get('bbox', [0, 0, 0, 0]))
        key = (bbox, txt)
        if key not in seen:
            seen.add(key)
            clean.append(s)
    return clean

def is_page_header(block, page_h, page_w):
    bbox = block.get('bbox', [0, 0, 0, 0])
    # Headers are strictly in top 13% of the page
    if bbox[3] > page_h * 0.13:
        return False
    
    text = "".join(s['text'] for l in block.get('lines', []) for s in l.get('spans', [])).strip()
    if not text:
        return False
        
    for pat in _PAGE_HEADER_PATTERNS:
        if pat.search(text):
            return True
    # If text is very short single page number or header text in extreme top margin
    if bbox[1] < page_h * 0.11 and (_HEADER_DIGITS_RE.match(text) or len(text) <= 30 and '/' in text):
        return True
    return False

def is_page_footer(block, page_h):
    bbox = block.get('bbox', [0, 0, 0, 0])
    # Footers are strictly in bottom 10%
    if bbox[1] < page_h * 0.90:
        return False
    text = "".join(s['text'] for l in block.get('lines', []) for s in l.get('spans', [])).strip()
    # Solitary page numbers
    if _FOOTER_PAGE_NUM_RE.match(text):
        return True
    return False

def parse_footnote_marker(text):
    m = _FN_MARKER_PARSE_RE.match(text)
    if m:
        marker_str = m.group(1).strip()
        num = CIRCLED_MAP.get(marker_str)
        if not num:
            digs = _DIGITS_RE.findall(marker_str)
            num = int(digs[0]) if digs else 1
        return num, marker_str, text[m.end():].strip()
    return None, None, text

_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def _sort_blocks_by_row_and_x(blocks: List[Dict[str, Any]], y_tol: float = 5.0) -> List[Dict[str, Any]]:
    """Cluster blocks into horizontal bands within y_tol and sort each band left-to-right."""
    if len(blocks) <= 1:
        return list(blocks)
    by_y = sorted(
        blocks,
        key=lambda b: (
            (b.get("bbox", [0, 0, 0, 0])[1] + b.get("bbox", [0, 0, 0, 0])[3]) / 2.0,
            b.get("bbox", [0, 0, 0, 0])[0],
        ),
    )
    rows: List[List[Dict[str, Any]]] = []
    row_anchors: List[float] = []
    for b in by_y:
        bbox = b.get("bbox", [0, 0, 0, 0])
        yc = (bbox[1] + bbox[3]) / 2.0
        if rows and abs(yc - row_anchors[-1]) <= y_tol:
            rows[-1].append(b)
        else:
            rows.append([b])
            row_anchors.append(yc)
    ordered: List[Dict[str, Any]] = []
    for r in rows:
        r.sort(key=lambda b: b.get("bbox", [0, 0, 0, 0])[0])
        ordered.extend(r)
    return ordered


def _extract_primary_font_key(lines: List[Dict[str, Any]], default_size: float = 10.5) -> Tuple[str, str, float]:
    """Return (font_key, clean_font_name, rounded_size) prioritizing CJK spans by character count."""
    best_cjk_fn = ""
    best_cjk_size = default_size
    best_cjk_len = -1
    best_any_fn = ""
    best_any_size = default_size
    best_any_len = -1
    for ln in lines:
        for sp in ln.get("spans", []):
            txt = (sp.get("text") or "").strip()
            raw_fn = (sp.get("font") or "").split("+", 1)[-1].strip()
            if not raw_fn or not txt:
                continue
            sz = round(float(sp.get("size", default_size) or default_size) * 2) / 2
            cjk_len = len(_CJK_CHAR_RE.findall(txt))
            if cjk_len > best_cjk_len:
                best_cjk_len = cjk_len
                best_cjk_fn = raw_fn
                best_cjk_size = sz
            if len(txt) > best_any_len:
                best_any_len = len(txt)
                best_any_fn = raw_fn
                best_any_size = sz
    chosen_fn = best_cjk_fn if best_cjk_len > 0 else best_any_fn
    chosen_sz = best_cjk_size if best_cjk_len > 0 else best_any_size
    if not chosen_fn:
        return "", "", default_size
    return f"{chosen_fn} ({chosen_sz}pt)", chosen_fn, chosen_sz


def _lookup_block_font_mapping(
    lines: List[Dict[str, Any]],
    font_role_map: Optional[Dict[str, Any]],
    is_toc_line: bool = False,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Lookup (role, docx_style, mapped_by) prioritizing CJK spans over leading ASCII digits."""
    if not font_role_map or is_toc_line:
        return None, None, None
    ordered_spans = []
    for idx_l, _line in enumerate(lines):
        for idx_s, _span in enumerate(_line.get("spans", [])):
            txt = (_span.get("text") or "").strip()
            has_cjk = 1 if _CJK_CHAR_RE.search(txt) else 0
            ordered_spans.append((has_cjk, len(txt), -idx_l, -idx_s, _span))
    ordered_spans.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)

    for _, _, _, _, _span in ordered_spans:
        _raw_fn = (_span.get("font") or "").split("+", 1)[-1]
        if not _raw_fn:
            continue
        _size = round(_span.get("size", 0) * 2) / 2
        _candidates = [
            f"{_raw_fn} ({_size}pt)",
            f"{_raw_fn} ({_size:.1f}pt)",
            f"{_raw_fn}_{_size}",
            _raw_fn,
        ]
        for _cand in _candidates:
            if _cand in font_role_map:
                _entry = font_role_map[_cand]
                _role = _entry.get("role")
                _style = _entry.get("docx_style")
                _mapped_by = _entry.get("mapped_by")
                if _role or _style:
                    return _role, _style, _mapped_by
    return None, None, None


def _map_ai_review_to_font_suggestion(
    review: Dict[str, Any],
    style_mapping: Dict[str, str],
    sample_text: str,
) -> Optional[Dict[str, Any]]:
    """Convert a review_uncertain_layout decision into a persistable fonts.json suggestion."""
    role = review.get("role")
    level = review.get("level")
    ui_role: Optional[str] = None
    docx_style: Optional[str] = None
    if role == "heading":
        lvl = level if level in (1, 2, 3) else 2
        ui_role = f"H{lvl}"
        docx_style = style_mapping.get(f"h{lvl}") or f"heading {lvl}"
    elif role == "quote":
        ui_role = "楷體"
        docx_style = style_mapping.get("kaiti") or None
    elif role == "caption":
        ui_role = "圖說"
        docx_style = style_mapping.get("image_caption") or None
    elif role == "body":
        ui_role = "正文"
        docx_style = style_mapping.get("body") or "Normal"
    if not ui_role:
        return None
    return {
        "role": ui_role,
        "docx_style": docx_style,
        "confidence": review.get("confidence"),
        "reason": review.get("reason", ""),
        "sample": sample_text[:60],
        "mapped_by": "ai_layout",
    }


def _parse_pdf_layout_flow(
    doc: fitz.Document,
    pdf_name: str = "",
    style_mapping: Optional[Dict[str, str]] = None,
    font_role_map: Optional[Dict[str, Any]] = None,
    enable_footnotes: bool = True,
    ai_kaiti_classifier: Optional[Any] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    page_range: Optional[Tuple[int, int]] = None,
    strip_headers_heuristic: bool = False,
) -> Tuple[List[str], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """
    純記憶體版面與流式閱讀解析核心 (Pure Parsing Core)。
    
    職責：
    - 遍歷 PDF 頁面結構，執行表格偵測、頁眉/頁尾剔除、腳注解析、標題識別、段落防黏連重流。
    - 產出未嵌入圖檔路徑之 Markdown 頁面字串（含圖片佔位符號）、待提取圖檔幾何資訊清單與稽核數據。
    - 保留結構化 layout_records (段落、幾何 bbox、字型、字級、樣式)，供 AST 構建器使用。
    - 絕不執行任何檔案建立、磁碟寫入（images/、.md、稀有字報告）或目錄變更等副作用。
    """
    if style_mapping is None:
        style_mapping = {}
    total_pages = len(doc)
    
    # ── 全書特徵探勘與目錄索引建立 ──
    doc_profile = build_document_profile(doc)
    body_size = doc_profile.get("body_size", 10.5)
    body_font = doc_profile.get("body_font", "")
    toc_index = doc_profile.get("toc_index", {})
    toc_page_offset = [0 if doc_profile.get("is_native_toc") else None]
    if toc_index:
        print(f"[DocProfile] 成功建立標題索引共 {len(toc_index)} 筆 (原生書籤: {doc_profile.get('is_native_toc')})，正文基準: {body_size}pt / '{body_font}'")

    retained_font_suggestions: Dict[str, Dict[str, Any]] = {}
    ai_font_decision_cache: Dict[str, Dict[str, Any]] = {}
    if font_role_map:
        for _fk, _fval in font_role_map.items():
            if isinstance(_fval, dict) and _fval.get("mapped_by") == "ai_layout":
                _r = str(_fval.get("role") or "").upper()
                if _r in ("H1", "H2", "H3"):
                    ai_font_decision_cache[_fk] = {
                        "role": "heading",
                        "level": int(_r[1]),
                        "confidence": _fval.get("confidence", 0.85),
                        "reason": _fval.get("reason", "retained_ai_layout"),
                        "source": "gemma",
                    }
                elif _r in ("楷體", "楷体", "KAITI", "QUOTE"):
                    ai_font_decision_cache[_fk] = {
                        "role": "quote",
                        "level": None,
                        "confidence": _fval.get("confidence", 0.85),
                        "reason": _fval.get("reason", "retained_ai_layout"),
                        "source": "gemma",
                    }
                elif _r in ("正文", "內文", "BODY"):
                    ai_font_decision_cache[_fk] = {
                        "role": "body",
                        "level": None,
                        "confidence": _fval.get("confidence", 0.85),
                        "reason": _fval.get("reason", "retained_ai_layout"),
                        "source": "gemma",
                    }

    audit_data = {
        "pdf_name": pdf_name,
        "total_pages": total_pages,
        "headers_removed": 0,
        "footers_removed": 0,
        "headings_detected": [],
        "footnotes_matched": 0,
        "footnotes_fallback": 0,
        "footnotes_detail": [],
        "paragraphs_reflowed": 0,
        "ai_layout": {
            "model": DEFAULT_GEMMA_MODEL,
            "model_available": False,
            "confirmed_style_mapping": dict(style_mapping),
            "retained_font_suggestions": retained_font_suggestions,
            "decisions": [],
        },
        "doc_profile": {
            "body_size": body_size,
            "body_font": body_font,
            "toc_entries": len(toc_index),
            "is_native_toc": doc_profile.get("is_native_toc", False),
        }
    }
    audit_data["ai_layout"]["model_available"] = gemma_available(DEFAULT_GEMMA_MODEL)
    if not audit_data["ai_layout"]["model_available"]:
        print(f"[WARN] 本機未安裝 {DEFAULT_GEMMA_MODEL}，標題與斷行使用確定性判定。", flush=True)
    
    final_md_pages = []
    all_image_blocks = []
    layout_records = []

    start_page_idx = 0
    end_page_idx = total_pages
    if page_range:
        start_page_idx = max(0, page_range[0] - 1)
        end_page_idx = min(total_pages, page_range[1])

    for page_idx in range(start_page_idx, end_page_idx):
        page_num = page_idx + 1
        if progress_callback:
            progress_pct = int((page_num / total_pages) * 85)
            progress_callback(progress_pct, f"[INFO] 正在解析第 {page_num}/{total_pages} 頁 (版面/樣式/腳注抽取)...")
            
        page: Any = doc[page_idx]
        page_h = page.rect.height
        page_w = page.rect.width
        
        blocks = _split_merged_heading_blocks(page.get_text("dict").get("blocks", []))

        # ── Step 0: Detect tables via PyMuPDF find_tables() + 3-Line Table Reconstructor ──
        # Collect table bbox regions so we can exclude their text from body_blocks.
        page_tables = []  # list of fitz.table.Table objects
        reconstructed_tables = []  # list of ReconstructedTable objects (3-line tables)
        table_bboxes = []  # list of fitz.Rect for overlap checks

        def _block_overlaps_any_table(bbox_list, block_bbox):
            """Return True if block_bbox overlaps any known table region by >30%."""
            b = fitz.Rect(block_bbox)
            for tr in bbox_list:
                inter = b & tr
                if inter.is_empty:
                    continue
                inter_area = inter.width * inter.height
                b_area = b.width * b.height
                if inter_area / max(b_area, 1.0) > 0.30:
                    return True
            return False

        # Priority 1: High-precision 2D coordinate clustering for borderless 3-line tables
        if extract_reconstructed_tables_from_page is not None:
            try:
                three_line_list = extract_reconstructed_tables_from_page(page, blocks=blocks)
                for rtbl in three_line_list:
                    if not _block_overlaps_any_table(table_bboxes, rtbl.bbox):
                        reconstructed_tables.append(rtbl)
                        table_bboxes.append(fitz.Rect(rtbl.bbox))
            except Exception:
                pass

        # Priority 2: PyMuPDF standard bordered grid table detection (skipped if region already claimed)
        try:
            tabs = page.find_tables()
            if tabs and tabs.tables:
                for t in tabs.tables:
                    if _block_overlaps_any_table(table_bboxes, t.bbox):
                        continue
                    if is_valid_pymupdf_table is not None:
                        try:
                            cells = t.extract()
                        except Exception:
                            cells = []
                        if not is_valid_pymupdf_table(cells, t.bbox, page_w, page_h):
                            continue
                    page_tables.append(t)
                    table_bboxes.append(fitz.Rect(t.bbox))
        except Exception:
            pass  # find_tables() not available in older PyMuPDF – graceful fallback

        # Step 1: Collect valid text blocks, separate header/footer/footnote
        body_blocks = []
        footnote_blocks = []
        figure_blocks = []

        for b in blocks:
            block_type = b.get("type")
            
            if block_type == 1:
                if not (strip_headers_heuristic and (is_page_header(b, page_h, page_w) or is_page_footer(b, page_h))):
                    if not (table_bboxes and _block_overlaps_any_table(table_bboxes, b.get("bbox", [0, 0, 0, 0]))):
                        figure_blocks.append(b)
                continue
                
            if block_type != 0:
                continue

            # Clean duplicate spans within lines
            for line in b.get("lines", []):
                line["spans"] = clean_span_duplicates(line.get("spans", []))

            block_text = "".join(s.get("text", "") for l in b.get("lines", []) for s in l.get("spans", [])).strip()
            if not block_text:
                continue

            if strip_headers_heuristic and is_page_header(b, page_h, page_w):
                audit_data["headers_removed"] += 1
                continue
            if strip_headers_heuristic and is_page_footer(b, page_h):
                audit_data["footers_removed"] += 1
                continue

            bbox = b.get("bbox", [0, 0, 0, 0])

            # Skip blocks that belong to a detected table region
            # (they will be rendered via _table_to_markdown instead)
            if table_bboxes and _block_overlaps_any_table(table_bboxes, bbox):
                continue

            # Check if block is in footnote area:
            # Footnotes are located near bottom of page (y >= page_h * 0.72)
            # and MUST START with a footnote marker or be an immediate continuation of one
            sizes = [s.get("size", 0) for l in b.get("lines", []) for s in l.get("spans", [])]
            avg_size = sum(sizes) / len(sizes) if sizes else 10.0

            is_fn = False
            if enable_footnotes:
                starts_with_fn_marker = bool(_STARTS_WITH_FN_MARKER_RE.match(block_text))
                if bbox[1] >= page_h * 0.65 and avg_size < body_size:
                    if starts_with_fn_marker and not _H3_DECIMAL_RE.match(block_text) and not _H2_DECIMAL_RE.match(block_text):
                        is_fn = True
                    elif footnote_blocks and avg_size <= 10.0:
                        # Immediate subsequent block below a footnote block with small font
                        is_fn = True

            if is_fn:
                footnote_blocks.append(b)
            else:
                body_blocks.append(b)
                
        # Step 2: Parse footnotes on this page
        page_footnotes = []  # list of {id, marker, content, matched}
        current_fn_entry = None
        footnote_blocks = _sort_blocks_by_row_and_x(footnote_blocks, y_tol=5.0)

        for fb in footnote_blocks:
            fb_text = "".join(
                s.get("text", "") for l in fb.get("lines", []) for s in l.get("spans", [])
            ).strip()
            if not fb_text:
                continue

            # Split block text by ANY recognised footnote marker
            # This handles both circled numbers and [n] / (n) / n. styles
            parts = _FN_MARKER_SPLIT_RE.split(fb_text)

            # parts[0] — text before the first marker (may be empty)
            prefix = parts[0]
            m_start = _STARTS_WITH_FN_MARKER_RE.match(prefix)
            if m_start:
                # The prefix itself *is* a marker (split captured it)
                pass  # handled below in the loop
            elif prefix.strip():
                # Plain continuation text before any marker
                if current_fn_entry:
                    sep = " " if current_fn_entry["content"] else ""
                    current_fn_entry["content"] = str(current_fn_entry["content"]) + sep + prefix.strip()
                else:
                    # Orphaned text — treat as footnote #1 continuation
                    current_fn_entry = {"id": 1, "marker": "", "content": prefix.strip()}

            # Iterate: parts alternates [text, marker, text, marker, text ...]
            for i in range(1, len(parts), 2):
                marker_str = parts[i].strip()
                content_str = parts[i + 1].strip() if (i + 1) < len(parts) else ""

                num = _circled_to_int(marker_str)

                if current_fn_entry:
                    page_footnotes.append(current_fn_entry)

                current_fn_entry = {"id": num, "marker": marker_str, "content": content_str}

        if current_fn_entry:
            page_footnotes.append(current_fn_entry)

        # Step 3: Determine base_x0 and max_x1 for body paragraphs on this page
        normal_x0s = []
        normal_x1s = []
        for bb in body_blocks:
            lines = bb.get("lines", [])
            bb_text = "".join(s.get("text", "") for l in lines for s in l.get("spans", [])).strip()
            bbox = bb.get("bbox", [0, 0, 0, 0])
            center_x = (bbox[0] + bbox[2]) / 2.0
            is_centered = abs(center_x - (page_w / 2.0)) < (page_w * 0.12)
            if not is_centered and len(bb_text) > 10:
                normal_x0s.append(bbox[0])
                normal_x1s.append(bbox[2])
        base_x0 = min(normal_x0s) if normal_x0s else 65.0
        max_x1 = max(normal_x1s) if normal_x1s else (page_w - base_x0)

        page_paragraphs = []
        current_para_lines = []
        current_para_contributing_blocks = []
        current_para_is_kaiti = False
        current_para_custom_style = None
        last_block_x0 = 0.0
        last_block_x1 = 0.0
        last_block_y1 = 0.0
        last_block_last_line_x1 = 0.0
        last_heading_text = ""

        def flush_current_para():
            nonlocal current_para_lines, current_para_contributing_blocks, current_para_is_kaiti, current_para_custom_style
            if current_para_lines:
                # Splice lines smoothly
                para_text = ""
                for line_txt in current_para_lines:
                    if not para_text:
                        para_text = line_txt
                    else:
                        cjk_end = bool(_CJK_END_RE.search(para_text))
                        cjk_start = bool(_CJK_START_RE.search(line_txt))
                        if cjk_end and cjk_start:
                            para_text += line_txt
                            audit_data["paragraphs_reflowed"] += 1
                        else:
                            para_text += " " + line_txt

                # Split trailing inline heading if merged at sentence end (e.g. "...（疗效对比时剔除）。 4 讨论")
                trailing_h_text = ""
                m_trail = _TRAILING_HEADING_SPLIT_RE.match(para_text.strip())
                if m_trail:
                    para_text = m_trail.group(1).strip()
                    trailing_h_text = m_trail.group(2).strip()

                custom_style_val = ""
                if current_para_custom_style:
                    # Apply specific custom Word style from font mapping
                    custom_style_val = current_para_custom_style
                    para_md = f'::: {{custom-style="{current_para_custom_style}"}}\n{para_text}\n:::'
                elif current_para_is_kaiti:
                    # Apply custom Word style instead of basic blockquote
                    kaiti_style = style_mapping.get("kaiti") or "楷體2"
                    custom_style_val = kaiti_style
                    para_md = f'::: {{custom-style="{kaiti_style}"}}\n{para_text}\n:::'
                else:
                    body_style = style_mapping.get("body")
                    if body_style:
                        custom_style_val = body_style
                        para_md = f'::: {{custom-style="{body_style}"}}\n{para_text}\n:::'
                    else:
                        para_md = para_text
                page_paragraphs.append(para_md)

                # Record structured paragraph block
                para_bbox = _union_bboxes([b.get("bbox") for b in current_para_contributing_blocks if b.get("bbox")])
                dominant_font, avg_size = _compute_dominant_font_and_size(current_para_contributing_blocks, body_font, body_size)
                layout_records.append({
                    "type": "paragraph",
                    "page_num": page_num,
                    "raw_text": para_text,
                    "md_text": para_md,
                    "bbox": para_bbox,
                    "font_name": dominant_font,
                    "font_size": avg_size,
                    "custom_style": custom_style_val,
                })

                if trailing_h_text:
                    h_lvl = 3 if _H3_DECIMAL_RE.match(trailing_h_text) else 2
                    h_style = style_mapping.get(f"h{h_lvl}")
                    h_md = f"{'#' * h_lvl} {trailing_h_text} {{custom-style=\"{h_style}\"}}" if h_style else f"{'#' * h_lvl} {trailing_h_text}"
                    page_paragraphs.append(h_md)
                    audit_data["headings_detected"].append({
                        "page": page_num,
                        "level": f"H{h_lvl}",
                        "text": trailing_h_text,
                    })
                    layout_records.append({
                        "type": "heading",
                        "page_num": page_num,
                        "level": h_lvl,
                        "title": trailing_h_text,
                        "raw_text": h_md,
                        "bbox": para_bbox,
                        "font_name": dominant_font,
                        "font_size": avg_size,
                        "custom_style": h_style or "",
                    })

                current_para_lines = []
                current_para_contributing_blocks = []
                current_para_is_kaiti = False
                current_para_custom_style = None
        
        # ── Step 3: Interleave body_blocks, figure_blocks, and page_tables by reading order ──
        flow_items = []
        for bb in body_blocks:
            flow_items.append({
                "type": "text",
                "bbox": bb.get("bbox", [0, 0, 0, 0]),
                "data": bb
            })

        for block_idx, fig_b in enumerate(figure_blocks):
            flow_items.append({
                "type": "figure",
                "bbox": fig_b.get("bbox", [0, 0, 0, 0]),
                "data": (block_idx, fig_b)
            })

        for tbl in page_tables:
            flow_items.append({
                "type": "table",
                "bbox": list(tbl.bbox),
                "data": tbl
            })

        for rtbl in reconstructed_tables:
            flow_items.append({
                "type": "reconstructed_table",
                "bbox": list(rtbl.bbox),
                "data": rtbl,
            })

        # Pre-filter by confirmed font_role_map and deduplicate AI review by font group.
        ai_heading_by_block: Dict[int, Dict[str, Any]] = {}
        ai_candidates = []
        ai_candidate_meta: Dict[str, Tuple[int, str, str]] = {}
        page_blocks_by_font_key: Dict[str, List[int]] = {}
        page_queued_font_keys = set()

        for candidate_idx, candidate in enumerate(body_blocks):
            candidate_lines = candidate.get("lines", [])
            candidate_text = "".join(
                span.get("text", "") for candidate_line in candidate_lines
                for span in candidate_line.get("spans", [])
            ).strip()
            if not candidate_text or bool(_TOC_LINE_RE.search(candidate_text)):
                continue

            _c_role, _c_style, _c_mapped_by = _lookup_block_font_mapping(
                candidate_lines, font_role_map, is_toc_line=False
            )
            if (_c_role or _c_style) and _c_mapped_by != "ai_layout":
                continue

            cand_font_key, cand_clean_fn, cand_sz = _extract_primary_font_key(candidate_lines, body_size)
            if cand_font_key and cand_font_key in ai_font_decision_cache:
                cached_res = ai_font_decision_cache[cand_font_key]
                if cached_res.get("source") == "gemma":
                    ai_heading_by_block[id(candidate)] = cached_res
                continue

            if (
                _H1_PART_RE.match(candidate_text)
                or _H1_SPECIAL_RE.match(candidate_text)
                or _H1_CHAPTER_RE.match(candidate_text)
                or _H2_SECTION_RE.match(candidate_text)
                or _H2_DECIMAL_RE.match(candidate_text)
                or _H3_DECIMAL_RE.match(candidate_text)
                or _H2_INT_SPACE_RE.match(candidate_text)
            ):
                continue

            candidate_bbox = candidate.get("bbox", [0, 0, 0, 0])
            candidate_sizes = [span.get("size", 0.0) for ln in candidate_lines for span in ln.get("spans", [])]
            candidate_size = sum(candidate_sizes) / len(candidate_sizes) if candidate_sizes else body_size
            candidate_bold = any(span.get("flags", 0) & 16 for ln in candidate_lines for span in ln.get("spans", []))
            candidate_center = abs(((candidate_bbox[0] + candidate_bbox[2]) / 2.0) - page_w / 2.0) < page_w * 0.12

            is_plain_body_font = bool(
                cand_clean_fn
                and body_font
                and cand_clean_fn.lower() == body_font.lower()
                and abs(cand_sz - body_size) < 0.5
                and not candidate_bold
                and not candidate_center
            )
            if is_plain_body_font:
                continue

            candidate_is_heading_like = (
                2 <= len(candidate_text) <= 55
                and not re.search(r'[。！？；.]$', candidate_text)
                and not re.match(r'^(?:表|圖|图|Table|Figure)\s*\d+', candidate_text, re.IGNORECASE)
            )
            has_distinct_font = bool(cand_clean_fn and body_font and cand_clean_fn.lower() != body_font.lower())
            if candidate_is_heading_like and (candidate_bold or candidate_center or candidate_size > body_size + 0.3 or has_distinct_font):
                if cand_font_key:
                    page_blocks_by_font_key.setdefault(cand_font_key, []).append(id(candidate))
                    if cand_font_key in page_queued_font_keys:
                        continue
                    page_queued_font_keys.add(cand_font_key)
                paragraph_id = f"pdf-{page_num}-{candidate_idx}"
                ai_candidates.append({
                    "paragraph_id": paragraph_id,
                    "text": candidate_text,
                    "font_size": round(candidate_size, 2),
                    "is_bold": bool(candidate_bold),
                    "is_centered": bool(candidate_center),
                })
                ai_candidate_meta[paragraph_id] = (id(candidate), cand_font_key, candidate_text)

        if ai_candidates:
            for result in review_uncertain_layout(ai_candidates[:12], model=DEFAULT_GEMMA_MODEL):
                pid = str(result.get("paragraph_id") or "")
                meta = ai_candidate_meta.get(pid)
                if result.get("source") == "gemma" and meta:
                    blk_id, f_key, s_txt = meta
                    ai_heading_by_block[blk_id] = result
                    if f_key:
                        ai_font_decision_cache[f_key] = result
                        for other_id in page_blocks_by_font_key.get(f_key, []):
                            ai_heading_by_block[other_id] = result
                        sug = _map_ai_review_to_font_suggestion(result, style_mapping, s_txt)
                        if sug and f_key not in retained_font_suggestions:
                            retained_font_suggestions[f_key] = sug
                else:
                    if meta and meta[1]:
                        ai_font_decision_cache[meta[1]] = result
                    if result.get("ai_status") and result.get("ai_status") != "model_unavailable":
                        audit_data["ai_layout"]["decisions"].append({
                            "page": page_num,
                            "type": "classification_status",
                            "paragraph_id": result.get("paragraph_id"),
                            "status": result["ai_status"],
                        })

        # Sort by top-to-bottom reading order (y0, then x0)
        flow_items.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
        ai_boundary_by_item: Dict[str, Any] = {}

        for item in flow_items:
            itype = item["type"]
            if itype == "figure":
                flush_current_para()
                block_idx, _fig_b = item["data"]
                fig_bbox = item["bbox"]
                all_image_blocks.append({
                    "page_num": page_num,
                    "block_idx": block_idx,
                    "bbox": fig_bbox,
                    "page_w": page_w,
                    "page_h": page_h,
                })
                fig_raw_md = f"![__IMG_PLACEHOLDER_{page_num}_{block_idx}__]()"
                page_paragraphs.append(fig_raw_md)
                layout_records.append({
                    "type": "figure",
                    "page_num": page_num,
                    "block_idx": block_idx,
                    "raw_md": fig_raw_md,
                    "bbox": fig_bbox,
                    "font_name": "figure",
                    "font_size": 10.5,
                })
                last_block_x0 = fig_bbox[0]
                last_block_x1 = fig_bbox[2]
                last_block_y1 = fig_bbox[3]
                last_block_last_line_x1 = 0.0
                last_heading_text = ""
                continue
            elif itype == "table":
                flush_current_para()
                tbl = item["data"]
                tbl_md = _table_to_markdown(tbl, page_footnotes, page_num)
                if tbl_md:
                    page_paragraphs.append(tbl_md)
                tbl_bbox = item["bbox"]
                layout_records.append({
                    "type": "table",
                    "page_num": page_num,
                    "bbox": tbl_bbox,
                    "raw_md": tbl_md or "",
                })
                last_block_x0 = tbl_bbox[0]
                last_block_x1 = tbl_bbox[2]
                last_block_y1 = tbl_bbox[3]
                last_block_last_line_x1 = 0.0
                last_heading_text = ""
                continue
            elif itype == "reconstructed_table":
                flush_current_para()
                rtbl = item["data"]
                tbl_md = (
                    _replace_fn_markers_in_text(rtbl.markdown, page_footnotes, page_num)
                    if enable_footnotes and page_footnotes
                    else rtbl.markdown
                )
                if tbl_md:
                    page_paragraphs.append(tbl_md)
                tbl_bbox = item["bbox"]
                layout_records.append({
                    "type": "table",
                    "page_num": page_num,
                    "bbox": tbl_bbox,
                    "raw_md": tbl_md or "",
                    "caption_text": getattr(rtbl, "caption_text", ""),
                })
                last_block_x0 = tbl_bbox[0]
                last_block_x1 = tbl_bbox[2]
                last_block_y1 = tbl_bbox[3]
                last_block_last_line_x1 = 0.0
                last_heading_text = ""
                continue

            # ── Regular Text Block ──
            bb = item["data"]
            lines = bb.get("lines", [])
            if not lines:
                continue
            
            bb_text = "".join(s.get("text", "") for l in lines for s in l.get("spans", [])).strip()
            
            # De-duplicate doubled words caused by PDF rendering (e.g. 生命线生命线 -> 生命线)
            if len(bb_text) >= 4 and len(bb_text) % 2 == 0:
                half = len(bb_text) // 2
                if bb_text[:half] == bb_text[half:]:
                    bb_text = bb_text[:half]
                    
            sizes = [s.get("size", 0) for l in lines for s in l.get("spans", [])]
            avg_size = sum(sizes) / len(sizes) if sizes else 10.0
            bbox = bb.get("bbox", [0, 0, 0, 0])
            center_x = (bbox[0] + bbox[2]) / 2.0
            is_centered = abs(center_x - (page_w / 2.0)) < (page_w * 0.12)
            
            # Heading Detection
            heading_level = 0
            is_toc_line = bool(_TOC_LINE_RE.search(bb_text))
            
            clean_for_heading = _CLEAN_FOR_HEADING_RE.sub('', bb_text)
            # 排除前端編號（如「一、」、「1、」、「（一）」）後的純文字內容，避免「、」誤判為句中標點
            clean_content = _HEADING_PREFIX_CLEAN_RE.sub('', clean_for_heading)
            has_sentence_punct = bool(_SENTENCE_PUNCT_RE.search(clean_content))
            
            # ── Priority 0: 人工字體角色對應（優先權最高，直接覆蓋規則型判定）──
            _block_font_role, _block_docx_style, _block_mapped_by = _lookup_block_font_mapping(
                lines, font_role_map, is_toc_line=is_toc_line
            )
            if _block_mapped_by == "ai_layout":
                _block_font_role = None
                _block_docx_style = None

            _is_ignored_font = bool(_block_font_role and str(_block_font_role).strip().lower() in ('忽略', 'ignore', 'none'))
            _has_font_mapping = bool((_block_font_role or _block_docx_style) and not _is_ignored_font)

            if _is_ignored_font:
                heading_level = 0
            elif _block_font_role and not is_toc_line:
                _role_upper = _block_font_role.upper()
                if _role_upper == 'H1':
                    heading_level = 1
                elif _role_upper == 'H2':
                    heading_level = 2
                elif _role_upper == 'H3':
                    heading_level = 3
                # 「圖說」、「楷體」、「正文」等不轉為標題
            elif _block_docx_style and not is_toc_line:
                if _STYLE_HEADING1_RE.search(_block_docx_style):
                    heading_level = 1
                elif _STYLE_HEADING2_RE.search(_block_docx_style):
                    heading_level = 2
                elif _STYLE_HEADING3_RE.search(_block_docx_style):
                    heading_level = 3

            cur_last_line_x1 = lines[-1].get("bbox", bbox)[2] if lines else bbox[2]

            # ── 啟發式標題判定（Fallback）：僅在字體未在字體分析中指定時才執行 ──
            if not heading_level and not is_toc_line and not _has_font_mapping and not _is_ignored_font:
                is_candidate_heading = (
                    len(lines) <= 2
                    and 2 <= len(clean_for_heading) <= 35
                    and not has_sentence_punct
                    and not _LIST_NUM_PREFIX_RE.match(bb_text)
                    and not re.match(r'^(?:[¡•●◆■※★\-]|（?[一二三四五六七八九十\d]+）?[、.·\s]+[是為有在]|[圖表]\s*\d+[-_.]\d+[\s　]+[是為有在])', bb_text)
                )

                if re.match(r'^[圖图表]\s*\d+[\s\u3000]', bb_text):
                    is_candidate_heading = False

                # Priority 1: 目錄索引 / PDF 原生書籤直接命中（100% 命中無規則標題）
                if is_candidate_heading and toc_index:
                    toc_lvl = _match_toc_heading(clean_for_heading, page_num, toc_index, toc_page_offset)
                    if not toc_lvl:
                        toc_lvl = _match_toc_heading(bb_text, page_num, toc_index, toc_page_offset)
                    if toc_lvl > 0:
                        heading_level = toc_lvl

                # Priority 2: 原有標準 Regex 規則
                if not heading_level:
                    if _H1_PART_RE.match(bb_text) or _H1_SPECIAL_RE.match(bb_text):
                        heading_level = 1
                    elif _H1_CHAPTER_RE.match(bb_text):
                        heading_level = 2
                    elif _H2_SECTION_RE.match(bb_text):
                        heading_level = 2
                    elif _H3_DECIMAL_RE.match(bb_text) and not has_sentence_punct:
                        heading_level = 3
                    elif _H2_DECIMAL_RE.match(bb_text) and not has_sentence_punct:
                        heading_level = 2
                    elif _H2_INT_SPACE_RE.match(bb_text) and not has_sentence_punct:
                        heading_level = 2
                    elif _H2_NUM_RE.match(bb_text) and not has_sentence_punct:
                        heading_level = 3
                    elif _H3_SUB_RE1.match(bb_text) and 2 <= len(clean_for_heading) <= 30 and not has_sentence_punct:
                        heading_level = 3

                # Priority 3: 相對字級與黑體/粗體幾何特徵判定（取代死板的 avg_size >= 10.8）
                if not heading_level and is_candidate_heading:
                    if not _CHART_TABLE_END_RE.search(bb_text) and not _CIRCLED_START_RE.search(bb_text):
                        span_fonts = [(s.get("font") or "").split("+", 1)[-1].lower() for l in lines for s in l.get("spans", [])]
                        is_heiti_or_bold = any(
                            ("hei" in fn or "黑" in fn or "bold" in fn or "bd" in fn or "heavy" in fn or (s.get("flags", 0) & 16))
                            for l in lines for s in l.get("spans", [])
                            for fn in [(s.get("font") or "").lower()]
                        )
                        body_font_clean = body_font.lower() if body_font else ""
                        cjk_span_fonts = [fn for fn in span_fonts if not any(w in fn for w in ("times", "arial", "helvetica", "georgia", "courier", "symbol"))]
                        is_different_font_from_body = bool(body_font_clean and cjk_span_fonts and any(fn != body_font_clean for fn in cjk_span_fonts))

                        # 真正置中判定：左右邊距平衡且兩側有明顯留白，絕非貼齊左邊界之普通正文
                        left_margin = bbox[0]
                        right_margin = page_w - bbox[2]
                        is_true_centered = bool(
                            is_centered
                            and (bbox[0] > base_x0 + 10.0)
                            and abs(left_margin - right_margin) < max(25.0, page_w * 0.08)
                        )

                        if avg_size >= body_size + 1.5:
                            heading_level = 2  # 字級明顯大於正文基準
                        elif is_true_centered and avg_size >= body_size + 0.5:
                            heading_level = 2  # 真正居中且字級微大於正文
                        elif is_heiti_or_bold and (is_different_font_from_body or avg_size >= body_size):
                            # 與正文同字級但換成黑體/粗體的短句標題（排除以助詞結尾的普通句）
                            if not re.search(r'[的了在]$', clean_content):
                                heading_level = 3
                        elif is_true_centered and (is_heiti_or_bold or is_different_font_from_body) and avg_size >= body_size - 0.5:
                            # 真正居中且具有粗體或相異字體之短標題
                            if not re.search(r'[的了在]$', clean_content):
                                heading_level = 2

            ai_review = ai_heading_by_block.get(id(bb))
            ai_heading_applied = False
            if (
                not heading_level
                and not _has_font_mapping
                and not _is_ignored_font
                and not is_toc_line
                and ai_review
                and ai_review.get("role") == "heading"
            ):
                heading_level = ai_review.get("level") or 0
                ai_heading_applied = heading_level in (1, 2, 3)

            if heading_level > 0:
                flush_current_para()
                last_block_x0 = bbox[0]
                last_block_x1 = bbox[2]
                last_block_y1 = bbox[3]
                last_block_last_line_x1 = cur_last_line_x1
                # Deduplicate identical consecutive headings on the same page
                if bb_text == last_heading_text:
                    continue
                last_heading_text = bb_text
                
                audit_data["headings_detected"].append({
                    "page": page_num,
                    "level": f"H{heading_level}",
                    "text": bb_text,
                    "source": "gemma" if ai_heading_applied else "deterministic",
                    "confidence": ai_review.get("confidence") if (ai_heading_applied and ai_review) else None,
                    "reason": ai_review.get("reason", "") if (ai_heading_applied and ai_review) else "",
                })
                # Custom style annotation: font mapping docx_style takes highest priority
                custom_style = _block_docx_style or style_mapping.get(f"h{heading_level}")
                if custom_style:
                    formatted_heading = f"{'#' * heading_level} {bb_text} {{custom-style=\"{custom_style}\"}}"
                else:
                    formatted_heading = f"{'#' * heading_level} {bb_text}"
                page_paragraphs.append(formatted_heading)

                h_font, h_size = _compute_dominant_font_and_size([bb], body_font, body_size)
                layout_records.append({
                    "type": "heading",
                    "page_num": page_num,
                    "level": heading_level,
                    "title": bb_text,
                    "raw_text": formatted_heading,
                    "bbox": bbox,
                    "font_name": h_font,
                    "font_size": h_size,
                    "custom_style": custom_style or "",
                })
                continue
            else:
                last_heading_text = ""
                
            # ── Regular Body Text ──────────────────────────────────────────────
            # ── 圖說（Caption）判斷：人工字體角色優先 ──
            is_block_caption = (not _is_ignored_font and (
                (_block_font_role and _block_font_role.lower() in ('圖說', '图说', 'caption')) or
                (_block_docx_style and bool(_STYLE_CAPTION_RE.search(_block_docx_style)))
            ))
            if is_block_caption:
                # 用 custom-style 輸出圖說段落，讓 Pandoc 套用對應 Word 樣式
                flush_current_para()
                _caption_style = _block_docx_style or style_mapping.get("image_caption")
                if not _caption_style and font_role_map:
                    for line in lines:
                        for span in line.get('spans', []):
                            raw_fn = (span.get('font') or '').split('+', 1)[-1]
                            size_v = round(span.get('size', 0) * 2) / 2
                            _candidates = [
                                f"{raw_fn} ({size_v}pt)",
                                f"{raw_fn} ({size_v:.1f}pt)",
                                f"{raw_fn}_{size_v}",
                                raw_fn
                            ]
                            for _cand in _candidates:
                                if _cand in font_role_map:
                                    _caption_style = font_role_map[_cand].get('docx_style')
                                    break
                            if _caption_style:
                                break
                        if _caption_style:
                            break
                if _caption_style:
                    cap_md = f'::: {{custom-style="{_caption_style}"}}\n{bb_text}\n:::'
                    page_paragraphs.append(cap_md)
                else:
                    cap_md = f'*{bb_text}*'
                    page_paragraphs.append(cap_md)  # fallback: 斜體

                c_font, c_size = _compute_dominant_font_and_size([bb], body_font, body_size)
                layout_records.append({
                    "type": "caption",
                    "page_num": page_num,
                    "raw_text": bb_text,
                    "md_text": cap_md,
                    "bbox": bbox,
                    "font_name": c_font,
                    "font_size": c_size,
                    "custom_style": _caption_style or "",
                })
                last_block_x0 = bbox[0]
                last_block_x1 = bbox[2]
                last_block_y1 = bbox[3]
                last_block_last_line_x1 = cur_last_line_x1
                continue

            # Check font for KaiTi (Rule-based + AI Vision fallback)
            total_chars = 0
            kaiti_chars = 0
            block_font_names = set()  # 收集此 block 的所有 font name
            for line in lines:
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if not span_text: continue
                    total_chars += len(span_text)
                    font_name = span.get("font", "").lower()
                    if font_name:
                        block_font_names.add(font_name)
                    if "kai" in font_name or "楷" in font_name or "kt" in font_name:
                        kaiti_chars += len(span_text)

            # ── 人工字體角色：楷體優先 ──
            if _is_ignored_font:
                is_block_kaiti = False
            elif _block_font_role and _block_font_role.lower() in ('楷體', '楷体', 'kaiti', 'blockquote'):
                is_block_kaiti = True
            elif _block_docx_style and bool(_STYLE_KAI_RE.search(_block_docx_style)):
                is_block_kaiti = True
            elif _has_font_mapping:
                # 已明確映射為其他樣式者，不再觸發楷體規則
                is_block_kaiti = False
            elif ai_review and ai_review.get("source") == "gemma" and ai_review.get("role") == "quote":
                is_block_kaiti = True
            else:
                is_block_kaiti = (total_chars > 0 and (kaiti_chars / total_chars) > 0.5)
            
            # AI Vision fallback: 若規則型判定失敗且 AI 可用，且該字型未人工指定
            if not is_block_kaiti and not _has_font_mapping and not _is_ignored_font and ai_kaiti_classifier is not None:
                try:
                    is_block_kaiti = ai_kaiti_classifier.is_block_kaiti(
                        page=page, block_bbox=bbox, block_text=bb_text,
                        font_names=list(block_font_names),
                    )
                except Exception:
                    pass  # AI 失敗時靜默降級，使用規則型結果

            # Determine custom style for regular paragraph (if not caption)
            block_custom_style = _block_docx_style if (_has_font_mapping and not _is_ignored_font and not is_block_caption) else None

            # Check indentation to determine whether this block starts a new paragraph
            is_indented = (bbox[0] - base_x0) >= max(10.0, avg_size * 1.4)
            curr_has_space_indent = bool(re.match(r'^[\u3000]{1,2}|^\s{2,4}', bb_text))
            indent_jump = bool((bbox[0] - last_block_x0) >= 5.0)

            vertical_gap = (bbox[1] - last_block_y1) if last_block_y1 > 0 else 0.0
            prev_ref_x1 = last_block_last_line_x1 if last_block_last_line_x1 > 0 else last_block_x1
            prev_block_was_short_line = bool(prev_ref_x1 > 0 and prev_ref_x1 < max_x1 - max(avg_size * 2.0, 20.0))
            is_large_vertical_gap = bool(vertical_gap > avg_size * 1.5)

            if current_para_lines:
                should_flush = False
                ai_boundary_override = ai_boundary_by_item.get(item.get("ai_boundary_key"))
                is_unclosed_continuation = False
                prev_is_heading_like = False
                curr_clean = bb_text.strip()
                # 1. 樣式/字體邊界（人工映射 Word 樣式或楷體不同）-> 強制分段
                if is_block_kaiti != current_para_is_kaiti:
                    should_flush = True
                elif block_custom_style != current_para_custom_style:
                    should_flush = True
                else:
                    prev_clean = current_para_lines[-1].strip() if current_para_lines else ""
                    curr_clean = bb_text.strip()

                    # 2. 當前行開頭為條列編號/前綴（BUG-006A 防禦）-> 強制分段
                    if curr_clean and _PARA_START_PREFIX_RE.match(curr_clean):
                        should_flush = True
                    else:
                        prev_ends_with_open = bool(_OPEN_PUNCT_RE.search(prev_clean))
                        unclosed_delims = update_delimiter_stack(prev_clean) if update_delimiter_stack else []
                        has_unclosed_cjk_quote = bool(
                            len(unclosed_delims) > 0
                            or prev_clean.count('《') > prev_clean.count('》')
                            or prev_clean.count('“') > prev_clean.count('”')
                            or prev_clean.count('（') > prev_clean.count('）')
                            or prev_clean.count('(') > prev_clean.count(')')
                        )
                        is_unclosed_continuation = prev_ends_with_open or has_unclosed_cjk_quote

                        # 3. 獨立無編號短小標題判定（BUG-004 防黏連保護）
                        prev_clean_content = _HEADING_PREFIX_CLEAN_RE.sub('', _CLEAN_FOR_HEADING_RE.sub('', prev_clean))
                        prev_has_sentence_punct = bool(_SENTENCE_PUNCT_RE.search(prev_clean_content))
                        prev_is_heading_like = bool(
                            not is_unclosed_continuation
                            and len(current_para_lines) == 1
                            and 2 <= len(prev_clean_content) <= 35
                            and not prev_has_sentence_punct
                            and prev_block_was_short_line
                            and not re.search(r'[的了在和与]$', prev_clean_content)
                        )
                        if prev_is_heading_like:
                            should_flush = True
                        elif is_unclosed_continuation:
                            # 句中未閉合書名號、括號或引號（BUG-006B）：強制流式接續
                            should_flush = False
                        else:
                            # 4. 垂直空隙（段距跳躍，適用首行無縮排現代版式）
                            if is_large_vertical_gap:
                                should_flush = True
                            else:
                                # 5. 終止標點判定（剝離行尾注標後檢查句號、問號、感嘆號等）
                                prev_no_mark = _TRAILING_MARK_RE.sub('', prev_clean)
                                prev_has_terminal = bool(_TERMINAL_PUNCT_RE.search(prev_no_mark))
                                prev_ends_with_colon = bool(re.search(r'[：:]$', prev_no_mark))
                                is_hanging_indent_citation = bool(
                                    current_para_lines
                                    and re.match(r'^\[\d+\]', current_para_lines[0].strip())
                                    and not re.match(r'^\[\d+\]', curr_clean)
                                )

                                if prev_has_terminal:
                                    # 有句末標點且（有縮排、未滿行、或有行距）-> 正常自然段結束
                                    if is_indented or curr_has_space_indent or prev_block_was_short_line or vertical_gap > avg_size * 0.9:
                                        should_flush = True
                                elif prev_ends_with_colon and not is_hanging_indent_citation and (is_indented or curr_has_space_indent or prev_block_was_short_line):
                                    # 冒號後接縮排或短行引出下文（非文獻懸掛縮排）-> 獨立段落
                                    should_flush = True
                                elif not is_hanging_indent_citation and (is_indented or curr_has_space_indent) and indent_jump and prev_block_was_short_line:
                                    # 6. 無終止標點但有明確首行縮排跳躍且前行未滿行 -> 容錯分段
                                    should_flush = True

                    if (
                        ai_boundary_override is not None
                        and not is_unclosed_continuation
                        and not prev_is_heading_like
                        and not (curr_clean and _PARA_START_PREFIX_RE.match(curr_clean))
                        and block_custom_style == current_para_custom_style
                        and is_block_kaiti == current_para_is_kaiti
                    ):
                        ai_should_break = ai_boundary_override.get("should_break") if isinstance(ai_boundary_override, dict) else ai_boundary_override
                        if type(ai_should_break) is bool:
                            should_flush = ai_should_break
                        audit_data["ai_layout"]["decisions"].append({
                            "page": page_num,
                            "type": "boundary",
                            "source": "gemma",
                            "previous": prev_clean[:120],
                            "next": curr_clean[:120],
                            "decision": "break" if should_flush else "merge",
                            "confidence": ai_boundary_override.get("confidence") if isinstance(ai_boundary_override, dict) else None,
                        })

                if should_flush:
                    flush_current_para()

            if not current_para_lines:
                current_para_is_kaiti = is_block_kaiti
                current_para_custom_style = block_custom_style

            # Process lines in this block, replacing footnote anchors
            block_has_valid_line = False
            for line in lines:
                line_str = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
                if not line_str:
                    continue
                line_str = _replace_fn_markers_in_text(line_str, page_footnotes, page_num)
                current_para_lines.append(line_str)
                block_has_valid_line = True
            if block_has_valid_line:
                current_para_contributing_blocks.append(bb)

            last_block_x0 = bbox[0]
            last_block_x1 = bbox[2]
            last_block_y1 = bbox[3]
            last_block_last_line_x1 = cur_last_line_x1
                
        # Flush any remaining body text
        flush_current_para()

        # Step 4: Handle footnotes that didn't match any body/table marker (Fallback anchoring)
        for fn in page_footnotes:
            fn_id = fn["id"]
            fn_tag = f"[^p{page_num}_{fn_id}]"
            if not fn.get("matched", False):
                # Safely anchor footnote to last paragraph on page
                if page_paragraphs:
                    page_paragraphs[-1] += fn_tag
                else:
                    page_paragraphs.append(fn_tag)
                audit_data["footnotes_fallback"] += 1
                audit_data["footnotes_detail"].append({
                    "page": page_num,
                    "id": fn_id,
                    "status": "FALLBACK (正文上標模糊，降級錨定段末)",
                    "content": fn["content"][:60]
                })
            else:
                audit_data["footnotes_matched"] += 1
                audit_data["footnotes_detail"].append({
                    "page": page_num,
                    "id": fn_id,
                    "status": "MATCHED (雙向匹配精準錨定)",
                    "content": fn["content"][:60]
                })

            # Append Pandoc footnote definition
            page_paragraphs.append(f"{fn_tag}: {fn['content']}")
            layout_records.append({
                "type": "footnote",
                "page_num": page_num,
                "fn_id": fn_id,
                "tag": fn_tag,
                "content": fn['content'],
            })

        if page_paragraphs:
            final_md_pages.append("\n\n".join(page_paragraphs))

    try:
        from src.extraction.contracts import validate_layout_records
        validate_layout_records(layout_records)
    except Exception as val_err:
        print(f"[Warning] Layout records contract validation notice: {val_err}")

    return final_md_pages, all_image_blocks, audit_data, layout_records


def process_book_vector_pdf(
    pdf_path,
    output_dir,
    output_stem=None,
    style_mapping=None,
    progress_callback=None,
    no_footnote: bool = False,
    ai_kaiti=None,
    ai_kaiti_threshold=None,
    enable_footnotes: bool = True,
    isolate_images_by_stem: Optional[bool] = None,
):
    """
    Extract vector PDF with:
    1. Header / footer removal
    2. Footnote parsing, anchor substitution, and footnote block formatting
    3. Heading level classification (H1, H2, H3) + custom Word style mapping
    4. Paragraph reflow (eliminating PDF line-wrap broken sentences)
    5. Returns audit report data dict
    """
    if not enable_footnotes:
        no_footnote = True
    elif no_footnote:
        enable_footnotes = False

    if style_mapping is None:
        style_mapping = {}
    if isinstance(style_mapping, str):
        try:
            style_mapping = json.loads(style_mapping)
        except Exception:
            style_mapping = {}

    # ── 讀取人工字體角色對應表（fonts.json）──
    # 優先順序高於規則型 regex，讓使用者的手動設定生效。
    try:
        from src.scripts.pdf_font_analyzer import get_font_role_map
        _fonts_json = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json')
        _fonts_json = os.path.normpath(_fonts_json)
        font_role_map = get_font_role_map(_fonts_json)
    except Exception:
        try:
            from scripts.pdf_font_analyzer import get_font_role_map
            _fonts_json = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json')
            _fonts_json = os.path.normpath(_fonts_json)
            font_role_map = get_font_role_map(_fonts_json)
        except Exception:
            font_role_map = {}
    if font_role_map:
        print(f"[FontMap] 已載入人工字體對應表，共 {len(font_role_map)} 筆")

    stem = output_stem or os.path.basename(pdf_path).rsplit(".", 1)[0]
    os.makedirs(output_dir, exist_ok=True)
    out_md_path = os.path.join(output_dir, f"{stem}.md")

    # ── AI Kaiti Classifier 初始化（若啟用且可用）──
    ai_kaiti_classifier = None
    try:
        from config import CFG, AI
        should_enable = ai_kaiti if ai_kaiti is not None else CFG.ai_kaiti_enabled
        if should_enable and AIKaitiClassifier is not None:
            threshold = float(ai_kaiti_threshold if ai_kaiti_threshold is not None else getattr(CFG, "ai_kaiti_threshold", 0.65))
            ai_kaiti_classifier = AIKaitiClassifier(
                api_key=AI.gemini_key or "",
                model=CFG.ai_kaiti_model,
                min_confidence=threshold,
            )
            if ai_kaiti_classifier.is_available:
                print(f"[AI-Kaiti] Gemini Vision 楷體辨識已啟用 (信心閾值: {threshold})")
            else:
                print("[AI-Kaiti] Gemini API Key 未設定，楷體 AI 辨識已停用")
                ai_kaiti_classifier = None
    except ImportError:
        pass

    doc = fitz.open(pdf_path)
    try:
        final_md_pages, all_image_blocks, audit_data, _ = _parse_pdf_layout_flow(
            doc=doc,
            pdf_name=os.path.basename(pdf_path),
            style_mapping=style_mapping,
            font_role_map=font_role_map,
            enable_footnotes=enable_footnotes,
            ai_kaiti_classifier=ai_kaiti_classifier,
            progress_callback=progress_callback,
        )
    finally:
        doc.close()

    retained_suggestions = audit_data.get("ai_layout", {}).get("retained_font_suggestions")
    if retained_suggestions:
        try:
            from src.scripts.pdf_font_analyzer import save_ai_layout_suggestions_to_fonts_json
            _fonts_json_out = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json'))
            saved_cnt = save_ai_layout_suggestions_to_fonts_json(_fonts_json_out, retained_suggestions)
            if saved_cnt > 0:
                print(f"[FontMap] 已保留 {saved_cnt} 筆 AI 版面預判字型建議至 fonts.json 供人工審核")
        except Exception:
            pass
            
    # Write final Markdown file
    full_markdown = "\n\n".join(final_md_pages)
    
    # ── Phase 2: Image Extraction for PyMuPDF (with per-book namespace isolation) ──
    use_stem_subdir = isolate_images_by_stem if isolate_images_by_stem is not None else bool(output_stem)
    images_dir = os.path.join(output_dir, "images", stem) if use_stem_subdir else os.path.join(output_dir, "images")
    image_path_map = {}
    if all_image_blocks:
        try:
            from src.scripts.pdf_image_extractor import extract_pdf_images
            image_path_map = extract_pdf_images(
                pdf_path=pdf_path,
                image_blocks=all_image_blocks,
                output_dir=images_dir,
                progress_callback=progress_callback
            )
            if progress_callback:
                progress_callback(85, f"[INFO] 成功提取 {len(image_path_map)} 張圖片。")
        except Exception as img_err:
            if progress_callback:
                progress_callback(85, f"[WARN] 圖片提取失敗: {img_err}")
                
    # ── Replace image placeholders with actual paths ──
    def _repl_placeholder(match):
        p_num = int(match.group(1))
        b_idx = int(match.group(2))
        saved_path = image_path_map.get((p_num, b_idx))
        if saved_path:
            img_rel = os.path.relpath(saved_path, output_dir).replace("\\", "/")
            return f"![]({img_rel}){{width=80%}}"
        return "" # Remove placeholder if not found

    full_markdown = _IMG_PLACEHOLDER_RE.sub(_repl_placeholder, full_markdown)
    
    # ── 統一後處理深模組 ──
    from src.extraction.post_processor import postprocess_markdown
    
    full_markdown, rare_char_stats = postprocess_markdown(
        markdown_text=full_markdown,
        pdf_name=os.path.basename(pdf_path),
        output_dir=output_dir,
        style_mapping=style_mapping,
        progress_callback=progress_callback,
        enable_dictionary_postprocess=False
    )
    
    audit_data["rare_char_corrections"] = rare_char_stats.get("corrections_applied", 0)
    audit_data["rare_char_suspicious"] = rare_char_stats.get("suspicious_chars_found", 0)
    
    with open(out_md_path, "w", encoding="utf-8") as f:
        f.write(full_markdown)
    
    # ── AI Kaiti 統計輸出 ──
    if ai_kaiti_classifier is not None:
        stats_summary = ai_kaiti_classifier.get_stats_summary()
        print(f"[AI-Kaiti] {stats_summary}")
        audit_data["ai_kaiti_stats"] = ai_kaiti_classifier.stats
        if progress_callback:
            progress_callback(90, f"[AI-Kaiti] {stats_summary}")
        
    return out_md_path, audit_data


def build_book_ast(
    layout_records: List[Dict[str, Any]],
    image_blocks: List[Dict[str, Any]],
    audit_data: Dict[str, Any],
    pdf_name: str = "",
    total_pages: int = 0,
    doc_profile: Optional[Dict[str, Any]] = None,
    split_level: int = 2,
) -> BookAST:
    """
    Pure builder transforming structured layout records into a BookAST instance
    comprising SectionUnit and ParagraphUnit hierarchies.
    """
    if doc_profile is None:
        doc_profile = audit_data.get("doc_profile", {})

    sections: List[SectionUnit] = []
    current_sec: Optional[SectionUnit] = None
    sec_counter = 0

    def start_new_section(title: str, level: int) -> SectionUnit:
        nonlocal sec_counter
        sec_id = f"sec_{sec_counter:03d}"
        sec_counter += 1
        sec = SectionUnit(
            section_id=sec_id,
            title=title,
            level=level,
            paragraphs=[],
        )
        sections.append(sec)
        return sec

    for rec in layout_records:
        rtype = rec.get("type")
        page_num = rec.get("page_num", 1)

        if rtype == "heading" and rec.get("level", 2) <= split_level:
            # Starts a new section
            heading_title = rec.get("title", "")
            heading_level = rec.get("level", 2)
            current_sec = start_new_section(heading_title, heading_level)

            # Record the heading as paragraph #1 of the section
            p_id = f"{current_sec.section_id}_p001"
            p = ParagraphUnit(
                para_id=p_id,
                raw_text=rec.get("raw_text", f"{'#' * heading_level} {heading_title}"),
                page_num=page_num,
                bbox=rec.get("bbox"),
                font_name=rec.get("font_name", ""),
                font_size=rec.get("font_size", 0.0),
                custom_style=rec.get("custom_style", ""),
            )
            current_sec.paragraphs.append(p)
            continue

        # If no section has been created yet, start a preamble section
        if current_sec is None:
            current_sec = start_new_section("__PREAMBLE__", 0)

        p_idx = len(current_sec.paragraphs) + 1
        p_id = f"{current_sec.section_id}_p{p_idx:03d}"

        if rtype == "heading":
            h_level = rec.get("level", 3)
            h_title = rec.get("title", "")
            p = ParagraphUnit(
                para_id=p_id,
                raw_text=rec.get("raw_text", f"{'#' * h_level} {h_title}"),
                page_num=page_num,
                bbox=rec.get("bbox"),
                font_name=rec.get("font_name", ""),
                font_size=rec.get("font_size", 0.0),
                custom_style=rec.get("custom_style", ""),
            )
            current_sec.paragraphs.append(p)

        elif rtype == "paragraph":
            p = ParagraphUnit(
                para_id=p_id,
                raw_text=rec.get("raw_text", ""),
                page_num=page_num,
                bbox=rec.get("bbox"),
                font_name=rec.get("font_name", ""),
                font_size=rec.get("font_size", 0.0),
                custom_style=rec.get("custom_style", ""),
            )
            current_sec.paragraphs.append(p)

        elif rtype == "caption":
            p = ParagraphUnit(
                para_id=p_id,
                raw_text=rec.get("raw_text", ""),
                page_num=page_num,
                bbox=rec.get("bbox"),
                font_name=rec.get("font_name", ""),
                font_size=rec.get("font_size", 0.0),
                custom_style=rec.get("custom_style", ""),
            )
            current_sec.paragraphs.append(p)

        elif rtype == "figure":
            p = ParagraphUnit(
                para_id=p_id,
                raw_text=f"![__IMG_PLACEHOLDER_{page_num}_{rec.get('block_idx', 0)}__]()",
                page_num=page_num,
                bbox=rec.get("bbox"),
                font_name="image",
                font_size=0.0,
            )
            current_sec.paragraphs.append(p)

        elif rtype == "table":
            p = ParagraphUnit(
                para_id=p_id,
                raw_text=rec.get("raw_md", ""),
                page_num=page_num,
                bbox=rec.get("bbox"),
                font_name="table",
                font_size=0.0,
            )
            current_sec.paragraphs.append(p)

        elif rtype == "footnote":
            p = ParagraphUnit(
                para_id=p_id,
                raw_text=f"{rec.get('tag', '')}: {rec.get('content', '')}",
                page_num=page_num,
                bbox=None,
                font_name="footnote",
                font_size=0.0,
            )
            current_sec.paragraphs.append(p)

    # Empty document fallback
    if not sections:
        sections.append(SectionUnit(
            section_id="sec_001",
            title="__DOCUMENT__",
            level=1,
            paragraphs=[],
        ))

    for sec in sections:
        sec.raw_content = sec.effective_content

    return BookAST(
        sections=sections,
        image_blocks=image_blocks,
        audit_data=audit_data,
        pdf_name=pdf_name,
        total_pages=total_pages,
        doc_profile=doc_profile or {},
    )


def extract_book_vector_ast(
    pdf_path: str | Path,
    style_mapping: Optional[Dict[str, str]] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    no_footnote: bool = False,
    ai_kaiti: Optional[bool] = None,
    ai_kaiti_threshold: Optional[float] = None,
    enable_footnotes: bool = True,
    split_level: int = 2,
    page_range: Optional[Tuple[int, int]] = None,
) -> BookAST:
    """
    Extracts vector PDF into a structured BookAST in pure memory.

    Guarantees:
    - Pure read-only operation: performs zero file writes and zero directory creation.
    - Preserves paragraph bbox (72-DPI points), 1-based page_num, font_name, font_size.
    - Strictly releases fitz.Document resource handle on both normal return and exception.
    - Returns exactly one BookAST instance.
    """
    pdf_path_str = str(pdf_path)
    if not os.path.isfile(pdf_path_str):
        raise FileNotFoundError(f"PDF file not found: {pdf_path_str}")

    if not enable_footnotes:
        no_footnote = True
    elif no_footnote:
        enable_footnotes = False

    if style_mapping is None:
        style_mapping = {}
    if isinstance(style_mapping, str):
        try:
            style_mapping = json.loads(style_mapping)
        except Exception:
            style_mapping = {}

    font_role_map = {}
    try:
        from src.scripts.pdf_font_analyzer import get_font_role_map
        _fonts_json = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json')
        _fonts_json = os.path.normpath(_fonts_json)
        font_role_map = get_font_role_map(_fonts_json)
    except Exception:
        try:
            from scripts.pdf_font_analyzer import get_font_role_map
            _fonts_json = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json')
            _fonts_json = os.path.normpath(_fonts_json)
            font_role_map = get_font_role_map(_fonts_json)
        except Exception:
            font_role_map = {}

    ai_kaiti_classifier = None
    if ai_kaiti and AIKaitiClassifier is not None:
        try:
            from config import CFG, AI
            threshold = float(ai_kaiti_threshold if ai_kaiti_threshold is not None else getattr(CFG, "ai_kaiti_threshold", 0.65))
            ai_kaiti_classifier = AIKaitiClassifier(
                api_key=AI.gemini_key or "",
                model=CFG.ai_kaiti_model,
                min_confidence=threshold,
            )
            if not ai_kaiti_classifier.is_available:
                ai_kaiti_classifier = None
        except Exception:
            ai_kaiti_classifier = None

    doc = fitz.open(pdf_path_str)
    try:
        _final_md_pages, all_image_blocks, audit_data, layout_records = _parse_pdf_layout_flow(
            doc=doc,
            pdf_name=os.path.basename(pdf_path_str),
            style_mapping=style_mapping,
            font_role_map=font_role_map,
            enable_footnotes=enable_footnotes,
            ai_kaiti_classifier=ai_kaiti_classifier,
            progress_callback=progress_callback,
            page_range=page_range,
        )
        total_pages = len(doc)
    finally:
        doc.close()

    return build_book_ast(
        layout_records=layout_records,
        image_blocks=all_image_blocks,
        audit_data=audit_data,
        pdf_name=os.path.basename(pdf_path_str),
        total_pages=total_pages,
        doc_profile=audit_data.get("doc_profile", {}),
        split_level=split_level,
    )


__all__ = [
    "process_book_vector_pdf",
    "extract_book_vector_ast",
    "build_book_ast",
    "BookAST",
    "SectionAdapter",
    "SectionUnit",
    "ParagraphUnit",
]
