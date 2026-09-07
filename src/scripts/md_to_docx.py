import os
import glob
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
import pypandoc

try:
    pypandoc.get_pandoc_version()
except OSError:
    print("Downloading pandoc...")
    pypandoc.download_pandoc()

def main():
    input_dir = os.path.join('data', '03_output')
    template_path = os.path.join('data', 'database_text', 'template.docx')
    
    if not os.path.exists(template_path):
        print(f"Error: Template not found at {template_path}")
        return
        
    md_files = glob.glob(os.path.join(input_dir, '*.md'))
    print(f"Found {len(md_files)} Markdown files to convert.")
    
    for md_path in md_files:
        print(f"Converting: {md_path}")
        try:
            out_name = Path(md_path).stem + ".docx"
            out_path = os.path.join(input_dir, out_name)
            
            # Step 1: Convert MD (including raw HTML tables) to intermediate HTML
            html = pypandoc.convert_file(
                md_path,
                'html',
                format='markdown+raw_html+tex_math_dollars',
                extra_args=['--math-method=mathjax']
            )

            # Step 2: Convert HTML to DOCX with reference doc (native table generation)
            pypandoc.convert_text(
                html,
                'docx',
                format='html',
                outputfile=out_path,
                extra_args=[f'--reference-doc={template_path}']
            )
            print(f"Saved DOCX to {out_path}")
        except Exception as e:
            print(f"Error converting {md_path}: {e}")

if __name__ == '__main__':
    main()
