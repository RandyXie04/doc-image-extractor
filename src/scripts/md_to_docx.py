import os
import glob
import sys
import argparse
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
# pyrefly: ignore [missing-import]
import pypandoc

# Configure pypandoc to use the bundled pandoc.exe if available
if getattr(sys, 'frozen', False):
    # Running in a PyInstaller bundle
    bundle_dir = Path(sys._MEIPASS)
else:
    # Running in normal Python environment
    bundle_dir = Path(__file__).parent.parent.parent.resolve()

bundled_pandoc = bundle_dir / 'bin' / 'pandoc.exe'
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
    args = parser.parse_args()

    input_dir = os.path.join('data', '03_output')
    template_path = os.path.join('data', 'database_text', 'template.docx')
    pdf_dir = os.path.join('data', 'database_text')
    
    if not os.path.exists(template_path):
        print(f"Error: Template not found at {template_path}")
        return
        
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
            
            # Escape "1. " to "1\. " to prevent Word auto-numbering
            md_content = re.sub(r'(?m)^(\s*\d+)\.\s', r'\1\\. ', md_content)
            
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
            pypandoc.convert_text(
                html,
                'docx',
                format='html',
                outputfile=out_path,
                extra_args=[f'--reference-doc={template_path}']
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
