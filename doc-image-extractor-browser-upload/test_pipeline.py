from pathlib import Path
import io
import zipfile

import fitz
from PIL import Image, ImageDraw

from app import extract_images_from_docx, extract_images_from_pdf, make_zip, ExtractionResult

ROOT = Path(__file__).parent
TEST_DIR = ROOT / "test_assets"
TEST_DIR.mkdir(exist_ok=True)

img = Image.new("RGB", (80, 60), (20, 80, 160))
draw = ImageDraw.Draw(img)
draw.rectangle((10, 10, 70, 50), fill=(230, 190, 40))
png_bytes = io.BytesIO()
img.save(png_bytes, format="PNG")

pdf_path = TEST_DIR / "sample.pdf"
doc = fitz.open()
page = doc.new_page(width=240, height=180)
page.insert_image(fitz.Rect(20, 20, 180, 140), stream=png_bytes.getvalue())
doc.save(pdf_path)
doc.close()

docx_path = TEST_DIR / "sample.docx"
with zipfile.ZipFile(docx_path, "w") as archive:
    archive.writestr("[Content_Types].xml", "<?xml version='1.0'?><Types></Types>")
    archive.writestr("word/media/image1.png", png_bytes.getvalue())
    archive.writestr("word/media/not-image.bin", b"not an image")

pdf_output = TEST_DIR / "pdf_output"
docx_output = TEST_DIR / "docx_output"
pdf_images, pdf_warnings = extract_images_from_pdf(pdf_path, pdf_output)
docx_images, docx_warnings = extract_images_from_docx(docx_path, docx_output)
assert len(pdf_images) == 1, (len(pdf_images), pdf_warnings)
assert pdf_images[0].path.suffix == ".png"
assert len(docx_images) == 1, (len(docx_images), docx_warnings)
assert docx_images[0].path.read_bytes() == png_bytes.getvalue()
archive = make_zip([
    ExtractionResult(pdf_path.name, "PDF", pdf_images, pdf_warnings),
    ExtractionResult(docx_path.name, "DOCX", docx_images, docx_warnings),
])
with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
    names = sorted(zip_file.namelist())
    assert names == ["sample/ image1.png"] or names, names
    assert any(name.startswith("sample/") for name in names), names

print(f"PDF images: {len(pdf_images)}; DOCX images: {len(docx_images)}; ZIP bytes: {len(archive)}")
print("Pipeline test passed")
