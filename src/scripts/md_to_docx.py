import os
import glob
import sys
import argparse
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
# pyrefly: ignore [missing-import]
import pypandoc

# Configure pypandoc to use the bundled pandoc.exe if available
try:
    from src.utils.path_helper import get_bundled_pandoc, get_data_dir, get_config_dir
except ImportError:
    import sys
    from pathlib import Path
    _fallback_root = Path(__file__).parent.parent.parent.resolve()
    if str(_fallback_root) not in sys.path:
        sys.path.insert(0, str(_fallback_root))
    from src.utils.path_helper import get_bundled_pandoc, get_data_dir, get_config_dir

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

def main():
    parser = argparse.ArgumentParser(description="Convert Markdown to Word Document.")
    parser.add_argument('--files', '--target', nargs='+', help="Specific markdown files to convert")
    parser.add_argument('--template', help="Explicit path to a .docx reference template (overrides auto-detect)")
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
    # 4. config dir template.docx
    # 5. script dir template.docx
    if args.template and Path(args.template).exists():
        template_path = args.template
        print(f"Using template (from --template arg): {template_path}")
    else:
        _template_candidates = [
            _data_dir / 'database_text' / 'custom_templates' / 'user_template.docx',  # user uploaded
            _data_dir / 'database_text' / 'template.docx',
            _config_dir / 'template.docx',
            _script_dir / 'template.docx',
        ]
        template_path = None
        for _candidate in _template_candidates:
            if _candidate.exists():
                template_path = str(_candidate)
                print(f"Using template: {template_path}")
                break

        if template_path is None:
            _searched = ', '.join(str(c) for c in _template_candidates)
            print(f"Warning: template.docx not found (searched: {_searched}). "
                  "Converting without reference doc — styles may differ.")
        
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
    import re
    import tempfile
    import json
    
    # 讀取人工判定方正亂碼字庫
    correction_dict_path = _data_dir / 'Json' / 'founder_correction_dict.json'
    founder_corrections = {}
    if correction_dict_path.exists():
        try:
            with open(correction_dict_path, 'r', encoding='utf-8') as f:
                founder_corrections = json.load(f)
            print(f"載入方正亂碼人工判定字庫，共 {len(founder_corrections)} 筆對應。")
        except Exception as e:
            print(f"[Warning] 讀取 founder_correction_dict.json 失敗: {e}")
            
    # 準備紀錄新發現的可疑亂碼
    suspicious_chars_file = _data_dir / '03_output' / 'suspicious_founder_chars.json'
    suspicious_chars_set = set()
    if suspicious_chars_file.exists():
        try:
            with open(suspicious_chars_file, 'r', encoding='utf-8') as f:
                suspicious_chars_set = set(json.load(f))
        except Exception:
            pass
    
    for md_path in md_files:
        print(f"Converting: {md_path}")
        temp_md_path = None
        try:
            out_name = Path(md_path).stem + ".docx"
            out_dir = os.path.dirname(md_path) or input_dir
            out_path = os.path.join(out_dir, out_name)
            
            # Step 0: Read MD, escape numbered lists, save to isolated UUID temp file
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
                
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
                try:
                    from founder_tools.fix_founder_fonts import clean_founder_text
                    md_content = clean_founder_text(md_content)
                except ImportError:
                    pass
            
            # 偵測並記錄可疑的未登錄亂碼 (擴展偵測範圍)
            # PUA 區 + 彝文音節區 + CJK 相容區 + 替換字元 + 零寬字元
            suspicious_pattern = re.compile(
                r'[\uE000-\uF8FF'        # PUA 私用區
                r'\uFFFD'                 # 替換字元 (OCR 無法辨識)
                r'\uA000-\uA4CF'          # 彝文音節區 (方正 GBK 映射殘留)
                r'\uF900-\uFAFF'          # CJK 相容表意文字區
                r'\u200B-\u200D'           # 零寬字元
                r'\uFEFF'                 # BOM 標記
                r']'
            )
            found_suspicious_chars = suspicious_pattern.findall(md_content)
            if found_suspicious_chars:
                suspicious_chars_set.update(found_suspicious_chars)
                
                # 建立帶上下文的詳細記錄
                detailed_findings = []
                for m in suspicious_pattern.finditer(md_content):
                    ch = m.group(0)
                    pos = m.start()
                    ctx_start = max(0, pos - 15)
                    ctx_end = min(len(md_content), pos + 16)
                    context = md_content[ctx_start:ctx_end].replace('\n', '↵')
                    marker_pos = pos - ctx_start
                    context_marked = context[:marker_pos] + f"【{ch}】" + context[marker_pos + 1:]
                    detailed_findings.append({
                        "char": ch,
                        "unicode": f"U+{ord(ch):04X}",
                        "context": context_marked
                    })
                
                try:
                    # 寫入簡易字元清單
                    with open(suspicious_chars_file, 'w', encoding='utf-8') as f:
                        json.dump(list(suspicious_chars_set), f, ensure_ascii=False, indent=2)
                    # 寫入詳細上下文報告
                    detailed_file = _data_dir / '03_output' / 'suspicious_founder_chars_detailed.json'
                    with open(detailed_file, 'w', encoding='utf-8') as f:
                        json.dump(detailed_findings, f, ensure_ascii=False, indent=2)
                    print(f"[REVIEW] ⚠️ 偵測到 {len(found_suspicious_chars)} 處可疑字元，詳細報告：{detailed_file}")
                except Exception as e:
                    print(f"[Warning] 寫入 suspicious_founder_chars 失敗: {e}")


            
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
            md_base_dir = os.path.dirname(os.path.abspath(md_path))
            def _resolve_img_path(m):
                alt_text = m.group(1)
                img_path_raw = m.group(2)
                # 若已是絕對路徑或網路 URL，則不處理
                if os.path.isabs(img_path_raw) or img_path_raw.startswith(('http://', 'https://')):
                    return m.group(0)
                abs_img = os.path.normpath(os.path.join(md_base_dir, img_path_raw))
                if os.path.exists(abs_img):
                    # 使用正斜線以確保跨平台相容性
                    return f"![{alt_text}]({abs_img.replace(os.sep, '/')})"
                return m.group(0)
            md_content = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _resolve_img_path, md_content)

            temp_md_path = os.path.join(tempfile.gettempdir(), f"temp_{uuid.uuid4().hex}.md")
            with open(temp_md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)

            # Step 1: Convert MD (including raw HTML tables) to intermediate HTML
            html = pypandoc.convert_file(
                temp_md_path,
                'html',
                format='markdown+raw_html+tex_math_dollars',
                extra_args=['--math-method=mathjax']
            )

            # Inject Table CSS for Solid Black Borders
            table_css = "<style>table, th, td { border: 1px solid black; border-collapse: collapse; }</style>\n"
            html = table_css + html

            # Step 2: Convert HTML to DOCX with reference doc (native table generation)
            # 加入 --resource-path 確保 Pandoc 能解析圖片路徑並嵌入 Word
            pandoc_extra = []
            if template_path:
                pandoc_extra.append(f'--reference-doc={template_path}')
            pandoc_extra.append(f'--resource-path={md_base_dir}')
            pypandoc.convert_text(
                html,
                'docx',
                format='html',
                outputfile=out_path,
                extra_args=pandoc_extra
            )
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
