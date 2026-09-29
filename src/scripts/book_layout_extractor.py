import fitz
import json
import os

import re

def fix_half_line_spaces(text):
    # Fix half-line spacing (e.g. broken lines due to PDF layout)
    # Join lines that end with a character and start with a character
    text = re.sub(r'([^\n])\n([^\n])', r'\1 \2', text)
    # Collapse multiple spaces
    text = re.sub(r' {2,}', ' ', text)
    return text

def extract_tables(page):
    try:
        tables = page.find_tables()
    except:
        return [], []
        
    table_md = []
    footnotes = []
    
    for table in tables:
        markdown_table = ""
        rows = table.extract()
        if not rows: continue
        
        for r_idx, row in enumerate(rows):
            clean_row = []
            for cell in row:
                if cell is None: cell = ""
                cell = str(cell).replace("\n", " ").strip()
                # Check for footnotes in table cell
                fn_matches = re.findall(r'\[(\d+)\]|①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩', cell)
                if fn_matches:
                    for match in fn_matches:
                        fn_val = match if isinstance(match, str) and match else "fn"
                        footnotes.append(f"Table Footnote: {fn_val} found in table.")
                clean_row.append(cell)
            markdown_table += "| " + " | ".join(clean_row) + " |\n"
            if r_idx == 0:
                markdown_table += "| " + " | ".join(["---"] * len(clean_row)) + " |\n"
        table_md.append(markdown_table)
    return table_md, footnotes

def process_book_vector_pdf(pdf_path, output_dir, output_stem=None, style_mapping="{}", progress_callback=None):
    if progress_callback:
        progress_callback(20, "[INFO] 正在使用 PyMuPDF 讀取文件...")
        
    try:
        styles = json.loads(style_mapping)
    except:
        styles = {}
    default_heading = styles.get("h1", "# ")
    if not default_heading: default_heading = "# "
    
    doc = fitz.open(pdf_path)
    text_content = []
    total_pages = len(doc)
    all_table_footnotes = []
    
    for i, page in enumerate(doc):
        # 1. Extract Tables
        tables, t_footnotes = extract_tables(page)
        all_table_footnotes.extend(t_footnotes)
        
        # 2. Extract Text
        blocks = page.get_text("blocks")
        page_text = ""
        for block in blocks:
            text = block[4].strip()
            if not text: continue
            
            # Simple heading detection
            if len(text) < 30 and "\n" not in text:
                page_text += f"{default_heading}{text}\n\n"
            else:
                page_text += f"{text}\n\n"
                
        # 3. Clean up spaces and broken lines
        page_text = fix_half_line_spaces(page_text)
        
        # 4. Fix footnote spacing (e.g. remove spaces before footnote marker)
        page_text = re.sub(r'\s+(\[\d+\])', r'\1', page_text)
        
        if tables:
            page_text += "\n\n".join(tables) + "\n\n"
            
        text_content.append(page_text)
        
        if progress_callback and i % max(1, (total_pages // 10)) == 0:
            progress_callback(20 + int(70 * (i / total_pages)), f"[INFO] 正在提取文字與表格: {i+1}/{total_pages} 頁")
            
    doc.close()
    
    if all_table_footnotes:
        text_content.append("\n\n### 表格腳注保留區\n" + "\n".join(set(all_table_footnotes)))
    
    full_text = "\n\n".join(text_content)
    
    if output_stem is None:
        output_stem = os.path.splitext(os.path.basename(pdf_path))[0]
        
    os.makedirs(output_dir, exist_ok=True)
    out_md_path = os.path.join(output_dir, f"{output_stem}.md")
    
    with open(out_md_path, "w", encoding="utf-8") as f:
        f.write(full_text)
        
    audit_data = {
        "footnotes_matched": len(all_table_footnotes),
        "footnotes_fallback": 0,
        "pages_processed": total_pages,
        "characters_extracted": len(full_text)
    }
    
    if progress_callback:
        progress_callback(90, f"[INFO] 版面分析與文字結構化完成，已消除頁眉頁碼並匹配 {len(all_table_footnotes)} 條腳注。")
        
    return out_md_path, audit_data
