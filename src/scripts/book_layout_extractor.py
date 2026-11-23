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
        clean_table_cell_text,
        is_continuation_table_marker,
        is_valid_pymupdf_table,
        extract_reconstructed_tables_from_page,
        merge_gfm_tables_if_compatible,
        normalize_pymupdf_table_rows,
        rect_union_intersection_area,
    )
except ImportError:
    try:
        from extraction.table_reconstructor import (
            clean_table_cell_text,
            is_continuation_table_marker,
            is_valid_pymupdf_table,
            extract_reconstructed_tables_from_page,
            merge_gfm_tables_if_compatible,
            normalize_pymupdf_table_rows,
            rect_union_intersection_area,
        )
    except ImportError:
        clean_table_cell_text = None
        is_continuation_table_marker = None
        is_valid_pymupdf_table = None
        extract_reconstructed_tables_from_page = None
        merge_gfm_tables_if_compatible = None
        normalize_pymupdf_table_rows = None
        rect_union_intersection_area = None

try:
    from src.scripts.paragraph_reconstruction import update_delimiter_stack
except ImportError:
    try:
        from paragraph_reconstruction import update_delimiter_stack
    except ImportError:
        update_delimiter_stack = None

try:
    from src.scripts.paragraph_reconstruction import (
        LineRecord,
        SpanRecord,
        stitch_physical_lines,
    )
except ImportError:
    try:
        from paragraph_reconstruction import (
            LineRecord,
            SpanRecord,
            stitch_physical_lines,
        )
    except ImportError:
        LineRecord = None
        SpanRecord = None
        stitch_physical_lines = None

_fonts_json: Optional[str] = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json')
)

from src.extraction.citation_and_footnote_utils import (
    CIRCLED_MAP,
    FN_MARKER_PATTERN,
    _CITATION_PRECEDING_RE,
    _DIGITS_RE,
    _FN_MARKER_PARSE_RE,
    _FN_MARKER_SPLIT_RE,
    _STARTS_WITH_FN_MARKER_RE,
    _SUPERSCRIPT_CHAR_MAP,
    _WEAK_MARKER_RE,
    _circled_to_int,
    _replace_fn_markers_in_text,
    is_citation_continuation_marker,
    is_strong_citation_text,
    is_valid_footnote_split_match,
    try_replace_alpha_fallback,
)

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
_TERMINAL_PUNCT_RE = re.compile(r'(?:[。！？!?…]+|(?<=[\u4e00-\u9fff])．|(?<!\d)(?:18|19|20)\d{2}．)[”’」』）)\]】]*$')
_TRAILING_MARK_RE = re.compile(r'(?:\[\d+(?:[-–,，]\d+)*\]|[①-⑳]|\^\[\d+\])+$')
_PARA_START_PREFIX_RE = re.compile(
    r'^(?:(?!(?:18|19|20)\d{2}[.．])[（(]?[一二三四五六七八九十\d]+[)）、.．](?![0-9%％])|[\[［【]\s*\d+\s*[\]］】](?![，。；：、,.])|[①-⑳]|[•●◆■※★\-])'
)
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


def _table_to_markdown(table, page_footnotes: list, page_num: int) -> str:
    """Convert a PyMuPDF Table object to a GFM Markdown table string.
    Footnote markers inside cells are replaced with Pandoc ref-tags."""
    try:
        rows = table.extract()  # list[list[str|None]]
    except Exception:
        return ""
    if not rows:
        return ""

    if normalize_pymupdf_table_rows is not None:
        cleaned_rows = normalize_pymupdf_table_rows(rows, table_obj=table)
    else:
        cleaned_rows = [
            [
                clean_table_cell_text(c) if clean_table_cell_text is not None else (c or "").replace("\n", " ").strip()
                for c in row
            ]
            for row in rows
        ]

    md_rows = []
    for r_idx, row in enumerate(cleaned_rows):
        cells = []
        for cell_text in row:
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

def _normalize_symbol_font_spans(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map single alphabet letters in sequence symbol fonts (e.g. RopeSequenceNumber)
    to standard Unicode circled numbers ①..⑩ without breaking text flow."""
    for s in spans:
        font_name = (s.get("font") or "").lower()
        if any(kw in font_name for kw in ("ropesequencenumber", "sequencenumber", "circlednumber")):
            txt = s.get("text", "")
            if len(txt) == 1 and ('a' <= txt <= 'j' or 'A' <= txt <= 'J'):
                num = ord(txt.lower()) - ord('a') + 1
                s["text"] = chr(0x2460 + num - 1)
    return spans

def is_page_header(block, page_h, page_w):
    bbox = block.get('bbox', [0, 0, 0, 0])
    w = bbox[2] - bbox[0]
    # Side margin running header / edge cut label (narrow vertical text in extreme outer margins)
    if (bbox[0] > page_w * 0.88 or bbox[2] < page_w * 0.12) and w < 25:
        return True

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


def _parse_retained_ai_font_entry(fval: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    role_upper = str(fval.get("role") or "").upper()
    role_map = {
        "H1": ("heading", 1),
        "H2": ("heading", 2),
        "H3": ("heading", 3),
        "楷體": ("quote", None),
        "楷体": ("quote", None),
        "KAITI": ("quote", None),
        "QUOTE": ("quote", None),
        "正文": ("body", None),
        "內文": ("body", None),
        "BODY": ("body", None),
    }
    if role_upper not in role_map:
        return None
    role_name, level_val = role_map[role_upper]
    return {
        "role": role_name,
        "level": level_val,
        "confidence": fval.get("confidence", 0.85),
        "reason": fval.get("reason", "retained_ai_layout"),
        "source": "gemma",
    }


def _build_ai_font_decision_cache(font_role_map: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    cache: Dict[str, Dict[str, Any]] = {}
    if not font_role_map:
        return cache
    for fk, fval in font_role_map.items():
        if isinstance(fval, dict) and fval.get("mapped_by") == "ai_layout":
            parsed = _parse_retained_ai_font_entry(fval)
            if parsed is not None:
                cache[fk] = parsed
    return cache


def _init_layout_audit_data(
    pdf_name: str,
    total_pages: int,
    style_mapping: Dict[str, str],
    retained_font_suggestions: Dict[str, Dict[str, Any]],
    doc_profile: Dict[str, Any],
) -> Dict[str, Any]:
    body_size = doc_profile.get("body_size", 10.5)
    body_font = doc_profile.get("body_font", "")
    toc_index = doc_profile.get("toc_index", {})
    model_avail = gemma_available(DEFAULT_GEMMA_MODEL)
    if not model_avail:
        print(f"[WARN] 本機未安裝 {DEFAULT_GEMMA_MODEL}，標題與斷行使用確定性判定。", flush=True)
    return {
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
            "model_available": model_avail,
            "confirmed_style_mapping": dict(style_mapping),
            "retained_font_suggestions": retained_font_suggestions,
            "decisions": [],
        },
        "doc_profile": {
            "body_size": body_size,
            "body_font": body_font,
            "toc_entries": len(toc_index),
            "is_native_toc": doc_profile.get("is_native_toc", False),
        },
    }


def _block_overlaps_any_table(bbox_list: List[Any], block_bbox: Sequence[float]) -> bool:
    """Return True if block_bbox overlaps the union of known table regions by >30%."""
    if not bbox_list:
        return False
    b = fitz.Rect(block_bbox)
    b_area = max(b.width * b.height, 1.0)
    if rect_union_intersection_area is not None:
        b_coords = (float(b.x0), float(b.y0), float(b.x1), float(b.y1))
        tr_coords = [(float(tr.x0), float(tr.y0), float(tr.x1), float(tr.y1)) for tr in bbox_list]
        return rect_union_intersection_area(b_coords, tr_coords) / b_area > 0.30
    for tr in bbox_list:
        inter = b & tr
        if inter.is_empty:
            continue
        if (inter.width * inter.height) / b_area > 0.30:
            return True
    return False


def _table_overlaps_any_table(bbox_list: List[Any], table_bbox: Sequence[float]) -> bool:
    """Bidirectional union overlap check between a candidate table and already accepted table bboxes."""
    if _block_overlaps_any_table(bbox_list, table_bbox):
        return True
    if not bbox_list or rect_union_intersection_area is None:
        return False
    cand_rect = fitz.Rect(table_bbox)
    cand_coords = (float(cand_rect.x0), float(cand_rect.y0), float(cand_rect.x1), float(cand_rect.y1))
    for tr in bbox_list:
        tr_area = max(tr.width * tr.height, 1.0)
        tr_coords = (float(tr.x0), float(tr.y0), float(tr.x1), float(tr.y1))
        if rect_union_intersection_area(tr_coords, [cand_coords]) / tr_area > 0.30:
            return True
    return False


def _detect_three_line_tables(page: Any, blocks: List[Dict[str, Any]], table_bboxes: List[Any]) -> List[Any]:
    reconstructed_tables: List[Any] = []
    if extract_reconstructed_tables_from_page is None:
        return reconstructed_tables
    try:
        three_line_list = extract_reconstructed_tables_from_page(page, blocks=blocks)
    except Exception:
        return reconstructed_tables
    for rtbl in three_line_list:
        if not _table_overlaps_any_table(table_bboxes, rtbl.bbox):
            reconstructed_tables.append(rtbl)
            table_bboxes.append(fitz.Rect(rtbl.bbox))
    return reconstructed_tables


def _is_valid_bordered_table(t: Any, page_w: float, page_h: float) -> bool:
    if is_valid_pymupdf_table is None:
        return True
    try:
        cells = t.extract()
    except Exception:
        cells = []
    return bool(is_valid_pymupdf_table(cells, t.bbox, page_w, page_h))


def _detect_bordered_page_tables(page: Any, page_w: float, page_h: float, table_bboxes: List[Any]) -> List[Any]:
    page_tables: List[Any] = []
    try:
        tabs = page.find_tables()
    except Exception:
        return page_tables
    if not (tabs and tabs.tables):
        return page_tables
    for t in tabs.tables:
        if _table_overlaps_any_table(table_bboxes, t.bbox):
            continue
        if _is_valid_bordered_table(t, page_w, page_h):
            page_tables.append(t)
            table_bboxes.append(fitz.Rect(t.bbox))
    return page_tables


def _clean_block_spans_and_extract_text(block: Dict[str, Any]) -> str:
    for line in block.get("lines", []):
        cleaned_spans = clean_span_duplicates(line.get("spans", []))
        line["spans"] = _normalize_symbol_font_spans(cleaned_spans)
    return "".join(s.get("text", "") for l in block.get("lines", []) for s in l.get("spans", [])).strip()


def _is_vector_footnote_candidate(
    block: Dict[str, Any],
    block_text: str,
    page_w: float,
    page_h: float,
    body_size: float,
    enable_footnotes: bool,
    footnote_blocks: List[Dict[str, Any]],
) -> bool:
    if not enable_footnotes:
        return False
    bbox = block.get("bbox", [0, 0, 0, 0])
    w = bbox[2] - bbox[0]
    is_side_margin = (bbox[0] > page_w * 0.88 or bbox[2] < page_w * 0.12) and w < 25
    sizes = [s.get("size", 0) for l in block.get("lines", []) for s in l.get("spans", [])]
    avg_size = sum(sizes) / len(sizes) if sizes else 10.0
    if is_side_margin or bbox[1] < page_h * 0.65 or avg_size >= body_size:
        return False
    starts_with_fn = bool(_STARTS_WITH_FN_MARKER_RE.match(block_text))
    if (starts_with_fn or is_strong_citation_text(block_text)) and not _H3_DECIMAL_RE.match(block_text) and not _H2_DECIMAL_RE.match(block_text):
        return True
    if footnote_blocks and avg_size < body_size - 0.5:
        prev_bbox = footnote_blocks[-1].get("bbox", [0, 0, 0, 0])
        return bool(bbox[1] >= prev_bbox[1] and abs(bbox[0] - prev_bbox[0]) < 50)
    return False


def _partition_page_blocks(
    blocks: List[Dict[str, Any]],
    page_w: float,
    page_h: float,
    body_size: float,
    enable_footnotes: bool,
    strip_headers_heuristic: bool,
    table_bboxes: List[Any],
    audit_data: Dict[str, Any],
    is_cropped: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    body_blocks: List[Dict[str, Any]] = []
    footnote_blocks: List[Dict[str, Any]] = []
    figure_blocks: List[Dict[str, Any]] = []

    for b in blocks:
        block_type = b.get("type")
        if block_type == 1:
            bbox_img = b.get("bbox", [0, 0, 0, 0])
            if is_cropped:
                cy_img = (float(bbox_img[1]) + float(bbox_img[3])) * 0.5
                if cy_img < 0.0 or cy_img > page_h:
                    continue
            is_hf = strip_headers_heuristic and (is_page_header(b, page_h, page_w) or is_page_footer(b, page_h))
            if not is_hf and not (table_bboxes and _block_overlaps_any_table(table_bboxes, bbox_img)):
                figure_blocks.append(b)
            continue
        if block_type != 0:
            continue
        block_text = _clean_block_spans_and_extract_text(b)
        if not block_text:
            continue
        bbox = b.get("bbox", [0, 0, 0, 0])
        if is_cropped:
            cy = (float(bbox[1]) + float(bbox[3])) * 0.5
            cx = (float(bbox[0]) + float(bbox[2])) * 0.5
            if cy < 0.0 or cy > page_h or cx < 0.0 or cx > page_w:
                continue
        if (bbox[0] > page_w * 0.88 or bbox[2] < page_w * 0.12) and (bbox[2] - bbox[0]) < 25:
            continue
        if strip_headers_heuristic and is_page_header(b, page_h, page_w):
            audit_data["headers_removed"] += 1
            continue
        if strip_headers_heuristic and is_page_footer(b, page_h):
            audit_data["footers_removed"] += 1
            continue
        if table_bboxes and _block_overlaps_any_table(table_bboxes, bbox):
            continue
        if _is_vector_footnote_candidate(b, block_text, page_w, page_h, body_size, enable_footnotes, footnote_blocks):
            footnote_blocks.append(b)
        else:
            body_blocks.append(b)

    return body_blocks, footnote_blocks, figure_blocks


def _split_footnote_block_into_parts(fb_text: str) -> List[str]:
    raw_matches = list(_FN_MARKER_SPLIT_RE.finditer(fb_text))
    valid_matches = [m for m in raw_matches if is_valid_footnote_split_match(fb_text, m)]
    parts: List[str] = []
    last_end = 0
    for m in valid_matches:
        parts.append(fb_text[last_end:m.start()])
        parts.append(m.group(0))
        last_end = m.end()
    parts.append(fb_text[last_end:])
    return parts


def _consume_footnote_prefix(prefix: str, current_fn_entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if _STARTS_WITH_FN_MARKER_RE.match(prefix) or not prefix.strip():
        return current_fn_entry
    if re.match(r'^(?:注[释釋]?|脚[注釋]?|参考[文献獻]|References?|NOTES?)[:：]?\s*$', prefix.strip(), re.I):
        return current_fn_entry
    if current_fn_entry:
        sep = " " if current_fn_entry["content"] else ""
        current_fn_entry["content"] = str(current_fn_entry["content"]) + sep + prefix.strip()
        return current_fn_entry
    return {"id": 1, "marker": "", "content": prefix.strip()}


def _parse_page_footnotes_from_blocks(footnote_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    page_footnotes: List[Dict[str, Any]] = []
    current_fn_entry: Optional[Dict[str, Any]] = None
    sorted_blocks = _sort_blocks_by_row_and_x(footnote_blocks, y_tol=5.0)

    for fb in sorted_blocks:
        fb_text = "".join(s.get("text", "") for l in fb.get("lines", []) for s in l.get("spans", [])).strip()
        if not fb_text:
            continue
        parts = _split_footnote_block_into_parts(fb_text)
        current_fn_entry = _consume_footnote_prefix(parts[0], current_fn_entry)

        for i in range(1, len(parts), 2):
            marker_str = parts[i].strip()
            content_str = parts[i + 1].strip() if (i + 1) < len(parts) else ""
            num = _circled_to_int(marker_str)
            prev_content = str(current_fn_entry.get("content", "")) if current_fn_entry else ""
            if current_fn_entry and is_citation_continuation_marker(marker_str, num, prev_content):
                sep = "" if prev_content.endswith((":", "：", ";", "；")) else " "
                current_fn_entry["content"] = (prev_content + sep + marker_str + (" " + content_str if content_str else "")).strip()
                continue
            if current_fn_entry:
                page_footnotes.append(current_fn_entry)
            current_fn_entry = {"id": num, "marker": marker_str, "content": content_str}

    if current_fn_entry:
        page_footnotes.append(current_fn_entry)
    return page_footnotes


def _compute_page_x_margins(body_blocks: List[Dict[str, Any]], page_w: float) -> Tuple[float, float]:
    normal_x0s: List[float] = []
    normal_x1s: List[float] = []
    for bb in body_blocks:
        lines = bb.get("lines", [])
        bb_text = "".join(s.get("text", "") for l in lines for s in l.get("spans", [])).strip()
        bbox = bb.get("bbox", [0, 0, 0, 0])
        is_centered = abs(((bbox[0] + bbox[2]) / 2.0) - (page_w / 2.0)) < (page_w * 0.12)
        if not is_centered and len(bb_text) > 10:
            normal_x0s.append(bbox[0])
            normal_x1s.append(bbox[2])
    base_x0 = min(normal_x0s) if normal_x0s else 65.0
    max_x1 = max(normal_x1s) if normal_x1s else (page_w - base_x0)
    return base_x0, max_x1


def _lines_share_physical_row(
    bbox_a: Sequence[float],
    bbox_b: Sequence[float],
    body_size: float,
    y_overlap_ratio: float = 0.45,
) -> bool:
    """Return True if two line bboxes occupy the same physical horizontal row."""
    h_a = max(0.0, float(bbox_a[3]) - float(bbox_a[1]))
    h_b = max(0.0, float(bbox_b[3]) - float(bbox_b[1]))
    min_h = min(h_a, h_b)
    if min_h > 0.0:
        overlap = min(float(bbox_a[3]), float(bbox_b[3])) - max(float(bbox_a[1]), float(bbox_b[1]))
        if overlap >= min_h * y_overlap_ratio:
            return True
    yc_a = (float(bbox_a[1]) + float(bbox_a[3])) / 2.0
    yc_b = (float(bbox_b[1]) + float(bbox_b[3])) / 2.0
    return abs(yc_a - yc_b) <= body_size * 0.55


def _line_record_to_pymupdf_line(
    lr: Any,
    orig_span_by_id: Dict[int, Dict[str, Any]],
    orig_span_by_sig: Dict[Tuple[str, Tuple[float, ...], str], Dict[str, Any]],
    orig_line_meta: Dict[str, Dict[str, Any]],
    body_size: float,
) -> Dict[str, Any]:
    """Convert a stitched LineRecord back to a PyMuPDF-compatible line dict."""
    py_spans: List[Dict[str, Any]] = []
    for sr in getattr(lr, "spans", []):
        sig = (sr.text, tuple(round(float(v), 2) for v in sr.bbox), sr.font_family)
        orig = orig_span_by_id.get(id(sr)) or orig_span_by_sig.get(sig)
        py_spans.append({
            "text": sr.text,
            "bbox": [round(float(v), 2) for v in sr.bbox],
            "font": sr.font_family,
            "size": float(sr.font_size),
            "flags": int(sr.font_flags),
            "origin": (
                list(orig["origin"])
                if (orig and "origin" in orig)
                else [round(float(sr.bbox[0]), 2), round(float(sr.bbox[3]), 2)]
            ),
        })

    # If stitch_physical_lines inserted ASCII space in lr.text without adding a space SpanRecord,
    # materialize synthetic space spans so span concatenation matches lr.text verbatim.
    lr_text = getattr(lr, "text", "") or ""
    if py_spans and lr_text:
        joined = "".join(sp["text"] for sp in py_spans)
        if joined != lr_text and joined.replace(" ", "") == lr_text.replace(" ", ""):
            synced_spans: List[Dict[str, Any]] = []
            pos = 0
            for sp in py_spans:
                sp_txt = sp["text"]
                if not sp_txt:
                    continue
                if pos < len(lr_text) and lr_text[pos] == " " and not sp_txt.startswith(" "):
                    prev_sp = synced_spans[-1] if synced_spans else sp
                    prev_bbox = prev_sp["bbox"]
                    sp_bbox = sp["bbox"]
                    synced_spans.append({
                        "text": " ",
                        "bbox": [
                            prev_bbox[2],
                            min(prev_bbox[1], sp_bbox[1]),
                            max(prev_bbox[2], sp_bbox[0]),
                            max(prev_bbox[3], sp_bbox[3]),
                        ],
                        "font": prev_sp["font"],
                        "size": prev_sp["size"],
                        "flags": prev_sp["flags"],
                        "origin": [prev_bbox[2], prev_bbox[3]],
                    })
                    pos += 1
                synced_spans.append(sp)
                pos += len(sp_txt)
            py_spans = synced_spans
    elif not py_spans and lr_text:
        py_spans = [{
            "text": lr_text,
            "bbox": [round(float(v), 2) for v in lr.bbox],
            "font": "",
            "size": float(body_size),
            "flags": 0,
            "origin": [round(float(lr.bbox[0]), 2), round(float(lr.bbox[3]), 2)],
        }]

    l_meta = orig_line_meta.get(getattr(lr, "line_id", ""), {})
    return {
        "bbox": [round(float(v), 2) for v in lr.bbox],
        "wmode": l_meta.get("wmode", 0),
        "dir": l_meta.get("dir", [1.0, 0.0]),
        "spans": py_spans,
    }


def _stitch_body_lines_into_blocks(
    body_blocks: List[Dict[str, Any]],
    body_size: float,
) -> List[Dict[str, Any]]:
    """Expand body blocks into LineRecords, stitch physical line fragments, and repack into blocks."""
    if not body_blocks or stitch_physical_lines is None or LineRecord is None or SpanRecord is None:
        return list(body_blocks)

    line_records: List[Any] = []
    orig_span_by_id: Dict[int, Dict[str, Any]] = {}
    orig_span_by_sig: Dict[Tuple[str, Tuple[float, ...], str], Dict[str, Any]] = {}
    orig_line_meta: Dict[str, Dict[str, Any]] = {}

    for b_idx, block in enumerate(body_blocks):
        block_id = f"b{b_idx}"
        blk_bbox = block.get("bbox", [0.0, 0.0, 0.0, 0.0])
        for l_idx, line in enumerate(block.get("lines", [])):
            span_records: List[Any] = []
            for sp in line.get("spans", []):
                txt = sp.get("text", "")
                if not txt:
                    continue
                sp_bbox = sp.get("bbox") or line.get("bbox") or blk_bbox
                sr = SpanRecord(
                    text=txt,
                    bbox=(float(sp_bbox[0]), float(sp_bbox[1]), float(sp_bbox[2]), float(sp_bbox[3])),
                    font_family=str(sp.get("font") or ""),
                    font_size=float(sp.get("size") or body_size or 10.5),
                    font_flags=int(sp.get("flags") or 0),
                )
                span_records.append(sr)
                orig_span_by_id[id(sr)] = sp
                orig_span_by_sig[(sr.text, tuple(round(v, 2) for v in sr.bbox), sr.font_family)] = sp
            if not span_records:
                continue
            ln_bbox = line.get("bbox") or _union_bboxes([sr.bbox for sr in span_records]) or blk_bbox
            ln_id = f"{block_id}_l{l_idx}"
            orig_line_meta[ln_id] = {
                "wmode": line.get("wmode", 0),
                "dir": line.get("dir", [1.0, 0.0]),
            }
            line_records.append(
                LineRecord(
                    line_id=ln_id,
                    page_num=0,
                    text="".join(sr.text for sr in span_records),
                    bbox=(float(ln_bbox[0]), float(ln_bbox[1]), float(ln_bbox[2]), float(ln_bbox[3])),
                    spans=span_records,
                    block_id=block_id,
                    line_order=l_idx,
                )
            )

    if not line_records:
        return []

    stitched_lines = stitch_physical_lines(line_records, body_size=body_size)

    repacked_blocks: List[Dict[str, Any]] = []
    cur_block_id: Optional[str] = None
    cur_lrs: List[Any] = []
    cur_py_lines: List[Dict[str, Any]] = []

    def _flush_repacked() -> None:
        if not cur_py_lines:
            return
        blk_bbox = _union_bboxes([ln["bbox"] for ln in cur_py_lines]) or list(cur_py_lines[0]["bbox"])
        repacked_blocks.append({
            "type": 0,
            "bbox": blk_bbox,
            "lines": cur_py_lines,
        })

    for lr in stitched_lines:
        py_line = _line_record_to_pymupdf_line(
            lr, orig_span_by_id, orig_span_by_sig, orig_line_meta, body_size
        )
        same_block = bool(
            cur_lrs
            and lr.block_id
            and lr.block_id == cur_block_id
            and not _lines_share_physical_row(cur_lrs[-1].bbox, lr.bbox, body_size)
        )
        if same_block:
            cur_lrs.append(lr)
            cur_py_lines.append(py_line)
        else:
            _flush_repacked()
            cur_block_id = lr.block_id
            cur_lrs = [lr]
            cur_py_lines = [py_line]

    _flush_repacked()
    return repacked_blocks


def _build_interleaved_flow_items(
    body_blocks: List[Dict[str, Any]],
    figure_blocks: List[Dict[str, Any]],
    page_tables: List[Any],
    reconstructed_tables: List[Any],
) -> List[Dict[str, Any]]:
    flow_items: List[Dict[str, Any]] = [
        {"type": "text", "bbox": bb.get("bbox", [0, 0, 0, 0]), "data": bb}
        for bb in body_blocks
    ]
    flow_items.extend(
        {"type": "figure", "bbox": fig_b.get("bbox", [0, 0, 0, 0]), "data": (block_idx, fig_b)}
        for block_idx, fig_b in enumerate(figure_blocks)
    )
    flow_items.extend(
        {"type": "table", "bbox": list(tbl.bbox), "data": tbl}
        for tbl in page_tables
    )
    flow_items.extend(
        {"type": "reconstructed_table", "bbox": list(rtbl.bbox), "data": rtbl}
        for rtbl in reconstructed_tables
    )
    return _sort_blocks_by_row_and_x(flow_items, y_tol=5.0)


def _is_standard_regex_heading_text(text: str) -> bool:
    return bool(
        _H1_PART_RE.match(text)
        or _H1_SPECIAL_RE.match(text)
        or _H1_CHAPTER_RE.match(text)
        or _H2_SECTION_RE.match(text)
        or _H2_DECIMAL_RE.match(text)
        or _H3_DECIMAL_RE.match(text)
        or _H2_INT_SPACE_RE.match(text)
    )


def _evaluate_ai_heading_candidate(
    candidate: Dict[str, Any],
    candidate_idx: int,
    page_num: int,
    page_w: float,
    body_size: float,
    body_font: str,
    font_role_map: Optional[Dict[str, Any]],
    ai_font_decision_cache: Dict[str, Dict[str, Any]],
    ai_heading_by_block: Dict[int, Dict[str, Any]],
    page_blocks_by_font_key: Dict[str, List[int]],
    page_queued_font_keys: set,
) -> Optional[Tuple[Dict[str, Any], Tuple[int, str, str]]]:
    candidate_lines = candidate.get("lines", [])
    candidate_text = "".join(s.get("text", "") for ln in candidate_lines for s in ln.get("spans", [])).strip()
    if not candidate_text or bool(_TOC_LINE_RE.search(candidate_text)):
        return None
    c_role, c_style, c_mapped_by = _lookup_block_font_mapping(candidate_lines, font_role_map, is_toc_line=False)
    if (c_role or c_style) and c_mapped_by != "ai_layout":
        return None
    cand_font_key, cand_clean_fn, cand_sz = _extract_primary_font_key(candidate_lines, body_size)
    if cand_font_key and cand_font_key in ai_font_decision_cache:
        cached_res = ai_font_decision_cache[cand_font_key]
        if cached_res.get("source") == "gemma":
            ai_heading_by_block[id(candidate)] = cached_res
        return None
    if _is_standard_regex_heading_text(candidate_text):
        return None
    candidate_bbox = candidate.get("bbox", [0, 0, 0, 0])
    candidate_sizes = [span.get("size", 0.0) for ln in candidate_lines for span in ln.get("spans", [])]
    candidate_size = sum(candidate_sizes) / len(candidate_sizes) if candidate_sizes else body_size
    candidate_bold = any(span.get("flags", 0) & 16 for ln in candidate_lines for span in ln.get("spans", []))
    candidate_center = abs(((candidate_bbox[0] + candidate_bbox[2]) / 2.0) - page_w / 2.0) < page_w * 0.12
    is_plain_body = bool(
        cand_clean_fn and body_font and cand_clean_fn.lower() == body_font.lower()
        and abs(cand_sz - body_size) < 0.5 and not candidate_bold and not candidate_center
    )
    if is_plain_body:
        return None
    is_heading_like = (
        2 <= len(candidate_text) <= 55
        and not re.search(r'[。！？；.]$', candidate_text)
        and not re.match(r'^(?:表|圖|图|Table|Figure)\s*\d+', candidate_text, re.IGNORECASE)
    )
    has_distinct_font = bool(cand_clean_fn and body_font and cand_clean_fn.lower() != body_font.lower())
    if not (is_heading_like and (candidate_bold or candidate_center or candidate_size > body_size + 0.3 or has_distinct_font)):
        return None
    if cand_font_key:
        page_blocks_by_font_key.setdefault(cand_font_key, []).append(id(candidate))
        if cand_font_key in page_queued_font_keys:
            return None
        page_queued_font_keys.add(cand_font_key)
    paragraph_id = f"pdf-{page_num}-{candidate_idx}"
    payload = {
        "paragraph_id": paragraph_id,
        "text": candidate_text,
        "font_size": round(candidate_size, 2),
        "is_bold": bool(candidate_bold),
        "is_centered": bool(candidate_center),
    }
    return payload, (id(candidate), cand_font_key, candidate_text)


def _record_gemma_heading_review_result(
    result: Dict[str, Any],
    meta: Optional[Tuple[int, str, str]],
    page_num: int,
    style_mapping: Dict[str, str],
    ai_heading_by_block: Dict[int, Dict[str, Any]],
    ai_font_decision_cache: Dict[str, Dict[str, Any]],
    page_blocks_by_font_key: Dict[str, List[int]],
    retained_font_suggestions: Dict[str, Dict[str, Any]],
    audit_data: Dict[str, Any],
) -> None:
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
        return
    if meta and meta[1]:
        ai_font_decision_cache[meta[1]] = result
    if result.get("ai_status") and result.get("ai_status") != "model_unavailable":
        audit_data["ai_layout"]["decisions"].append({
            "page": page_num,
            "type": "classification_status",
            "paragraph_id": result.get("paragraph_id"),
            "status": result["ai_status"],
        })


def _review_page_ai_heading_candidates(
    body_blocks: List[Dict[str, Any]],
    page_num: int,
    page_w: float,
    body_size: float,
    body_font: str,
    font_role_map: Optional[Dict[str, Any]],
    style_mapping: Dict[str, str],
    ai_font_decision_cache: Dict[str, Dict[str, Any]],
    retained_font_suggestions: Dict[str, Dict[str, Any]],
    audit_data: Dict[str, Any],
) -> Dict[int, Dict[str, Any]]:
    ai_heading_by_block: Dict[int, Dict[str, Any]] = {}
    ai_candidates: List[Dict[str, Any]] = []
    ai_candidate_meta: Dict[str, Tuple[int, str, str]] = {}
    page_blocks_by_font_key: Dict[str, List[int]] = {}
    page_queued_font_keys: set = set()

    for candidate_idx, candidate in enumerate(body_blocks):
        evaluated = _evaluate_ai_heading_candidate(
            candidate, candidate_idx, page_num, page_w, body_size, body_font,
            font_role_map, ai_font_decision_cache, ai_heading_by_block,
            page_blocks_by_font_key, page_queued_font_keys,
        )
        if evaluated is not None:
            payload, meta = evaluated
            ai_candidates.append(payload)
            ai_candidate_meta[payload["paragraph_id"]] = meta

    if ai_candidates:
        for result in review_uncertain_layout(ai_candidates[:12], model=DEFAULT_GEMMA_MODEL):
            pid = str(result.get("paragraph_id") or "")
            _record_gemma_heading_review_result(
                result, ai_candidate_meta.get(pid), page_num, style_mapping,
                ai_heading_by_block, ai_font_decision_cache, page_blocks_by_font_key,
                retained_font_suggestions, audit_data,
            )
    return ai_heading_by_block


def _splice_paragraph_lines(lines_list: List[str], audit_data: Dict[str, Any]) -> str:
    para_text = ""
    for line_txt in lines_list:
        if not para_text:
            para_text = line_txt
        elif _CJK_END_RE.search(para_text) and _CJK_START_RE.search(line_txt):
            para_text += line_txt
            audit_data["paragraphs_reflowed"] += 1
        else:
            para_text += " " + line_txt
    return para_text


def _format_styled_paragraph_md(
    para_text: str, custom_style: Optional[str], is_kaiti: bool, style_mapping: Dict[str, str]
) -> Tuple[str, str]:
    if custom_style:
        return custom_style, f'::: {{custom-style="{custom_style}"}}\n{para_text}\n:::'
    if is_kaiti:
        kaiti_style = style_mapping.get("kaiti") or "楷體2"
        return kaiti_style, f'::: {{custom-style="{kaiti_style}"}}\n{para_text}\n:::'
    body_style = style_mapping.get("body")
    if body_style:
        return body_style, f'::: {{custom-style="{body_style}"}}\n{para_text}\n:::'
    return "", para_text


def _emit_trailing_heading_if_present(
    trailing_h_text: str,
    page_num: int,
    para_bbox: Any,
    dominant_font: str,
    avg_size: float,
    style_mapping: Dict[str, str],
    page_paragraphs: List[str],
    layout_records: List[Dict[str, Any]],
    audit_data: Dict[str, Any],
) -> None:
    if not trailing_h_text:
        return
    h_lvl = 3 if _H3_DECIMAL_RE.match(trailing_h_text) else 2
    h_style = style_mapping.get(f"h{h_lvl}")
    h_md = f"{'#' * h_lvl} {trailing_h_text} {{custom-style=\"{h_style}\"}}" if h_style else f"{'#' * h_lvl} {trailing_h_text}"
    page_paragraphs.append(h_md)
    audit_data["headings_detected"].append({"page": page_num, "level": f"H{h_lvl}", "text": trailing_h_text})
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


def _flush_accumulated_paragraph(
    state: Dict[str, Any],
    page_num: int,
    body_font: str,
    body_size: float,
    style_mapping: Dict[str, str],
    page_paragraphs: List[str],
    layout_records: List[Dict[str, Any]],
    audit_data: Dict[str, Any],
) -> None:
    if not state["lines"]:
        return
    para_text = _splice_paragraph_lines(state["lines"], audit_data)
    trailing_h_text = ""
    m_trail = _TRAILING_HEADING_SPLIT_RE.match(para_text.strip())
    if m_trail:
        para_text = m_trail.group(1).strip()
        trailing_h_text = m_trail.group(2).strip()

    custom_style_val, para_md = _format_styled_paragraph_md(
        para_text, state["custom_style"], state["is_kaiti"], style_mapping
    )
    page_paragraphs.append(para_md)

    para_bbox = _union_bboxes([b.get("bbox") for b in state["contributing_blocks"] if b.get("bbox")])
    dominant_font, avg_size = _compute_dominant_font_and_size(state["contributing_blocks"], body_font, body_size)
    para_rec: Dict[str, Any] = {
        "type": "paragraph",
        "page_num": page_num,
        "raw_text": para_text,
        "md_text": para_md,
        "bbox": para_bbox,
        "font_name": dominant_font,
        "font_size": avg_size,
        "custom_style": custom_style_val,
    }
    layout_records.append(para_rec)
    para_metas = state.get("para_metas_by_id")
    if isinstance(para_metas, dict):
        para_metas[id(para_rec)] = {
            "line_count": len(state["lines"]),
            "last_line_x1": state["last_line_x1"],
            "first_line_bbox": state.get("first_line_bbox"),
            "first_raw_line": state.get("first_raw_line", ""),
        }

    _emit_trailing_heading_if_present(
        trailing_h_text, page_num, para_bbox, dominant_font, avg_size,
        style_mapping, page_paragraphs, layout_records, audit_data,
    )
    state["last_flushed_para_text"] = trailing_h_text if trailing_h_text else para_text
    state["lines"] = []
    state["contributing_blocks"] = []
    state["is_kaiti"] = False
    state["custom_style"] = None
    state["first_line_bbox"] = None
    state["first_raw_line"] = ""


def _detect_font_mapped_heading_level(
    block_font_role: Optional[str], block_docx_style: Optional[str], is_toc_line: bool, is_ignored_font: bool
) -> int:
    if is_ignored_font or is_toc_line:
        return 0
    if block_font_role:
        role_upper = block_font_role.upper()
        if role_upper in ("H1", "H2", "H3"):
            return int(role_upper[1])
        return 0
    if block_docx_style:
        if _STYLE_HEADING1_RE.search(block_docx_style):
            return 1
        if _STYLE_HEADING2_RE.search(block_docx_style):
            return 2
        if _STYLE_HEADING3_RE.search(block_docx_style):
            return 3
    return 0


def _detect_regex_heading_level(bb_text: str, clean_for_heading: str, has_sentence_punct: bool) -> int:
    if _H1_PART_RE.match(bb_text) or _H1_SPECIAL_RE.match(bb_text):
        return 1
    if _H1_CHAPTER_RE.match(bb_text) or _H2_SECTION_RE.match(bb_text):
        return 2
    if has_sentence_punct:
        return 0
    if _H3_DECIMAL_RE.match(bb_text):
        return 3
    if _H2_DECIMAL_RE.match(bb_text) or _H2_INT_SPACE_RE.match(bb_text):
        return 2
    if _H2_NUM_RE.match(bb_text):
        return 3
    if _H3_SUB_RE1.match(bb_text) and 2 <= len(clean_for_heading) <= 30:
        return 3
    return 0


def _detect_geometric_heading_level(
    lines: List[Dict[str, Any]],
    bb_text: str,
    clean_content: str,
    bbox: Sequence[float],
    avg_size: float,
    body_size: float,
    body_font: str,
    is_centered: bool,
    base_x0: float,
    page_w: float,
) -> int:
    if _CHART_TABLE_END_RE.search(bb_text) or _CIRCLED_START_RE.search(bb_text):
        return 0
    span_fonts = [(s.get("font") or "").split("+", 1)[-1].lower() for l in lines for s in l.get("spans", [])]
    is_heiti_or_bold = any(
        ("hei" in fn or "黑" in fn or "bold" in fn or "bd" in fn or "heavy" in fn or (s.get("flags", 0) & 16))
        for l in lines for s in l.get("spans", [])
        for fn in [(s.get("font") or "").lower()]
    )
    body_font_clean = body_font.lower() if body_font else ""
    cjk_span_fonts = [fn for fn in span_fonts if not any(w in fn for w in ("times", "arial", "helvetica", "georgia", "courier", "symbol"))]
    is_diff_font = bool(body_font_clean and cjk_span_fonts and any(fn != body_font_clean for fn in cjk_span_fonts))
    is_true_centered = bool(
        is_centered and (bbox[0] > base_x0 + 10.0) and abs(bbox[0] - (page_w - bbox[2])) < max(25.0, page_w * 0.08)
    )
    if avg_size >= body_size + 1.5 or (is_true_centered and avg_size >= body_size + 0.5):
        return 2
    if is_heiti_or_bold and (is_diff_font or avg_size >= body_size) and not re.search(r'[的了在]$', clean_content):
        return 3
    if is_true_centered and (is_heiti_or_bold or is_diff_font) and avg_size >= body_size - 0.5 and not re.search(r'[的了在]$', clean_content):
        return 2
    return 0


def _resolve_block_heading_level(
    bb: Dict[str, Any],
    lines: List[Dict[str, Any]],
    bb_text: str,
    bbox: Sequence[float],
    avg_size: float,
    page_num: int,
    page_w: float,
    base_x0: float,
    body_size: float,
    body_font: str,
    toc_index: Dict[str, Any],
    toc_page_offset: List[Any],
    block_font_role: Optional[str],
    block_docx_style: Optional[str],
    has_font_mapping: bool,
    is_ignored_font: bool,
    ai_heading_by_block: Dict[int, Dict[str, Any]],
) -> Tuple[int, bool, Optional[Dict[str, Any]], bool]:
    is_toc_line = bool(_TOC_LINE_RE.search(bb_text))
    clean_for_heading = _CLEAN_FOR_HEADING_RE.sub('', bb_text)
    clean_content = _HEADING_PREFIX_CLEAN_RE.sub('', clean_for_heading)
    has_sentence_punct = bool(_SENTENCE_PUNCT_RE.search(clean_content))
    is_centered = abs(((bbox[0] + bbox[2]) / 2.0) - (page_w / 2.0)) < (page_w * 0.12)

    heading_level = _detect_font_mapped_heading_level(block_font_role, block_docx_style, is_toc_line, is_ignored_font)
    if not heading_level and not is_toc_line and not has_font_mapping and not is_ignored_font:
        is_cand = (
            len(lines) <= 2 and 2 <= len(clean_for_heading) <= 35 and not has_sentence_punct
            and not _LIST_NUM_PREFIX_RE.match(bb_text)
            and not re.match(r'^(?:[¡•●◆■※★\-]|（?[一二三四五六七八九十\d]+）?[、.·\s]+[是為有在]|[圖表]\s*\d+[-_.]\d+[\s　]+[是為有在])', bb_text)
            and not re.match(r'^[圖图表]\s*\d+[\s\u3000]', bb_text)
        )
        if is_cand and toc_index:
            heading_level = _match_toc_heading(clean_for_heading, page_num, toc_index, toc_page_offset) or _match_toc_heading(bb_text, page_num, toc_index, toc_page_offset)
        if not heading_level:
            heading_level = _detect_regex_heading_level(bb_text, clean_for_heading, has_sentence_punct)
        if not heading_level and is_cand:
            heading_level = _detect_geometric_heading_level(
                lines, bb_text, clean_content, bbox, avg_size, body_size, body_font, is_centered, base_x0, page_w
            )

    ai_review = ai_heading_by_block.get(id(bb))
    ai_heading_applied = False
    if not heading_level and not has_font_mapping and not is_ignored_font and not is_toc_line and ai_review and ai_review.get("role") == "heading":
        heading_level = ai_review.get("level") or 0
        ai_heading_applied = heading_level in (1, 2, 3)

    return heading_level, ai_heading_applied, ai_review, is_toc_line


def _lookup_caption_style_from_spans(
    lines: List[Dict[str, Any]], font_role_map: Optional[Dict[str, Any]]
) -> Optional[str]:
    if not font_role_map:
        return None
    for span in (sp for ln in lines for sp in ln.get("spans", [])):
        raw_fn = (span.get("font") or "").split("+", 1)[-1]
        size_v = round(span.get("size", 0) * 2) / 2
        for cand in (f"{raw_fn} ({size_v}pt)", f"{raw_fn} ({size_v:.1f}pt)", f"{raw_fn}_{size_v}", raw_fn):
            if cand in font_role_map and font_role_map[cand].get("docx_style"):
                return font_role_map[cand].get("docx_style")
    return None


def _emit_caption_block(
    bb: Dict[str, Any],
    lines: List[Dict[str, Any]],
    bb_text: str,
    bbox: Sequence[float],
    page_num: int,
    body_font: str,
    body_size: float,
    block_docx_style: Optional[str],
    style_mapping: Dict[str, str],
    font_role_map: Optional[Dict[str, Any]],
    page_paragraphs: List[str],
    layout_records: List[Dict[str, Any]],
) -> None:
    caption_style = block_docx_style or style_mapping.get("image_caption") or _lookup_caption_style_from_spans(lines, font_role_map)
    cap_md = f'::: {{custom-style="{caption_style}"}}\n{bb_text}\n:::' if caption_style else f'*{bb_text}*'
    page_paragraphs.append(cap_md)
    c_font, c_size = _compute_dominant_font_and_size([bb], body_font, body_size)
    layout_records.append({
        "type": "caption",
        "page_num": page_num,
        "raw_text": bb_text,
        "md_text": cap_md,
        "bbox": bbox,
        "font_name": c_font,
        "font_size": c_size,
        "custom_style": caption_style or "",
    })


def _resolve_rule_kaiti_status(
    block_font_role: Optional[str],
    block_docx_style: Optional[str],
    has_font_mapping: bool,
    is_ignored_font: bool,
    ai_review: Optional[Dict[str, Any]],
    total_chars: int,
    kaiti_chars: int,
) -> bool:
    if is_ignored_font:
        return False
    if block_font_role and block_font_role.lower() in ("楷體", "楷体", "kaiti", "blockquote"):
        return True
    if block_docx_style and bool(_STYLE_KAI_RE.search(block_docx_style)):
        return True
    if has_font_mapping:
        return False
    if ai_review and ai_review.get("source") == "gemma" and ai_review.get("role") == "quote":
        return True
    return total_chars > 0 and (kaiti_chars / total_chars) > 0.5


def _determine_block_kaiti_status(
    page: Any,
    lines: List[Dict[str, Any]],
    bb_text: str,
    bbox: Sequence[float],
    block_font_role: Optional[str],
    block_docx_style: Optional[str],
    has_font_mapping: bool,
    is_ignored_font: bool,
    ai_review: Optional[Dict[str, Any]],
    ai_kaiti_classifier: Any,
) -> bool:
    total_chars = 0
    kaiti_chars = 0
    block_font_names = set()
    for span in (sp for ln in lines for sp in ln.get("spans", [])):
        span_text = span.get("text", "").strip()
        if not span_text:
            continue
        total_chars += len(span_text)
        font_name = span.get("font", "").lower()
        if font_name:
            block_font_names.add(font_name)
        if "kai" in font_name or "楷" in font_name or "kt" in font_name:
            kaiti_chars += len(span_text)

    is_kaiti = _resolve_rule_kaiti_status(
        block_font_role, block_docx_style, has_font_mapping, is_ignored_font, ai_review, total_chars, kaiti_chars
    )
    if not is_kaiti and not has_font_mapping and not is_ignored_font and ai_kaiti_classifier is not None:
        try:
            is_kaiti = ai_kaiti_classifier.is_block_kaiti(
                page=page, block_bbox=bbox, block_text=bb_text, font_names=list(block_font_names),
            )
        except Exception:
            pass
    return is_kaiti


def _has_unclosed_delimiters(prev_clean: str) -> bool:
    prev_ends_with_open = bool(_OPEN_PUNCT_RE.search(prev_clean))
    unclosed_delims = update_delimiter_stack(prev_clean) if update_delimiter_stack else []
    has_unclosed_cjk_quote = bool(
        len(unclosed_delims) > 0
        or prev_clean.count('《') > prev_clean.count('》')
        or prev_clean.count('“') > prev_clean.count('”')
        or prev_clean.count('（') > prev_clean.count('）')
        or prev_clean.count('(') > prev_clean.count(')')
    )
    return prev_ends_with_open or has_unclosed_cjk_quote


def _evaluate_punctuation_and_indent_break(
    prev_clean: str,
    curr_clean: str,
    first_para_line: str,
    is_indented: bool,
    curr_has_space_indent: bool,
    indent_jump: bool,
    prev_block_was_short_line: bool,
    vertical_gap: float,
    avg_size: float,
) -> bool:
    if vertical_gap > avg_size * 1.5:
        return True
    prev_no_mark = _TRAILING_MARK_RE.sub('', prev_clean)
    prev_has_terminal = bool(_TERMINAL_PUNCT_RE.search(prev_no_mark))
    prev_ends_with_colon = bool(re.search(r'[：:]$', prev_no_mark))
    is_hanging_citation = bool(
        first_para_line
        and re.match(r'^[\[［【]\s*\d+\s*[\]］】]', first_para_line)
        and not re.match(r'^[\[［【]\s*\d+\s*[\]］】]', curr_clean)
    )
    if prev_has_terminal:
        return bool(is_indented or curr_has_space_indent or prev_block_was_short_line or vertical_gap > avg_size * 0.9)
    if prev_ends_with_colon and not is_hanging_citation and (is_indented or curr_has_space_indent or prev_block_was_short_line):
        return True
    if not is_hanging_citation and (is_indented or curr_has_space_indent) and indent_jump and prev_block_was_short_line:
        return True
    return False


def _should_flush_before_block(
    state: Dict[str, Any],
    bb_text: str,
    bbox: Sequence[float],
    avg_size: float,
    base_x0: float,
    max_x1: float,
    is_block_kaiti: bool,
    block_custom_style: Optional[str],
    ai_boundary_override: Any,
    page_num: int,
    audit_data: Dict[str, Any],
    first_line_x0: Optional[float] = None,
    raw_first_line: Optional[str] = None,
) -> bool:
    if not state["lines"]:
        return False
    if is_block_kaiti != state["is_kaiti"] or block_custom_style != state["custom_style"]:
        return True
    prev_clean = state["lines"][-1].strip()
    curr_clean = bb_text.strip()
    if curr_clean and _PARA_START_PREFIX_RE.match(curr_clean):
        return True

    effective_x0 = first_line_x0 if first_line_x0 is not None else bbox[0]
    space_probe = raw_first_line if raw_first_line is not None else bb_text
    is_indented = (effective_x0 - base_x0) >= max(10.0, avg_size * 1.4)
    curr_has_space_indent = bool(re.match(r'^(?:[\u3000\u2003]| {2,4})', space_probe))
    indent_jump = bool((effective_x0 - state["last_x0"]) >= 5.0)
    vertical_gap = (bbox[1] - state["last_y1"]) if state["last_y1"] > 0 else 0.0
    prev_ref_x1 = state["last_line_x1"] if state["last_line_x1"] > 0 else state["last_x1"]
    prev_short = bool(prev_ref_x1 > 0 and prev_ref_x1 < max_x1 - max(avg_size * 2.0, 20.0))

    is_unclosed = _has_unclosed_delimiters(prev_clean)
    prev_clean_content = _HEADING_PREFIX_CLEAN_RE.sub('', _CLEAN_FOR_HEADING_RE.sub('', prev_clean))
    prev_is_heading_like = bool(
        not is_unclosed and len(state["lines"]) == 1 and 2 <= len(prev_clean_content) <= 35
        and not _SENTENCE_PUNCT_RE.search(prev_clean_content) and prev_short
        and not re.search(r'[的了在和与]$', prev_clean_content)
    )

    if prev_is_heading_like:
        should_flush = True
    elif is_unclosed:
        should_flush = False
    else:
        should_flush = _evaluate_punctuation_and_indent_break(
            prev_clean, curr_clean, state["lines"][0].strip(),
            is_indented, curr_has_space_indent, indent_jump, prev_short, vertical_gap, avg_size,
        )

    if ai_boundary_override is not None and not is_unclosed and not prev_is_heading_like:
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
    return should_flush


def _update_state_coords(
    state: Dict[str, Any], bbox: Sequence[float], last_line_x1: float = 0.0, reset_heading: bool = True
) -> None:
    state["last_x0"] = bbox[0]
    state["last_x1"] = bbox[2]
    state["last_y1"] = bbox[3]
    state["last_line_x1"] = last_line_x1
    if reset_heading:
        state["last_heading_text"] = ""


def _handle_non_text_flow_item(
    item: Dict[str, Any],
    state: Dict[str, Any],
    page_num: int,
    page_w: float,
    page_h: float,
    body_font: str,
    body_size: float,
    enable_footnotes: bool,
    page_footnotes: List[Dict[str, Any]],
    style_mapping: Dict[str, str],
    all_image_blocks: List[Dict[str, Any]],
    page_paragraphs: List[str],
    layout_records: List[Dict[str, Any]],
    audit_data: Dict[str, Any],
) -> bool:
    itype = item["type"]
    if itype == "text":
        return False

    _flush_accumulated_paragraph(
        state, page_num, body_font, body_size, style_mapping, page_paragraphs, layout_records, audit_data
    )
    item_bbox = item["bbox"]
    _update_state_coords(state, item_bbox, 0.0, reset_heading=True)

    if itype == "figure":
        block_idx, _ = item["data"]
        all_image_blocks.append({"page_num": page_num, "block_idx": block_idx, "bbox": item_bbox, "page_w": page_w, "page_h": page_h})
        fig_raw_md = f"![__IMG_PLACEHOLDER_{page_num}_{block_idx}__]()"
        page_paragraphs.append(fig_raw_md)
        layout_records.append({"type": "figure", "page_num": page_num, "block_idx": block_idx, "raw_md": fig_raw_md, "bbox": item_bbox, "font_name": "figure", "font_size": 10.5})
        return True
    if itype == "table":
        tbl_md = _table_to_markdown(item["data"], page_footnotes, page_num)
        if tbl_md:
            page_paragraphs.append(tbl_md)
        layout_records.append({"type": "table", "page_num": page_num, "bbox": item_bbox, "raw_md": tbl_md or ""})
        return True
    if itype == "reconstructed_table":
        rtbl = item["data"]
        tbl_md = _replace_fn_markers_in_text(rtbl.markdown, page_footnotes, page_num) if (enable_footnotes and page_footnotes) else rtbl.markdown
        if tbl_md:
            page_paragraphs.append(tbl_md)
        layout_records.append({
            "type": "table", "page_num": page_num, "bbox": item_bbox, "raw_md": tbl_md or "",
            "caption_text": getattr(rtbl, "caption_text", ""),
        })
    return True


def _emit_heading_block(
    bb: Dict[str, Any],
    bb_text: str,
    bbox: Sequence[float],
    cur_last_line_x1: float,
    heading_level: int,
    ai_heading_applied: bool,
    ai_review: Optional[Dict[str, Any]],
    block_docx_style: Optional[str],
    state: Dict[str, Any],
    page_num: int,
    body_font: str,
    body_size: float,
    style_mapping: Dict[str, str],
    page_paragraphs: List[str],
    layout_records: List[Dict[str, Any]],
    audit_data: Dict[str, Any],
) -> None:
    _flush_accumulated_paragraph(
        state, page_num, body_font, body_size, style_mapping, page_paragraphs, layout_records, audit_data
    )
    prev_heading = state["last_heading_text"]
    _update_state_coords(state, bbox, cur_last_line_x1, reset_heading=False)
    if bb_text == prev_heading:
        return
    state["last_heading_text"] = bb_text
    audit_data["headings_detected"].append({
        "page": page_num,
        "level": f"H{heading_level}",
        "text": bb_text,
        "source": "gemma" if ai_heading_applied else "deterministic",
        "confidence": ai_review.get("confidence") if (ai_heading_applied and ai_review) else None,
        "reason": ai_review.get("reason", "") if (ai_heading_applied and ai_review) else "",
    })
    custom_style = block_docx_style or style_mapping.get(f"h{heading_level}")
    formatted_heading = f"{'#' * heading_level} {bb_text} {{custom-style=\"{custom_style}\"}}" if custom_style else f"{'#' * heading_level} {bb_text}"
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


def _append_block_lines_to_state(
    bb: Dict[str, Any],
    lines: List[Dict[str, Any]],
    state: Dict[str, Any],
    is_block_kaiti: bool,
    block_custom_style: Optional[str],
    page_footnotes: List[Dict[str, Any]],
    page_num: int,
) -> None:
    if not state["lines"]:
        state["is_kaiti"] = is_block_kaiti
        state["custom_style"] = block_custom_style

    block_has_valid_line = False
    for line in lines:
        line_str = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
        if not line_str:
            continue
        preceding_ctx = state["lines"][-1] if state["lines"] else state["last_flushed_para_text"]
        state["lines"].append(_replace_fn_markers_in_text(line_str, page_footnotes, page_num, preceding_context=preceding_ctx))
        block_has_valid_line = True
    if block_has_valid_line:
        state["contributing_blocks"].append(bb)


def _process_text_flow_item(
    item: Dict[str, Any],
    page: Any,
    state: Dict[str, Any],
    page_num: int,
    page_w: float,
    base_x0: float,
    max_x1: float,
    body_font: str,
    body_size: float,
    toc_index: Dict[str, Any],
    toc_page_offset: List[Any],
    font_role_map: Optional[Dict[str, Any]],
    style_mapping: Dict[str, str],
    ai_heading_by_block: Dict[int, Dict[str, Any]],
    ai_boundary_by_item: Dict[str, Any],
    ai_kaiti_classifier: Any,
    page_footnotes: List[Dict[str, Any]],
    page_paragraphs: List[str],
    layout_records: List[Dict[str, Any]],
    audit_data: Dict[str, Any],
) -> None:
    bb = item["data"]
    lines = bb.get("lines", [])
    if not lines:
        return
    raw_first_line = "".join(s.get("text", "") for s in lines[0].get("spans", []))
    first_line_bbox = list(lines[0].get("bbox", bb.get("bbox", [0, 0, 0, 0])))
    bb_text = "".join(s.get("text", "") for l in lines for s in l.get("spans", [])).strip()
    if len(bb_text) >= 4 and len(bb_text) % 2 == 0 and bb_text[:len(bb_text) // 2] == bb_text[len(bb_text) // 2:]:
        bb_text = bb_text[:len(bb_text) // 2]

    sizes = [s.get("size", 0) for l in lines for s in l.get("spans", [])]
    avg_size = sum(sizes) / len(sizes) if sizes else 10.0
    bbox = bb.get("bbox", [0, 0, 0, 0])
    cur_last_line_x1 = lines[-1].get("bbox", bbox)[2] if lines else bbox[2]
    is_toc_line = bool(_TOC_LINE_RE.search(bb_text))

    block_font_role, block_docx_style, block_mapped_by = _lookup_block_font_mapping(lines, font_role_map, is_toc_line=is_toc_line)
    if block_mapped_by == "ai_layout":
        block_font_role, block_docx_style = None, None
    is_ignored_font = bool(block_font_role and str(block_font_role).strip().lower() in ("忽略", "ignore", "none"))
    has_font_mapping = bool((block_font_role or block_docx_style) and not is_ignored_font)

    heading_level, ai_heading_applied, ai_review, _ = _resolve_block_heading_level(
        bb, lines, bb_text, bbox, avg_size, page_num, page_w, base_x0, body_size, body_font,
        toc_index, toc_page_offset, block_font_role, block_docx_style, has_font_mapping, is_ignored_font, ai_heading_by_block,
    )
    if heading_level > 0:
        _emit_heading_block(
            bb, bb_text, bbox, cur_last_line_x1, heading_level, ai_heading_applied, ai_review,
            block_docx_style, state, page_num, body_font, body_size, style_mapping, page_paragraphs, layout_records, audit_data,
        )
        return

    state["last_heading_text"] = ""
    is_block_caption = not is_ignored_font and bool(
        (block_font_role and block_font_role.lower() in ("圖說", "图说", "caption"))
        or (block_docx_style and _STYLE_CAPTION_RE.search(block_docx_style))
    )
    if is_block_caption:
        _flush_accumulated_paragraph(state, page_num, body_font, body_size, style_mapping, page_paragraphs, layout_records, audit_data)
        _emit_caption_block(bb, lines, bb_text, bbox, page_num, body_font, body_size, block_docx_style, style_mapping, font_role_map, page_paragraphs, layout_records)
        _update_state_coords(state, bbox, cur_last_line_x1, reset_heading=False)
        return

    is_block_kaiti = _determine_block_kaiti_status(
        page, lines, bb_text, bbox, block_font_role, block_docx_style, has_font_mapping, is_ignored_font, ai_review, ai_kaiti_classifier,
    )
    block_custom_style = block_docx_style if (has_font_mapping and not is_ignored_font) else None
    ai_boundary_key = item.get("ai_boundary_key")
    ai_boundary_override = ai_boundary_by_item.get(ai_boundary_key) if isinstance(ai_boundary_key, str) else None
    if _should_flush_before_block(
        state, bb_text, bbox, avg_size, base_x0, max_x1, is_block_kaiti, block_custom_style,
        ai_boundary_override, page_num, audit_data,
        first_line_x0=first_line_bbox[0], raw_first_line=raw_first_line,
    ):
        _flush_accumulated_paragraph(state, page_num, body_font, body_size, style_mapping, page_paragraphs, layout_records, audit_data)

    if not state["lines"]:
        state["first_line_bbox"] = first_line_bbox
        state["first_raw_line"] = raw_first_line

    _append_block_lines_to_state(bb, lines, state, is_block_kaiti, block_custom_style, page_footnotes, page_num)
    _update_state_coords(state, bbox, cur_last_line_x1, reset_heading=False)


def _finalize_page_footnotes(
    page_footnotes: List[Dict[str, Any]],
    page_num: int,
    page_paragraphs: List[str],
    layout_records: List[Dict[str, Any]],
    audit_data: Dict[str, Any],
) -> None:
    for fn in page_footnotes:
        fn_id = fn["id"]
        fn_tag = f"[^p{page_num}_{fn_id}]"
        if not fn.get("matched", False):
            if page_paragraphs:
                new_p, replaced = try_replace_alpha_fallback(page_paragraphs[-1], fn_id, fn_tag)
                page_paragraphs[-1] = new_p if replaced else (page_paragraphs[-1] + fn_tag)
            else:
                page_paragraphs.append(fn_tag)
            audit_data["footnotes_fallback"] += 1
            audit_data["footnotes_detail"].append({
                "page": page_num,
                "id": fn_id,
                "status": "FALLBACK (正文上標模糊，降級錨定段末)",
                "content": fn["content"][:60],
            })
        else:
            audit_data["footnotes_matched"] += 1
            audit_data["footnotes_detail"].append({
                "page": page_num,
                "id": fn_id,
                "status": "MATCHED (雙向匹配精準錨定)",
                "content": fn["content"][:60],
            })

        page_paragraphs.append(f"{fn_tag}: {fn['content']}")
        layout_records.append({
            "type": "footnote",
            "page_num": page_num,
            "fn_id": fn_id,
            "tag": fn_tag,
            "content": fn["content"],
        })


_CUSTOM_STYLE_DIV_RE = re.compile(
    r'^:::\s*\{custom-style="([^"]+)"\}\s*\n(.*?)\n:::(\s*(?:\[\^p\d+_\d+\]\s*)*)$',
    re.DOTALL,
)
_CROSS_PAGE_ABBREV_DOT_RE = re.compile(
    r'(?:\b(?:p|pp|vol|no|fig|dr|mr|ms|vs|etc|ed|eds|st|ch|sec)|et\s+al|e\.g|i\.e|\b[A-Za-z]\.(?:[A-Za-z]\.)*)\.$',
    re.IGNORECASE,
)


def _unwrap_styled_div(md_text: str) -> Tuple[str, Optional[str], str]:
    """Strip an outer Pandoc custom-style div and return (inner_text, style_name, trailing_tags)."""
    m = _CUSTOM_STYLE_DIV_RE.match(md_text or "")
    if m:
        return m.group(2).strip(), m.group(1), m.group(3).strip()
    return (md_text or "").strip(), None, ""


def _is_cross_page_terminal(text: str) -> bool:
    """Return True if *text* ends with sentence-terminal punctuation rather than a mid-sentence wrap."""
    cleaned = re.sub(r'(?:\[\^p\d+_\d+\])+\s*$', '', text).rstrip()
    no_mark = _TRAILING_MARK_RE.sub('', cleaned)
    if _TERMINAL_PUNCT_RE.search(no_mark):
        return True
    core = re.sub(r'[”’」』）)\]】"\']+$', '', no_mark).rstrip()
    if core.endswith('.') and not _CROSS_PAGE_ABBREV_DOT_RE.search(core):
        return True
    return False


def _find_prev_nonempty_page(
    page_snapshots: List[Dict[str, Any]], start_idx: int
) -> Optional[Dict[str, Any]]:
    idx = start_idx
    while idx >= 0:
        if page_snapshots[idx]["records"]:
            return page_snapshots[idx]
        idx -= 1
    return None


def _get_last_body_record_and_md_idx(snap: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], int]:
    records = snap["records"]
    trailing_fn_count = 0
    for rec in reversed(records):
        if rec.get("type") == "footnote":
            trailing_fn_count += 1
        else:
            break
    body_idx = len(records) - 1 - trailing_fn_count
    md_idx = len(snap["paragraphs"]) - 1 - trailing_fn_count
    if body_idx < 0 or md_idx < 0:
        return None, -1
    return records[body_idx], md_idx


def _should_merge_cross_page_paragraphs(
    prev_snap: Dict[str, Any],
    curr_snap: Dict[str, Any],
    prev_rec: Dict[str, Any],
    curr_rec: Dict[str, Any],
    para_metas_by_id: Dict[int, Dict[str, Any]],
) -> bool:
    if prev_rec.get("type") != "paragraph" or curr_rec.get("type") != "paragraph":
        return False
    if prev_rec.get("custom_style", "") != curr_rec.get("custom_style", ""):
        return False
    if abs(float(prev_rec.get("font_size", 0.0)) - float(curr_rec.get("font_size", 0.0))) > 0.6:
        return False

    prev_text = str(prev_rec.get("raw_text", "")).strip()
    curr_text = str(curr_rec.get("raw_text", "")).strip()
    if not prev_text or not curr_text:
        return False
    if _TOC_LINE_RE.search(prev_text) or _TOC_LINE_RE.search(curr_text):
        return False

    prev_check = re.sub(r'(?:\[\^p\d+_\d+\])+\s*$', '', prev_text).rstrip()
    is_unclosed = _has_unclosed_delimiters(prev_check)
    if _is_cross_page_terminal(prev_check) and not is_unclosed:
        return False

    prev_meta = para_metas_by_id.get(id(prev_rec), {})
    curr_meta = para_metas_by_id.get(id(curr_rec), {})

    prev_line_count = int(prev_meta.get("line_count", 1))
    prev_clean_content = _HEADING_PREFIX_CLEAN_RE.sub('', _CLEAN_FOR_HEADING_RE.sub('', prev_check))
    prev_last_x1 = float(prev_meta.get("last_line_x1", 0.0))
    prev_max_x1 = float(prev_meta.get("max_x1", prev_snap.get("max_x1", 0.0)))
    prev_body_size = float(prev_snap.get("body_size", 10.5))
    prev_is_short = bool(prev_last_x1 > 0 and prev_last_x1 < prev_max_x1 - max(prev_body_size * 2.0, 20.0))
    if (
        not is_unclosed and prev_line_count == 1 and 2 <= len(prev_clean_content) <= 35
        and not _SENTENCE_PUNCT_RE.search(prev_clean_content) and prev_is_short
        and not re.search(r'[的了在和与]$', prev_clean_content)
    ):
        return False

    if (
        not is_unclosed and prev_last_x1 > 0
        and prev_last_x1 < prev_max_x1 - max(prev_body_size * 4.0, 45.0)
        and not re.search(r'[，,、；;：:\-—]$', prev_check)
    ):
        return False

    if _PARA_START_PREFIX_RE.match(curr_text):
        return False

    curr_raw_first_line = str(curr_meta.get("first_raw_line", ""))
    if re.match(r'^(?:[\u3000\u2003]| {2,4})', curr_raw_first_line):
        return False

    curr_base_x0 = float(curr_snap.get("base_x0", 65.0))
    curr_page_w = float(curr_snap.get("page_w", 595.0))
    curr_body_size = float(curr_snap.get("body_size", 10.5))
    curr_first_bbox = curr_meta.get("first_line_bbox") or curr_rec.get("bbox") or [0.0, 0.0, 0.0, 0.0]
    if len(curr_first_bbox) >= 4 and (float(curr_first_bbox[0]) - curr_base_x0) >= max(10.0, curr_body_size * 1.4):
        return False

    if len(curr_first_bbox) >= 4:
        is_centered = abs(((float(curr_first_bbox[0]) + float(curr_first_bbox[2])) / 2.0) - (curr_page_w / 2.0)) < (curr_page_w * 0.12)
        if (
            is_centered and (float(curr_first_bbox[0]) > curr_base_x0 + 10.0)
            and abs(float(curr_first_bbox[0]) - (curr_page_w - float(curr_first_bbox[2]))) < max(25.0, curr_page_w * 0.08)
        ):
            return False

    curr_line_count = int(curr_meta.get("line_count", 1))
    curr_clean_content = _HEADING_PREFIX_CLEAN_RE.sub('', _CLEAN_FOR_HEADING_RE.sub('', curr_text))
    if (
        curr_line_count == 1 and 2 <= len(curr_clean_content) <= 35
        and not _SENTENCE_PUNCT_RE.search(curr_clean_content)
        and not re.search(r'[。！？!?…．.]$', curr_text)
    ):
        return False

    return True


def _merge_cross_page_layout_paragraphs(
    page_snapshots: List[Dict[str, Any]],
    para_metas_by_id: Dict[int, Dict[str, Any]],
    audit_data: Dict[str, Any],
) -> None:
    """Merge incomplete prose paragraphs across consecutive pages while preserving layout contracts."""
    if len(page_snapshots) < 2:
        return

    for idx in range(len(page_snapshots) - 1):
        prev_snap = _find_prev_nonempty_page(page_snapshots, idx)
        curr_snap = page_snapshots[idx + 1]
        if prev_snap is None or not curr_snap["records"] or not curr_snap["paragraphs"]:
            continue

        prev_rec, prev_md_idx = _get_last_body_record_and_md_idx(prev_snap)
        curr_rec = curr_snap["records"][0]
        if prev_rec is None or prev_md_idx < 0:
            continue

        if not _should_merge_cross_page_paragraphs(prev_snap, curr_snap, prev_rec, curr_rec, para_metas_by_id):
            continue

        prev_inner, style_name, trailing_tags = _unwrap_styled_div(prev_snap["paragraphs"][prev_md_idx])
        prev_raw = f"{prev_inner}{trailing_tags}" if trailing_tags else (prev_inner or str(prev_rec.get("raw_text", "")).strip())
        curr_inner, _, curr_trailing = _unwrap_styled_div(curr_snap["paragraphs"][0])
        curr_raw = f"{curr_inner}{curr_trailing}" if curr_trailing else (curr_inner or str(curr_rec.get("raw_text", "")).strip())

        if _CJK_END_RE.search(prev_raw) and _CJK_START_RE.search(curr_raw):
            merged_text = prev_raw + curr_raw
            audit_data["paragraphs_reflowed"] += 1
        else:
            merged_text = prev_raw + " " + curr_raw

        effective_style = style_name or str(prev_rec.get("custom_style", ""))
        merged_md = (
            f'::: {{custom-style="{effective_style}"}}\n{merged_text}\n:::'
            if effective_style
            else merged_text
        )

        prev_snap["paragraphs"][prev_md_idx] = merged_md
        prev_rec["raw_text"] = merged_text
        prev_rec["md_text"] = merged_md

        prev_meta = para_metas_by_id.setdefault(id(prev_rec), {})
        curr_meta = para_metas_by_id.get(id(curr_rec), {})
        prev_meta["line_count"] = int(prev_meta.get("line_count", 1)) + int(curr_meta.get("line_count", 1))
        prev_meta["last_line_x1"] = curr_meta.get("last_line_x1", prev_meta.get("last_line_x1", 0.0))
        prev_meta["max_x1"] = curr_snap.get("max_x1", prev_meta.get("max_x1", prev_snap.get("max_x1", 0.0)))

        curr_snap["paragraphs"].pop(0)
        curr_snap["records"].pop(0)


_MARGIN_FOOTER_PAGE_RE = re.compile(
    r"^(?:[·•\-—\s]*\d{1,4}[·•\-—\s]*|(?:第\s*)?\d{1,4}\s*[页頁]|\d+\s*/\s*\d+)$"
)
_CUSTOM_STYLE_ATTR_TAIL_RE = re.compile(r'\s*\{custom-style="[^"]+"\}\s*$')


def _extract_layout_record_plain_text(rec: Dict[str, Any]) -> str:
    rtype = rec.get("type")
    if rtype == "heading":
        return str(rec.get("title", "")).strip()
    raw = str(rec.get("raw_text", "")).strip()
    inner, _, _ = _unwrap_styled_div(raw)
    return inner.strip()


def _extract_para_md_plain_text(md_text: str) -> str:
    inner, _, _ = _unwrap_styled_div((md_text or "").strip())
    inner = inner.lstrip("#").strip()
    return _CUSTOM_STYLE_ATTR_TAIL_RE.sub("", inner).strip()


def _is_margin_running_footer_record(rec: Dict[str, Any], page_h: float) -> bool:
    if rec.get("type") not in ("paragraph", "heading"):
        return False
    bbox = rec.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return False
    if float(bbox[1]) < page_h * 0.87:
        return False
    txt = _extract_layout_record_plain_text(rec)
    if not txt or "\n" in txt or len(txt) > 30:
        return False
    return bool(_MARGIN_FOOTER_PAGE_RE.match(txt))


def _is_margin_running_header_record(
    rec: Dict[str, Any],
    page_h: float,
    body_size: float,
    has_xu_biao_after: bool,
) -> bool:
    if rec.get("type") not in ("paragraph", "heading"):
        return False
    bbox = rec.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return False
    if float(bbox[3]) > page_h * 0.13:
        return False
    txt = _extract_layout_record_plain_text(rec)
    if not txt or "\n" in txt or len(txt) > 45:
        return False
    if re.match(r"^\s*表\s*\d+", txt) or re.search(r"[。！？!?…；;]$", txt):
        return False
    if re.match(r"^(?:\d+[.、．]|[（(]\d+[)）])", txt):
        return False
    fsize = float(rec.get("font_size") or body_size or 10.5)
    return bool(has_xu_biao_after or fsize <= max(body_size, 10.5) * 1.05)


def _merge_cross_page_layout_tables(page_snapshots: List[Dict[str, Any]]) -> None:
    """
    Merge split tables across consecutive page boundaries when intervening blocks
    between the trailing table and leading table contain at most a '续表'/'續表' marker
    (or zero body paragraphs, ignoring margin running headers/footers), column counts match,
    and either a continuation marker is present or the continuation table's first row repeats
    the prior header row.
    """
    if len(page_snapshots) < 2 or merge_gfm_tables_if_compatible is None or is_continuation_table_marker is None:
        return

    for idx in range(len(page_snapshots) - 1):
        skipped_footer_snaps: List[Dict[str, Any]] = []
        prev_snap: Optional[Dict[str, Any]] = None
        probe_idx = idx
        while probe_idx >= 0:
            cand = page_snapshots[probe_idx]
            if not cand["records"]:
                probe_idx -= 1
                continue
            cand_h = float(cand.get("page_h", 800.0))
            if all(_is_margin_running_footer_record(r, cand_h) for r in cand["records"]):
                skipped_footer_snaps.append(cand)
                probe_idx -= 1
                continue
            prev_snap = cand
            break

        curr_snap = page_snapshots[idx + 1]
        if prev_snap is None or not curr_snap["records"] or not curr_snap["paragraphs"]:
            continue

        prev_records = prev_snap["records"]
        prev_page_h = float(prev_snap.get("page_h", 800.0))
        prev_tbl_rec_idx: Optional[int] = None
        prev_trailing_footer_texts: List[str] = []
        for r_i in range(len(prev_records) - 1, -1, -1):
            rec = prev_records[r_i]
            if rec.get("type") == "table":
                prev_tbl_rec_idx = r_i
                break
            if _is_margin_running_footer_record(rec, prev_page_h):
                prev_trailing_footer_texts.append(_extract_layout_record_plain_text(rec))
                continue
            break
        if prev_tbl_rec_idx is None:
            continue
        prev_rec = prev_records[prev_tbl_rec_idx]
        prev_raw_md = str(prev_rec.get("raw_md", "")).strip()
        if not prev_raw_md:
            continue

        curr_records = curr_snap["records"]
        curr_page_h = float(curr_snap.get("page_h", 800.0))
        curr_body_size = float(curr_snap.get("body_size", 10.5))
        curr_table_rec_idx: Optional[int] = None
        xu_biao_rec_indices: List[int] = []
        margin_hdr_rec_indices: List[int] = []
        allowed_leading_plain_texts: List[str] = []
        intervening_valid = True
        for r_i, rec in enumerate(curr_records):
            rtype = rec.get("type")
            if rtype == "table":
                curr_table_rec_idx = r_i
                break
            if rtype in ("paragraph", "heading"):
                txt_probe = _extract_layout_record_plain_text(rec)
                if is_continuation_table_marker(txt_probe):
                    xu_biao_rec_indices.append(r_i)
                    allowed_leading_plain_texts.append(txt_probe)
                    if len(xu_biao_rec_indices) > 1:
                        intervening_valid = False
                        break
                    continue
                next_rec = curr_records[r_i + 1] if (r_i + 1) < len(curr_records) else None
                has_xu_biao_next = bool(
                    next_rec is not None
                    and next_rec.get("type") in ("paragraph", "heading")
                    and is_continuation_table_marker(_extract_layout_record_plain_text(next_rec))
                )
                if _is_margin_running_header_record(rec, curr_page_h, curr_body_size, has_xu_biao_next):
                    margin_hdr_rec_indices.append(r_i)
                    allowed_leading_plain_texts.append(txt_probe)
                    if len(margin_hdr_rec_indices) > 1:
                        intervening_valid = False
                        break
                    continue
            intervening_valid = False
            break

        if not intervening_valid or curr_table_rec_idx is None:
            continue

        curr_rec = curr_records[curr_table_rec_idx]
        curr_raw_md = str(curr_rec.get("raw_md", "")).strip()
        if not curr_raw_md:
            continue

        curr_paras = curr_snap["paragraphs"]
        curr_tbl_md_idx = next(
            (p_i for p_i, p_txt in enumerate(curr_paras) if p_txt.strip() == curr_raw_md),
            None,
        )
        if curr_tbl_md_idx is None:
            continue

        xu_biao_md_indices: List[int] = []
        allowed_hdr_set = set(allowed_leading_plain_texts)
        paras_before_valid = True
        for p_i in range(curr_tbl_md_idx):
            p_raw = str(curr_paras[p_i]).strip()
            if not p_raw:
                continue
            plain_p = _extract_para_md_plain_text(p_raw)
            if is_continuation_table_marker(plain_p):
                xu_biao_md_indices.append(p_i)
                if len(xu_biao_md_indices) > 1:
                    paras_before_valid = False
                    break
            elif plain_p in allowed_hdr_set:
                continue
            else:
                paras_before_valid = False
                break
        if not paras_before_valid:
            continue

        has_xu_biao = bool(xu_biao_rec_indices or xu_biao_md_indices)
        merged_md = merge_gfm_tables_if_compatible(
            prev_raw_md,
            curr_raw_md,
            has_continuation_marker=has_xu_biao,
        )
        if merged_md is None:
            continue

        prev_paras = prev_snap["paragraphs"]
        prev_tbl_md_idx = next(
            (p_i for p_i in range(len(prev_paras) - 1, -1, -1) if prev_paras[p_i].strip() == prev_raw_md),
            None,
        )
        if prev_tbl_md_idx is None:
            continue

        # Verify trailing paragraphs on prev_snap match only the bridged margin footers
        trailing_para_count = len(prev_paras) - 1 - prev_tbl_md_idx
        trailing_rec_count = len(prev_records) - 1 - prev_tbl_rec_idx
        if trailing_para_count != trailing_rec_count:
            continue
        if trailing_para_count > 0:
            allowed_footer_set = set(prev_trailing_footer_texts)
            if not all(_extract_para_md_plain_text(prev_paras[k]) in allowed_footer_set for k in range(prev_tbl_md_idx + 1, len(prev_paras))):
                continue

        prev_paras[prev_tbl_md_idx] = merged_md
        prev_rec["raw_md"] = merged_md

        for _ in range(trailing_rec_count):
            prev_paras.pop()
            prev_records.pop()

        for f_snap in skipped_footer_snaps:
            f_snap["records"].clear()
            f_snap["paragraphs"].clear()

        for p_i in range(curr_tbl_md_idx, -1, -1):
            curr_paras.pop(p_i)
        for r_i in range(curr_table_rec_idx, -1, -1):
            curr_records.pop(r_i)


def _process_single_pdf_page_layout(
    page: Any,
    page_num: int,
    body_size: float,
    body_font: str,
    toc_index: Dict[str, Any],
    toc_page_offset: List[Any],
    style_mapping: Dict[str, str],
    font_role_map: Optional[Dict[str, Any]],
    enable_footnotes: bool,
    strip_headers_heuristic: bool,
    ai_kaiti_classifier: Any,
    ai_font_decision_cache: Dict[str, Dict[str, Any]],
    retained_font_suggestions: Dict[str, Dict[str, Any]],
    final_md_pages: List[str],
    all_image_blocks: List[Dict[str, Any]],
    layout_records: List[Dict[str, Any]],
    audit_data: Dict[str, Any],
    para_metas_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
    page_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> None:
    page_h = page.rect.height
    page_w = page.rect.width
    blocks = _split_merged_heading_blocks(page.get_text("dict").get("blocks", []))

    table_bboxes: List[Any] = []
    page_tables = _detect_bordered_page_tables(page, page_w, page_h, table_bboxes)
    reconstructed_tables = _detect_three_line_tables(page, blocks, table_bboxes)

    try:
        is_cropped = bool(
            getattr(page, "cropbox", None) is not None
            and getattr(page, "mediabox", None) is not None
            and page.cropbox != page.mediabox
        )
    except Exception:
        is_cropped = False

    body_blocks, footnote_blocks, figure_blocks = _partition_page_blocks(
        blocks, page_w, page_h, body_size, enable_footnotes, strip_headers_heuristic, table_bboxes, audit_data,
        is_cropped=is_cropped,
    )
    body_blocks = _stitch_body_lines_into_blocks(body_blocks, body_size)
    page_footnotes = _parse_page_footnotes_from_blocks(footnote_blocks)
    base_x0, max_x1 = _compute_page_x_margins(body_blocks, page_w)
    flow_items = _build_interleaved_flow_items(body_blocks, figure_blocks, page_tables, reconstructed_tables)
    ai_heading_by_block = _review_page_ai_heading_candidates(
        body_blocks, page_num, page_w, body_size, body_font, font_role_map,
        style_mapping, ai_font_decision_cache, retained_font_suggestions, audit_data,
    )

    page_paragraphs: List[str] = []
    page_records: List[Dict[str, Any]] = []
    ai_boundary_by_item: Dict[str, Any] = {}
    state: Dict[str, Any] = {
        "lines": [],
        "contributing_blocks": [],
        "is_kaiti": False,
        "custom_style": None,
        "last_x0": 0.0,
        "last_x1": 0.0,
        "last_y1": 0.0,
        "last_line_x1": 0.0,
        "last_heading_text": "",
        "last_flushed_para_text": "",
        "first_line_bbox": None,
        "first_raw_line": "",
        "para_metas_by_id": para_metas_by_id,
    }

    for item in flow_items:
        if _handle_non_text_flow_item(
            item, state, page_num, page_w, page_h, body_font, body_size, enable_footnotes,
            page_footnotes, style_mapping, all_image_blocks, page_paragraphs, page_records, audit_data,
        ):
            continue
        _process_text_flow_item(
            item, page, state, page_num, page_w, base_x0, max_x1, body_font, body_size,
            toc_index, toc_page_offset, font_role_map, style_mapping, ai_heading_by_block,
            ai_boundary_by_item, ai_kaiti_classifier, page_footnotes, page_paragraphs, page_records, audit_data,
        )

    _flush_accumulated_paragraph(
        state, page_num, body_font, body_size, style_mapping, page_paragraphs, page_records, audit_data
    )
    _finalize_page_footnotes(page_footnotes, page_num, page_paragraphs, page_records, audit_data)
    if page_snapshots is not None:
        wide_boxes = [
            b.get("bbox", [0, 0, 0, 0])
            for b in body_blocks
            if (b.get("bbox", [0, 0, 0, 0])[2] - b.get("bbox", [0, 0, 0, 0])[0]) >= page_w * 0.35
        ]
        snap_base_x0 = min((bx[0] for bx in wide_boxes), default=base_x0)
        snap_max_x1 = max((bx[2] for bx in wide_boxes), default=max_x1)
        page_snapshots.append({
            "page_num": page_num,
            "page_w": page_w,
            "page_h": page_h,
            "base_x0": snap_base_x0,
            "max_x1": snap_max_x1,
            "body_size": body_size,
            "paragraphs": page_paragraphs,
            "records": page_records,
        })
    else:
        layout_records.extend(page_records)
        if page_paragraphs:
            final_md_pages.append("\n\n".join(page_paragraphs))


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
    """
    style_map = style_mapping or {}
    total_pages = len(doc)

    doc_profile = build_document_profile(doc)
    body_size = doc_profile.get("body_size", 10.5)
    body_font = doc_profile.get("body_font", "")
    toc_index = doc_profile.get("toc_index", {})
    toc_page_offset = [0 if doc_profile.get("is_native_toc") else None]
    if toc_index:
        print(f"[DocProfile] 成功建立標題索引共 {len(toc_index)} 筆 (原生書籤: {doc_profile.get('is_native_toc')})，正文基準: {body_size}pt / '{body_font}'")

    retained_font_suggestions: Dict[str, Dict[str, Any]] = {}
    ai_font_decision_cache = _build_ai_font_decision_cache(font_role_map)
    audit_data = _init_layout_audit_data(pdf_name, total_pages, style_map, retained_font_suggestions, doc_profile)

    final_md_pages: List[str] = []
    all_image_blocks: List[Dict[str, Any]] = []
    layout_records: List[Dict[str, Any]] = []
    para_metas_by_id: Dict[int, Dict[str, Any]] = {}
    page_snapshots: List[Dict[str, Any]] = []

    start_page_idx = max(0, page_range[0] - 1) if page_range else 0
    end_page_idx = min(total_pages, page_range[1]) if page_range else total_pages

    for page_idx in range(start_page_idx, end_page_idx):
        page_num = page_idx + 1
        if progress_callback:
            progress_callback(int((page_num / total_pages) * 85), f"[INFO] 正在解析第 {page_num}/{total_pages} 頁 (版面/樣式/腳注抽取)...")
        _process_single_pdf_page_layout(
            doc[page_idx], page_num, body_size, body_font, toc_index, toc_page_offset,
            style_map, font_role_map, enable_footnotes, strip_headers_heuristic,
            ai_kaiti_classifier, ai_font_decision_cache, retained_font_suggestions,
            final_md_pages, all_image_blocks, layout_records, audit_data,
            para_metas_by_id=para_metas_by_id, page_snapshots=page_snapshots,
        )

    _merge_cross_page_layout_tables(page_snapshots)
    _merge_cross_page_layout_paragraphs(page_snapshots, para_metas_by_id, audit_data)
    for snap in page_snapshots:
        if snap["paragraphs"]:
            final_md_pages.append("\n\n".join(snap["paragraphs"]))
        layout_records.extend(snap["records"])

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
    fonts_json_path: Optional[str] = None,
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
        _active_fonts = fonts_json_path if fonts_json_path is not None else _fonts_json
        if _active_fonts is None:
            _active_fonts = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json'))
        font_role_map = get_font_role_map(_active_fonts)
    except Exception:
        try:
            from scripts.pdf_font_analyzer import get_font_role_map
            _active_fonts = fonts_json_path if fonts_json_path is not None else _fonts_json
            if _active_fonts is None:
                _active_fonts = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json'))
            font_role_map = get_font_role_map(_active_fonts)
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
            _active_fonts_out = fonts_json_path if fonts_json_path is not None else _fonts_json
            if _active_fonts_out is None:
                _active_fonts_out = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json'))
            saved_cnt = save_ai_layout_suggestions_to_fonts_json(_active_fonts_out, retained_suggestions)
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
    fonts_json_path: Optional[str] = None,
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
        _active_fonts = fonts_json_path if fonts_json_path is not None else _fonts_json
        if _active_fonts is None:
            _active_fonts = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json'))
        font_role_map = get_font_role_map(_active_fonts)
    except Exception:
        try:
            from scripts.pdf_font_analyzer import get_font_role_map
            _active_fonts = fonts_json_path if fonts_json_path is not None else _fonts_json
            if _active_fonts is None:
                _active_fonts = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fonts.json'))
            font_role_map = get_font_role_map(_active_fonts)
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
