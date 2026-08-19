from pathlib import Path
import zipfile

import fitz

import app

ROOT = Path(__file__).parent
TEST_DIR = ROOT / "p0_test_assets"
TEST_DIR.mkdir(exist_ok=True)

pdf_path = TEST_DIR / "many_pages.pdf"
doc = fitz.open()
for _ in range(3):
    doc.new_page()
doc.save(pdf_path)
doc.close()
old_page_limit = app.MAX_PDF_PAGES
app.MAX_PDF_PAGES = 2
_, warnings = app.extract_images_from_pdf(pdf_path, TEST_DIR / "pdf_output")
app.MAX_PDF_PAGES = old_page_limit
assert any("只處理前 2 頁" in warning for warning in warnings), warnings

docx_path = TEST_DIR / "many_media.docx"
with zipfile.ZipFile(docx_path, "w") as archive:
    for index in range(1001):
        archive.writestr(f"word/media/image{index:04d}.png", b"x")
old_media_limit = app.MAX_DOCX_MEDIA_FILES
app.MAX_DOCX_MEDIA_FILES = 1000
images, warnings = app.extract_images_from_docx(docx_path, TEST_DIR / "docx_output")
app.MAX_DOCX_MEDIA_FILES = old_media_limit
assert len(images) == 1000, len(images)
assert any("超過 1000 個" in warning for warning in warnings), warnings

print("P0 resource-limit test passed")
