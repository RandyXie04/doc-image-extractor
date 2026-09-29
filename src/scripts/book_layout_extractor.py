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

# pyrefly: ignore [missing-import]
import fitz

# Try to import project helpers
try:
    from src.founder_tools.core.heading_detector import HeadingDetector
except ImportError:
    HeadingDetector = None

CIRCLED_MAP = {
    '①': 1, '②': 2, '③': 3, '④': 4, '⑤': 5,
    '⑥': 6, '⑦': 7, '⑧': 8, '⑨': 9, '⑩': 10,
    # Extended circled numbers ⑪–⑳ (U+246A–U+2473)
    '⑪': 11, '⑫': 12, '⑬': 13, '⑭': 14, '⑮': 15,
    '⑯': 16, '⑰': 17, '⑱': 18, '⑲': 19, '⑳': 20,
}

# Regex pattern matching any recognised footnote marker (circled / bracketed / numbered-dot)
FN_MARKER_PATTERN = r'([\u2460-\u2473]|\[\d+\]|\(\d+\)|\d+\.)'


def _circled_to_int(marker_str: str) -> int:
    """Convert any footnote marker string to its integer index."""
    if marker_str in CIRCLED_MAP:
        return CIRCLED_MAP[marker_str]
    digs = re.findall(r'\d+', marker_str)
    return int(digs[0]) if digs else 1


def _replace_fn_markers_in_text(text: str, page_footnotes: list, page_num: int) -> str:
    """Replace all recognised footnote marker occurrences in *text* with Pandoc ref-tags.
    Works for both body paragraphs and table cells."""
    for fn in page_footnotes:
        m_str = fn.get('marker', '')
        if m_str and m_str in text:
            fn_tag = f"[^p{page_num}_{fn['id']}]"
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
        
    # Header patterns
    patterns = [
        r'版图之枷',
        r'军事后勤视野',
        r'^[上下中]篇[:：|｜]',
        r'第[一二三四五六七八九十百]+章',
        r'^/\s*\d+',
        r'^\d+\s*/',
        r'^\d{1,4}$',
        r'^(?:目\s*录|目录|序|结语|主要参考文献|后\s*记|后记)\s*/',
        r'/\s*(?:目\s*录|目录|序|结语|主要参考文献|后\s*记|后记)'
    ]
    for pat in patterns:
        if re.search(pat, text):
            return True
    # If text is very short single page number or header text in extreme top margin
    if bbox[1] < page_h * 0.11 and (re.match(r'^\d+$', text) or len(text) <= 30 and '/' in text):
        return True
    return False

def is_page_footer(block, page_h):
    bbox = block.get('bbox', [0, 0, 0, 0])
    # Footers are strictly in bottom 10%
    if bbox[1] < page_h * 0.90:
        return False
    text = "".join(s['text'] for l in block.get('lines', []) for s in l.get('spans', [])).strip()
    # Solitary page numbers
    if re.match(r'^\s*\d{1,4}\s*$', text):
        return True
    return False

def parse_footnote_marker(text):
    m = re.match(r'^\s*([①-⑩\u2460-\u2473]|\[\d+\]|\(\d+\)|\d+\.)\s*', text)
    if m:
        marker_str = m.group(1).strip()
        num = CIRCLED_MAP.get(marker_str)
        if not num:
            digs = re.findall(r'\d+', marker_str)
            num = int(digs[0]) if digs else 1
        return num, marker_str, text[m.end():].strip()
    return None, None, text

def process_book_vector_pdf(pdf_path, output_dir, output_stem=None, style_mapping=None, progress_callback=None):
    """
    Extract vector PDF with:
    1. Header / footer removal
    2. Footnote parsing, anchor substitution, and footnote block formatting
    3. Heading level classification (H1, H2, H3) + custom Word style mapping
    4. Paragraph reflow (eliminating PDF line-wrap broken sentences)
    5. Returns audit report data dict
    """
    if style_mapping is None:
        style_mapping = {}
    if isinstance(style_mapping, str):
        try:
            style_mapping = json.loads(style_mapping)
        except Exception:
            style_mapping = {}

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    stem = output_stem or os.path.basename(pdf_path).rsplit(".", 1)[0]
    
    os.makedirs(output_dir, exist_ok=True)
    out_md_path = os.path.join(output_dir, f"{stem}.md")
    
    audit_data = {
        "pdf_name": os.path.basename(pdf_path),
        "total_pages": total_pages,
        "headers_removed": 0,
        "footers_removed": 0,
        "headings_detected": [],
        "footnotes_matched": 0,
        "footnotes_fallback": 0,
        "footnotes_detail": [],
        "paragraphs_reflowed": 0
    }
    
    final_md_pages = []
    
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
                if inter.get_area() / max(b.get_area(), 1.0) > 0.30:
                    return True
            return False

        # Step 1: Collect valid text blocks, separate header/footer/footnote
        body_blocks = []
        footnote_blocks = []

        for b in blocks:
            if b.get("type") != 0:
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
            # Starts with footnote marker (e.g. ①, [1], (1)) — use extended pattern
            starts_with_fn_marker = bool(re.match(
                r'^\s*(' + FN_MARKER_PATTERN + r')\s*', block_text
            ))

            if bbox[1] >= page_h * 0.72 and avg_size <= 9.5:
                if starts_with_fn_marker:
                    is_fn = True
                elif footnote_blocks:
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
            parts = re.split(FN_MARKER_PATTERN, fb_text)

            # parts[0] — text before the first marker (may be empty)
            prefix = parts[0]
            m_start = re.match(r'^\s*' + FN_MARKER_PATTERN + r'\s*', prefix)
            if m_start:
                # The prefix itself *is* a marker (split captured it)
                pass  # handled below in the loop
            elif prefix.strip():
                # Plain continuation text before any marker
                if current_fn_entry:
                    sep = " " if current_fn_entry["content"] else ""
                    current_fn_entry["content"] += sep + prefix.strip()
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

        # Step 3: Determine base_x0 for body paragraphs on this page
        normal_x0s = []
        for bb in body_blocks:
            lines = bb.get("lines", [])
            bb_text = "".join(s.get("text", "") for l in lines for s in l.get("spans", [])).strip()
            bbox = bb.get("bbox", [0, 0, 0, 0])
            center_x = (bbox[0] + bbox[2]) / 2.0
            is_centered = abs(center_x - (page_w / 2.0)) < (page_w * 0.12)
            if not is_centered and len(bb_text) > 10:
                normal_x0s.append(bbox[0])
        base_x0 = min(normal_x0s) if normal_x0s else 65.0

        page_paragraphs = []
        current_para_lines = []
        current_para_is_kaiti = False
        last_heading_text = ""

        def flush_current_para():
            nonlocal current_para_lines, current_para_is_kaiti
            if current_para_lines:
                # Splice lines smoothly
                para_text = ""
                for line_txt in current_para_lines:
                    if not para_text:
                        para_text = line_txt
                    else:
                        cjk_end = bool(re.search(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]$', para_text))
                        cjk_start = bool(re.search(r'^[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', line_txt))
                        if cjk_end and cjk_start:
                            para_text += line_txt
                            audit_data["paragraphs_reflowed"] += 1
                        else:
                            para_text += " " + line_txt
                if current_para_is_kaiti:
                    para_text = "> " + para_text
                page_paragraphs.append(para_text)
                current_para_lines = []
                current_para_is_kaiti = False
        
        for bb in body_blocks:
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
            is_toc_line = bool(re.search(r'[…\.]{2,}\s*\d+$', bb_text))
            
            clean_for_heading = re.sub(r'[①-⑩\u2460-\u2473\s]', '', bb_text)
            has_sentence_punct = bool(re.search(r'[。，；？！“”‘’：:、]', clean_for_heading))
            
            if not is_toc_line:
                # Rule 1: Regex for Major Chapters / Book Sections (H1/H2)
                if re.match(r'^(?:[上下中]\s*篇(?:\s+[^\n]+)?)$', bb_text) or \
                   re.match(r'^(?:目\s*录|目录|序|后\s*记|后记|结\s*语|结语|主要参考文献)$', bb_text):
                    heading_level = 1
                elif re.match(r'^第[一二三四五六七八九十百]+章(?:\s+[^\n]+)?$', bb_text):
                    heading_level = 2
                # Rule 2: Section titles (H2) - Must be short and without sentence punctuation
                elif (is_centered or avg_size >= 10.8) and 2 <= len(clean_for_heading) <= 20 and not has_sentence_punct:
                    if not re.search(r'示意图|表$', bb_text) and not re.search(r'^[①-⑩]', bb_text):
                        heading_level = 2
                # Rule 3: Sub-sections (H3)
                elif (re.match(r'^[（(][一二三四五六七八九十\d]+[)）]', bb_text) or re.match(r'^\d+\.\d+', bb_text)) and not has_sentence_punct:
                    heading_level = 3
                
            if heading_level > 0:
                flush_current_para()
                # Deduplicate identical consecutive headings on the same page
                if bb_text == last_heading_text:
                    continue
                last_heading_text = bb_text
                
                audit_data["headings_detected"].append({
                    "page": page_num,
                    "level": f"H{heading_level}",
                    "text": bb_text
                })
                # Custom style annotation if configured
                style_key = f"h{heading_level}"
                custom_style = style_mapping.get(style_key)
                if custom_style:
                    formatted_heading = f"{'#' * heading_level} {bb_text} {{custom-style=\"{custom_style}\"}}"
                else:
                    formatted_heading = f"{'#' * heading_level} {bb_text}"
                page_paragraphs.append(formatted_heading)
                continue
            else:
                last_heading_text = ""
                
            # Regular Body Text
            # Check font for KaiTi
            total_chars = 0
            kaiti_chars = 0
            for line in lines:
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if not span_text: continue
                    total_chars += len(span_text)
                    font_name = span.get("font", "").lower()
                    if "kai" in font_name or "楷" in font_name or "kaiti" in font_name:
                        kaiti_chars += len(span_text)
            
            is_block_kaiti = (total_chars > 0 and (kaiti_chars / total_chars) > 0.5)

            # Check indentation to determine whether this block starts a new paragraph
            is_indented = (bbox[0] - base_x0) >= 12.0
            
            # If this block has an indent, flush the previous paragraph
            if is_indented:
                flush_current_para()
                
            if is_block_kaiti:
                current_para_is_kaiti = True
                
            # Process lines in this block, replacing footnote anchors
            for line in lines:
                line_str = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
                if not line_str:
                    continue
                line_str = _replace_fn_markers_in_text(line_str, page_footnotes, page_num)
                current_para_lines.append(line_str)
                
        # Flush any remaining body text
        flush_current_para()

        # ── Step 3b: Render detected tables (inserted in document order) ──────
        # Tables are inserted *after* the body paragraphs gathered so far;
        # a future improvement can sort by y-position across body+table elements.
        for tbl in page_tables:
            tbl_md = _table_to_markdown(tbl, page_footnotes, page_num)
            if tbl_md:
                page_paragraphs.append(tbl_md)

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

        if page_paragraphs:
            final_md_pages.append("\n\n".join(page_paragraphs))
            
    # Write final Markdown file
    full_markdown = "\n\n".join(final_md_pages)
    
    # ── 生僻字後處理：靜態字典校正 + 方正亂碼修復 + 可疑字元偵測 ──
    try:
        from src.scripts.ocr_rare_char_corrector import postprocess_ocr_markdown
    except ImportError:
        try:
            from scripts.ocr_rare_char_corrector import postprocess_ocr_markdown
        except ImportError:
            postprocess_ocr_markdown = None
    
    if postprocess_ocr_markdown is not None:
        # 動態取得 data_dir 路徑
        try:
            from config import PATHS
            data_dir = str(PATHS.data_dir)
        except ImportError:
            data_dir = str(Path(__file__).parent.parent.parent / "data")
        
        full_markdown, rare_char_stats = postprocess_ocr_markdown(
            markdown_text=full_markdown,
            data_dir=data_dir,
            pdf_name=os.path.basename(pdf_path),
            output_dir=output_dir,
        )
        corrected = rare_char_stats.get("corrections_applied", 0)
        suspicious = rare_char_stats.get("suspicious_chars_found", 0)
        audit_data["rare_char_corrections"] = corrected
        audit_data["rare_char_suspicious"] = suspicious
        if progress_callback:
            if corrected > 0:
                progress_callback(88, f"[INFO] 靜態字典自動修正了 {corrected} 處已知錯字。")
            if suspicious > 0:
                progress_callback(89, f"[REVIEW] ⚠️ 偵測到 {suspicious} 處可疑字元（疑似生僻字/亂碼），覆核報告已生成。")
    
    with open(out_md_path, "w", encoding="utf-8") as f:
        f.write(full_markdown)
        
    return out_md_path, audit_data
