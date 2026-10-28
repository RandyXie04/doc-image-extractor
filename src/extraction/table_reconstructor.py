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


def detect_three_line_table_regions(
    page: Any,
    blocks: Optional[Sequence[dict]] = None,
) -> List[TableRegion]:
    """
    Detects academic three-line tables (三線表) on a fitz.Page by clustering horizontal rules
    (top rule, header bottom rule, optional sub-header rule, and table bottom rule) and extracting
    segmented X column boundaries directly from the vector line segments.
    """
    raw_segments = _extract_horizontal_segments(page)
    if not raw_segments:
        return []

    page_w = float(page.rect.width) if hasattr(page, "rect") else 530.0
    min_rule_width = page_w * 0.35

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

        used_indices.update({idx_top, idx_mid, idx_bot})
        sub_y: Optional[float] = None
        for idx_s, s_rule in sub_rules:
            if rule_top[0] + 4.0 < s_rule[0] < rule_mid[0] - 4.0:
                sub_y = s_rule[0]
                used_indices.add(idx_s)
                break

        best_hints = max((rule_top[4], rule_mid[4], rule_bot[4]), key=len)
        x0 = min(rule_top[1], rule_mid[1], rule_bot[1])
        x1 = max(rule_top[2], rule_mid[2], rule_bot[2])
        y0 = rule_top[0]
        y1 = rule_bot[0]

        caption_txt = ""
        if blocks:
            for b in blocks:
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

        regions.append(
            TableRegion(
                bbox=(round(x0 - 4.0, 2), round(y0 - 3.0, 2), round(x1 + 4.0, 2), round(y1 + 3.0, 2)),
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
