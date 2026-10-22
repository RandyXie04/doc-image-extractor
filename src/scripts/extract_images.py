# -*- coding: utf-8 -*-
"""
文件圖片無損提取核心模組 (DOCX / PDF)
支援自 Word (.docx) 與 PDF (.pdf) 文件中批量無損提取內嵌圖片，
支援印刷墨水色彩校正、可選灰階轉換，並封裝打包為 ZIP 檔案。
"""

import io
import os
import posixpath
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import List, Optional, Set, Tuple

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


def convert_to_grayscale_helper(img: Image.Image, ext: str = ".png") -> Image.Image:
    """
    將圖片轉為灰階，若含有透明度 (Alpha 通道)：
    - 若輸出格式支援透明度 (.png, .webp, .tif, .tiff)，保留 Alpha 通道 (LA 模式)，
      並清理完全透明像素 (A==0) 的亮度為純白 (255)，避免不支援 Alpha 的檢視器或解碼器顯示為黑底。
    - 若輸出格式不支援透明度 (.jpg, .jpeg, .bmp)，先將圖片與純白底色合成，
      再轉為灰階 L 模式，避免透明區域填充為黑色。
    若無透明度，直接轉為 L 模式。
    """
    ext = ext.lower()
    has_alpha = (
        img.mode in ("RGBA", "LA", "PA") or
        (img.mode == "P" and "transparency" in img.info) or
        ("A" in img.getbands())
    )
    supports_alpha = ext in {".png", ".webp", ".tif", ".tiff"}

    if has_alpha:
        if supports_alpha:
            if img.mode != "RGBA":
                rgba = img.convert("RGBA")
            else:
                rgba = img
            r, g, b, a = rgba.split()
            gray = Image.merge("RGB", (r, g, b)).convert("L")
            # 完全透明處 (a == 0) 底色設為純白 (255)，避免 Alpha 被忽略時顯示為黑底
            white = Image.new("L", img.size, 255)
            mask_transparent = a.point(lambda p: 255 if p == 0 else 0)
            gray_cleaned = Image.composite(white, gray, mask_transparent)
            return Image.merge("LA", (gray_cleaned, a))
        else:
            # 不支援透明度的格式，先與純白背景合成
            if img.mode != "RGBA":
                rgba = img.convert("RGBA")
            else:
                rgba = img
            white_bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            composited = Image.alpha_composite(white_bg, rgba)
            return composited.convert("L")
    else:
        return img.convert("L")


def get_active_docx_media_entries(z: zipfile.ZipFile, duplicate_policy: str = "every_occurrence") -> List[str]:
    """
    從 Word (.docx) ZIP 結構中解析所有被實際引用的圖片檔案路徑。
    Word 在使用者刪除圖片後，往往不會自 word/media/ 目錄物理刪除檔案；
    本函式透過解析 document.xml、頁首、頁尾、註腳等活躍 XML 部件及其 .rels 關聯，
    僅提取正文中真正被引用的圖片，排除已刪除的孤立圖片。

    支援 duplicate_policy:
      - "every_occurrence": 提取文檔中每一次出現的圖片（包含在不同段落/位置重複引用的相同圖檔，依出現順序保留）。
      - "unique": 針對同一媒體檔案僅保留第一份引用。
    回傳按文件出現順序排列的 ZIP 內路徑列表 (例: ['word/media/image1.png', ...])。
    """
    namelist = set(z.namelist())
    active_images: List[str] = []
    seen: Set[str] = set()

    # 主要正文優先，隨後為頁首、頁尾、註腳、附註、留言等
    doc_parts: List[str] = []
    if "word/document.xml" in namelist:
        doc_parts.append("word/document.xml")

    other_parts: List[str] = []
    for name in sorted(namelist):
        if name == "word/document.xml":
            continue
        if name.startswith("word/") and name.endswith(".xml") and "/_rels/" not in name:
            basename = posixpath.basename(name)
            # 排除非內容/版面結構的 XML 部件
            if not basename.startswith(("styles", "settings", "webSettings", "fontTable", "theme", "numbering")):
                other_parts.append(name)

    all_parts = doc_parts + other_parts
    parsed_any_xml = False

    for part_name in all_parts:
        rels_name = posixpath.join(
            posixpath.dirname(part_name),
            "_rels",
            posixpath.basename(part_name) + ".rels"
        )
        if rels_name not in namelist:
            continue

        try:
            rels_root = ET.fromstring(z.read(rels_name))
        except Exception:
            continue

        rel_map = {}
        for rel in rels_root.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
            r_id = rel.get("Id")
            target = rel.get("Target")
            if not r_id or not target:
                continue

            if target.startswith("/"):
                resolved = target.lstrip("/")
            else:
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(part_name), target))

            ext = posixpath.splitext(resolved)[1].lower()
            if ext in IMAGE_EXTENSIONS and resolved in namelist:
                rel_map[r_id] = resolved

        if not rel_map:
            continue

        try:
            part_root = ET.fromstring(z.read(part_name))
            parsed_any_xml = True
        except Exception:
            continue

        # MCE (Markup Compatibility and Extensibility) 規範：
        # 若 AlternateContent 中已有 Choice，則 Fallback 僅供舊版相容顯示用之重複備援，應移除以避免單一圖片被重複計數
        for ac in part_root.findall(".//{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent"):
            choice = ac.find("{http://schemas.openxmlformats.org/markup-compatibility/2006}Choice")
            fallback = ac.find("{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback")
            if choice is not None and fallback is not None:
                ac.remove(fallback)

        for elem in part_root.iter():
            for attr_val in elem.attrib.values():
                if attr_val in rel_map:
                    img_path = rel_map[attr_val]
                    if duplicate_policy == "unique":
                        if img_path not in seen:
                            seen.add(img_path)
                            active_images.append(img_path)
                    else:
                        active_images.append(img_path)
                    break

    # 降級保護：若未成功解析任何 XML 或非標準結構，但 word/media/ 存在，才作為最後備用回退
    if not parsed_any_xml and not active_images:
        media_entries = [
            name for name in z.namelist()
            if name.lower().startswith("word/media/") and not name.endswith("/")
        ]
        return sorted(media_entries)

    return active_images


def extract_from_docx(
    docx_path: str,
    output_dir: str,
    to_grayscale: bool = False,
    duplicate_policy: str = "every_occurrence"
) -> int:
    """
    從 Word (.docx) 文件中無損提取所有內嵌圖片。
    .docx 本質為 OpenXML ZIP 封裝，透過解析正文與關聯表過濾已被刪除的孤立圖片。
    支援 duplicate_policy: "unique" | "every_occurrence" (預設)。
    """
    if not zipfile.is_zipfile(docx_path):
        raise ValueError(f"檔案不是有效的 DOCX 或 ZIP 格式: {docx_path}")

    os.makedirs(output_dir, exist_ok=True)
    count = 0

    with zipfile.ZipFile(docx_path, "r") as z:
        media_entries = get_active_docx_media_entries(z, duplicate_policy=duplicate_policy)

        for entry in media_entries:
            ext = os.path.splitext(entry)[1].lower()

            if ext not in IMAGE_EXTENSIONS:
                continue

            count += 1
            filename = f"image{count}{ext}"
            save_path = os.path.join(output_dir, filename)

            # 若目錄已存在同名檔案，遞增計數避免覆蓋
            while os.path.exists(save_path):
                count += 1
                filename = f"image{count}{ext}"
                save_path = os.path.join(output_dir, filename)

            raw_data = z.read(entry)

            if to_grayscale and ext in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}:
                try:
                    img = Image.open(io.BytesIO(raw_data))
                    img = convert_to_grayscale_helper(img, ext)
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

    return count


def extract_from_pdf(pdf_path: str, output_dir: str, to_grayscale: bool = False, duplicate_policy: str = "every_occurrence", progress_callback=None) -> int:
    """
    從 PDF (.pdf) 文件中無損提取所有圖片，支援進階的遮罩(Mask)解析、去重複與透明度合成。
    支援 duplicate_policy: "unique" | "every_occurrence"。
    """
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    count = 0
    seen_xrefs = set()
    MIN_WIDTH = 50
    MIN_HEIGHT = 50

    try:
        total_pages = len(doc)
        for page_index in range(total_pages):
            if progress_callback:
                progress_callback(85, f"[INFO] 正在掃描並提取圖片 (第 {page_index+1}/{total_pages} 頁)...")
                
            page = doc[page_index]
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref = img_info[0]

                if duplicate_policy == "unique" and xref in seen_xrefs:
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
                    if is_mask or pix.colorspace is None or (is_inverted_decode and pix.n <= 2):
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

                        if to_grayscale:
                            final_img = convert_to_grayscale_helper(final_img, ".tif")

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
                            # PNG 不支援 CMYK/DeviceN，若非 RGB/Gray 需先轉 RGB 才能合成透明度
                            if not pix.colorspace or pix.colorspace.name not in ("DeviceRGB", "DeviceGray"):
                                pix = fitz.Pixmap(fitz.csRGB, pix)

                            pix_combined = fitz.Pixmap(pix, pix_mask)
                            
                            if to_grayscale:
                                img = Image.frombytes("RGBA", [pix_combined.width, pix_combined.height], pix_combined.samples)
                                img = convert_to_grayscale_helper(img, ".png")
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
                        # PNG 格式不支援 CMYK/DeviceN，若非 RGB/Gray 需轉為 RGB
                        if not pix.colorspace or pix.colorspace.name not in ("DeviceRGB", "DeviceGray"):
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                            
                        if to_grayscale:
                            mode = "RGBA" if pix.alpha else "RGB"
                            img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                            img = convert_to_grayscale_helper(img, ".png")
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
    to_grayscale: bool = False,
    duplicate_policy: str = "every_occurrence"
) -> Tuple[int, str]:
    """
    整合處理函式：自動判斷副檔名執行提取並封裝成 ZIP。
    回傳 (提取數量, zip路徑)
    """
    ext = Path(file_path).suffix.lower()
    os.makedirs(temp_dir, exist_ok=True)

    if ext == ".docx":
        count = extract_from_docx(file_path, temp_dir, to_grayscale=to_grayscale, duplicate_policy=duplicate_policy)
    elif ext == ".pdf":
        count = extract_from_pdf(file_path, temp_dir, to_grayscale=to_grayscale, duplicate_policy=duplicate_policy)
    else:
        raise ValueError(f"不支援的檔案格式: {ext} (僅支援 .docx 與 .pdf)")

    if count > 0:
        package_to_zip(temp_dir, output_zip_path)

    return count, output_zip_path
