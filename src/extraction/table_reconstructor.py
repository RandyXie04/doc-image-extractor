# -*- coding: utf-8 -*-
"""
Pure Algorithmic Operator for 2D Table Reconstruction & False-Table Filtering (ADR-007)
=======================================================================================
Enforces the Zero Raw-Dict Policy via frozen dataclasses:
- Filters false-positive 1x2 decorative drop-cap boxes produced by PyMuPDF find_tables().
- Detects Chinese academic three-line tables (三線表) via horizontal drawing rules and column segment hints.
- Reconstructs 2D cell grids from character/span coordinates, resolving multi-line headers
  and vertically centered row-span cells (e.g. group labels centered across 4 rows).
"""

from __future__ import annotations
import html as _html_mod
import re
from dataclasses import dataclass
from typing import List, Tuple, Sequence, Optional, Any


@dataclass(frozen=True)
class TextSpan2D:
    """Immutable 2D text unit (character or span) with bounding box in PDF points."""
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_name: str = ""
    font_size: float = 0.0

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) * 0.5

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) * 0.5


@dataclass(frozen=True)
class TableRegion:
    """Immutable geometric specification of a detected three-line table on a page."""
    bbox: Tuple[float, float, float, float]
    top_rule_y: float
    mid_rule_y: float
    bot_rule_y: float
    col_x_hints: Tuple[float, ...]
    sub_header_rule_y: Optional[float] = None
    caption_text: str = ""


@dataclass(frozen=True)
class ReconstructedTable:
    """Immutable reconstructed table output with structured cells and GFM Pipe Table markdown."""
    bbox: Tuple[float, float, float, float]
    headers: Tuple[str, ...]
    rows: Tuple[Tuple[str, ...], ...]
    markdown: str
    caption_text: str = ""


@dataclass(frozen=True)
class TableCellSpan:
    """Immutable table cell with explicit rowspan/colspan metadata."""
    text: str
    rowspan: int = 1
    colspan: int = 1
    is_header: bool = False


_TABLE_CAPTION_RE = re.compile(r"^\s*表\s*\d+")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CJK_SPURIOUS_SPACE_RE = re.compile(
    r"(?<=[\u4e00-\u9fff\u3400-\u4dbf\u3001-\u303f\uff01-\uffef\u2018-\u201f\u2014\u2026\u00b7])[ \t]+(?=[\u4e00-\u9fff\u3400-\u4dbf\u3001-\u303f\uff01-\uffef\u2018-\u201f\u2014\u2026\u00b7])"
)
_CJK_OPEN_PUNCT_SPACE_RE = re.compile(r"(?<=[（【「『《〈、])[ \t]+")
_CJK_CLOSE_PUNCT_SPACE_RE = re.compile(r"[ \t]+(?=[）】」』》〉，。、；：！？])")
_OP_AFTER_SPACE_RE = re.compile(
    r"(?<=[＞＜≥≤﹥﹤～±])[ \t]+(?=[\d\u4e00-\u9fff\u3400-\u4dbf\u2160-\u217f+\-（(])"
)
_OP_BEFORE_SPACE_RE = re.compile(
    r"(?<=[\d\u4e00-\u9fff\u3400-\u4dbf\u2160-\u217f）)])[ \t]+(?=[＞＜≥≤﹥﹤～±])"
)
_CJK_SLASH_SPACE_RE = re.compile(
    r"(?<=[\u4e00-\u9fff\u3400-\u4dbf])[ \t]*/[ \t]*(?=[\u4e00-\u9fff\u3400-\u4dbf])"
)
_ROMAN_CJK_SPACE_RE = re.compile(
    r"(?<=[\u2160-\u217f])[ \t]+(?=[\u4e00-\u9fff\u3400-\u4dbf])|(?<=[\u4e00-\u9fff\u3400-\u4dbf])[ \t]+(?=[\u2160-\u217f])"
)
_DIGIT_CJK_UNIT_SPACE_RE = re.compile(
    r"(?<=\d)[ \t]+(?=[个例年月日周天次岁级条项种层倍分秒])"
)
_PRE_SCRIPT_TAG_SPACE_RE = re.compile(r"[ \t]+(?=<(?:sup|sub)>)")
_CJK_EDGE_CHAR_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\u3001-\u303f\uff01-\uffef\u2018-\u201f\u2014\u2026\u00b7\u2160-\u217f\u2460-\u2473＞＜≥≤﹥﹤＝±×÷～°%‰／]"
)
_XU_BIAO_BARE_RE = re.compile(
    r"^[（(]?\s*(?:续\s*前?\s*表|續\s*前?\s*表)\s*[）)]?[：:.]?\s*$"
)
_XU_BIAO_PREFIXED_RE = re.compile(
    r"^[（(]?\s*(?:续\s*表|續\s*表)\s*\d*(?:[-—–.．]\d+)*(?:[\s\u3000:：].{0,60})?\s*[）)]?$"
)
_TABLE_CAPTION_CONT_RE = re.compile(
    r"^表\s*\d+(?:[-—–.．]\d+)*[^\n]{0,65}(?:[（(]\s*(?:续\s*表?|續\s*表?|续\s*\d+|續\s*\d+)\s*[）)]|[\s\u3000]+(?:续\s*表?|續\s*表?))\s*$"
)
_TABLE_EN_CONT_RE = re.compile(
    r"^Table\s+\d+(?:[.-]\d+)*[^\n]{0,65}\(\s*cont(?:inued)?\.?\s*\)\s*$",
    re.I,
)
_STANDALONE_PAGE_NUM_RE = re.compile(
    r"^\s*(?:(?:[-—–·•]\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?(?:\s*[-—–·•])?|第\s*\d{1,4}\s*[页頁])\s*$"
)
_TABLE_NOTE_PREFIX_RE = re.compile(
    r"^\s*(?:(?:表\s*[注註]|[注註]\s*\d*|说\s*明|說\s*明|附\s*[注註]|Notes?)\s*[：:.]|[※＊\*]\s*(?:[注註]|表示|指|为|為))",
    re.I,
)
_TABLE_NOTE_NEW_ITEM_RE = re.compile(
    r"^\s*(?:(?:表\s*[注註]|[注註]\s*\d*|说\s*明|說\s*明|附\s*[注註]|Notes?)\s*[：:.]|[·•●▪◆※＊\*]|[\u2460-\u2473]|\d+\s*[.、）)]|[a-zA-Z]\s*[.）)])",
    re.I,
)
_PLACEHOLDER_HEADER_CELL_RE = re.compile(
    r"^(?:欄|栏|列|col(?:umn)?|field|unnamed)\s*[:：_-]?\s*\d+$",
    re.I,
)
_CIRCLED_FN_ONLY_RE = re.compile(r"^[\u2460-\u2473\s]+$")
_TOC_DOT_LEADER_RE = re.compile(r"[\.…·\u0107\x08\-_]{2,}\s*\d+\s*$")
_TOC_CHAPTER_PAGE_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[一二三四五六七八九十百零\d]+\s*[章节節篇卷回讲講]"
    r"|附\s*录|主要?参考文献|参考文献|后\s*记|结\s*语|前\s*言|序\s*言|引\s*言"
    r"|[一二三四五六七八九十百]+[、.．]\s*[^\d\n]"
    r"|\d+\.\d+(?:\.\d+)?[\s\u3000]+[^\d\n]"
    r"|(?:Chapter|Part|Section|Appendix)\s+\d+"
    r").*\s+\d{1,4}\s*$",
    re.I,
)
_TOC_HEADING_RE = re.compile(r"^\s*(?:目[\s\u3000]*录|目[\s\u3000]*錄|TABLE\s+OF\s+CONTENTS|CONTENTS)\s*$", re.I)
_GFM_SEP_CELL_RE = re.compile(r"^:?-{2,}:?$")


def _normalize_table_line_spacing(raw_line: str) -> str:
    s = _CONTROL_CHAR_RE.sub("", raw_line).strip()
    if not s:
        return ""
    s = _CJK_SPURIOUS_SPACE_RE.sub("", s)
    s = _CJK_OPEN_PUNCT_SPACE_RE.sub("", s)
    s = _CJK_CLOSE_PUNCT_SPACE_RE.sub("", s)
    s = _OP_AFTER_SPACE_RE.sub("", s)
    s = _OP_BEFORE_SPACE_RE.sub("", s)
    s = _CJK_SLASH_SPACE_RE.sub("/", s)
    s = _ROMAN_CJK_SPACE_RE.sub("", s)
    s = _DIGIT_CJK_UNIT_SPACE_RE.sub("", s)
    s = _PRE_SCRIPT_TAG_SPACE_RE.sub("", s)
    return s


def clean_table_cell_text(cell: Optional[str]) -> str:
    """
    Normalizes PDF table cell text by stripping control characters and spurious
    justification spaces between CJK/Roman/operator tokens and joining wrapped CJK
    lines without inserting extra spaces, while preserving ASCII word/list spacing
    (e.g. '1. 八珍粥 2. 桂圆红枣粥') and inline <sup>/<sub> tags.
    """
    if not cell:
        return ""
    cleaned_lines: List[str] = []
    for raw_line in str(cell).splitlines():
        s = _normalize_table_line_spacing(raw_line)
        if s:
            cleaned_lines.append(s)
    if not cleaned_lines:
        return ""
    joined = cleaned_lines[0]
    for nxt in cleaned_lines[1:]:
        prev_is_edge = bool(_CJK_EDGE_CHAR_RE.match(joined[-1])) or joined.endswith(("</sup>", "</sub>"))
        nxt_is_edge = bool(_CJK_EDGE_CHAR_RE.match(nxt[0])) or nxt.startswith(("<sup>", "<sub>"))
        if prev_is_edge and nxt_is_edge:
            joined += nxt
        else:
            joined += " " + nxt
    joined = _normalize_table_line_spacing(joined)
    return re.sub(r"[ \t]{2,}", " ", joined).strip()


def extract_cell_text_with_scripts(
    page: Any,
    cell_bbox: Sequence[float],
    fallback_text: str = "",
) -> str:
    """
    Extract table cell text from a PyMuPDF page clipped to cell_bbox, preserving
    genuine raised superscripts (<sup>...</sup>) and lowered subscripts (<sub>...</sub>)
    while leaving circled footnote markers untouched for downstream footnote replacement.
    """
    if page is None or not cell_bbox or len(cell_bbox) < 4:
        return clean_table_cell_text(fallback_text)
    try:
        import fitz

        clip_rect = fitz.Rect(
            float(cell_bbox[0]),
            float(cell_bbox[1]),
            float(cell_bbox[2]),
            float(cell_bbox[3]),
        )
        if clip_rect.width <= 0.5 or clip_rect.height <= 0.5:
            return clean_table_cell_text(fallback_text)
        raw_dict = page.get_text("dict", clip=clip_rect)
    except Exception:
        return clean_table_cell_text(fallback_text)

    raw_spans: List[Tuple[float, float, float, float, float, int, str]] = []
    for blk in raw_dict.get("blocks", []):
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            for sp in ln.get("spans", []):
                txt = _CONTROL_CHAR_RE.sub("", str(sp.get("text", "")))
                if not txt:
                    continue
                sb = sp.get("bbox", [0, 0, 0, 0])
                if len(sb) < 4:
                    continue
                x0, y0, x1, y1 = float(sb[0]), float(sb[1]), float(sb[2]), float(sb[3])
                # Skip spans whose centers lie outside the cell bbox
                cx = (x0 + x1) * 0.5
                cy = (y0 + y1) * 0.5
                if not (
                    clip_rect.x0 - 1.5 <= cx <= clip_rect.x1 + 1.5
                    and clip_rect.y0 - 1.5 <= cy <= clip_rect.y1 + 1.5
                ):
                    continue
                size = float(sp.get("size", 0.0))
                flags = int(sp.get("flags", 0))
                raw_spans.append((x0, y0, x1, y1, size, flags, txt))

    if not raw_spans:
        return clean_table_cell_text(fallback_text)

    # Group spans into visual lines using vertical overlap/proximity
    raw_spans.sort(key=lambda it: ((it[1] + it[3]) * 0.5, it[0]))
    visual_lines: List[List[Tuple[float, float, float, float, float, int, str]]] = []
    for sp in raw_spans:
        x0, y0, x1, y1, size, flags, txt = sp
        placed = False
        for vline in visual_lines:
            # Compare against non-tiny anchor spans in line if available
            max_sz = max(s[4] for s in vline)
            anchors = [s for s in vline if s[4] >= max_sz * 0.8] or vline
            l_y0 = min(s[1] for s in anchors)
            l_y1 = max(s[3] for s in anchors)
            l_h = max(l_y1 - l_y0, max_sz, 4.0)
            overlap = min(y1, l_y1) - max(y0, l_y0)
            if overlap >= -l_h * 0.15 and abs(((y0 + y1) * 0.5) - ((l_y0 + l_y1) * 0.5)) <= l_h * 0.65:
                vline.append(sp)
                placed = True
                break
        if not placed:
            visual_lines.append([sp])

    # Sort visual lines top-to-bottom
    visual_lines.sort(key=lambda vl: min(s[1] for s in vl))

    rendered_lines: List[str] = []
    has_script = False
    for vline in visual_lines:
        vline.sort(key=lambda s: s[0])
        non_ws = [s for s in vline if s[6].strip()]
        if not non_ws:
            continue
        base_size = max(s[4] for s in non_ws)
        base_spans = [s for s in non_ws if s[4] >= base_size * 0.85]
        if not base_spans or base_size <= 0.0:
            rendered_lines.append("".join(s[6] for s in vline))
            continue
        base_y0 = sum(s[1] for s in base_spans) / len(base_spans)
        base_y1 = sum(s[3] for s in base_spans) / len(base_spans)
        base_cy = (base_y0 + base_y1) * 0.5

        parts: List[str] = []
        prev_x1: Optional[float] = None
        for x0, y0, x1, y1, size, flags, txt in vline:
            stripped_txt = txt.strip()
            if not stripped_txt:
                parts.append(txt)
                prev_x1 = x1
                continue
            if (
                prev_x1 is not None
                and x0 - prev_x1 > base_size * 0.35
                and parts
                and not parts[-1].endswith(" ")
                and not txt.startswith(" ")
            ):
                parts.append(" ")
            cy = (y0 + y1) * 0.5
            is_smaller = size <= base_size * 0.78
            is_sup_flag = bool(flags & 1) and size <= base_size * 0.88
            if (is_smaller or is_sup_flag) and not _CIRCLED_FN_ONLY_RE.match(stripped_txt):
                if y1 < base_y1 - base_size * 0.16 and cy < base_cy - base_size * 0.08:
                    parts.append(f"<sup>{stripped_txt}</sup>")
                    if txt[-1].isspace():
                        parts.append(" ")
                    has_script = True
                    prev_x1 = x1
                    continue
                if y0 > base_y0 + base_size * 0.16 and cy > base_cy + base_size * 0.08:
                    parts.append(f"<sub>{stripped_txt}</sub>")
                    if txt[-1].isspace():
                        parts.append(" ")
                    has_script = True
                    prev_x1 = x1
                    continue
            # Strip PyMuPDF-synthesized leading space immediately after <sup>/<sub> before tight chemical/unit continuation (e.g. H<sub>2</sub>O, 10<sup>9</sup>/L)
            if (
                parts
                and parts[-1].endswith(("</sup>", "</sub>"))
                and prev_x1 is not None
                and x0 - prev_x1 <= base_size * 0.25
                and txt.startswith(" ")
                and re.match(r"^[A-Z0-9/%°]", stripped_txt)
            ):
                parts.append(txt.lstrip(" "))
            else:
                parts.append(txt)
            prev_x1 = x1
        line_str = "".join(parts)
        line_str = line_str.replace("</sup><sup>", "").replace("</sub><sub>", "")
        rendered_lines.append(line_str)

    if not has_script and fallback_text:
        return clean_table_cell_text(fallback_text)
    return clean_table_cell_text("\n".join(rendered_lines))


def split_trailing_table_notes(
    rows: Sequence[Sequence[str]],
    table_obj: Any = None,
) -> Tuple[List[List[str]], List[str]]:
    """
    Detach trailing completely-empty rows and trailing single-cell table note blocks
    (e.g., '注：...', '表注：...', '说明：...', 'Note: ...' and wrapped continuation rows)
    that PyMuPDF erroneously absorbs into the bottom of a bordered table.
    Returns (body_rows, note_paragraphs).
    """
    if not rows:
        return [], []
    row_list: List[List[str]] = [list(r) for r in rows]

    # Trim trailing completely empty rows first
    while len(row_list) > 1 and all(not c.strip() for c in row_list[-1]):
        row_list.pop()

    ncols = max((len(r) for r in row_list), default=0)
    if len(row_list) < 2 or ncols < 2:
        return row_list, []

    # Walk backwards over trailing suffix of rows containing <= 1 non-empty cell
    suffix_start = len(row_list)
    for r_idx in range(len(row_list) - 1, 0, -1):
        non_empty = [c.strip() for c in row_list[r_idx] if c.strip()]
        if len(non_empty) <= 1:
            suffix_start = r_idx
        else:
            break

    if suffix_start >= len(row_list):
        return row_list, []

    # Find the earliest row in [suffix_start .. end) starting with an explicit table-note prefix
    note_start: Optional[int] = None
    for r_idx in range(suffix_start, len(row_list)):
        non_empty = [c.strip() for c in row_list[r_idx] if c.strip()]
        if len(non_empty) == 1 and _TABLE_NOTE_PREFIX_RE.match(non_empty[0]):
            note_start = r_idx
            break

    if note_start is None or note_start < 1:
        return row_list, []

    raw_note_lines: List[str] = []
    for r_idx in range(note_start, len(row_list)):
        non_empty = [c.strip() for c in row_list[r_idx] if c.strip()]
        if non_empty:
            raw_note_lines.append(non_empty[0])

    # Merge wrapped continuation note rows while keeping distinct bullet/note items separate
    note_paragraphs: List[str] = []
    for line in raw_note_lines:
        if not note_paragraphs:
            note_paragraphs.append(line)
            continue
        prev = note_paragraphs[-1]
        starts_new = bool(_TABLE_NOTE_NEW_ITEM_RE.match(line))
        prev_complete = bool(re.search(r"[。！？.!?；;]$", prev))
        if starts_new or prev_complete:
            note_paragraphs.append(line)
        else:
            if _CJK_EDGE_CHAR_RE.match(prev[-1]) and _CJK_EDGE_CHAR_RE.match(line[0]):
                note_paragraphs[-1] = prev + line
            else:
                note_paragraphs[-1] = prev + " " + line

    body_rows = row_list[:note_start]
    # Also strip any empty spacer rows that sat immediately above the note block
    while len(body_rows) > 1 and all(not c.strip() for c in body_rows[-1]):
        body_rows.pop()

    return body_rows, note_paragraphs


def normalize_pymupdf_table_rows(
    rows: Sequence[Sequence[Any]],
    table_obj: Any = None,
) -> List[List[str]]:
    """
    Cleans cell text via clean_table_cell_text(), trims trailing completely empty rows,
    and collapses phantom narrow sliver columns (e.g., <12pt inset border artifacts where
    one column has an empty header and cells across every row are mutually exclusive with
    the adjacent column).
    """
    if not rows:
        return []
    ncols = max((len(r) for r in rows if r), default=0)
    if ncols == 0:
        return []

    cleaned: List[List[str]] = []
    for r in rows:
        row_cells = [clean_table_cell_text(r[c] if c < len(r) else "") for c in range(ncols)]
        cleaned.append(row_cells)

    while len(cleaned) > 1 and all(not c for c in cleaned[-1]):
        cleaned.pop()

    if ncols < 2 or len(cleaned) < 2:
        return cleaned

    min_widths: List[Optional[float]] = [None] * ncols
    t_rows = getattr(table_obj, "rows", None) if table_obj is not None else None
    if t_rows:
        for c_idx in range(ncols):
            ws: List[float] = []
            for tr in t_rows:
                cells = getattr(tr, "cells", None)
                if cells and c_idx < len(cells) and cells[c_idx] is not None:
                    box = cells[c_idx]
                    if len(box) >= 4:
                        ws.append(float(box[2]) - float(box[0]))
            if ws:
                min_widths[c_idx] = min(ws)

    changed = True
    while changed and len(cleaned[0]) >= 2:
        changed = False
        cur_cols = len(cleaned[0])
        for c_idx in range(cur_cols - 1):
            hdr_left = cleaned[0][c_idx]
            hdr_right = cleaned[0][c_idx + 1]
            if hdr_left and hdr_right:
                continue
            disjoint = all(not (r[c_idx] and r[c_idx + 1]) for r in cleaned)
            if not disjoint:
                continue
            mw_l = min_widths[c_idx]
            mw_r = min_widths[c_idx + 1]
            has_sliver = (
                (mw_l is not None and mw_l < 12.0)
                or (mw_r is not None and mw_r < 12.0)
            )
            if t_rows and not has_sliver:
                continue
            if not t_rows and (hdr_left or hdr_right):
                # Without geometry info, only collapse completely empty trailing/leading column
                empty_l = all(not r[c_idx] for r in cleaned)
                empty_r = all(not r[c_idx + 1] for r in cleaned)
                if not (empty_l or empty_r):
                    continue
            merged_rows: List[List[str]] = []
            for r in cleaned:
                merged_cell = r[c_idx] or r[c_idx + 1]
                merged_rows.append(r[:c_idx] + [merged_cell] + r[c_idx + 2:])
            cleaned = merged_rows
            if mw_l is not None and mw_r is not None:
                merged_w: Optional[float] = mw_l + mw_r
            else:
                merged_w = mw_r if mw_l is None else mw_l
            min_widths = min_widths[:c_idx] + [merged_w] + min_widths[c_idx + 2:]
            changed = True
            break

    return cleaned


def is_continuation_table_marker(text: str) -> bool:
    """
    Return True when text represents a continuation-table marker, including:
    - Bare '续表' / '續表' / '(续表)' / '（续前表）'
    - Numbered continuation markers such as '续表13-1', '表13-1（续）', '表13-1 标题（续）', 'Table 1 (continued)'
    """
    if not text:
        return False
    stripped = text.strip().lstrip("#").strip()
    if not stripped or len(stripped) > 85 or "\n" in stripped:
        return False
    if re.search(r"[。！？!?；;]$", stripped):
        return False
    if _XU_BIAO_BARE_RE.match(stripped):
        return True
    if _XU_BIAO_PREFIXED_RE.match(stripped):
        return True
    if _TABLE_CAPTION_CONT_RE.match(stripped):
        return True
    if _TABLE_EN_CONT_RE.match(stripped):
        return True
    return False


def is_standalone_page_number_text(text: str) -> bool:
    """Return True when text is solely a standalone page number (e.g. '256', '- 12 -', '·283·', '第12页')."""
    if not text:
        return False
    stripped = text.strip().lstrip("#").strip()
    if not stripped or "\n" in stripped:
        return False
    return bool(_STANDALONE_PAGE_NUM_RE.match(stripped))


def is_placeholder_header_cell(text: str) -> bool:
    """Return True for synthetic placeholder column names like '欄1', '栏2', '列3', 'Col 1', 'Unnamed: 0'."""
    if not text:
        return False
    return bool(_PLACEHOLDER_HEADER_CELL_RE.match(text.strip()))


def is_placeholder_header_row(row: Sequence[str]) -> bool:
    """Return True when a row consists solely of placeholder column names (and optional empty cells)."""
    if not row:
        return False
    placeholder_hits = 0
    for cell in row:
        s = str(cell or "").strip()
        if not s:
            continue
        if is_placeholder_header_cell(s):
            placeholder_hits += 1
        else:
            return False
    return placeholder_hits >= 1


def build_table_span_grid(
    cleaned_rows: Sequence[Sequence[str]],
    table_obj: Any = None,
) -> Tuple[List[List[Optional[TableCellSpan]]], bool]:
    """
    Build a 2D TableCellSpan grid preserving explicit PyMuPDF geometric rowspan/colspan
    as well as implicit leading-column hierarchical category rowspans (e.g. '临床标准'
    spanning multiple sub-rows in Table 16-3).
    Returns (span_grid, has_merges).
    """
    nrows = len(cleaned_rows)
    if nrows == 0:
        return [], False
    ncols = max((len(r) for r in cleaned_rows), default=0)
    if ncols == 0:
        return [], False

    # Initialize plain 1x1 cell grid
    grid: List[List[Optional[TableCellSpan]]] = [
        [
            TableCellSpan(
                text=str(cleaned_rows[r][c] if c < len(cleaned_rows[r]) else ""),
                rowspan=1,
                colspan=1,
                is_header=(r == 0),
            )
            for c in range(ncols)
        ]
        for r in range(nrows)
    ]
    has_merges = False

    # 1. Explicit geometric rowspan/colspan from PyMuPDF table_obj.rows
    t_rows = getattr(table_obj, "rows", None) if table_obj is not None else None
    if t_rows and len(t_rows) >= nrows:
        raw_boxes: List[List[Optional[Tuple[float, float, float, float]]]] = []
        valid_geom = True
        for r in range(nrows):
            cells = getattr(t_rows[r], "cells", None)
            if not cells or len(cells) != ncols:
                valid_geom = False
                break
            row_b: List[Optional[Tuple[float, float, float, float]]] = []
            for c in range(ncols):
                b = cells[c]
                if b is not None and len(b) >= 4:
                    row_b.append((float(b[0]), float(b[1]), float(b[2]), float(b[3])))
                else:
                    row_b.append(None)
            raw_boxes.append(row_b)

        if valid_geom:
            # Estimate nominal column left/right edges from single-column cells
            col_x0s: List[Optional[float]] = [None] * ncols
            col_x1s: List[Optional[float]] = [None] * ncols
            for c in range(ncols):
                xs = [
                    raw_boxes[r][c]
                    for r in range(nrows)
                    if raw_boxes[r][c] is not None
                    and (c + 1 >= ncols or raw_boxes[r][c + 1] is not None)
                ]
                if xs:
                    col_x0s[c] = min(b[0] for b in xs if b is not None)
                    col_x1s[c] = min(b[2] for b in xs if b is not None)

            covered = [[False] * ncols for _ in range(nrows)]
            for r in range(nrows):
                for c in range(ncols):
                    if covered[r][c]:
                        grid[r][c] = None
                        continue
                    box = raw_boxes[r][c]
                    if box is None:
                        continue
                    # Determine horizontal colspan over contiguous None/identical-box right neighbors
                    cspan = 1
                    while c + cspan < ncols and not covered[r][c + cspan]:
                        nb = raw_boxes[r][c + cspan]
                        same_box = nb is not None and all(abs(nb[k] - box[k]) <= 2.0 for k in range(4))
                        col_x1 = col_x1s[c + cspan]
                        none_covered = nb is None and (
                            col_x1 is None or box[2] >= col_x1 - 3.0
                        )
                        if same_box or none_covered:
                            cspan += 1
                        else:
                            break
                    # Determine vertical rowspan over contiguous None/identical-box below neighbors
                    rspan = 1
                    while r + rspan < nrows:
                        can_extend = True
                        for dc in range(cspan):
                            if covered[r + rspan][c + dc]:
                                can_extend = False
                                break
                            nb = raw_boxes[r + rspan][c + dc]
                            if nb is None:
                                # Only count None as rowspan if box extends past top edge of row r + rspan
                                target_r = r + rspan
                                row_y0s = [
                                    b[1]
                                    for j, b in enumerate(raw_boxes[target_r])
                                    if b is not None and not covered[target_r][j]
                                ]
                                if not row_y0s:
                                    row_y0s = [b[1] for b in raw_boxes[target_r] if b is not None]
                                if row_y0s:
                                    # Use max(y0) so tall merged cells repeating an earlier row's y0 cannot lower this row's top edge
                                    if box[3] < max(row_y0s) + 3.0:
                                        can_extend = False
                                        break
                                else:
                                    # Fully-spanned row (all boxes None): check whether box reaches the next non-empty row or extends past row r's bottom
                                    next_y0: Optional[float] = None
                                    for probe_r in range(target_r + 1, nrows):
                                        probe_y0s = [b[1] for b in raw_boxes[probe_r] if b is not None]
                                        if probe_y0s:
                                            next_y0 = max(probe_y0s)
                                            break
                                    if next_y0 is not None:
                                        if box[3] < next_y0 - 3.0:
                                            can_extend = False
                                            break
                                    else:
                                        row_r_y1s = [b[3] for b in raw_boxes[r] if b is not None]
                                        if not row_r_y1s or box[3] < min(row_r_y1s) + 3.0:
                                            can_extend = False
                                            break
                            elif not all(abs(nb[k] - box[k]) <= 2.0 for k in range(4)):
                                can_extend = False
                                break
                        if can_extend:
                            rspan += 1
                        else:
                            break
                    if cspan > 1 or rspan > 1:
                        has_merges = True
                        grid[r][c] = TableCellSpan(
                            text=str(cleaned_rows[r][c]),
                            rowspan=rspan,
                            colspan=cspan,
                            is_header=(r == 0),
                        )
                        for dr in range(rspan):
                            for dc in range(cspan):
                                if dr == 0 and dc == 0:
                                    continue
                                covered[r + dr][c + dc] = True
                                grid[r + dr][c + dc] = None

    # 2. Implicit first-column vertical category grouping (e.g. Table 16-3 '临床标准' / '实验室标准')
    header_rows = min(nrows, max((c.rowspan for c in grid[0] if c is not None), default=1))
    col0_has_vmerge = False
    for row_idx in range(header_rows, nrows):
        cell0 = grid[row_idx][0]
        if cell0 is None or cell0.rowspan > 1:
            col0_has_vmerge = True
            break
    if not col0_has_vmerge and ncols >= 3 and nrows >= header_rows + 3:
        first_body_cell = grid[header_rows][0]
        if first_body_cell is not None and first_body_cell.colspan == 1 and first_body_cell.text.strip():
            groups: List[Tuple[int, int]] = []
            blank_followers = 0
            r = header_rows
            while r < nrows:
                c0 = grid[r][0]
                c1 = grid[r][1]
                if c0 is not None and c0.colspan == 1 and c0.text.strip():
                    end_r = r
                    # Only expand into follower rows where col 0 is empty (colspan=1) AND col 1 is non-empty
                    if c1 is not None and c1.text.strip():
                        while end_r + 1 < nrows:
                            next_c0 = grid[end_r + 1][0]
                            next_c1 = grid[end_r + 1][1]
                            if (
                                next_c0 is not None
                                and next_c0.colspan == 1
                                and not next_c0.text.strip()
                                and next_c1 is not None
                                and next_c1.text.strip()
                            ):
                                end_r += 1
                            else:
                                break
                    span_len = end_r - r + 1
                    if span_len >= 2:
                        groups.append((r, span_len))
                        blank_followers += span_len - 1
                    r = end_r + 1
                else:
                    r += 1
            body_count = nrows - header_rows
            if len(groups) >= 2 or (len(groups) >= 1 and blank_followers * 2 >= body_count):
                has_merges = True
                for start_r, span_len in groups:
                    orig = grid[start_r][0]
                    if orig is None:
                        continue
                    grid[start_r][0] = TableCellSpan(
                        text=orig.text,
                        rowspan=span_len,
                        colspan=orig.colspan,
                        is_header=orig.is_header,
                    )
                    for dr in range(1, span_len):
                        grid[start_r + dr][0] = None

    return grid, has_merges


def _escape_html_preserving_scripts(text: str) -> str:
    """Escape HTML special chars while preserving intentional <sup>...</sup> and <sub>...</sub> tags."""
    if not text:
        return ""
    tokens: List[Tuple[str, str]] = []

    def _stash(m: re.Match) -> str:
        idx = len(tokens)
        tag = m.group(1).lower()
        inner = _html_mod.escape(m.group(2), quote=False)
        tokens.append((f"\x00SCRIPT{idx}\x00", f"<{tag}>{inner}</{tag}>"))
        return tokens[-1][0]

    stashed = re.sub(r"<(sup|sub)>([^<]*)</\1>", _stash, text, flags=re.I)
    escaped = _html_mod.escape(stashed, quote=False)
    for placeholder, rendered in tokens:
        escaped = escaped.replace(placeholder, rendered)
    return escaped


def render_span_grid_to_html(span_grid: Sequence[Sequence[Optional[TableCellSpan]]]) -> str:
    """Render a 2D TableCellSpan grid into semantic HTML <table> preserving rowspan/colspan."""
    if not span_grid:
        return ""
    header_row_count = min(
        len(span_grid),
        max((cell.rowspan for cell in span_grid[0] if cell is not None), default=1),
    )
    lines = ["<table>", "<thead>"]
    for r_idx, row in enumerate(span_grid):
        if r_idx == header_row_count:
            lines.append("</thead>")
            lines.append("<tbody>")
        tag = "th" if r_idx < header_row_count else "td"
        cell_parts: List[str] = []
        for cell in row:
            if cell is None:
                continue
            attrs: List[str] = []
            if cell.rowspan > 1:
                attrs.append(f'rowspan="{cell.rowspan}"')
            if cell.colspan > 1:
                attrs.append(f'colspan="{cell.colspan}"')
            attr_str = (" " + " ".join(attrs)) if attrs else ""
            cell_parts.append(f"<{tag}{attr_str}>{_escape_html_preserving_scripts(cell.text)}</{tag}>")
        lines.append("<tr>" + "".join(cell_parts) + "</tr>")
    if len(span_grid) <= header_row_count:
        lines.append("</thead>")
    else:
        lines.append("</tbody>")
    lines.append("</table>")
    return "\n".join(lines)


def _split_gfm_pipe_row(line: str) -> Optional[List[str]]:
    s = line.strip()
    if not s.startswith("|"):
        return None
    parts = re.split(r"(?<!\\)\|", s)
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1] == "":
        parts = parts[:-1]
    if not parts:
        return None
    return [p.strip() for p in parts]


def _parse_gfm_pipe_table(md_text: str) -> Optional[Tuple[List[str], List[str], List[List[str]]]]:
    lines = [ln.strip() for ln in (md_text or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    headers = _split_gfm_pipe_row(lines[0])
    sep = _split_gfm_pipe_row(lines[1])
    if not headers or not sep or len(headers) != len(sep):
        return None
    if not all(_GFM_SEP_CELL_RE.match(c.replace(" ", "")) for c in sep):
        return None
    body_rows: List[List[str]] = []
    for ln in lines[2:]:
        row = _split_gfm_pipe_row(ln)
        if row is None:
            return None
        if len(row) < len(headers):
            row = row + [""] * (len(headers) - len(row))
        elif len(row) > len(headers):
            row = row[:len(headers)]
        body_rows.append(row)
    return headers, sep, body_rows


def _gfm_table_to_html(md_text: str) -> Optional[str]:
    """Convert a GFM pipe table into semantic HTML <table> for mixed HTML/GFM merging."""
    parsed = _parse_gfm_pipe_table(md_text)
    if parsed is None:
        return None
    headers, _, body_rows = parsed
    lines = [
        "<table>",
        "<thead>",
        "<tr>"
        + "".join(
            f"<th>{_escape_html_preserving_scripts(h.replace(r'\|', '|'))}</th>"
            for h in headers
        )
        + "</tr>",
        "</thead>",
    ]
    if body_rows:
        lines.append("<tbody>")
        for row in body_rows:
            lines.append(
                "<tr>"
                + "".join(
                    f"<td>{_escape_html_preserving_scripts(c.replace(r'\|', '|'))}</td>"
                    for c in row
                )
                + "</tr>"
            )
        lines.append("</tbody>")
    lines.append("</table>")
    return "\n".join(lines)


def _html_tr_logical_sigs(tr_list: Sequence[str]) -> List[Tuple[str, ...]]:
    """Expand a sequence of HTML <tr> elements into normalized logical-grid cell text tuples."""
    cell_re = re.compile(r"<(th|td)\b([^>]*)>(.*?)</\1>", flags=re.I | re.S)
    active: dict[int, Tuple[int, int]] = {}
    sigs: List[Tuple[str, ...]] = []
    for tr_html in tr_list:
        row_vals: List[str] = []
        col = 0
        next_active: dict[int, Tuple[int, int]] = {}
        for m in cell_re.finditer(tr_html):
            while col in active:
                rem, w = active[col]
                row_vals.extend([""] * w)
                if rem > 1:
                    next_active[col] = (rem - 1, w)
                col += w
            attrs = m.group(2) or ""
            rm = re.search(r'rowspan\s*=\s*["\']?(\d+)', attrs, flags=re.I)
            cm = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs, flags=re.I)
            rspan = max(1, int(rm.group(1))) if rm else 1
            cspan = max(1, int(cm.group(1))) if cm else 1
            plain = re.sub(r"</?[a-zA-Z][^>]*>", "", m.group(3) or "")
            norm = re.sub(r"\s+", "", _html_mod.unescape(plain))
            row_vals.append(norm)
            if cspan > 1:
                row_vals.extend([""] * (cspan - 1))
            if rspan > 1:
                next_active[col] = (rspan - 1, cspan)
            col += cspan
        while col in active:
            rem, w = active[col]
            row_vals.extend([""] * w)
            if rem > 1:
                next_active[col] = (rem - 1, w)
            col += w
        active = next_active
        sigs.append(tuple(row_vals))
    return sigs


def _parse_html_table_parts(html_text: str) -> Optional[Tuple[int, List[str], List[str], int]]:
    """Parse an HTML <table> into (col_count, header_cell_texts, all_tr_html_strings, thead_row_count)."""
    stripped = (html_text or "").strip()
    if not stripped.lower().startswith("<table"):
        return None
    tr_matches = re.findall(r"<tr\b[^>]*>.*?</tr>", stripped, flags=re.I | re.S)
    if not tr_matches:
        return None

    def _row_col_count(tr_html: str) -> int:
        total = 0
        for m in re.finditer(r"<(?:th|td)\b([^>]*)>", tr_html, flags=re.I):
            cm = re.search(r'colspan\s*=\s*["\']?(\d+)', m.group(1), flags=re.I)
            total += int(cm.group(1)) if cm else 1
        return total

    def _row_plain_cells(tr_html: str) -> List[str]:
        cells: List[str] = []
        for m in re.finditer(r"<(?:th|td)\b[^>]*>(.*?)</(?:th|td)>", tr_html, flags=re.I | re.S):
            plain = re.sub(r"</?[a-zA-Z][^>]*>", "", m.group(1))
            cells.append(re.sub(r"\s+", "", _html_mod.unescape(plain)))
        return cells

    ncols = _row_col_count(tr_matches[0])
    if ncols <= 0:
        return None
    thead_m = re.search(r"<thead\b[^>]*>(.*?)</thead>", stripped, flags=re.I | re.S)
    if thead_m:
        thead_cnt = max(1, len(re.findall(r"<tr\b[^>]*>.*?</tr>", thead_m.group(1), flags=re.I | re.S)))
    else:
        max_rspan = 1
        for m in re.finditer(r"<(?:th|td)\b([^>]*)>", tr_matches[0], flags=re.I):
            rm = re.search(r'rowspan\s*=\s*["\']?(\d+)', m.group(1), flags=re.I)
            if rm:
                max_rspan = max(max_rspan, int(rm.group(1)))
        thead_cnt = min(len(tr_matches), max_rspan)
    hdr_cells = _row_plain_cells(tr_matches[0])
    return ncols, hdr_cells, tr_matches, min(thead_cnt, len(tr_matches))


def merge_html_tables_if_compatible(
    prev_html: str,
    curr_html: str,
    has_continuation_marker: bool = False,
) -> Optional[str]:
    """Merge two HTML <table> blocks when column counts match and headers/marker are compatible."""
    p_info = _parse_html_table_parts(prev_html)
    c_info = _parse_html_table_parts(curr_html)
    if p_info is None or c_info is None:
        return None
    p_cols, p_hdr, p_trs, p_thead_cnt = p_info
    c_cols, c_hdr, c_trs, c_thead_cnt = c_info
    if p_cols != c_cols or not p_trs or not c_trs:
        return None

    p_hdr_row0_sig = _html_tr_logical_sigs([p_trs[0]])[0]
    c_hdr_row0_sig = _html_tr_logical_sigs([c_trs[0]])[0]
    headers_match = bool(
        (any(p_hdr) and p_hdr == c_hdr)
        or (any(p_hdr_row0_sig) and p_hdr_row0_sig == c_hdr_row0_sig)
    )
    curr_placeholder = is_placeholder_header_row(c_hdr)
    if not (has_continuation_marker or headers_match or curr_placeholder):
        return None

    def _row_max_rowspan(tr_html: str) -> int:
        mx = 1
        for m in re.finditer(r"<(?:th|td)\b([^>]*)>", tr_html, flags=re.I):
            rm = re.search(r'rowspan\s*=\s*["\']?(\d+)', m.group(1), flags=re.I)
            if rm:
                mx = max(mx, int(rm.group(1)))
        return mx

    if headers_match:
        # Strip full repeated multi-row header when all header rows match;
        # never slice mid-rowspan or leave orphaned sub-header rows of a matching multi-row thead.
        p_hdr_sigs = _html_tr_logical_sigs(p_trs[:p_thead_cnt])
        c_hdr_sigs = _html_tr_logical_sigs(c_trs[:p_thead_cnt]) if len(c_trs) >= p_thead_cnt else []
        if p_hdr_sigs and p_hdr_sigs == c_hdr_sigs:
            strip_cnt = p_thead_cnt
        elif c_thead_cnt > 1 and c_thead_cnt == p_thead_cnt:
            strip_cnt = c_thead_cnt
        else:
            strip_cnt = max(1, _row_max_rowspan(c_trs[0]))
        append_trs = c_trs[min(strip_cnt, len(c_trs)):]
    elif curr_placeholder:
        strip_cnt = max(1, _row_max_rowspan(c_trs[0]))
        append_trs = c_trs[min(strip_cnt, len(c_trs)):]
    else:
        append_trs = c_trs

    # Deduplicate redundant fragment tables whose non-empty body rows are 100% present in prev_html
    prev_body_trs = p_trs[p_thead_cnt:]
    prev_body_sigs = {sig for sig in _html_tr_logical_sigs(prev_body_trs) if any(sig)}
    cand_sigs = [sig for sig in _html_tr_logical_sigs(append_trs) if any(sig)]
    if cand_sigs and prev_body_sigs and all(sig in prev_body_sigs for sig in cand_sigs):
        append_trs = []

    # Convert <th> to <td> for data-only continuation rows appended into tbody
    normalized_append: List[str] = []
    for tr in append_trs:
        tr_td = re.sub(r"<(/?)th\b", r"<\1td", tr, flags=re.I)
        normalized_append.append(tr_td)

    out_lines = ["<table>", "<thead>"]
    out_lines.extend(p_trs[:p_thead_cnt])
    out_lines.append("</thead>")
    body_out = list(prev_body_trs) + normalized_append
    if body_out:
        out_lines.append("<tbody>")
        out_lines.extend(body_out)
        out_lines.append("</tbody>")
    out_lines.append("</table>")
    return "\n".join(out_lines)


def merge_gfm_tables_if_compatible(
    prev_md: str,
    curr_md: str,
    has_continuation_marker: bool = False,
) -> Optional[str]:
    """
    Merge two Markdown/HTML tables if column counts match AND
    (has_continuation_marker OR header rows match OR continuation uses placeholder headers like '欄1'/'欄2').
    Supports GFM+GFM, HTML+HTML, and mixed HTML+GFM/GFM+HTML pairs.
    Strips duplicate/placeholder header rows automatically and deduplicates redundant fragment tables.
    """
    prev_is_html = (prev_md or "").strip().lower().startswith("<table")
    curr_is_html = (curr_md or "").strip().lower().startswith("<table")
    if prev_is_html or curr_is_html:
        prev_h = prev_md if prev_is_html else _gfm_table_to_html(prev_md)
        curr_h = curr_md if curr_is_html else _gfm_table_to_html(curr_md)
        if prev_h is None or curr_h is None:
            return None
        return merge_html_tables_if_compatible(prev_h, curr_h, has_continuation_marker=has_continuation_marker)

    parsed_prev = _parse_gfm_pipe_table(prev_md)
    parsed_curr = _parse_gfm_pipe_table(curr_md)
    if parsed_prev is None or parsed_curr is None:
        return None

    prev_headers, prev_sep, prev_rows = parsed_prev
    curr_headers, _, curr_rows = parsed_curr
    if len(prev_headers) != len(curr_headers) or not prev_headers:
        return None

    norm_prev = [re.sub(r"\s+", "", h) for h in prev_headers]
    norm_curr = [re.sub(r"\s+", "", h) for h in curr_headers]
    has_nonempty_header = any(norm_prev)
    headers_match = has_nonempty_header and (norm_prev == norm_curr)
    curr_placeholder = is_placeholder_header_row(curr_headers)

    if not (has_continuation_marker or headers_match or curr_placeholder):
        return None

    rows_to_append = curr_rows if (headers_match or curr_placeholder) else [curr_headers] + curr_rows

    # Deduplicate fragment tables whose non-empty data rows are already 100% present in prev_rows
    def _row_sig(row: Sequence[str]) -> Tuple[str, ...]:
        return tuple(re.sub(r"\s+", "", c) for c in row)

    prev_sigs = {_row_sig(r) for r in prev_rows if any(c.strip() for c in r)}
    non_empty_cand = [r for r in rows_to_append if any(c.strip() for c in r)]
    if non_empty_cand and prev_sigs and all(_row_sig(r) in prev_sigs for r in non_empty_cand):
        rows_to_append = []

    md_lines = [
        "| " + " | ".join(prev_headers) + " |",
        "| " + " | ".join(prev_sep) + " |",
    ]
    for row in prev_rows + rows_to_append:
        md_lines.append("| " + " | ".join(row) + " |")
    return "\n".join(md_lines)


def rect_union_intersection_area(
    target_bbox: Sequence[float],
    rects: Sequence[Sequence[float]],
) -> float:
    """Computes the exact area of `target_bbox ∩ (⋃ rects)` using a pure sweep-line."""
    if len(target_bbox) < 4 or not rects:
        return 0.0
    tx0, ty0, tx1, ty1 = float(target_bbox[0]), float(target_bbox[1]), float(target_bbox[2]), float(target_bbox[3])
    if tx1 <= tx0 or ty1 <= ty0:
        return 0.0

    inters: List[Tuple[float, float, float, float]] = []
    for r in rects:
        if len(r) < 4:
            continue
        ix0 = max(tx0, float(r[0]))
        iy0 = max(ty0, float(r[1]))
        ix1 = min(tx1, float(r[2]))
        iy1 = min(ty1, float(r[3]))
        if ix1 > ix0 and iy1 > iy0:
            inters.append((ix0, iy0, ix1, iy1))

    if not inters:
        return 0.0
    if len(inters) == 1:
        r0 = inters[0]
        return (r0[2] - r0[0]) * (r0[3] - r0[1])

    xs = sorted({x for r in inters for x in (r[0], r[2])})
    total_area = 0.0
    for i in range(len(xs) - 1):
        xa, xb = xs[i], xs[i + 1]
        if xb <= xa:
            continue
        y_intervals = sorted((r[1], r[3]) for r in inters if r[0] <= xa and r[2] >= xb)
        if not y_intervals:
            continue
        cur_y0, cur_y1 = y_intervals[0]
        y_len = 0.0
        for ya, yb in y_intervals[1:]:
            if ya <= cur_y1:
                if yb > cur_y1:
                    cur_y1 = yb
            else:
                y_len += cur_y1 - cur_y0
                cur_y0, cur_y1 = ya, yb
        y_len += cur_y1 - cur_y0
        total_area += (xb - xa) * y_len
    return total_area


def is_valid_pymupdf_table(
    cells_matrix: Sequence[Sequence[Any]],
    table_bbox: Sequence[float],
    page_w: float,
    page_h: float = 800.0,
) -> bool:
    """
    Filters out false-positive decorative boxes (e.g., 1x2 or 2x2 chapter opening drop-cap frames
    like [['', ''], ['', '第\\n强']]) returned by PyMuPDF's page.find_tables().
    """
    if not cells_matrix or len(table_bbox) < 4:
        return False

    x0, y0, x1, y1 = float(table_bbox[0]), float(table_bbox[1]), float(table_bbox[2]), float(table_bbox[3])
    width = x1 - x0
    height = y1 - y0
    if width <= 10.0 or height <= 10.0:
        return False

    non_empty_cells = 0
    total_chars = 0
    all_text_parts: List[str] = []
    for row in cells_matrix:
        if not row:
            continue
        for cell in row:
            txt = str(cell or "").strip()
            if txt:
                non_empty_cells += 1
                compact = re.sub(r"\s+", "", txt)
                total_chars += len(compact)
                all_text_parts.append(compact)

    # Decorative drop-cap boxes are narrow (< 28% page width) and contain very few characters (<= 6)
    if width < page_w * 0.28 and total_chars <= 8:
        return False

    # Even wider boxes with only 1 non-empty cell or <= 4 total chars are not real data tables
    if non_empty_cells <= 1 or total_chars <= 4:
        return False

    return True


def _extract_horizontal_segments(page: Any) -> List[Tuple[float, float, float]]:
    """
    Extracts horizontal line segments (y, x0, x1) from page.get_drawings().
    Pure memory operation with zero disk I/O.
    """
    try:
        drawings = page.get_drawings()
    except Exception:
        return []

    raw_segments: List[Tuple[float, float, float]] = []
    for d in drawings:
        for item in d.get("items", []):
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) <= 2.0 and abs(p2.x - p1.x) >= 12.0:
                    y_val = (float(p1.y) + float(p2.y)) * 0.5
                    x_min = min(float(p1.x), float(p2.x))
                    x_max = max(float(p1.x), float(p2.x))
                    raw_segments.append((y_val, x_min, x_max))
            elif kind == "re":
                r = item[1]
                if float(r.height) <= 3.0 and float(r.width) >= 12.0:
                    y_val = (float(r.y0) + float(r.y1)) * 0.5
                    raw_segments.append((y_val, float(r.x0), float(r.x1)))

    return raw_segments


def _extract_vertical_segments(page: Any, page_w: float) -> List[Tuple[float, float, float]]:
    """
    Extracts vertical border segments (x, y0, y1) from page.get_drawings()
    to distinguish vertical-bordered grid tables from borderless three-line tables.
    """
    try:
        drawings = page.get_drawings()
    except Exception:
        return []

    v_segments: List[Tuple[float, float, float]] = []
    for d in drawings:
        stroke_opacity = d.get("stroke_opacity")
        if stroke_opacity is not None and float(stroke_opacity) <= 0.0:
            continue
        stroke_color = d.get("color")
        stroke_width = d.get("width")
        is_visible_stroke = (
            (stroke_color is not None or d.get("type") in ("s", "fs"))
            and (stroke_width is None or float(stroke_width) > 0.0)
            and stroke_color != (1.0, 1.0, 1.0)
        )
        for item in d.get("items", []):
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.x - p2.x) <= 2.0 and abs(p2.y - p1.y) >= 10.0:
                    x_val = (float(p1.x) + float(p2.x)) * 0.5
                    y_min = min(float(p1.y), float(p2.y))
                    y_max = max(float(p1.y), float(p2.y))
                    v_segments.append((x_val, y_min, y_max))
            elif kind == "re":
                r = item[1]
                rw = float(r.width)
                rh = float(r.height)
                if rw <= 3.0 and rh >= 10.0:
                    v_segments.append(((float(r.x0) + float(r.x1)) * 0.5, float(r.y0), float(r.y1)))
                elif is_visible_stroke and rh >= 10.0 and 12.0 <= rw < page_w * 0.92:
                    v_segments.append((float(r.x0), float(r.y0), float(r.y1)))
                    v_segments.append((float(r.x1), float(r.y0), float(r.y1)))

    return v_segments


def _extract_valid_bordered_table_bboxes(
    page: Any,
    page_w: float,
    page_h: float,
) -> List[Tuple[float, float, float, float]]:
    """Returns bboxes of valid bordered tables detected by PyMuPDF page.find_tables()."""
    try:
        tabs = page.find_tables()
    except Exception:
        return []
    if not (tabs and getattr(tabs, "tables", None)):
        return []

    bboxes: List[Tuple[float, float, float, float]] = []
    for t in tabs.tables:
        try:
            cells = t.extract()
        except Exception:
            cells = []
        if is_valid_pymupdf_table(cells, t.bbox, page_w, page_h):
            bboxes.append((float(t.bbox[0]), float(t.bbox[1]), float(t.bbox[2]), float(t.bbox[3])))
    return bboxes


def _has_vertical_borders(
    v_segments: Sequence[Tuple[float, float, float]],
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> bool:
    """Return True if at least 2 vertical border segments overlap the candidate table box."""
    if not v_segments:
        return False
    hits = 0
    for vx, vy0, vy1 in v_segments:
        if x0 - 4.0 <= vx <= x1 + 4.0:
            v_overlap = min(vy1, y1 + 2.0) - max(vy0, y0 - 2.0)
            if v_overlap >= 8.0:
                hits += 1
                if hits >= 2:
                    return True
    return False


def _is_toc_false_positive_region(
    blocks: Sequence[dict],
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> bool:
    """
    Detects Table-of-Contents decorative horizontal-rule bands (e.g., chapter bars
    framing '第一章 ... 1' without vertical dividers) that mimic three-line rule spacing.
    """
    if not blocks:
        return False

    is_toc_page = False
    region_lines: List[Tuple[float, float, str]] = []
    for b in blocks:
        if b.get("type", 0) != 0:
            continue
        bb = b.get("bbox", [0, 0, 0, 0])
        full_txt = "".join(
            s.get("text", "")
            for l in b.get("lines", [])
            for s in l.get("spans", [])
        ).strip()
        if not full_txt:
            continue
        if _TOC_HEADING_RE.match(full_txt):
            is_toc_page = True

        for ln in b.get("lines", []):
            lb = ln.get("bbox", bb)
            l_txt = "".join(s.get("text", "") for s in ln.get("spans", [])).strip()
            if not l_txt:
                continue
            l_cy = (float(lb[1]) + float(lb[3])) * 0.5
            l_x0 = float(lb[0])
            if (y0 - 4.0 <= l_cy <= y1 + 4.0) and (float(lb[2]) >= x0 - 8.0 and l_x0 <= x1 + 8.0):
                region_lines.append((l_cy, l_x0, l_txt))

    if not region_lines:
        return False

    region_lines.sort(key=lambda item: (item[0], item[1]))
    banded_lines: List[List[Tuple[float, float, str]]] = []
    for item in region_lines:
        if not banded_lines or abs(item[0] - banded_lines[-1][0][0]) > 5.5:
            banded_lines.append([item])
        else:
            banded_lines[-1].append(item)

    line_texts: List[str] = []
    for grp in banded_lines:
        grp.sort(key=lambda item: item[1])
        combined = " ".join(part[2] for part in grp).strip()
        if combined:
            line_texts.append(combined)

    if not line_texts:
        return False

    toc_hits = sum(
        1 for ln in line_texts
        if _TOC_DOT_LEADER_RE.search(ln) or _TOC_CHAPTER_PAGE_RE.match(ln)
    )
    if toc_hits >= 2 or (toc_hits >= 1 and toc_hits == len(line_texts)):
        return True

    if is_toc_page:
        page_num_end_hits = sum(1 for ln in line_texts if re.search(r"\s+\d{1,4}\s*$", ln))
        if page_num_end_hits >= 2 and page_num_end_hits >= len(line_texts) * 0.5:
            return True

    return False


def detect_three_line_table_regions(
    page: Any,
    blocks: Optional[Sequence[dict]] = None,
) -> List[TableRegion]:
    """
    Detects academic three-line tables (三線表) on a fitz.Page by clustering horizontal rules
    (top rule, header bottom rule, optional sub-header rule, and table bottom rule) and extracting
    segmented X column boundaries directly from the vector line segments.
    Excludes full-grid vertical-bordered tables, PyMuPDF bordered tables, and TOC decorative rule bands.
    """
    raw_segments = _extract_horizontal_segments(page)
    if not raw_segments:
        return []

    page_w = float(page.rect.width) if hasattr(page, "rect") else 530.0
    page_h = float(page.rect.height) if hasattr(page, "rect") else 800.0
    min_rule_width = page_w * 0.35

    bordered_bboxes = _extract_valid_bordered_table_bboxes(page, page_w, page_h)
    v_segments = _extract_vertical_segments(page, page_w)

    if bordered_bboxes:
        filtered_segments: List[Tuple[float, float, float]] = []
        for sy, sx0, sx1 in raw_segments:
            sx_mid = (sx0 + sx1) * 0.5
            inside_bordered = any(
                (bx0 - 2.0 <= sx_mid <= bx1 + 2.0) and (by0 - 2.0 <= sy <= by1 + 2.0)
                for bx0, by0, bx1, by1 in bordered_bboxes
            )
            if not inside_bordered:
                filtered_segments.append((sy, sx0, sx1))
        raw_segments = filtered_segments
        if not raw_segments:
            return []

    resolved_blocks: Sequence[dict]
    if blocks is not None:
        resolved_blocks = blocks
    else:
        try:
            resolved_blocks = page.get_text("dict").get("blocks", [])
        except Exception:
            resolved_blocks = []

    # Group segments by Y coordinate (within 2.0pt tolerance)
    raw_segments.sort(key=lambda s: (s[0], s[1]))
    y_groups: List[List[Tuple[float, float, float]]] = []
    for seg in raw_segments:
        if not y_groups or abs(seg[0] - y_groups[-1][0][0]) > 2.0:
            y_groups.append([seg])
        else:
            y_groups[-1].append(seg)

    # Build consolidated horizontal rules: (y_mean, x_min, x_max, span_coverage, boundary_x_points)
    rules: List[Tuple[float, float, float, float, Tuple[float, ...]]] = []
    for grp in y_groups:
        y_mean = sum(s[0] for s in grp) / len(grp)
        x_min = min(s[1] for s in grp)
        x_max = max(s[2] for s in grp)
        total_span = x_max - x_min
        if total_span < min_rule_width * 0.5:
            continue

        # Collect distinct X segment endpoints
        x_pts: List[float] = []
        for _, sx0, sx1 in sorted(grp, key=lambda x: x[1]):
            for pt in (sx0, sx1):
                if not x_pts or abs(pt - x_pts[-1]) > 3.0:
                    x_pts.append(round(pt, 2))
        rules.append((y_mean, x_min, x_max, total_span, tuple(x_pts)))

    # Identify full-width rules (top, mid, bot) vs partial sub-header rules
    regions: List[TableRegion] = []
    used_indices: set[int] = set()

    for i, r_top in enumerate(rules):
        if i in used_indices or r_top[3] < min_rule_width:
            continue

        matching_full: List[Tuple[int, Tuple[float, float, float, float, Tuple[float, ...]]]] = [(i, r_top)]
        sub_rules: List[Tuple[int, Tuple[float, float, float, float, Tuple[float, ...]]]] = []

        for j in range(i + 1, len(rules)):
            if j in used_indices:
                continue
            cand = rules[j]
            if cand[0] - matching_full[-1][1][0] > 320.0:
                break
            same_left = abs(cand[1] - r_top[1]) <= 12.0
            same_right = abs(cand[2] - r_top[2]) <= 12.0
            if same_left and same_right:
                matching_full.append((j, cand))
                if len(matching_full) == 3:
                    break
            elif (
                len(matching_full) == 1
                and cand[1] >= r_top[1] + 15.0
                and abs(cand[2] - r_top[2]) <= 15.0
                and (cand[0] - r_top[0]) <= 45.0
            ):
                sub_rules.append((j, cand))

        if len(matching_full) < 3:
            continue

        idx_top, rule_top = matching_full[0]
        idx_mid, rule_mid = matching_full[1]
        idx_bot, rule_bot = matching_full[2]

        if not (10.0 <= (rule_mid[0] - rule_top[0]) <= 85.0 and (rule_bot[0] - rule_mid[0]) >= 18.0):
            continue

        x0 = min(rule_top[1], rule_mid[1], rule_bot[1])
        x1 = max(rule_top[2], rule_mid[2], rule_bot[2])
        y0 = rule_top[0]
        y1 = rule_bot[0]
        cand_bbox = (round(x0 - 4.0, 2), round(y0 - 3.0, 2), round(x1 + 4.0, 2), round(y1 + 3.0, 2))

        if _has_vertical_borders(v_segments, x0, y0, x1, y1):
            continue

        if bordered_bboxes:
            cand_area = max((cand_bbox[2] - cand_bbox[0]) * (cand_bbox[3] - cand_bbox[1]), 1.0)
            union_ov = rect_union_intersection_area(cand_bbox, bordered_bboxes)
            if union_ov / cand_area > 0.30:
                continue
            if any(
                rect_union_intersection_area(bb, [cand_bbox]) / max((bb[2] - bb[0]) * (bb[3] - bb[1]), 1.0) > 0.30
                for bb in bordered_bboxes
            ):
                continue

        caption_txt = ""
        if resolved_blocks:
            for b in resolved_blocks:
                if b.get("type", 0) != 0:
                    continue
                bb = b.get("bbox", [0, 0, 0, 0])
                if y0 - 42.0 <= bb[1] <= y0 + 2.0:
                    txt = "".join(
                        s.get("text", "")
                        for l in b.get("lines", [])
                        for s in l.get("spans", [])
                    ).strip()
                    if _TABLE_CAPTION_RE.match(txt):
                        caption_txt = txt
                        break

        if not caption_txt and _is_toc_false_positive_region(resolved_blocks, x0, y0, x1, y1):
            continue

        used_indices.update({idx_top, idx_mid, idx_bot})
        sub_y: Optional[float] = None
        for idx_s, s_rule in sub_rules:
            if rule_top[0] + 4.0 < s_rule[0] < rule_mid[0] - 4.0:
                sub_y = s_rule[0]
                used_indices.add(idx_s)
                break

        best_hints = max((rule_top[4], rule_mid[4], rule_bot[4]), key=len)

        regions.append(
            TableRegion(
                bbox=cand_bbox,
                top_rule_y=round(y0, 2),
                mid_rule_y=round(rule_mid[0], 2),
                bot_rule_y=round(y1, 2),
                col_x_hints=best_hints,
                sub_header_rule_y=round(sub_y, 2) if sub_y is not None else None,
                caption_text=caption_txt,
            )
        )

    return regions


def extract_char_spans_from_page(page: Any, clip_bbox: Sequence[float]) -> List[TextSpan2D]:
    """
    Extracts character-level TextSpan2D objects within clip_bbox using page.get_text("rawdict").
    Using character-level boxes guarantees that adjacent columns merged into a single PDF span
    (e.g. '组别例数' or '治疗前13.47±3.04 6.63±1.11') split cleanly along col_x_hints!
    """
    import fitz

    rect = fitz.Rect(clip_bbox[0], clip_bbox[1], clip_bbox[2], clip_bbox[3])
    try:
        raw = page.get_text("rawdict", clip=rect)
    except Exception:
        raw = page.get_text("dict", clip=rect)

    char_spans: List[TextSpan2D] = []
    for b in raw.get("blocks", []):
        if b.get("type", 0) != 0:
            continue
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                f_name = s.get("font", "")
                f_size = float(s.get("size", 0.0))
                chars = s.get("chars")
                if chars:
                    for c in chars:
                        ch = c.get("c", "")
                        if not ch:
                            continue
                        cb = c.get("bbox", s.get("bbox", [0, 0, 0, 0]))
                        char_spans.append(
                            TextSpan2D(
                                text=ch,
                                x0=float(cb[0]),
                                y0=float(cb[1]),
                                x1=float(cb[2]),
                                y1=float(cb[3]),
                                font_name=f_name,
                                font_size=f_size,
                            )
                        )
                else:
                    txt = s.get("text", "")
                    if not txt.strip():
                        continue
                    sb = s.get("bbox", [0, 0, 0, 0])
                    # Interpolate per-character X boxes if rawdict chars are unavailable
                    n = len(txt)
                    w_step = (float(sb[2]) - float(sb[0])) / max(n, 1)
                    for i, ch in enumerate(txt):
                        char_spans.append(
                            TextSpan2D(
                                text=ch,
                                x0=float(sb[0]) + i * w_step,
                                y0=float(sb[1]),
                                x1=float(sb[0]) + (i + 1) * w_step,
                                y1=float(sb[3]),
                                font_name=f_name,
                                font_size=f_size,
                            )
                        )
    return char_spans


def _derive_column_boundaries(
    spans: Sequence[TextSpan2D],
    region: TableRegion,
) -> List[Tuple[float, float]]:
    """
    Returns a list of (col_x0, col_x1) intervals defining the table columns.
    Prefers vector segment boundaries (region.col_x_hints) when >= 3 boundaries exist;
    otherwise clusters X projections of header spans.
    """
    hints = list(region.col_x_hints)
    if len(hints) >= 3:
        return [(hints[i], hints[i + 1]) for i in range(len(hints) - 1)]

    # Fallback: cluster header spans along X axis
    header_spans = [
        s for s in spans
        if region.top_rule_y - 2.0 <= s.cy <= region.mid_rule_y + 2.0 and s.text.strip()
    ]
    if not header_spans:
        header_spans = [s for s in spans if s.text.strip()]
    if not header_spans:
        return [(region.bbox[0], region.bbox[2])]

    sorted_s = sorted(header_spans, key=lambda s: s.x0)
    clusters: List[List[TextSpan2D]] = [[sorted_s[0]]]
    for s in sorted_s[1:]:
        prev_x1 = max(x.x1 for x in clusters[-1])
        if s.x0 - prev_x1 > 12.0:
            clusters.append([s])
        else:
            clusters[-1].append(s)

    bounds: List[Tuple[float, float]] = []
    table_x0, _, table_x1, _ = region.bbox
    centers = [
        (min(x.x0 for x in c), max(x.x1 for x in c))
        for c in clusters
    ]
    for i, (cx0, cx1) in enumerate(centers):
        left = table_x0 if i == 0 else (centers[i - 1][1] + cx0) * 0.5
        right = table_x1 if i == len(centers) - 1 else (cx1 + centers[i + 1][0]) * 0.5
        bounds.append((left, right))
    return bounds


def _find_col_index(cx: float, col_bounds: Sequence[Tuple[float, float]]) -> int:
    """Maps a horizontal center coordinate cx to its column index."""
    for idx, (x0, x1) in enumerate(col_bounds):
        if x0 <= cx <= x1:
            return idx
    # Closest column fallback
    best_idx = 0
    best_dist = float("inf")
    for idx, (x0, x1) in enumerate(col_bounds):
        mid = (x0 + x1) * 0.5
        d = abs(cx - mid)
        if d < best_dist:
            best_dist = d
            best_idx = idx
    return best_idx


def _join_cell_chars(chars: Sequence[TextSpan2D]) -> str:
    """
    Sorts characters within a cell by (line_band, x0) and joins them cleanly,
    removing redundant internal newlines while preserving single spaces around units/symbols.
    """
    if not chars:
        return ""
    sorted_by_y = sorted(chars, key=lambda c: (c.y0, c.x0))
    lines: List[List[TextSpan2D]] = [[sorted_by_y[0]]]
    for c in sorted_by_y[1:]:
        prev_cy = sum(x.cy for x in lines[-1]) / len(lines[-1])
        if abs(c.cy - prev_cy) <= 5.5:
            lines[-1].append(c)
        else:
            lines.append([c])

    line_strs: List[str] = []
    for ln in lines:
        ln_sorted = sorted(ln, key=lambda c: c.x0)
        s = "".join(c.text for c in ln_sorted).strip()
        if s:
            line_strs.append(s)

    joined = "".join(line_strs)
    # Clean multiple spaces
    joined = re.sub(r"\s{2,}", " ", joined).strip()
    return joined


def reconstruct_table_from_2d_spans(
    spans: Sequence[TextSpan2D],
    region: TableRegion,
) -> Optional[ReconstructedTable]:
    """
    Reconstructs a structured table (headers + rows + GFM Markdown) from 2D character/text spans
    inside a TableRegion.
    Handles:
    1. Multi-line / hierarchical headers (e.g., '性别（例） -> 男 | 女' or wrapped units '晨僵时间（min）').
    2. Vertically centered row-span cells in group columns (e.g., '刺络埋线组 | 43' centered across 4 rows).
    """
    in_region = [
        s for s in spans
        if region.top_rule_y - 3.0 <= s.cy <= region.bot_rule_y + 3.0
        and region.bbox[0] - 5.0 <= s.cx <= region.bbox[2] + 5.0
        and s.text.strip()
    ]
    if not in_region:
        return None

    col_bounds = _derive_column_boundaries(in_region, region)
    num_cols = len(col_bounds)
    if num_cols < 2:
        return None

    # 1. Reconstruct Header Row (top_rule_y <= cy <= mid_rule_y)
    header_chars = [s for s in in_region if s.cy <= region.mid_rule_y + 1.5]
    headers: List[str] = []
    if region.sub_header_rule_y is not None:
        # Hierarchical two-tier header (like Page 156 Table 1)
        # Spans purely above sub_header_rule_y are parent group headers (e.g., 性别（例）, 年龄（岁）, 病程)
        top_tier_chars = sorted(
            [s for s in header_chars if s.y1 <= region.sub_header_rule_y + 1.5],
            key=lambda s: s.x0,
        )
        parent_groups: List[List[TextSpan2D]] = []
        for ch in top_tier_chars:
            if not parent_groups or ch.x0 - max(x.x1 for x in parent_groups[-1]) > 14.0:
                parent_groups.append([ch])
            else:
                parent_groups[-1].append(ch)
        parent_labels = [
            ((min(x.x0 for x in grp) + max(x.x1 for x in grp)) * 0.5, _join_cell_chars(grp))
            for grp in parent_groups
        ]

        for c_idx, (cx0, cx1) in enumerate(col_bounds):
            col_all = [s for s in header_chars if _find_col_index(s.cx, col_bounds) == c_idx]
            col_bot = [s for s in col_all if s.y0 >= region.sub_header_rule_y - 1.5]
            if not col_bot:
                # Vertically centered full-height header cell (e.g. 组别, 例数)
                headers.append(_join_cell_chars(col_all) or f"欄{c_idx + 1}")
            else:
                bot_txt = _join_cell_chars(col_bot)
                col_mid_x = (cx0 + cx1) * 0.5
                if parent_labels:
                    _, p_txt = min(parent_labels, key=lambda p: abs(p[0] - col_mid_x))
                    headers.append(f"{p_txt}-{bot_txt}" if p_txt and p_txt != bot_txt else bot_txt)
                else:
                    headers.append(bot_txt or f"欄{c_idx + 1}")
    else:
        for c_idx in range(num_cols):
            col_h = [s for s in header_chars if _find_col_index(s.cx, col_bounds) == c_idx]
            headers.append(_join_cell_chars(col_h) or f"欄{c_idx + 1}")

    # 2. Reconstruct Body Rows (mid_rule_y < cy <= bot_rule_y)
    body_chars = [s for s in in_region if s.cy > region.mid_rule_y + 1.5]
    if not body_chars:
        return None

    # Group body chars by column first, then cluster each column's Y-lines
    col_y_clusters: List[List[Tuple[float, List[TextSpan2D]]]] = []
    for c_idx in range(num_cols):
        c_chars = sorted(
            [s for s in body_chars if _find_col_index(s.cx, col_bounds) == c_idx],
            key=lambda s: s.cy,
        )
        clusters: List[List[TextSpan2D]] = []
        for ch in c_chars:
            if not clusters or abs(ch.cy - (sum(x.cy for x in clusters[-1]) / len(clusters[-1]))) > 6.5:
                clusters.append([ch])
            else:
                clusters[-1].append(ch)
        col_y_clusters.append([
            (sum(x.cy for x in cl) / len(cl), cl)
            for cl in clusters
        ])

    # Determine primary row Y-grid from the rightmost data columns (which never use vertical row-spanning)
    right_cols_clusters = col_y_clusters[min(2, num_cols - 1):]
    anchor_clusters = max(right_cols_clusters, key=len) if right_cols_clusters else max(col_y_clusters, key=len)
    if not anchor_clusters:
        return None

    row_y_centers = [cy for cy, _ in anchor_clusters]
    num_rows = len(row_y_centers)
    if num_rows == 0:
        return None

    # Initialize 2D grid: num_rows x num_cols
    grid: List[List[str]] = [["" for _ in range(num_cols)] for _ in range(num_rows)]

    # Populate each column into the primary row grid
    for c_idx in range(num_cols):
        c_clusters = col_y_clusters[c_idx]
        if not c_clusters:
            continue

        # Case A: Column has the exact same number of row clusters as num_rows -> direct 1-to-1 mapping
        if len(c_clusters) == num_rows:
            for r_idx, (_, cl_chars) in enumerate(c_clusters):
                grid[r_idx][c_idx] = _join_cell_chars(cl_chars)
            continue

        # Case B: Left-side group column (c_idx <= 1) with vertically centered or wrapped group labels
        # Example 1: Table 4 has num_rows=8 (2 groups of 4 rows) and c_clusters has 2 items ('刺络埋线组', '药物组')
        # Example 2: Table 3 has num_rows=8 (2 groups of 4 rows) and c_idx=0 has 5 wrapped lines (3 in group 1, 2 in group 2)
        if c_idx <= 1 and num_rows >= 2:
            # Determine how many logical groups exist by checking c_idx=1 (usually '例数' which is 1 line per group)
            ref_group_clusters = col_y_clusters[1] if (num_cols > 1 and 0 < len(col_y_clusters[1]) < num_rows) else c_clusters
            num_groups = len(ref_group_clusters)
            if 1 <= num_groups < num_rows and num_rows % num_groups == 0:
                rows_per_group = num_rows // num_groups
                for g_idx in range(num_groups):
                    r_start = g_idx * rows_per_group
                    r_end = (g_idx + 1) * rows_per_group - 1
                    y_min_bound = (
                        region.mid_rule_y
                        if g_idx == 0
                        else (row_y_centers[r_start - 1] + row_y_centers[r_start]) * 0.5
                    )
                    y_max_bound = (
                        region.bot_rule_y
                        if g_idx == num_groups - 1
                        else (row_y_centers[r_end] + row_y_centers[r_end + 1]) * 0.5
                    )
                    grp_chars = [
                        ch
                        for cy, cl in c_clusters
                        if y_min_bound <= cy <= y_max_bound
                        for ch in cl
                    ]
                    if grp_chars:
                        # Snap vertically centered group cell to the first row (r_start) of the group!
                        grid[r_start][c_idx] = _join_cell_chars(grp_chars)
                continue

        # Case C: Wrapped multi-line cell within a 2-row table (e.g. Table 1 '埋线刺' + '络组' around row 0)
        row_buckets: List[List[TextSpan2D]] = [[] for _ in range(num_rows)]
        for cy, cl_chars in c_clusters:
            best_r = min(range(num_rows), key=lambda r: abs(cy - row_y_centers[r]))
            row_buckets[best_r].extend(cl_chars)
        for r_idx in range(num_rows):
            if row_buckets[r_idx]:
                grid[r_idx][c_idx] = _join_cell_chars(row_buckets[r_idx])

    # Format as GFM Pipe Table
    def _esc(val: str) -> str:
        return val.replace("|", "&#124;").replace("\n", " ").strip()

    clean_headers = tuple(_esc(h) for h in headers)
    clean_rows = tuple(tuple(_esc(cell) for cell in row) for row in grid if any(cell.strip() for cell in row))
    if not clean_rows:
        return None

    md_lines = [
        "| " + " | ".join(clean_headers) + " |",
        "| " + " | ".join(["---"] * num_cols) + " |",
    ]
    for r in clean_rows:
        md_lines.append("| " + " | ".join(r) + " |")

    return ReconstructedTable(
        bbox=region.bbox,
        headers=clean_headers,
        rows=clean_rows,
        markdown="\n".join(md_lines),
        caption_text=region.caption_text,
    )


def extract_reconstructed_tables_from_page(
    page: Any,
    blocks: Optional[Sequence[dict]] = None,
) -> List[ReconstructedTable]:
    """
    High-level pure operator that detects all three-line tables on a fitz.Page
    and reconstructs each into a ReconstructedTable.
    """
    regions = detect_three_line_table_regions(page, blocks=blocks)
    results: List[ReconstructedTable] = []
    for reg in regions:
        spans = extract_char_spans_from_page(page, reg.bbox)
        tbl = reconstruct_table_from_2d_spans(spans, reg)
        if tbl is not None:
            results.append(tbl)
    return results
