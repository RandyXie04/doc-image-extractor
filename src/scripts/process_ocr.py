import os
import glob
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

try:
    from rapid_doc import RapidDoc
except ImportError:
    print("rapid_doc not installed yet.")
    RapidDoc = None

def main():
    if not RapidDoc:
        print("RapidDoc is not available.")
        return
        
    engine = RapidDoc()
    
    input_dir = os.path.join('data', 'database_text')
    output_dir = os.path.join('data', '03_output')
    os.makedirs(output_dir, exist_ok=True)
    
    pdf_files = glob.glob(os.path.join(input_dir, 'OCR*.pdf'))
    print(f"Found {len(pdf_files)} PDF files to process.")
    
    for pdf_path in pdf_files:
        print(f"Processing: {pdf_path}")
        try:
            # RapidDoc API: returns tuple (markdown_content, elapsed_time) or similar in some versions, 
            # or a single result. We handle safely.
            res = engine(pdf_path)
            
            md_content = ""
            if hasattr(res, 'markdown'):
                md_content = res.markdown
            elif isinstance(res, tuple) and len(res) >= 1:
                md_content = res[0].markdown if hasattr(res[0], 'markdown') else str(res[0])
            elif isinstance(res, str):
                md_content = res
            else:
                md_content = str(res)
                
            out_name = Path(pdf_path).stem + ".md"
            out_path = os.path.join(output_dir, out_name)
            
            with open(out_path, 'w', encoding='utf-8') as out_f:
                out_f.write(md_content)
                
            print(f"Saved MD to {out_path}")
        except Exception as e:
            print(f"Error processing {pdf_path}: {e}")

if __name__ == '__main__':
    main()
