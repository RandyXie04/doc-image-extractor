# -*- coding: utf-8 -*-
"""
文件圖片無損提取核心模組 (DOCX / PDF)
支援自 Word (.docx) 與 PDF (.pdf) 文件中批量無損提取內嵌圖片，
支援印刷墨水色彩校正、可選灰階轉換，並封裝打包為 ZIP 檔案。
"""

import io
import os
import posixpath
import struct
import urllib.parse
import zipfile
from src.utils.safe_xml import Element as XmlElement, fromstring as safe_xml_fromstring
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pymupdf as fitz
from PIL import Image, ImageOps

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".dib", ".tiff", ".tif",
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


_DOCX_EXCLUDED_PARTS = (
    "styles", "settings", "websettings", "fonttable", "theme", "numbering"
)
_MC_NS = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_PIXMAP_N_TO_PIL_MODE = {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}


def _resolve_docx_rel_target(
    part_norm: str,
    target: str,
    exact_name_map: Dict[str, str],
) -> Optional[str]:
    """Normalize a DOCX .rels Target path and match case-insensitively against ZIP entries."""
    target_clean = urllib.parse.unquote(target.strip().replace("\\", "/"))
    if not target_clean or target_clean.startswith("#"):
        return None

    candidates: List[str] = []
    if target_clean.startswith("/"):
        candidates.append(posixpath.normpath(target_clean.lstrip("/")))
    else:
        part_dir = posixpath.dirname(part_norm)
        candidates.append(posixpath.normpath(posixpath.join(part_dir, target_clean)))
        root_rel = posixpath.normpath(target_clean)
        while root_rel.startswith("../"):
            root_rel = root_rel[3:]
        root_rel = root_rel.lstrip("/")
        if root_rel not in candidates:
            candidates.append(root_rel)

    for candidate in candidates:
        matched = exact_name_map.get(candidate.lower())
        if matched:
            ext = posixpath.splitext(matched)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                return matched
    return None


def _subtree_has_rel(elem: XmlElement, rel_map: Dict[str, str]) -> bool:
    for node in elem.iter():
        for attr_val in node.attrib.values():
            if attr_val in rel_map:
                return True
    return False


def _decode_dib_image(raw_data: bytes) -> Optional[Image.Image]:
    """Decode headered or headerless raw Windows DIB bytes into a Pillow Image."""
    try:
        img = Image.open(io.BytesIO(raw_data))
        img.load()
        return img
    except Exception:
        pass

    try:
        from PIL import BmpImagePlugin
        img = BmpImagePlugin.DibImageFile(io.BytesIO(raw_data))
        img.load()
        return img
    except Exception:
        pass

    if len(raw_data) >= 12 and not raw_data.startswith(b"BM"):
        try:
            header_size = struct.unpack("<I", raw_data[:4])[0]
            palette_bytes = 0
            if header_size == 12:
                bit_count = struct.unpack("<H", raw_data[10:12])[0]
                if bit_count <= 8:
                    palette_bytes = (1 << bit_count) * 3
            elif header_size >= 40 and len(raw_data) >= 36:
                bit_count = struct.unpack("<H", raw_data[14:16])[0]
                compression = struct.unpack("<I", raw_data[16:20])[0]
                clr_used = struct.unpack("<I", raw_data[32:36])[0]
                if clr_used > 0:
                    palette_bytes = clr_used * 4
                elif bit_count <= 8:
                    palette_bytes = (1 << bit_count) * 4
                elif compression == 3 and header_size == 40:
                    palette_bytes = 12
            bf_off_bits = 14 + header_size + palette_bytes
            bmp_header = struct.pack("<2sIHHI", b"BM", 14 + len(raw_data), 0, 0, bf_off_bits)
            img = Image.open(io.BytesIO(bmp_header + raw_data))
            img.load()
            return img
        except Exception:
            pass

    return None


def get_active_docx_media_entries(z: zipfile.ZipFile, duplicate_policy: str = "every_occurrence") -> List[str]:
    """
    從 Word (.docx) ZIP 結構中解析所有被實際引用的圖片檔案路徑。
    Word 在使用者刪除圖片後，往往不會自 word/media/ 目錄物理刪除檔案；
    本函式透過解析 document.xml、頁首、頁尾、註腳、VML 繪圖等活躍部件及其 .rels 關聯，
    僅提取正文中真正被引用的圖片，排除已刪除的孤立圖片。

    支援 duplicate_policy:
      - "every_occurrence": 提取文檔中每一次出現的圖片（包含在不同段落/位置重複引用的相同圖檔，依出現順序保留）。
      - "unique": 針對同一媒體檔案僅保留第一份引用。
    回傳按文件出現順序排列的 ZIP 內路徑列表 (例: ['word/media/image1.png', ...])。
    """
    raw_names = z.namelist()
    exact_name_map: Dict[str, str] = {}
    for name in raw_names:
        if name.endswith("/"):
            continue
        norm_lower = name.replace("\\", "/").lstrip("/").lower()
        exact_name_map.setdefault(norm_lower, name)

    active_images: List[str] = []
    seen: Set[str] = set()

    # 主要正文優先，隨後為頁首、頁尾、註腳、附註、VML 繪圖等
    doc_parts: List[str] = []
    if "word/document.xml" in exact_name_map:
        doc_parts.append(exact_name_map["word/document.xml"])

    other_parts: List[str] = []
    for name in sorted(raw_names):
        if name.endswith("/"):
            continue
        norm = name.replace("\\", "/").lstrip("/")
        norm_lower = norm.lower()
        if norm_lower == "word/document.xml":
            continue
        if norm_lower.startswith("word/") and (norm_lower.endswith(".xml") or norm_lower.endswith(".vml")) and "/_rels/" not in norm_lower:
            basename_lower = posixpath.basename(norm_lower)
            if not basename_lower.startswith(_DOCX_EXCLUDED_PARTS):
                other_parts.append(name)

    all_parts = doc_parts + other_parts

    for part_name in all_parts:
        part_norm = part_name.replace("\\", "/").lstrip("/")
        rels_norm = posixpath.join(
            posixpath.dirname(part_norm),
            "_rels",
            posixpath.basename(part_norm) + ".rels"
        )
        rels_zip_name = exact_name_map.get(rels_norm.lower())
        if not rels_zip_name:
            continue

        try:
            rels_root = safe_xml_fromstring(z.read(rels_zip_name))
        except Exception:
            continue

        rel_map: Dict[str, str] = {}
        for rel in rels_root.iter():
            if rel.tag.rsplit("}", 1)[-1] != "Relationship":
                continue
            if (rel.get("TargetMode") or "").strip().lower() == "external":
                continue
            r_id = rel.get("Id")
            target = rel.get("Target")
            if not r_id or not target:
                continue

            matched = _resolve_docx_rel_target(part_norm, target, exact_name_map)
            if matched:
                rel_map[r_id] = matched

        if not rel_map:
            continue

        try:
            part_root = safe_xml_fromstring(z.read(part_name))
        except Exception:
            continue

        # MCE (Markup Compatibility and Extensibility) 規範：
        # 僅當 Choice 內確實引用了有效圖片關聯時才移除 Fallback；若 Choice 為純向量等非圖片內容，保留 Fallback
        for ac in part_root.findall(f".//{_MC_NS}AlternateContent"):
            choices = ac.findall(f"{_MC_NS}Choice")
            fallback = ac.find(f"{_MC_NS}Fallback")
            if fallback is not None and any(_subtree_has_rel(ch, rel_map) for ch in choices):
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

    # 降級保護：若未解析出任何活躍圖片（含非標準 .rels 路徑情境），掃描 word/media/ 作為備用回退
    if not active_images:
        media_entries = [
            name for name in raw_names
            if not name.endswith("/")
            and name.replace("\\", "/").lstrip("/").lower().startswith("word/media/")
            and posixpath.splitext(name)[1].lower() in IMAGE_EXTENSIONS
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
    extracted_count = 0
    seq = 0

    with zipfile.ZipFile(docx_path, "r") as z:
        media_entries = get_active_docx_media_entries(z, duplicate_policy=duplicate_policy)

        for entry in media_entries:
            ext = os.path.splitext(entry)[1].lower()
            if ext not in IMAGE_EXTENSIONS:
                continue

            raw_data = z.read(entry)
            dib_img: Optional[Image.Image] = None
            if ext == ".dib":
                dib_img = _decode_dib_image(raw_data)
                target_ext = ".bmp" if dib_img is not None else ".dib"
            else:
                target_ext = ext

            seq += 1
            filename = f"image_{seq:04d}{target_ext}"
            save_path = os.path.join(output_dir, filename)

            # 若目錄已存在同名檔案，遞增流水號避免覆蓋，同時確保回傳實際提取數量
            while os.path.exists(save_path):
                seq += 1
                filename = f"image_{seq:04d}{target_ext}"
                save_path = os.path.join(output_dir, filename)

            if ext == ".dib":
                if dib_img is not None:
                    if to_grayscale:
                        dib_img = convert_to_grayscale_helper(dib_img, ".bmp")
                    elif dib_img.mode not in ("1", "L", "P", "RGB", "RGBA"):
                        dib_img = dib_img.convert("RGB")
                    dib_img.save(save_path, format="BMP")
                else:
                    with open(save_path, "wb") as f:
                        f.write(raw_data)
                extracted_count += 1
            elif to_grayscale and ext in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}:
                try:
                    img = Image.open(io.BytesIO(raw_data))
                    img = convert_to_grayscale_helper(img, ext)
                    save_format = (
                        "PNG" if ext == ".png"
                        else ("JPEG" if ext in {".jpg", ".jpeg"}
                        else ("BMP" if ext == ".bmp" else None))
                    )
                    if save_format:
                        img.save(save_path, format=save_format)
                    else:
                        img.save(save_path)
                except Exception:
                    with open(save_path, "wb") as f:
                        f.write(raw_data)
                extracted_count += 1
            else:
                with open(save_path, "wb") as f:
                    f.write(raw_data)
                extracted_count += 1

    return extracted_count


def _pixmap_to_pil_for_grayscale(pix: fitz.Pixmap) -> Tuple[fitz.Pixmap, Image.Image]:
    """Convert a PyMuPDF Pixmap (1/2/3/4 channels) into a Pillow Image for grayscale conversion."""
    mode = _PIXMAP_N_TO_PIL_MODE.get(pix.n)
    if mode is None:
        pix = fitz.Pixmap(fitz.csRGB, pix)
        mode = "RGBA" if pix.alpha else "RGB"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    return pix, img


def extract_from_pdf_with_manifest(
    pdf_path: str,
    output_dir: str,
    to_grayscale: bool = False,
    duplicate_policy: str = "every_occurrence",
    progress_callback=None,
    target_pages: Optional[Set[int]] = None,
    min_width: int = 16,
    min_height: int = 16,
) -> Tuple[int, List[Dict[str, Any]]]:
    """
    從 PDF (.pdf) 文件中無損提取所有圖片並回傳提取清單 (manifest)。
    支援進階遮罩 (Mask) 解析、視覺閱讀順序排序、去重複與透明度合成。
    每筆 manifest 項目格式：
      {"page_num": int, "seq": int, "xref": int, "bbox": Optional[Tuple[float, float, float, float]], "path": str}
    """
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    count = 0
    manifest: List[Dict[str, Any]] = []
    seen_xrefs: Set[int] = set()

    try:
        total_pages = len(doc)
        for page_index in range(total_pages):
            page_num = page_index + 1
            if target_pages is not None and page_num not in target_pages:
                continue

            if progress_callback:
                progress_callback(85, f"[INFO] 正在掃描並提取圖片 (第 {page_num}/{total_pages} 頁)...")

            page = doc[page_index]
            image_list = page.get_images(full=True)

            # 收集該頁所有圖片出現位置，依視覺閱讀順序 (y0, x0) 排序（未排版資源置於末尾）
            rects_cache: Dict[int, List[Any]] = {}
            xref_occ_counter: Dict[int, int] = {}
            candidates: List[Tuple[Tuple[float, float, int], int, Optional[Tuple[float, float, float, float]]]] = []

            for orig_idx, img_info in enumerate(image_list):
                xref = img_info[0]
                if xref not in rects_cache:
                    try:
                        rects_cache[xref] = page.get_image_rects(xref)
                    except Exception:
                        rects_cache[xref] = []

                occ_idx = xref_occ_counter.get(xref, 0)
                xref_occ_counter[xref] = occ_idx + 1

                rects = rects_cache[xref]
                bbox: Optional[Tuple[float, float, float, float]] = None
                if occ_idx < len(rects):
                    r = rects[occ_idx]
                    bbox = (float(r.x0), float(r.y0), float(r.x1), float(r.y1))
                    sort_key = (float(r.y0), float(r.x0), orig_idx)
                else:
                    sort_key = (float("inf"), float("inf"), orig_idx)

                candidates.append((sort_key, xref, bbox))

            candidates.sort(key=lambda item: item[0])

            page_seq = 0
            for _, xref, bbox in candidates:
                if duplicate_policy == "unique" and xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                pix = None
                pix_mask = None
                pix_combined = None
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue

                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)

                    if width < min_width or height < min_height:
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
                    next_seq = page_seq + 1

                    # =======================================================
                    # 情況 1：ImageMask 或單色反白遮罩 ➔ 輸出 .tif (含 LZW 壓縮)
                    # =======================================================
                    if is_mask or pix.colorspace is None or (is_inverted_decode and pix.n <= 2):
                        img_filename = f"image_p{page_num:04d}_{next_seq:03d}.tif"
                        img_filepath = os.path.join(output_dir, img_filename)

                        if pix.n > 2:
                            pix = fitz.Pixmap(fitz.csGRAY, pix)

                        if pix.n == 2:
                            la_img = Image.frombytes("LA", (pix.width, pix.height), pix.samples)
                            l_chan, a_chan = la_img.split()
                            if CASE1_OUTPUT_MODE == "TRANSPARENT":
                                black_layer = Image.new("RGBA", la_img.size, (0, 0, 0, 255))
                                transparent_bg = Image.new("RGBA", la_img.size, (0, 0, 0, 0))
                                final_img = Image.composite(black_layer, transparent_bg, l_chan)
                            else:
                                inv_l = ImageOps.invert(l_chan)
                                white_bg = Image.new("L", la_img.size, 255)
                                final_img = Image.composite(inv_l, white_bg, a_chan)
                        else:
                            mask_img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
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
                        page_seq = next_seq
                        count += 1
                        manifest.append({
                            "page_num": page_num,
                            "seq": page_seq,
                            "xref": xref,
                            "bbox": bbox,
                            "path": img_filepath,
                        })
                        continue

                    # =======================================================
                    # 情況 2：含有獨立透明遮罩 (SMask) 的圖片 ➔ 輸出 .png
                    # =======================================================
                    if smask_xref > 0:
                        seen_xrefs.add(smask_xref)
                        img_filename = f"image_p{page_num:04d}_{next_seq:03d}.png"
                        img_filepath = os.path.join(output_dir, img_filename)
                        try:
                            pix_mask = fitz.Pixmap(doc, smask_xref)
                            if pix_mask.alpha:
                                pix_mask = fitz.Pixmap(pix_mask, 0)
                            if pix_mask.colorspace and pix_mask.colorspace.name != "DeviceGray":
                                pix_mask = fitz.Pixmap(fitz.csGRAY, pix_mask)

                            # PNG 不支援 CMYK/DeviceN，若非 RGB/Gray 需先轉 RGB 才能合成透明度
                            if not pix.colorspace or pix.colorspace.name not in ("DeviceRGB", "DeviceGray"):
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            if pix.alpha:
                                pix = fitz.Pixmap(pix, 0)

                            pix_combined = fitz.Pixmap(pix, pix_mask)

                            if to_grayscale:
                                pix_combined, img = _pixmap_to_pil_for_grayscale(pix_combined)
                                img = convert_to_grayscale_helper(img, ".png")
                                img.save(img_filepath, format="PNG")
                            else:
                                pix_combined.save(img_filepath)

                            page_seq = next_seq
                            count += 1
                            manifest.append({
                                "page_num": page_num,
                                "seq": page_seq,
                                "xref": xref,
                                "bbox": bbox,
                                "path": img_filepath,
                            })
                            continue
                        except Exception:
                            pass

                    # =======================================================
                    # 情況 3：一般常規點陣圖（無遮罩） ➔ 輸出 .png
                    # =======================================================
                    img_filename = f"image_p{page_num:04d}_{next_seq:03d}.png"
                    img_filepath = os.path.join(output_dir, img_filename)
                    try:
                        # PNG 格式不支援 CMYK/DeviceN，若非 RGB/Gray 需轉為 RGB
                        if not pix.colorspace or pix.colorspace.name not in ("DeviceRGB", "DeviceGray"):
                            pix = fitz.Pixmap(fitz.csRGB, pix)

                        if to_grayscale:
                            pix, img = _pixmap_to_pil_for_grayscale(pix)
                            img = convert_to_grayscale_helper(img, ".png")
                            img.save(img_filepath, format="PNG")
                        else:
                            pix.save(img_filepath)
                        page_seq = next_seq
                        count += 1
                        manifest.append({
                            "page_num": page_num,
                            "seq": page_seq,
                            "xref": xref,
                            "bbox": bbox,
                            "path": img_filepath,
                        })
                    except Exception:
                        # 降級保護：若 Pixmap 轉換異常，使用原始二進位流寫入
                        image_bytes = base_image.get("image")
                        image_ext = base_image.get("ext", "bin")
                        if image_bytes:
                            fallback_path = os.path.join(
                                output_dir,
                                f"image_p{page_num:04d}_{next_seq:03d}.{image_ext}",
                            )
                            with open(fallback_path, "wb") as f:
                                f.write(image_bytes)
                            page_seq = next_seq
                            count += 1
                            manifest.append({
                                "page_num": page_num,
                                "seq": page_seq,
                                "xref": xref,
                                "bbox": bbox,
                                "path": fallback_path,
                            })

                except Exception as e:
                    print(f"[Warning] 提取第 {page_index + 1} 頁圖片 xref {xref} 失敗: {e}")
                    continue
                finally:
                    pix = None
                    pix_mask = None
                    pix_combined = None
    finally:
        doc.close()

    return count, manifest


def extract_from_pdf(
    pdf_path: str,
    output_dir: str,
    to_grayscale: bool = False,
    duplicate_policy: str = "every_occurrence",
    progress_callback=None,
    target_pages: Optional[Set[int]] = None,
    min_width: int = 16,
    min_height: int = 16,
) -> int:
    """
    從 PDF (.pdf) 文件中無損提取所有圖片，支援進階的遮罩(Mask)解析、去重複與透明度合成。
    支援 duplicate_policy: "unique" | "every_occurrence"。
    可選 target_pages (1-indexed): 僅提取指定頁碼之圖片，大幅縮減記憶體與暫存磁碟開銷。
    """
    count, _ = extract_from_pdf_with_manifest(
        pdf_path=pdf_path,
        output_dir=output_dir,
        to_grayscale=to_grayscale,
        duplicate_policy=duplicate_policy,
        progress_callback=progress_callback,
        target_pages=target_pages,
        min_width=min_width,
        min_height=min_height,
    )
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
