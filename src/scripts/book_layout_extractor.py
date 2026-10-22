# // ==============================================================================
# // book_layout_extractor.py: High-precision Book Vector Layout Extractor
# // - Header / Footer stripping
# // - Footnote extraction, bidirectional anchor matching, and Pandoc syntax
# // - Heading level detection (H1, H2, H3) with custom Word style mapping
# // - Chinese line wrap reflow (smooth paragraph splicing without intra-break)
# // - Comprehensive conversion auditing and tracking
# // ==============================================================================

import os
import sys
import re
import json
from pathlib import Path
from collections import Counter
from typing import Optional, Dict, Any, List, Tuple, Callable, Sequence

# pyrefly: ignore [missing-import]
import fitz

try:
    from src.pod_studio.section_ast import BookAST, SectionAdapter, SectionUnit, ParagraphUnit
except ImportError:
    try:
        from pod_studio.section_ast import BookAST, SectionAdapter, SectionUnit, ParagraphUnit
    except ImportError:
        BookAST = None
        SectionAdapter = None
        SectionUnit = None
        ParagraphUnit = None

# Try to import project helpers
try:
    from src.founder_tools.core.heading_detector import HeadingDetector, _match_toc_entry
except ImportError:
    try:
        from founder_tools.core.heading_detector import HeadingDetector, _match_toc_entry
    except ImportError:
        HeadingDetector = None
        _match_toc_entry = None

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

CIRCLED_MAP = {
    '①': 1, '②': 2, '③': 3, '④': 4, '⑤': 5,
    '⑥': 6, '⑦': 7, '⑧': 8, '⑨': 9, '⑩': 10,
    # Extended circled numbers ⑪–⑳ (U+246A–U+2473)
    '⑪': 11, '⑫': 12, '⑬': 13, '⑭': 14, '⑮': 15,
    '⑯': 16, '⑰': 17, '⑱': 18, '⑲': 19, '⑳': 20,
}

# Regex pattern matching any recognised footnote marker (circled / bracketed / numbered-dot / bare number with space)
# Added expanded unicode ranges for circled numbers > 10 and dingbats.
FN_MARKER_PATTERN = r'([\u2460-\u24ff\u2780-\u2793\u3251-\u325f]|\[\d+\]|\(\d+\)|\d+\.)'
_WEAK_MARKER_RE = re.compile(r'^[\d.、\s()（）]+$')
_DIGITS_RE = re.compile(r'\d+')
_FN_MARKER_SPLIT_RE = re.compile(FN_MARKER_PATTERN)
_STARTS_WITH_FN_MARKER_RE = re.compile(r'^\s*(' + FN_MARKER_PATTERN + r')\s*')
_FN_MARKER_PARSE_RE = re.compile(r'^\s*([①-⑩\u2460-\u2473]|\[\d+\]|\(\d+\)|\d+\.)\s*')

_PAGE_HEADER_PATTERNS = [
    re.compile(r'版图之枷'),
    re.compile(r'军事后勤视野'),
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
_HEADING_PREFIX_CLEAN_RE = re.compile(r'^(?:第[一二三四五六七八九十百零\d]+[章节條条回讲講篇卷]|(?:Chapter|Part)\s*\d+|[一二三四五六七八九十百\d]+[、. ]|[（(][一二三四五六七八九十\d]+[)）]|\d+\.\d+(?:\.\d+)?)\s*', re.I)
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
_H2_NUM_RE = re.compile(r'^[一二三四五六七八九十百\d]+[、. ][^\n]{2,30}$')
_H3_SUB_RE1 = re.compile(r'^[（(][一二三四五六七八九十\d]+[)）]')
_H3_SUB_RE2 = re.compile(r'^\d+\.\d+')
_CHART_TABLE_END_RE = re.compile(r'示意图|表$')
_CIRCLED_START_RE = re.compile(r'^[①-⑩]')
_IMG_PLACEHOLDER_RE = re.compile(r'!\[__IMG_PLACEHOLDER_(\d+)_(\d+)__\]\(\)')


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


def _union_bboxes(bboxes: Sequence[Sequence[float]]) -> Optional[List[float]]:
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
        raw_toc = doc.get_toc()
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
                    blocks = doc[p_idx].get_text("dict").get("blocks", [])
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
            page_dict = doc[p_idx].get_text("dict")
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


def _circled_to_int(marker_str: str) -> int:
    """Convert any footnote marker string to its integer index."""
    if marker_str in CIRCLED_MAP:
        return CIRCLED_MAP[marker_str]
    digs = _DIGITS_RE.findall(marker_str)
    return int(digs[0]) if digs else 1


def _replace_fn_markers_in_text(text: str, page_footnotes: list, page_num: int) -> str:
    """Replace all recognised footnote marker occurrences in *text* with Pandoc ref-tags.
    Works for both body paragraphs and table cells."""
    for fn in page_footnotes:
        m_str = fn.get('marker', '')
        if not m_str:
            continue
        fn_tag = f"[^p{page_num}_{fn['id']}]"
        if _WEAK_MARKER_RE.match(m_str):
            # 針對弱標記（如 '1.' 或 '(1)'），要求前後不能是數字以防止誤傷小數點（如 31.5%）或正文數值
            safe_pat = re.compile(r'(?<!\d)' + re.escape(m_str) + r'(?!\d)')
            new_text, n_subs = safe_pat.subn(fn_tag, text, count=1)
            if n_subs > 0:
                text = new_text
                fn['matched'] = True
        elif m_str in text:
            text = text.replace(m_str, fn_tag, 1)
            fn['matched'] = True
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

def _parse_pdf_layout_flow(
    doc: fitz.Document,
    pdf_name: str = "",
    style_mapping: Optional[Dict[str, str]] = None,
    font_role_map: Optional[Dict[str, Any]] = None,
    enable_footnotes: bool = True,
    ai_kaiti_classifier: Optional[Any] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
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
        "doc_profile": {
            "body_size": body_size,
            "body_font": body_font,
            "toc_entries": len(toc_index),
            "is_native_toc": doc_profile.get("is_native_toc", False),
        }
    }
    
    final_md_pages = []
    all_image_blocks = []
    layout_records = []

    for page_idx in range(total_pages):
        page_num = page_idx + 1
        if progress_callback:
            progress_pct = int((page_num / total_pages) * 85)
            progress_callback(progress_pct, f"[INFO] 正在解析第 {page_num}/{total_pages} 頁 (版面/樣式/腳注抽取)...")
            
        page = doc[page_idx]
        page_h = page.rect.height
        page_w = page.rect.width
        
        blocks = page.get_text("dict").get("blocks", [])

        # ── Step 0: Detect tables via PyMuPDF find_tables() ──────────────────
        # Collect table bbox regions so we can exclude their text from body_blocks.
        page_tables = []  # list of fitz.table.Table objects
        table_bboxes = []  # list of fitz.Rect for overlap checks
        try:
            tabs = page.find_tables()
            if tabs and tabs.tables:
                page_tables = tabs.tables
                table_bboxes = [fitz.Rect(t.bbox) for t in page_tables]
        except Exception:
            pass  # find_tables() not available in older PyMuPDF – graceful fallback

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

        # Step 1: Collect valid text blocks, separate header/footer/footnote
        body_blocks = []
        footnote_blocks = []
        figure_blocks = []

        for b in blocks:
            block_type = b.get("type")
            
            if block_type == 1:
                if not is_page_header(b, page_h, page_w) and not is_page_footer(b, page_h):
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

            if is_page_header(b, page_h, page_w):
                audit_data["headers_removed"] += 1
                continue
            if is_page_footer(b, page_h):
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
                if bbox[1] >= page_h * 0.65:
                    if starts_with_fn_marker:
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

        # Sort by top-to-bottom reading order (y0, then x0)
        flow_items.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))

        for item in flow_items:
            itype = item["type"]
            if itype == "figure":
                flush_current_para()
                block_idx, fig_b = item["data"]
                fig_bbox = item["bbox"]
                all_image_blocks.append({
                    "page_num": page_num,
                    "block_idx": block_idx,
                    "bbox": fig_bbox,
                    "page_w": page_w,
                    "page_h": page_h,
                })
                layout_records.append({
                    "type": "figure",
                    "page_num": page_num,
                    "block_idx": block_idx,
                    "bbox": fig_bbox,
                    "page_w": page_w,
                    "page_h": page_h,
                })
                page_paragraphs.append(f"![__IMG_PLACEHOLDER_{page_num}_{block_idx}__]()")
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
            # 取此 block 第一個命中 font_role_map 的字體角色
            _block_font_role = None
            _block_docx_style = None
            if font_role_map and not is_toc_line:
                for _line in lines:
                    for _span in _line.get('spans', []):
                        _raw_fn = (_span.get('font') or '').split('+', 1)[-1]
                        _size = round(_span.get('size', 0) * 2) / 2
                        _candidates = [
                            f"{_raw_fn} ({_size}pt)",
                            f"{_raw_fn} ({_size:.1f}pt)",
                            f"{_raw_fn}_{_size}",
                            _raw_fn
                        ]
                        for _cand in _candidates:
                            if _cand in font_role_map:
                                _entry = font_role_map[_cand]
                                _block_font_role = _entry.get('role')
                                _block_docx_style = _entry.get('docx_style')
                                break
                        if _block_font_role or _block_docx_style:
                            break
                    if _block_font_role or _block_docx_style:
                        break

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
                is_candidate_heading = (len(lines) <= 2 and 2 <= len(clean_for_heading) <= 35 and not has_sentence_punct)

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
                    elif _H2_NUM_RE.match(bb_text) and not has_sentence_punct:
                        heading_level = 3
                    elif (_H3_SUB_RE1.match(bb_text) or _H3_SUB_RE2.match(bb_text)) and 2 <= len(clean_for_heading) <= 30 and not has_sentence_punct:
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
                        is_different_font_from_body = bool(body_font_clean and any(fn and fn != body_font_clean for fn in span_fonts))

                        if avg_size >= body_size + 1.5:
                            heading_level = 2  # 字級明顯大於正文基準
                        elif is_centered or avg_size >= body_size + 0.5:
                            heading_level = 2  # 居中或字級微大於正文
                        elif is_heiti_or_bold and (is_different_font_from_body or avg_size >= body_size):
                            # 與正文同字級但換成黑體/粗體的短句標題（排除以助詞結尾的普通句）
                            if not re.search(r'[的了在]$', clean_content):
                                heading_level = 3
                        elif is_centered and avg_size >= body_size - 0.5:
                            heading_level = 2

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
                    "text": bb_text
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
            is_indented = (bbox[0] - base_x0) >= 12.0

            vertical_gap = (bbox[1] - last_block_y1) if last_block_y1 > 0 else 0.0
            prev_ref_x1 = last_block_last_line_x1 if last_block_last_line_x1 > 0 else last_block_x1
            prev_block_was_short_line = bool(prev_ref_x1 > 0 and prev_ref_x1 < max_x1 - max(avg_size * 2.0, 20.0))
            is_large_vertical_gap = bool(vertical_gap > avg_size * 1.45)

            if current_para_lines:
                should_flush = False
                if is_block_kaiti != current_para_is_kaiti:
                    should_flush = True
                elif block_custom_style != current_para_custom_style:
                    should_flush = True
                # A new paragraph is indicated by an increase in indentation (e.g. from 2 chars to 4 chars)
                # or a large jump in indent. We use > 5.0 instead of abs() to avoid breaking on hanging indents
                elif is_indented and (bbox[0] - last_block_x0) >= 5.0:
                    should_flush = True
                # ✅ 防黏連 1：垂直段距跳躍（段前距/空行），強制獨立成段
                elif is_large_vertical_gap:
                    should_flush = True
                # ✅ 防黏連 2：前一區塊未滿行（提早換行），代表上一段已結束或是獨立小標，絕不硬接！
                elif prev_block_was_short_line:
                    should_flush = True

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
            
    # Write final Markdown file
    full_markdown = "\n\n".join(final_md_pages)
    
    # ── Phase 2: Image Extraction for PyMuPDF ──
    images_dir = os.path.join(output_dir, "images")
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
        doc_profile=doc_profile,
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
        final_md_pages, all_image_blocks, audit_data, layout_records = _parse_pdf_layout_flow(
            doc=doc,
            pdf_name=os.path.basename(pdf_path_str),
            style_mapping=style_mapping,
            font_role_map=font_role_map,
            enable_footnotes=enable_footnotes,
            ai_kaiti_classifier=ai_kaiti_classifier,
            progress_callback=progress_callback,
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
