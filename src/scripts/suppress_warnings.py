import re

with open('src/core_agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

suppress_code = '''
import warnings
warnings.filterwarnings("ignore", message=".*The `fitz` API is deprecated.*")
'''

content = content.replace('import pymupdf as fitz  # PyMuPDF', suppress_code + 'import pymupdf as fitz  # PyMuPDF')

with open('src/core_agent.py', 'w', encoding='utf-8') as f:
    f.write(content)

with open('src/web/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('import pymupdf as fitz', suppress_code + 'import pymupdf as fitz')

with open('src/web/app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Warning suppressed.")
