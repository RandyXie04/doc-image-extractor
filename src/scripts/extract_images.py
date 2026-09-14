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

# ==================== 偏好設定 ====================
# 情況 1 的背景處理模式：
#   "WHITE_BG"   : 白底黑線（實體印刷、Word/InDesign 排版最穩定）
#   "TRANSPARENT": 透明底黑線
CASE1_OUTPUT_MODE = "WHITE_BG"
# =================================================


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
    從 PDF (.pdf) 文件中無損提取所有圖片，支援進階的遮罩(Mask)解析、去重複與透明度合成。
    """
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    count = 0
    seen_xrefs = set()
    MIN_WIDTH = 50
    MIN_HEIGHT = 50

    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref = img_info[0]

                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue

                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)

                    if width < MIN_WIDTH or height < MIN_HEIGHT:
                        continue

                    smask_xref = base_image.get("smask", 0)

                    # 檢測是否為 ImageMask 或特殊解碼遮罩
                    is_mask = False
                    try:
                        is_mask = doc.xref_get_key(xref, "ImageMask")[1] == "true"
                    except Exception:
                        pass

                    decode = ""
                    try:
                        decode = doc.xref_get_key(xref, "Decode")[1]
                    except Exception:
                        pass
                    is_inverted_decode = "[1 0]" in decode or "[ 1 0 ]" in decode

                    pix = fitz.Pixmap(doc, xref)

                    # =======================================================
                    # 情況 1：ImageMask 或單色反白遮罩 ➔ 輸出 .tif (含 LZW 壓縮)
                    # =======================================================
                    if is_mask or pix.colorspace is None or is_inverted_decode:
                        img_filename = f"page_{page_index+1:04d}_xref{xref}.tif"
                        img_filepath = os.path.join(output_dir, img_filename)

                        mask_img = Image.frombytes("L", [pix.width, pix.height], pix.samples)

                        if CASE1_OUTPUT_MODE == "TRANSPARENT":
                            black_layer = Image.new("RGBA", mask_img.size, (0, 0, 0, 255))
                            transparent_bg = Image.new("RGBA", mask_img.size, (0, 0, 0, 0))
                            final_img = Image.composite(black_layer, transparent_bg, mask_img)
                        else:
                            # 反轉負片：0 變純白底，255 變純黑線
                            final_img = ImageOps.invert(mask_img)

                        if to_grayscale and final_img.mode != "L":
                            final_img = final_img.convert("L")

                        final_img.save(img_filepath, format="TIFF", compression="tiff_lzw")
                        count += 1
                        continue

                    # =======================================================
                    # 情況 2：含有獨立透明遮罩 (SMask) 的圖片 ➔ 輸出 .png
                    # =======================================================
                    if smask_xref > 0:
                        seen_xrefs.add(smask_xref)
                        img_filename = f"page_{page_index+1:04d}_xref{xref}.png"
                        img_filepath = os.path.join(output_dir, img_filename)
                        try:
                            pix_mask = fitz.Pixmap(doc, smask_xref)
                            # PNG 不支援 CMYK，若為 CMYK (n>=5) 需先轉 RGB 才能合成透明度
                            if pix.n >= 5:
                                pix = fitz.Pixmap(fitz.csRGB, pix)

                            pix_combined = fitz.Pixmap(pix, pix_mask)
                            
                            if to_grayscale:
                                img = Image.frombytes("RGBA", [pix_combined.width, pix_combined.height], pix_combined.samples)
                                img = img.convert("LA")
                                img.save(img_filepath, format="PNG")
                            else:
                                pix_combined.save(img_filepath)
                            
                            count += 1
                            continue
                        except Exception:
                            pass

                    # =======================================================
                    # 情況 3：一般常規點陣圖（無遮罩） ➔ 輸出 .png
                    # =======================================================
                    img_filename = f"page_{page_index+1:04d}_xref{xref}.png"
                    img_filepath = os.path.join(output_dir, img_filename)
                    try:
                        if pix.n >= 5:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                            
                        if to_grayscale:
                            mode = "RGBA" if pix.alpha else "RGB"
                            img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                            img = img.convert("L")
                            img.save(img_filepath, format="PNG")
                        else:
                            pix.save(img_filepath)
                        count += 1
                    except Exception:
                        # 降級保護：若 Pixmap 轉換異常，使用原始二進位流寫入
                        image_bytes = base_image.get("image")
                        image_ext = base_image.get("ext", "bin")
                        if image_bytes:
                            fallback_path = os.path.join(output_dir, f"page_{page_index+1:04d}_xref{xref}.{image_ext}")
                            with open(fallback_path, "wb") as f:
                                f.write(image_bytes)
                            count += 1

                except Exception as e:
                    print(f"[Warning] 提取第 {page_index + 1} 頁圖片 xref {xref} 失敗: {e}")
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
