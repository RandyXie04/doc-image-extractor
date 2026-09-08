# -*- coding: utf-8 -*-
"""
文件圖片無損提取核心模組 (DOCX / PDF)
支援自 Word (.docx) 與 PDF (.pdf) 文件中批量無損提取內嵌圖片，
支援印刷墨水色彩校正、可選灰階轉換，並封裝打包為 ZIP 檔案。
"""

import io
import os
import sys
import zipfile
from pathlib import Path
from typing import Optional, Tuple

import pymupdf as fitz
from PIL import Image, ImageOps

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
    ".emf", ".wmf", ".svg", ".webp"
}


def extract_from_docx(docx_path: str, output_dir: str, to_grayscale: bool = False) -> int:
    """
    從 Word (.docx) 文件中無損提取所有內嵌圖片。
    .docx 本質為 OpenXML ZIP 封裝，圖片存儲於 word/media/ 目錄。
    """
    if not zipfile.is_zipfile(docx_path):
        raise ValueError(f"檔案不是有效的 DOCX 或 ZIP 格式: {docx_path}")

    os.makedirs(output_dir, exist_ok=True)
    count = 0

    with zipfile.ZipFile(docx_path, "r") as z:
        media_entries = [
            name for name in z.namelist()
            if name.lower().startswith("word/media/") and not name.endswith("/")
        ]

        for entry in sorted(media_entries):
            filename = os.path.basename(entry)
            ext = os.path.splitext(filename)[1].lower()

            if ext not in IMAGE_EXTENSIONS:
                continue

            save_path = os.path.join(output_dir, filename)

            # 防檔名衝突重複命名
            if os.path.exists(save_path):
                base, extension = os.path.splitext(filename)
                i = 2
                while os.path.exists(save_path):
                    save_path = os.path.join(output_dir, f"{base}_{i}{extension}")
                    i += 1

            raw_data = z.read(entry)

            if to_grayscale and ext in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}:
                try:
                    img = Image.open(io.BytesIO(raw_data))
                    img = img.convert("L")
                    save_format = "PNG" if ext == ".png" else ("JPEG" if ext in {".jpg", ".jpeg"} else None)
                    if save_format:
                        img.save(save_path, format=save_format)
                    else:
                        img.save(save_path)
                except Exception:
                    with open(save_path, "wb") as f:
                        f.write(raw_data)
            else:
                with open(save_path, "wb") as f:
                    f.write(raw_data)

            count += 1

    return count


def extract_from_pdf(pdf_path: str, output_dir: str, to_grayscale: bool = False) -> int:
    """
    從 PDF (.pdf) 文件中無損提取所有圖片，自動校正 DeviceN/CMYK 印刷墨水反相，統一輸出高品質 PNG。
    """
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    count = 0

    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                cs_name = img_info[5]
                alt_cs = img_info[6]

                try:
                    base_image = doc.extract_image(xref)
                    if not base_image or not base_image.get("image"):
                        continue

                    raw_bytes = base_image["image"]
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)

                    # 過濾無效極小裝飾線或微小噪點
                    if width < 10 or height < 10:
                        continue

                    img = Image.open(io.BytesIO(raw_bytes))

                    # 印刷色空間反相校正
                    if cs_name == "DeviceN" or alt_cs == "DeviceCMYK" or img.mode == "CMYK":
                        if img.mode in ("L", "1"):
                            img = ImageOps.invert(img.convert("L"))
                        elif img.mode == "CMYK":
                            img = ImageOps.invert(img.convert("RGB"))
                        else:
                            img = ImageOps.invert(img.convert("L"))
                    else:
                        if img.mode in ("P", "PA", "LA", "RGBA"):
                            img = img.convert("RGBA" if "A" in img.mode else "RGB")
                        elif img.mode not in ("RGB", "L"):
                            img = img.convert("RGB")

                    if to_grayscale:
                        img = img.convert("L")

                    filename = f"page{page_index + 1:04d}_img{img_index + 1:03d}.png"
                    save_path = os.path.join(output_dir, filename)
                    img.save(save_path, format="PNG")
                    count += 1

                except Exception as e:
                    print(f"[Warning] 提取第 {page_index + 1} 頁圖片 {img_index + 1} 失敗: {e}")
                    continue
    finally:
        doc.close()

    return count


def package_to_zip(folder_path: str, zip_output_path: str) -> str:
    """
    將指定目錄下的所有檔案打包成 ZIP 壓縮檔。
    """
    os.makedirs(os.path.dirname(os.path.abspath(zip_output_path)), exist_ok=True)
    with zipfile.ZipFile(zip_output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(folder_path):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, folder_path)
                zf.write(full_path, rel_path)
    return zip_output_path


def process_document_images(
    file_path: str,
    output_zip_path: str,
    temp_dir: str,
    to_grayscale: bool = False
) -> Tuple[int, str]:
    """
    整合處理函式：自動判斷副檔名執行提取並封裝成 ZIP。
    回傳 (提取數量, zip路徑)
    """
    ext = Path(file_path).suffix.lower()
    os.makedirs(temp_dir, exist_ok=True)

    if ext == ".docx":
        count = extract_from_docx(file_path, temp_dir, to_grayscale=to_grayscale)
    elif ext == ".pdf":
        count = extract_from_pdf(file_path, temp_dir, to_grayscale=to_grayscale)
    else:
        raise ValueError(f"不支援的檔案格式: {ext} (僅支援 .docx 與 .pdf)")

    if count > 0:
        package_to_zip(temp_dir, output_zip_path)

    return count, output_zip_path
