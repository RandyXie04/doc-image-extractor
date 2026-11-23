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


_TABLE_CAPTION_RE = re.compile(r"^\s*表\s*\d+")
_CJK_SPURIOUS_SPACE_RE = re.compile(
    r"(?<=[\u4e00-\u9fff\u3400-\u4dbf\u3001-\u303f\uff01-\uffef\u2018-\u201f\u2014\u2026\u00b7])[ \t]+(?=[\u4e00-\u9fff\u3400-\u4dbf\u3001-\u303f\uff01-\uffef\u2018-\u201f\u2014\u2026\u00b7])"
)
_CJK_EDGE_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3001-\u303f\uff01-\uffef\u2018-\u201f\u2014\u2026\u00b7]")
_XU_BIAO_RE = re.compile(r"^[（(]?\s*(?:续\s*表|續\s*表)\s*[）)]?[：:.]?\s*$")
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


def clean_table_cell_text(cell: Optional[str]) -> str:
    """
    Normalizes PDF table cell text by stripping spurious justification spaces between
    CJK characters/punctuation and joining wrapped CJK lines without inserting extra spaces,
    while preserving ASCII word/list spacing (e.g. '1. 八珍粥 2. 桂圆红枣粥').
    """
    if not cell:
        return ""
    cleaned_lines: List[str] = []
    for raw_line in str(cell).splitlines():
        s = _CJK_SPURIOUS_SPACE_RE.sub("", raw_line.strip())
        if s:
            cleaned_lines.append(s)
    if not cleaned_lines:
        return ""
    joined = cleaned_lines[0]
    for nxt in cleaned_lines[1:]:
        if _CJK_EDGE_CHAR_RE.match(joined[-1]) and _CJK_EDGE_CHAR_RE.match(nxt[0]):
            joined += nxt
        else:
            joined += " " + nxt
    return re.sub(r"\s{2,}", " ", joined).strip()


def normalize_pymupdf_table_rows(
    rows: Sequence[Sequence[Any]],
    table_obj: Any = None,
) -> List[List[str]]:
    """
    Cleans cell text via clean_table_cell_text() and collapses phantom narrow sliver columns
    (e.g., <12pt inset border artifacts where one column has an empty header and cells across
    every row are mutually exclusive with the adjacent column).
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
    """Return True when text represents a standalone continuation-table marker ('续表' / '續表')."""
    if not text:
        return False
    stripped = text.strip().lstrip("#").strip()
    return bool(_XU_BIAO_RE.match(stripped))


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


def merge_gfm_tables_if_compatible(
    prev_md: str,
    curr_md: str,
    has_continuation_marker: bool = False,
) -> Optional[str]:
    """
    Merge two GFM pipe tables if column counts match AND (has_continuation_marker OR header rows match).
    Strips duplicate header rows automatically when headers match; preserves data-only continuations
    when has_continuation_marker is True and the continuation starts with a data row.
    """
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

    if not (has_continuation_marker or headers_match):
        return None

    rows_to_append = curr_rows if headers_match else [curr_headers] + curr_rows
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
