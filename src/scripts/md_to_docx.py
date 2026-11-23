import os
import glob
import re
import sys
import argparse
from typing import Optional
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

def _is_xu_biao_paragraph(p_elem, qn) -> bool:
    if p_elem.tag != qn('w:p'):
        return False
    if (
        p_elem.find('.//' + qn('w:drawing')) is not None
        or p_elem.find('.//' + qn('w:pict')) is not None
        or p_elem.find('.//' + qn('w:object')) is not None
        or p_elem.find('.//' + qn('w:sectPr')) is not None
    ):
        return False
    txt = "".join(t.text or "" for t in p_elem.iter(qn('w:t'))).strip()
    if not txt:
        return True  # empty spacer paragraph
    try:
        from src.extraction.table_reconstructor import is_continuation_table_marker
        return is_continuation_table_marker(txt)
    except Exception:
        return bool(re.match(r'^[（(]?\s*(?:续\s*表|續\s*表)\s*[）)]?[：:.]?\s*$', txt))


def _coalesce_adjacent_docx_tables(doc, qn) -> int:
    """
    Coalesce adjacent compatible <w:tbl> elements separated only by empty <w:p> or at most one
    '续表'/'續表' <w:p> when column counts match and (has '续表'/'續表' or header rows match).
    Strips repeated header rows and intervening '续表'/empty paragraphs when merging.
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
        return [
            re.sub(r'\s+', '', "".join(t.text or "" for t in tc.iter(qn('w:t'))))
            for tc in tr_el.findall(qn('w:tc'))
        ]

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

            # Validate intervening paragraphs
            xu_biao_hits = 0
            valid_gap = True
            for b_el in between_elems:
                if not _is_xu_biao_paragraph(b_el, qn):
                    valid_gap = False
                    break
                b_txt = "".join(t.text or "" for t in b_el.iter(qn('w:t'))).strip()
                if b_txt:
                    xu_biao_hits += 1
                    if xu_biao_hits > 1:
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
            has_xu_biao = xu_biao_hits > 0
            if not (has_xu_biao or headers_match):
                prev_tbl = el
                between_elems = []
                continue

            rows_to_move = curr_trs[1:] if headers_match else curr_trs
            _sync_moved_row_widths(prev_tbl, el, rows_to_move, prev_cols)
            for tr in rows_to_move:
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
            for r_idx, tr in enumerate(trs):
                trPr = tr.find(qn('w:trPr'))
                if trPr is None:
                    trPr = OxmlElement('w:trPr')
                    tr.insert(0, trPr)
                existing_hdr = trPr.find(qn('w:tblHeader'))
                if r_idx == 0:
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

            temp_md_path = os.path.join(tempfile.gettempdir(), f"temp_{uuid.uuid4().hex}.md")
            with open(temp_md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)

            # Convert MD (including raw HTML tables) directly to DOCX
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
