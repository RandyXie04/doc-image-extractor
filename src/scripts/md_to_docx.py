import os
import glob
import html as _html_mod
import re
import sys
import argparse
from typing import List, Optional, Sequence, Tuple
if hasattr(sys.stdout, "reconfigure"):
    getattr(sys.stdout, "reconfigure")(encoding='utf-8')
from pathlib import Path
# pyrefly: ignore [missing-import]
import pypandoc

# Configure pypandoc to use the bundled pandoc.exe if available
try:
    from src.utils.path_helper import get_bundled_pandoc, get_data_dir, get_config_dir, get_template_path, resolve_active_template_path
except ImportError:
    import sys
    from pathlib import Path
    _fallback_root = Path(__file__).parent.parent.parent.resolve()
    if str(_fallback_root) not in sys.path:
        sys.path.insert(0, str(_fallback_root))
    from src.utils.path_helper import get_bundled_pandoc, get_data_dir, get_config_dir, get_template_path, resolve_active_template_path

bundled_pandoc = get_bundled_pandoc()
if bundled_pandoc.exists():
    os.environ.setdefault('PYPANDOC_PANDOC', str(bundled_pandoc))

try:
    pypandoc.get_pandoc_version()
except OSError:
    print("Pandoc not found natively. Attempting to download pandoc (may fail if firewalled)...")
    try:
        pypandoc.download_pandoc()
    except Exception as e:
        print(f"Error downloading pandoc: {e}")

def _classify_intervening_paragraph(p_elem, qn) -> str:
    """
    Classify an element between two adjacent <w:tbl> nodes into:
    - 'empty': empty spacer paragraph without drawings/breaks
    - 'continuation': continuation-table marker ('续表', '表13-1（续）', '续表13-1', etc.)
    - 'page_num': standalone unfiltered page number ('256', '- 12 -', '·283·', '第12页')
    - 'other': real prose, heading, image, or section break (must block merging)
    """
    if p_elem.tag != qn('w:p'):
        return 'other'
    if (
        p_elem.find('.//' + qn('w:drawing')) is not None
        or p_elem.find('.//' + qn('w:pict')) is not None
        or p_elem.find('.//' + qn('w:object')) is not None
        or p_elem.find('.//' + qn('w:sectPr')) is not None
    ):
        return 'other'
    txt = "".join(t.text or "" for t in p_elem.iter(qn('w:t'))).strip()
    if not txt:
        return 'empty'
    try:
        from src.extraction.table_reconstructor import (
            is_continuation_table_marker,
            is_standalone_page_number_text,
        )
        if is_continuation_table_marker(txt):
            return 'continuation'
        if is_standalone_page_number_text(txt):
            return 'page_num'
        return 'other'
    except Exception:
        if re.match(r'^[（(]?\s*(?:续\s*表|續\s*表)\s*[）)]?[：:.]?\s*$', txt):
            return 'continuation'
        if re.match(r'^\s*(?:[-—–·•]\s*)?\d{1,4}(?:\s*[-—–·•])?\s*$', txt):
            return 'page_num'
        return 'other'


def _is_xu_biao_paragraph(p_elem, qn) -> bool:
    return _classify_intervening_paragraph(p_elem, qn) in ('empty', 'continuation')


def _is_placeholder_header_cells(cells: Sequence[str]) -> bool:
    try:
        from src.extraction.table_reconstructor import is_placeholder_header_row
        return is_placeholder_header_row(cells)
    except Exception:
        pat = re.compile(r'^(?:欄|栏|列|col(?:umn)?|field|unnamed)\s*[:：_-]?\s*\d+$', re.I)
        hits = 0
        for c in cells:
            s = str(c or "").strip()
            if not s:
                continue
            if pat.match(s):
                hits += 1
            else:
                return False
        return hits >= 1


def _docx_table_header_row_count(trs, qn) -> int:
    """
    Determine the number of leading header rows in an OOXML <w:tbl>:
    1. Contiguous leading rows starting at row 0 that already carry <w:tblHeader/>.
    2. Vertical-merge continuation rows belonging strictly to <w:vMerge w:val="restart"/>
       cells started in row 0 (tracked per logical column so staggered body vMerges never leak).
    """
    if not trs:
        return 0
    header_cnt = 1

    def _has_tbl_header(tr_el) -> bool:
        trPr = tr_el.find(qn('w:trPr'))
        return trPr is not None and trPr.find(qn('w:tblHeader')) is not None

    if _has_tbl_header(trs[0]):
        idx = 1
        while idx < len(trs) and _has_tbl_header(trs[idx]):
            idx += 1
        header_cnt = max(header_cnt, idx)

    def _tc_grid_span(tc_el) -> int:
        tcPr = tc_el.find(qn('w:tcPr'))
        gs = tcPr.find(qn('w:gridSpan')) if tcPr is not None else None
        if gs is not None:
            raw_val = gs.get(qn('w:val'))
            if raw_val is not None:
                try:
                    return max(1, int(raw_val))
                except ValueError:
                    return 1
        return 1

    active_row0_vcols: set[int] = set()
    col = 0
    for tc in trs[0].findall(qn('w:tc')):
        span = _tc_grid_span(tc)
        tcPr = tc.find(qn('w:tcPr'))
        vm = tcPr.find(qn('w:vMerge')) if tcPr is not None else None
        if vm is not None and vm.get(qn('w:val')) == 'restart':
            active_row0_vcols.add(col)
        col += span

    if active_row0_vcols:
        for probe_idx in range(1, len(trs)):
            still_active: set[int] = set()
            col = 0
            for tc in trs[probe_idx].findall(qn('w:tc')):
                span = _tc_grid_span(tc)
                if col in active_row0_vcols:
                    tcPr = tc.find(qn('w:tcPr'))
                    vm = tcPr.find(qn('w:vMerge')) if tcPr is not None else None
                    if vm is not None and vm.get(qn('w:val')) in (None, 'continue'):
                        still_active.add(col)
                col += span
            if still_active:
                header_cnt = max(header_cnt, probe_idx + 1)
                active_row0_vcols = still_active
            else:
                break

    return min(header_cnt, len(trs))


def _coalesce_adjacent_docx_tables(doc, qn) -> int:
    """
    Coalesce adjacent compatible <w:tbl> elements separated only by empty <w:p>,
    unfiltered standalone page numbers, or at most one continuation marker
    ('续表'/'續表'/'表X-Y（续）'/etc.) when column counts match and
    (continuation marker present OR header rows match OR continuation has placeholder
    headers like '欄1'/'欄2'). Also deduplicates redundant fragment tables whose
    non-empty rows are already 100% present in the preceding main table.
    """
    body = doc.element.body
    children = list(body)
    prev_tbl = None
    between_elems = []
    merged_count = 0

    def _tbl_col_count(tbl_el) -> int:
        tblGrid = tbl_el.find(qn('w:tblGrid'))
        if tblGrid is not None:
            cols = tblGrid.findall(qn('w:gridCol'))
            if cols:
                return len(cols)
        trs = tbl_el.findall(qn('w:tr'))
        return len(trs[0].findall(qn('w:tc'))) if trs else 0

    def _row_cells_norm(tr_el) -> list[str]:
        vals: list[str] = []
        for tc in tr_el.findall(qn('w:tc')):
            txt = re.sub(r'\s+', '', "".join(t.text or "" for t in tc.iter(qn('w:t'))))
            tcPr = tc.find(qn('w:tcPr'))
            gs = tcPr.find(qn('w:gridSpan')) if tcPr is not None else None
            span = 1
            if gs is not None:
                raw_val = gs.get(qn('w:val'))
                if raw_val is not None:
                    try:
                        span = max(1, int(raw_val))
                    except ValueError:
                        span = 1
            vals.append(txt)
            if span > 1:
                vals.extend([""] * (span - 1))
        return vals

    def _row_has_vmerge_continue(tr_el) -> bool:
        for tc in tr_el.findall(qn('w:tc')):
            tcPr = tc.find(qn('w:tcPr'))
            vm = tcPr.find(qn('w:vMerge')) if tcPr is not None else None
            if vm is not None and vm.get(qn('w:val')) in (None, 'continue'):
                return True
        return False

    def _sync_moved_row_widths(prev_tbl_el, curr_tbl_el, moved_trs, cols_cnt: int) -> None:
        # Upgrade uniform equal-width Pandoc grid (e.g. <=72-col tables) if continuation has proportional grid
        prev_grid = prev_tbl_el.find(qn('w:tblGrid'))
        curr_grid = curr_tbl_el.find(qn('w:tblGrid'))
        if prev_grid is not None and curr_grid is not None:
            p_cols = prev_grid.findall(qn('w:gridCol'))
            c_cols = curr_grid.findall(qn('w:gridCol'))
            if len(p_cols) == len(c_cols) == cols_cnt and cols_cnt > 1:
                p_ws = [g.get(qn('w:w')) for g in p_cols]
                c_ws = [g.get(qn('w:w')) for g in c_cols]
                if len(set(p_ws)) == 1 and len(set(c_ws)) > 1:
                    for p_g, c_w in zip(p_cols, c_ws):
                        if c_w is not None:
                            p_g.set(qn('w:w'), c_w)

        prev_trs_now = prev_tbl_el.findall(qn('w:tr'))
        if not prev_trs_now:
            return
        tmpl_tcs = prev_trs_now[0].findall(qn('w:tc'))
        if len(tmpl_tcs) != cols_cnt:
            return
        tmpl_tcws = []
        for tc in tmpl_tcs:
            tcPr = tc.find(qn('w:tcPr'))
            tcW = tcPr.find(qn('w:tcW')) if tcPr is not None else None
            if tcW is not None and not (tcW.get(qn('w:type')) == 'auto' and tcW.get(qn('w:w')) == '0'):
                tmpl_tcws.append((tcW.get(qn('w:w')), tcW.get(qn('w:type'))))
            else:
                tmpl_tcws.append(None)
        if not any(tmpl_tcws):
            return
        for tr in moved_trs:
            tcs = tr.findall(qn('w:tc'))
            if len(tcs) != cols_cnt:
                continue
            for tc, tmpl_w in zip(tcs, tmpl_tcws):
                if tmpl_w is None:
                    continue
                tcPr = tc.find(qn('w:tcPr'))
                if tcPr is None:
                    continue
                tcW = tcPr.find(qn('w:tcW'))
                if tcW is not None:
                    if tmpl_w[0] is not None:
                        tcW.set(qn('w:w'), tmpl_w[0])
                    if tmpl_w[1] is not None:
                        tcW.set(qn('w:type'), tmpl_w[1])

    for el in children:
        if el.tag == qn('w:tbl'):
            if prev_tbl is None:
                prev_tbl = el
                between_elems = []
                continue

            # Validate intervening paragraphs (empty spacers, <=1 continuation marker, <=2 page numbers)
            xu_biao_hits = 0
            page_num_hits = 0
            valid_gap = True
            for b_el in between_elems:
                kind = _classify_intervening_paragraph(b_el, qn)
                if kind == 'empty':
                    continue
                if kind == 'continuation':
                    xu_biao_hits += 1
                    if xu_biao_hits > 1:
                        valid_gap = False
                        break
                elif kind == 'page_num':
                    page_num_hits += 1
                    if page_num_hits > 2:
                        valid_gap = False
                        break
                else:
                    valid_gap = False
                    break

            if not valid_gap:
                prev_tbl = el
                between_elems = []
                continue

            prev_trs = prev_tbl.findall(qn('w:tr'))
            curr_trs = el.findall(qn('w:tr'))
            if not prev_trs or not curr_trs:
                prev_tbl = el
                between_elems = []
                continue

            prev_cols = _tbl_col_count(prev_tbl)
            curr_cols = _tbl_col_count(el)
            if prev_cols == 0 or prev_cols != curr_cols:
                prev_tbl = el
                between_elems = []
                continue

            prev_hdr = _row_cells_norm(prev_trs[0])
            curr_hdr = _row_cells_norm(curr_trs[0])
            headers_match = bool(
                prev_hdr and any(prev_hdr) and len(prev_hdr) == len(curr_hdr) and prev_hdr == curr_hdr
            )
            curr_is_placeholder = _is_placeholder_header_cells(curr_hdr)
            has_xu_biao = xu_biao_hits > 0

            prev_hdr_cnt = _docx_table_header_row_count(prev_trs, qn)
            curr_hdr_cnt = _docx_table_header_row_count(curr_trs, qn)

            # Compute normalized signatures of existing non-empty rows in prev_tbl for fragment deduplication
            prev_row_sigs = {
                tuple(_row_cells_norm(tr))
                for tr in prev_trs
                if any(_row_cells_norm(tr))
            }
            if headers_match:
                if (
                    prev_hdr_cnt > 1
                    and len(curr_trs) >= prev_hdr_cnt
                    and [_row_cells_norm(tr) for tr in prev_trs[:prev_hdr_cnt]]
                    == [_row_cells_norm(tr) for tr in curr_trs[:prev_hdr_cnt]]
                ):
                    strip_cnt = prev_hdr_cnt
                else:
                    strip_cnt = max(1, curr_hdr_cnt)
                candidate_trs = curr_trs[min(strip_cnt, len(curr_trs)):]
            elif curr_is_placeholder:
                candidate_trs = curr_trs[min(max(1, curr_hdr_cnt), len(curr_trs)):]
            else:
                candidate_trs = curr_trs
            non_empty_cand_sigs = [
                tuple(_row_cells_norm(tr))
                for tr in candidate_trs
                if any(_row_cells_norm(tr))
            ]
            is_duplicate_fragment = bool(
                non_empty_cand_sigs
                and prev_row_sigs
                and len(candidate_trs) <= len(prev_trs)
                and all(sig in prev_row_sigs for sig in non_empty_cand_sigs)
            )

            if not (has_xu_biao or headers_match or curr_is_placeholder or is_duplicate_fragment):
                prev_tbl = el
                between_elems = []
                continue

            if is_duplicate_fragment:
                rows_to_move = []
            else:
                rows_to_move = [
                    tr for tr in candidate_trs
                    if any(_row_cells_norm(tr)) or _row_has_vmerge_continue(tr)
                ]

            if rows_to_move:
                _sync_moved_row_widths(prev_tbl, el, rows_to_move, prev_cols)
                for tr in rows_to_move:
                    trPr = tr.find(qn('w:trPr'))
                    if trPr is not None:
                        stale_hdr = trPr.find(qn('w:tblHeader'))
                        if stale_hdr is not None:
                            trPr.remove(stale_hdr)
                    prev_tbl.append(tr)
            for b_el in between_elems:
                body.remove(b_el)
            body.remove(el)
            between_elems = []
            merged_count += 1
        else:
            if prev_tbl is not None:
                between_elems.append(el)

    return merged_count


_HTML_TABLE_BLOCK_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.I | re.S)
_HTML_TABLE_SLOT_PREFIX = "ZZHTMLTABLESLOT"
_HTML_TABLE_SLOT_SUFFIX = "ZZ"
_INLINE_SCRIPT_HTML_RE = re.compile(r"<(sup|sub)>([^<]+)</\1>", re.I)
_INLINE_SCRIPT_TOKEN_RE = re.compile(r"ZZ(SUP|SUB)HEX([0-9A-F]+)ZZ|⟦(SUP|SUB):([^⟧]+)⟧")


def extract_html_tables_for_pandoc(md_content: str) -> Tuple[str, List[str]]:
    """
    Replace raw HTML <table>...</table> blocks with unique non-Markdown slot tokens
    prior to Pandoc conversion (Pandoc's DOCX writer drops raw HTML tables), returning
    (rewritten_md, extracted_html_tables).
    """
    tables: List[str] = []

    def _replace(m: re.Match) -> str:
        idx = len(tables)
        tables.append(m.group(0))
        return f"\n\n{_HTML_TABLE_SLOT_PREFIX}{idx}{_HTML_TABLE_SLOT_SUFFIX}\n\n"

    rewritten = _HTML_TABLE_BLOCK_RE.sub(_replace, md_content)
    return rewritten, tables


def protect_inline_scripts_for_pandoc(md_content: str) -> str:
    """
    Replace inline <sup>...</sup> and <sub>...</sub> tags with pure-alphanumeric
    UTF-8 hex sentinel tokens (ZZSUPHEX...ZZ / ZZSUBHEX...ZZ) before Pandoc runs
    with +raw_html -subscript, preventing Pandoc from stripping tags or parsing
    Markdown syntax characters (*, _, ^, ~, etc.) inside script payloads.
    """
    def _repl(m: re.Match) -> str:
        kind = m.group(1).upper()
        inner_text = _html_mod.unescape(m.group(2))
        inner_hex = inner_text.encode("utf-8").hex().upper()
        return f"ZZ{kind}HEX{inner_hex}ZZ"

    return _INLINE_SCRIPT_HTML_RE.sub(_repl, md_content)


def _append_html_inline_runs(p_el, cell_html: str, OxmlElement, qn, bold: bool = False) -> None:
    """Parse lightweight inline HTML (<sup>, <sub>, <b>/<strong>, <i>/<em>, <br>) into OOXML <w:r> nodes."""
    token_re = re.compile(r"(<(?:/)?(?:sup|sub|b|strong|i|em|br)\b[^>]*>)", re.I)
    parts = token_re.split(cell_html or "")
    sup_depth = 0
    sub_depth = 0
    b_depth = 1 if bold else 0
    i_depth = 0

    for part in parts:
        if not part:
            continue
        low = part.lower()
        if low.startswith("<br"):
            r_el = OxmlElement('w:r')
            r_el.append(OxmlElement('w:br'))
            p_el.append(r_el)
            continue
        if low.startswith("<sup"):
            sup_depth += 1
            continue
        if low.startswith("</sup"):
            sup_depth = max(0, sup_depth - 1)
            continue
        if low.startswith("<sub"):
            sub_depth += 1
            continue
        if low.startswith("</sub"):
            sub_depth = max(0, sub_depth - 1)
            continue
        if low.startswith("<b") or low.startswith("<strong"):
            b_depth += 1
            continue
        if low.startswith("</b") or low.startswith("</strong"):
            b_depth = max(0, b_depth - 1)
            continue
        if low.startswith("<i") or low.startswith("<em"):
            i_depth += 1
            continue
        if low.startswith("</i") or low.startswith("</em"):
            i_depth = max(0, i_depth - 1)
            continue

        # Strip only genuine leftover HTML tags (preserve math like 'x < 5 and y > 3') and unescape entities
        plain = _html_mod.unescape(re.sub(r"</?[a-zA-Z][^>]*>", "", part))
        if not plain:
            continue
        r_el = OxmlElement('w:r')
        rPr = OxmlElement('w:rPr')
        has_rpr = False
        if b_depth > 0:
            rPr.append(OxmlElement('w:b'))
            has_rpr = True
        if i_depth > 0:
            rPr.append(OxmlElement('w:i'))
            has_rpr = True
        if sup_depth > 0:
            va = OxmlElement('w:vertAlign')
            va.set(qn('w:val'), 'superscript')
            rPr.append(va)
            has_rpr = True
        elif sub_depth > 0:
            va = OxmlElement('w:vertAlign')
            va.set(qn('w:val'), 'subscript')
            rPr.append(va)
            has_rpr = True
        if has_rpr:
            r_el.append(rPr)
        t_el = OxmlElement('w:t')
        if plain[:1].isspace() or plain[-1:].isspace():
            t_el.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        t_el.text = plain
        r_el.append(t_el)
        p_el.append(r_el)


def _build_ooxml_table_from_html(html_table: str, OxmlElement, qn):
    """Build a native OOXML <w:tbl> element from an HTML <table> preserving rowspan/colspan/sup/sub."""
    tr_match_objs = list(re.finditer(r"<tr\b[^>]*>(.*?)</tr>", html_table, flags=re.I | re.S))
    if not tr_match_objs:
        return None

    thead_m = re.search(r"<thead\b[^>]*>.*?</thead>", html_table, flags=re.I | re.S)
    thead_span = thead_m.span() if thead_m else None

    cell_re = re.compile(r"<(th|td)\b([^>]*)>(.*?)</\1>", flags=re.I | re.S)
    raw_parsed_rows: List[Tuple[bool, List[Tuple[str, int, int, str]]]] = []
    for tr_m in tr_match_objs:
        in_thead = bool(thead_span is not None and thead_span[0] <= tr_m.start() < thead_span[1])
        tr_inner = tr_m.group(1)
        row_cells: List[Tuple[str, int, int, str]] = []
        for m in cell_re.finditer(tr_inner):
            tag = m.group(1).lower()
            attrs = m.group(2) or ""
            inner_html = m.group(3) or ""
            rm = re.search(r'rowspan\s*=\s*["\']?(\d+)', attrs, flags=re.I)
            cm = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs, flags=re.I)
            rspan = max(1, int(rm.group(1))) if rm else 1
            cspan = max(1, int(cm.group(1))) if cm else 1
            row_cells.append((tag, rspan, cspan, inner_html))
        raw_parsed_rows.append((in_thead, row_cells))

    # Determine true logical column count across all rows accounting for active rowspans
    # Keep empty <tr></tr> rows when active rowspans cover them; drop stray empty rows otherwise.
    parsed_rows: List[Tuple[bool, List[Tuple[str, int, int, str]]]] = []
    active_counts: dict[int, Tuple[int, int]] = {}
    ncols = 0
    for in_thead, r_cells in raw_parsed_rows:
        if not r_cells and not active_counts:
            continue
        parsed_rows.append((in_thead, r_cells))
        col = 0
        next_active: dict[int, Tuple[int, int]] = {}
        for _, rspan, cspan, _ in r_cells:
            while col in active_counts:
                rem, w = active_counts[col]
                if rem > 1:
                    next_active[col] = (rem - 1, w)
                col += w
            if rspan > 1:
                next_active[col] = (rspan - 1, cspan)
            col += cspan
        while col in active_counts:
            rem, w = active_counts[col]
            if rem > 1:
                next_active[col] = (rem - 1, w)
            col += w
        ncols = max(ncols, col)
        active_counts = next_active

    if not parsed_rows or ncols <= 0:
        return None

    # Determine which rows carry <w:tblHeader/> (explicit <thead> rows, or leading all-<th> rows)
    if thead_span is not None:
        header_row_flags = [in_thead for in_thead, _ in parsed_rows]
    else:
        header_row_flags = []
        still_hdr = True
        for _, r_cells in parsed_rows:
            if still_hdr and r_cells and all(tag == 'th' for tag, _, _, _ in r_cells):
                header_row_flags.append(True)
            else:
                still_hdr = False
                header_row_flags.append(False)

    tbl_el = OxmlElement('w:tbl')
    tblPr = OxmlElement('w:tblPr')
    tblStyle = OxmlElement('w:tblStyle')
    tblStyle.set(qn('w:val'), 'TableGrid')
    tblPr.append(tblStyle)
    tblW = OxmlElement('w:tblW')
    tblW.set(qn('w:w'), '5000')
    tblW.set(qn('w:type'), 'pct')
    tblPr.append(tblW)
    tbl_el.append(tblPr)

    tblGrid = OxmlElement('w:tblGrid')
    col_dxa = str(max(1000, int(9000 / ncols)))
    for _ in range(ncols):
        gc = OxmlElement('w:gridCol')
        gc.set(qn('w:w'), col_dxa)
        tblGrid.append(gc)
    tbl_el.append(tblGrid)

    # Emit <w:tr> rows with exact <w:gridSpan>, <w:vMerge>, and <w:tblHeader>
    active_vspans: dict[int, Tuple[int, int]] = {}
    for (_, r_cells), is_hdr_row in zip(parsed_rows, header_row_flags):
        tr_el = OxmlElement('w:tr')
        if is_hdr_row:
            trPr = OxmlElement('w:trPr')
            trPr.append(OxmlElement('w:tblHeader'))
            tr_el.append(trPr)
        col = 0
        next_active: dict[int, Tuple[int, int]] = {}

        def _emit_vmerge_cont(span_w: int) -> None:
            tc_cont = OxmlElement('w:tc')
            tcPr_c = OxmlElement('w:tcPr')
            if span_w > 1:
                gs_c = OxmlElement('w:gridSpan')
                gs_c.set(qn('w:val'), str(span_w))
                tcPr_c.append(gs_c)
            tcPr_c.append(OxmlElement('w:vMerge'))
            tc_cont.append(tcPr_c)
            tc_cont.append(OxmlElement('w:p'))
            tr_el.append(tc_cont)

        for tag, rspan, cspan, inner_html in r_cells:
            while col in active_vspans:
                rem, w = active_vspans[col]
                _emit_vmerge_cont(w)
                if rem > 1:
                    next_active[col] = (rem - 1, w)
                col += w

            tc_el = OxmlElement('w:tc')
            tcPr = OxmlElement('w:tcPr')
            if cspan > 1:
                gs = OxmlElement('w:gridSpan')
                gs.set(qn('w:val'), str(cspan))
                tcPr.append(gs)
            if rspan > 1:
                vm = OxmlElement('w:vMerge')
                vm.set(qn('w:val'), 'restart')
                tcPr.append(vm)
                next_active[col] = (rspan - 1, cspan)
            tc_el.append(tcPr)

            p_el = OxmlElement('w:p')
            _append_html_inline_runs(p_el, inner_html, OxmlElement, qn, bold=(tag == 'th'))
            tc_el.append(p_el)
            tr_el.append(tc_el)
            col += cspan

        while col < ncols:
            if col in active_vspans:
                rem, w = active_vspans[col]
                _emit_vmerge_cont(w)
                if rem > 1:
                    next_active[col] = (rem - 1, w)
                col += w
            else:
                tc_pad = OxmlElement('w:tc')
                tc_pad.append(OxmlElement('w:p'))
                tr_el.append(tc_pad)
                col += 1

        active_vspans = next_active
        tbl_el.append(tr_el)

    return tbl_el


def _expand_script_tokens_in_paragraph(p_el, OxmlElement, qn) -> bool:
    """Expand ZZSUPHEX.../ZZSUBHEX... (and legacy ⟦SUP:...⟧/⟦SUB:...⟧) tokens into native OOXML vertAlign runs."""
    import copy

    full_txt = "".join(t.text or "" for t in p_el.iter(qn('w:t')))
    if (
        "ZZSUPHEX" not in full_txt
        and "ZZSUBHEX" not in full_txt
        and "⟦SUP:" not in full_txt
        and "⟦SUB:" not in full_txt
    ):
        return False

    # Coalesce adjacent text-only <w:r> siblings with identical rPr so split tokens are reassembled
    def _is_plain_text_run(el) -> bool:
        if el.tag != qn('w:r'):
            return False
        return all(child.tag in (qn('w:rPr'), qn('w:t')) for child in el)

    def _rpr_sig(r_el) -> str:
        rPr = r_el.find(qn('w:rPr'))
        return str(rPr.xml) if rPr is not None else ""

    p_children = list(p_el)
    i = 0
    while i < len(p_children) - 1:
        cur = p_children[i]
        nxt = p_children[i + 1]
        if _is_plain_text_run(cur) and _is_plain_text_run(nxt) and _rpr_sig(cur) == _rpr_sig(nxt):
            cur_txt = "".join(t.text or "" for t in cur.findall(qn('w:t')))
            nxt_txt = "".join(t.text or "" for t in nxt.findall(qn('w:t')))
            combined = cur_txt + nxt_txt
            for old_t in list(cur.findall(qn('w:t'))):
                cur.remove(old_t)
            nt = OxmlElement('w:t')
            if combined[:1].isspace() or combined[-1:].isspace():
                nt.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            nt.text = combined
            cur.append(nt)
            p_el.remove(nxt)
            p_children.pop(i + 1)
            continue
        i += 1

    modified = False
    for r_el in list(p_el.findall(qn('w:r'))):
        t_nodes = r_el.findall(qn('w:t'))
        if not t_nodes:
            continue
        r_txt = "".join(t.text or "" for t in t_nodes)
        if not _INLINE_SCRIPT_TOKEN_RE.search(r_txt):
            continue

        orig_rPr = r_el.find(qn('w:rPr'))
        new_runs = []
        pos = 0
        for m in _INLINE_SCRIPT_TOKEN_RE.finditer(r_txt):
            if m.start() > pos:
                seg = r_txt[pos:m.start()]
                nr = OxmlElement('w:r')
                if orig_rPr is not None:
                    nr.append(copy.deepcopy(orig_rPr))
                nt = OxmlElement('w:t')
                if seg[:1].isspace() or seg[-1:].isspace():
                    nt.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                nt.text = seg
                nr.append(nt)
                new_runs.append(nr)

            if m.group(1) is not None:
                kind = m.group(1)
                try:
                    val = bytes.fromhex(m.group(2)).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    val = m.group(0)
            else:
                kind = m.group(3)
                val = _html_mod.unescape(m.group(4))

            sr = OxmlElement('w:r')
            srPr = copy.deepcopy(orig_rPr) if orig_rPr is not None else OxmlElement('w:rPr')
            existing_va = srPr.find(qn('w:vertAlign'))
            if existing_va is not None:
                srPr.remove(existing_va)
            va = OxmlElement('w:vertAlign')
            va.set(qn('w:val'), 'superscript' if kind == 'SUP' else 'subscript')
            srPr.append(va)
            sr.append(srPr)
            st = OxmlElement('w:t')
            if val[:1].isspace() or val[-1:].isspace():
                st.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            st.text = val
            sr.append(st)
            new_runs.append(sr)
            pos = m.end()

        if pos < len(r_txt):
            seg = r_txt[pos:]
            nr = OxmlElement('w:r')
            if orig_rPr is not None:
                nr.append(copy.deepcopy(orig_rPr))
            nt = OxmlElement('w:t')
            if seg[:1].isspace() or seg[-1:].isspace():
                nt.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
            nt.text = seg
            nr.append(nt)
            new_runs.append(nr)

        if new_runs:
            parent = r_el.getparent()
            idx = list(parent).index(r_el)
            parent.remove(r_el)
            for offset, nr in enumerate(new_runs):
                parent.insert(idx + offset, nr)
            modified = True

    return modified


def inject_html_tables_and_scripts_into_docx(
    docx_path: str,
    html_tables: Sequence[str],
) -> None:
    """
    Replace HTML-table slot paragraphs in a Pandoc-generated DOCX with native OOXML
    <w:tbl> elements (preserving rowspan/colspan/sup/sub) and expand inline ⟦SUP/SUB⟧
    script sentinel tokens into genuine Word vertAlign runs across body and tables.
    """
    if not os.path.exists(docx_path):
        return
    try:
        import docx
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
    except ImportError:
        return

    doc = docx.Document(docx_path)
    body = doc.element.body
    changed = False

    if html_tables:
        slot_re = re.compile(rf"^{_HTML_TABLE_SLOT_PREFIX}(\d+){_HTML_TABLE_SLOT_SUFFIX}$")
        for el in list(body):
            if el.tag != qn('w:p'):
                continue
            txt = "".join(t.text or "" for t in el.iter(qn('w:t'))).strip()
            m = slot_re.match(txt)
            if not m:
                continue
            slot_idx = int(m.group(1))
            if 0 <= slot_idx < len(html_tables):
                tbl_el = _build_ooxml_table_from_html(html_tables[slot_idx], OxmlElement, qn)
                if tbl_el is not None:
                    pos = list(body).index(el)
                    body.remove(el)
                    body.insert(pos, tbl_el)
                    changed = True

    # Expand protected ⟦SUP:...⟧ / ⟦SUB:...⟧ script runs in all paragraphs (body + tables)
    for p_el in body.iter(qn('w:p')):
        if _expand_script_tokens_in_paragraph(p_el, OxmlElement, qn):
            changed = True

    if changed:
        doc.save(docx_path)


def apply_table_styles_to_docx(docx_path: str) -> None:
    """
    修改表格製作樣式：
    1. 合併僅相隔空段或「續表」的跨頁相容表格（移除重複表頭）
    2. 表格樣式設為「表格格線」 (Table Grid)，寬度正規化為 100% 頁寬 (5000 pct)
    3. 首列設定跨頁重複標題 (<w:tblHeader/>)，所有列設定禁止跨頁斷裂 (<w:cantSplit/>)
    4. 表格內文字段落無任何特殊樣式設定 (重設為預設內文 Normal，移除 Compact 或其他 pStyle)
    """
    if not os.path.exists(docx_path):
        return

    try:
        import docx
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
    except ImportError:
        return

    try:
        doc = docx.Document(docx_path)
        if not doc.tables:
            return

        _coalesce_adjacent_docx_tables(doc, qn)

        grid_style = None
        for s_name in ['Table Grid', '表格格線', 'TableGrid']:
            if s_name in doc.styles:
                grid_style = doc.styles[s_name]
                break

        def _set_tbl_style_xml(table_elem):
            tblPr = table_elem._tbl.tblPr
            if tblPr is None:
                tblPr = OxmlElement('w:tblPr')
                table_elem._tbl.insert(0, tblPr)
            tblStyle = tblPr.find(qn('w:tblStyle'))
            if tblStyle is None:
                tblStyle = OxmlElement('w:tblStyle')
                tblPr.insert(0, tblStyle)
            tblStyle.set(qn('w:val'), 'TableGrid')

        def _normalize_table_width(table_elem):
            tblPr = table_elem._tbl.tblPr
            if tblPr is None:
                tblPr = OxmlElement('w:tblPr')
                table_elem._tbl.insert(0, tblPr)
            tblW = tblPr.find(qn('w:tblW'))
            if tblW is None:
                tblW = OxmlElement('w:tblW')
                tblStyle = tblPr.find(qn('w:tblStyle'))
                insert_idx = list(tblPr).index(tblStyle) + 1 if tblStyle is not None else 0
                tblPr.insert(insert_idx, tblW)
            tblW.set(qn('w:w'), '5000')
            tblW.set(qn('w:type'), 'pct')

        def _apply_row_repeat_and_cant_split(table_elem):
            trs = table_elem._tbl.findall(qn('w:tr'))
            if not trs:
                return
            header_end_idx = max(0, _docx_table_header_row_count(trs, qn) - 1)

            for r_idx, tr in enumerate(trs):
                trPr = tr.find(qn('w:trPr'))
                if trPr is None:
                    trPr = OxmlElement('w:trPr')
                    tr.insert(0, trPr)
                existing_hdr = trPr.find(qn('w:tblHeader'))
                if r_idx <= header_end_idx:
                    if trPr.find(qn('w:cantSplit')) is None:
                        cant = OxmlElement('w:cantSplit')
                        if existing_hdr is not None:
                            trPr.insert(list(trPr).index(existing_hdr), cant)
                        else:
                            trPr.append(cant)
                    if existing_hdr is None:
                        trPr.append(OxmlElement('w:tblHeader'))
                else:
                    if existing_hdr is not None:
                        trPr.remove(existing_hdr)
                    if trPr.find(qn('w:cantSplit')) is None:
                        trPr.append(OxmlElement('w:cantSplit'))

        def _format_table(tbl):
            if grid_style is not None:
                try:
                    tbl.style = grid_style
                except Exception:
                    _set_tbl_style_xml(tbl)
            else:
                _set_tbl_style_xml(tbl)

            _normalize_table_width(tbl)
            _apply_row_repeat_and_cant_split(tbl)

            for row in tbl.rows:
                for cell in row.cells:
                    tcPr = cell._tc.tcPr
                    if tcPr is not None:
                        tcW = tcPr.find(qn('w:tcW'))
                        if tcW is not None and tcW.get(qn('w:type')) == 'auto' and tcW.get(qn('w:w')) == '0':
                            tcPr.remove(tcW)
                    for p in cell.paragraphs:
                        try:
                            p.style = 'Normal'
                        except Exception:
                            pass
                        pPr = p._p.pPr
                        if pPr is not None:
                            pStyle = pPr.find(qn('w:pStyle'))
                            if pStyle is not None:
                                pPr.remove(pStyle)
                            if len(pPr) == 0:
                                p._p.remove(pPr)
                    for nested in cell.tables:
                        _format_table(nested)

        for tbl in doc.tables:
            _format_table(tbl)

        doc.save(docx_path)
        print(f"Applied 'Table Grid' style to {len(doc.tables)} table(s) in {docx_path}")
    except Exception as e:
        print(f"[Warning] 表格樣式後處理失敗: {e}")

_INTERNAL_IMAGE_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".dib", ".tif", ".tiff", ".gif"
)


def _should_clear_image_alt_text(alt_text: str) -> bool:
    """Return True if alt_text is an internal extracted filename (image_*/page_* or image extension)."""
    if not alt_text:
        return False
    lowered = alt_text.strip().lower()
    return lowered.startswith(("image_", "page_")) or lowered.endswith(_INTERNAL_IMAGE_EXTENSIONS)


def _resolve_img_path(
    m: re.Match,
    md_base_dir: str,
    default_img_width: Optional[str] = None,
) -> str:
    """Resolve a Markdown image match, clearing internal filename alt text and normalizing relative paths."""
    alt_text = m.group(1)
    img_path_raw = m.group(2)
    attrs = m.group(3) or ''

    # 若 alt_text 是內部圖檔名稱（以 image_/page_ 開頭或含常見圖片副檔名），清空之
    if _should_clear_image_alt_text(alt_text):
        alt_text = ''

    # 若尚未指定 width 屬性，且有預設寬度，則自動補上
    if default_img_width and 'width=' not in attrs:
        if attrs.strip():
            attrs = attrs.rstrip('}') + f' width={default_img_width}}}'
        else:
            attrs = f'{{width={default_img_width}}}'

    # 若已是絕對路徑或網路 URL，則不處理路徑
    if os.path.isabs(img_path_raw) or img_path_raw.startswith(('http://', 'https://')):
        return f"![{alt_text}]({img_path_raw}){attrs}"

    abs_img = os.path.normpath(os.path.join(md_base_dir, img_path_raw))
    if os.path.exists(abs_img):
        # 使用正斜線以確保跨平台相容性
        return f"![{alt_text}]({abs_img.replace(os.sep, '/')}){attrs}"
    return f"![{alt_text}]({img_path_raw}){attrs}"


def rewrite_markdown_image_paths(
    md_content: str,
    md_base_dir: str,
    default_img_width: Optional[str] = None,
) -> str:
    """Rewrite Markdown image tags to clear internal alt text, inject default width, and resolve paths."""
    return re.sub(
        r'!\[([^\]]*)\]\(([^)]+)\)(\{[^}]*\})?',
        lambda m: _resolve_img_path(m, md_base_dir=md_base_dir, default_img_width=default_img_width),
        md_content,
    )


def main():
    parser = argparse.ArgumentParser(description="Convert Markdown to Word Document.")
    parser.add_argument('--files', '--target', nargs='+', help="Specific markdown files to convert")
    parser.add_argument('--template', help="Explicit path to a .docx reference template (overrides auto-detect)")
    parser.add_argument('--image-width', default='80%', help="Default width for images without width attribute (e.g. '80%', '100%', 'none')")
    parser.add_argument('--skip-text-postprocess', action='store_true', help="Skip duplicate founder/symbol text postprocessing when already processed by MarkdownPostProcessor")
    args = parser.parse_args()

    # Resolve paths relative to the data directory
    _data_dir = get_data_dir()
    _config_dir = get_config_dir()
    _script_dir = Path(__file__).parent.resolve()

    input_dir  = str(_data_dir / '03_output')
    pdf_dir    = str(_data_dir / 'database_text')

    # Fallback chain for reference template:
    # 1. Explicit --template arg (highest priority)
    # 2. User-uploaded user_template.docx in custom_templates/
    # 3. Default template.docx in database_text/
    # 4. Bundled template.docx in package (src/founder_tools/template.docx)
    # 5. config dir template.docx
    # 6. script dir template.docx
    active_path = resolve_active_template_path(args.template)
    if active_path:
        template_path = str(active_path)
        print(f"Using template: {template_path}")
    else:
        template_path = None
        print("Warning: template.docx not found. Converting without reference doc — styles may differ.")
        
    md_files = []
    
    if args.files:
        md_files = args.files
        print(f"Using specified files: {md_files}")
    else:
        # Fallback to pdf stems
        pdf_files = glob.glob(os.path.join(pdf_dir, '*.pdf'))
        if not pdf_files:
            print("No PDF files found in database_text to align with. Please specify target md files using --files.")
            return
            
        for pdf in pdf_files:
            stem = Path(pdf).stem
            md_path = os.path.join(input_dir, f"{stem}.md")
            if os.path.exists(md_path):
                md_files.append(md_path)
            else:
                print(f"Warning: Expected output md not found for {stem}.pdf ({md_path})")
                
    if not md_files:
        print("No Markdown files to convert.")
        return
        
    print(f"Found {len(md_files)} Markdown files to convert.")
    
    import uuid
    import tempfile
    import json
    
    # 讀取人工判定方正亂碼字庫（僅在未經統一後處理時啟用）
    correction_dict_path = _data_dir / 'Json' / 'founder_correction_dict.json'
    founder_corrections = {}
    if not getattr(args, 'skip_text_postprocess', False) and correction_dict_path.exists():
        try:
            with open(correction_dict_path, 'r', encoding='utf-8') as f:
                founder_corrections = json.load(f)
            print(f"載入方正亂碼人工判定字庫，共 {len(founder_corrections)} 筆對應。")
        except Exception as e:
            print(f"[Warning] 讀取 founder_correction_dict.json 失敗: {e}")
            
    
    for md_path in md_files:
        print(f"Converting: {md_path}")
        temp_md_path = None
        try:
            out_name = Path(md_path).stem + ".docx"
            out_dir = os.path.dirname(md_path) or input_dir
            out_path = os.path.join(out_dir, out_name)
            already_postprocessed = bool(getattr(args, 'skip_text_postprocess', False))
            
            # Step 0: Read MD, escape numbered lists, save to isolated UUID temp file
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
                
            if not already_postprocessed:
                # 套用人工判定字庫替換 (方正排版亂碼修復)
                if founder_corrections:
                    for bad_char, good_char in founder_corrections.items():
                        if not bad_char or bad_char.startswith('_'):
                            continue
                        md_content = md_content.replace(bad_char, good_char)
                
                # 套用 clean_founder_text 方正亂碼修復 (涵蓋彝文區 GBK 映射等)
                try:
                    from src.founder_tools.fix_founder_fonts import clean_founder_text
                    md_content = clean_founder_text(md_content)
                except ImportError:
                    pass

            # Escape "1. " to "1\. " to prevent Word auto-numbering
            md_content = re.sub(r'(?m)^(\s*\d+)\.\s', r'\1\\. ', md_content)
            
            # 移除 OCR 產生的全形/半形 Latex 數學符號包裝，還原為純文字
            def clean_latex(m):
                c = m.group(1)
                # 替換常見的數學指令為純文字符號
                c = c.replace(r'\times', '×').replace(r'\div', '÷').replace(r'\pm', '±')
                c = c.replace(r'\circ', '°').replace(r'\sim', '~').replace(r'\cdot', '·')
                
                # 處理 \mathrm{...} 或 \text{...} 等指令（保留其內容）
                c = re.sub(r'\\[a-zA-Z]+\s*\{\s*(.*?)\s*\}', r'\1', c)
                # 移除殘留的 \xxx 指令
                c = re.sub(r'\\[a-zA-Z]+', '', c)
                
                c = re.sub(r'(?<=\d)\s+(?=\d)', '', c) # 移除數字間的空格
                c = re.sub(r'\s*°\s*', '°', c)       # 移除度數符號旁的空格
                
                # 移除大括號、反斜線、錢字號等 Latex 語法符號（保留 ^ 和 _，以維持 10^-4 這種表示法）
                c = re.sub(r'[\{\}\\\$]', '', c)
                # 整理符號前後的空格（例如將 10 ^ - 4 整理成 10^-4）
                c = re.sub(r'\s*([+\-^])\s*', r'\1', c)
                
                return re.sub(r'\s+', ' ', c).strip()
            
            md_content = re.sub(r'\\（（(.*?)）\\）', clean_latex, md_content)
            md_content = re.sub(r'\\\((.*?)\\\)', clean_latex, md_content)

            # 將 Markdown 中的相對圖片路徑轉為絕對路徑，確保 Pandoc 在任意工作目錄下都能找到圖檔
            # 同時支援圖片寬度屬性（如 {width=80%}），並清空圖檔檔名標籤避免 Pandoc 生成多餘圖說
            md_base_dir = os.path.dirname(os.path.abspath(md_path))
            default_img_width = args.image_width if getattr(args, 'image_width', None) and args.image_width.lower() != 'none' else None

            md_content = rewrite_markdown_image_paths(
                md_content,
                md_base_dir=md_base_dir,
                default_img_width=default_img_width,
            )
            
            # 清理未指定任何路徑之空白圖片標記（如 ![img]()），避免 Pandoc 輸出警告並殘留 'img' 文字
            md_content = re.sub(r'(?m)^\s*!\[[^\]]*\]\(\s*\)(?:\{[^\n}]*\})?\s*\n?', '', md_content)

            if not already_postprocessed:
                # 套用特殊排版符號還原（截斷括號、圓圈數字、波浪號正規化）
                try:
                    from src.extraction.symbol_mapper import restore_ocr_symbols
                    md_content, _ = restore_ocr_symbols(md_content)
                except ImportError:
                    pass

            # 確保圖片 Markdown 語法獨立成行（前後各加空行），並相容屬性語法 {...}
            img_token_pattern = r'!\[[^\]]*\]\([^)]+\)(?:\{[^\n}]*\})?'
            md_content = re.sub(r'([^\n])\n*(' + img_token_pattern + r')', r'\1\n\n\2', md_content)
            md_content = re.sub(r'(' + img_token_pattern + r')\n*([^\n])', r'\1\n\n\2', md_content)

            # 抽離 HTML <table>（保留 rowspan/colspan）並保護內文/GFM 表格中的 <sup>/<sub>
            md_content, extracted_html_tables = extract_html_tables_for_pandoc(md_content)
            md_content = protect_inline_scripts_for_pandoc(md_content)

            temp_md_path = os.path.join(tempfile.gettempdir(), f"temp_{uuid.uuid4().hex}.md")
            with open(temp_md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)

            # Convert MD directly to DOCX
            # 加入 --resource-path 確保 Pandoc 能解析圖片路徑並嵌入 Word
            # 使用 markdown-implicit_figures 停用自動將段落圖片視為 Figure Caption 的功能
            # 使用 -subscript 停用波浪號 ~ 轉換為下標 (subscript)，避免數字區間如 2~3次 被誤轉為小標/下標
            pandoc_extra = []
            if template_path:
                pandoc_extra.append(f'--reference-doc={template_path}')
            pandoc_extra.append(f'--resource-path={md_base_dir}')
            
            pypandoc.convert_file(
                temp_md_path,
                'docx',
                format='markdown-implicit_figures-subscript+raw_html+tex_math_dollars',
                outputfile=out_path,
                extra_args=pandoc_extra
            )
            inject_html_tables_and_scripts_into_docx(out_path, extracted_html_tables)
            apply_table_styles_to_docx(out_path)
            print(f"Saved DOCX to {out_path}")
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            print(f"[ERROR] Error converting {md_path}: {e}\n{tb_str}")
        finally:
            if temp_md_path and os.path.exists(temp_md_path):
                try:
                    os.remove(temp_md_path)
                except OSError:
                    pass

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        print(f"[FATAL] 未預期錯誤: {e}\n{traceback.format_exc()}")
        sys.exit(1)
