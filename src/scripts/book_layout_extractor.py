import fitz
import json
import os

def process_book_vector_pdf(pdf_path, output_dir, output_stem=None, style_mapping="{}", progress_callback=None):
    if progress_callback:
        progress_callback(20, "[INFO] 正在使用 PyMuPDF 讀取文件...")
    
    doc = fitz.open(pdf_path)
    text_content = []
    total_pages = len(doc)
    
    for i, page in enumerate(doc):
        text_content.append(page.get_text("text"))
        if progress_callback and i % max(1, (total_pages // 10)) == 0:
            progress_callback(20 + int(70 * (i / total_pages)), f"[INFO] 正在提取文字: {i+1}/{total_pages} 頁")
            
    doc.close()
    
    full_text = "\n\n".join(text_content)
    
    if output_stem is None:
        output_stem = os.path.splitext(os.path.basename(pdf_path))[0]
        
    os.makedirs(output_dir, exist_ok=True)
    out_md_path = os.path.join(output_dir, f"{output_stem}.md")
    
    with open(out_md_path, "w", encoding="utf-8") as f:
        f.write(full_text)
        
    audit_data = {
        "footnotes_matched": 0,
        "footnotes_fallback": 0,
        "pages_processed": total_pages,
        "characters_extracted": len(full_text)
    }
    
    if progress_callback:
        progress_callback(90, "[INFO] 文字提取完成，正在儲存文件...")
        
    return out_md_path, audit_data
