import re

with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update _process_single_page to return a dictionary and handle exceptions
old_func_def = 'def _process_single_page(args):'
new_func_def = 'def _process_single_page(args):\n    import traceback'
content = content.replace(old_func_def, new_func_def)

# Find the start of the `doc = fitz.open(input_pdf)`
old_try_block = '''    doc = fitz.open(input_pdf)
    try:'''
new_try_block = '''    try:
        doc = fitz.open(input_pdf)
    except Exception as e:
        return {"status": "error", "files": [], "error": f"無法開啟 PDF: {str(e)}"}
        
    try:'''
content = content.replace(old_try_block, new_try_block)

# Fix the returns inside _process_single_page
content = content.replace('return generated_files', 'return {"status": "success", "files": generated_files}')

content = re.sub(r'finally:\n\s*doc\.close\(\)\n\s*return \{"status": "success", "files": generated_files\}',
                 r'except Exception as e:\n        return {"status": "error", "files": generated_files, "error": str(e)}\n    finally:\n        doc.close()\n        \n    return {"status": "success", "files": generated_files}', 
                 content)

# Update the loop in extract_formulas
old_loop = '''                for idx_offset, result_files in enumerate(pool.imap(_process_single_page, tasks)):
                    if progress_callback:
                        progress_callback(idx_offset + 1, total_to_process, f"提取公式 (P{start_page_idx + idx_offset + 1})")
                    if result_files:
                        generated_files.extend(result_files)
                        count += len(result_files)
                        log_fn(f"  [P{start_page_idx + idx_offset + 1:03d}] AI 找到 {len(result_files)} 個獨立公式區塊")
                    else:
                        skipped_pages += 1'''

new_loop = '''                for idx_offset, res in enumerate(pool.imap(_process_single_page, tasks)):
                    current_p = start_page_idx + idx_offset + 1
                    if progress_callback:
                        progress_callback(idx_offset + 1, total_to_process, f"提取公式 (P{current_p})")
                        
                    if res.get("status") == "error":
                        log_fn(f"[ERROR] 第 {current_p} 頁處理發生例外：{res.get('error')}")
                        skipped_pages += 1
                        continue
                        
                    result_files = res.get("files", [])
                    if result_files:
                        generated_files.extend(result_files)
                        count += len(result_files)
                        log_fn(f"  [P{current_p:03d}] AI 找到 {len(result_files)} 個獨立公式區塊")
                    else:
                        skipped_pages += 1'''

content = content.replace(old_loop, new_loop)

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated return mechanism and logging.')
