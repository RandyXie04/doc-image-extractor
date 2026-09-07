with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# The string in the file actually contains a literal newline right after `.replace('`
bad_str = "right_text = page.get_text(\"text\", clip=right_rect).strip().replace('\n', '')"
good_str = "right_text = page.get_text(\"text\", clip=right_rect).strip().replace('\\n', '')"
content = content.replace(bad_str, good_str)

# Replace import fitz with import pymupdf as fitz
content = content.replace('import fitz  # PyMuPDF', 'import pymupdf as fitz  # PyMuPDF')
content = content.replace('import fitz, cv2, numpy as np, os, re', 'import pymupdf as fitz, cv2, numpy as np, os, re')

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed syntax error and fitz import warning.')
