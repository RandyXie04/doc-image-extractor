#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_image_extractor.py
======================
Standalone module for lossless image extraction from PDF files.

Strategy:
  Delegate actual image extraction to extract_images.extract_from_pdf_with_manifest()
  which properly handles:
    - Negative / ImageMask (inverted masks → white-bg black-line TIFF)
    - CMYK colour space (→ RGB conversion for PNG compatibility)
    - SMask transparency compositing (→ RGBA PNG)
  Then match extracted images to layout blocks by bounding-box overlap, sort per page
  in reading order (y0, x0), and write unified sequential filenames
  (`image_p{page_num:04d}_{seq:03d}.{ext}`).

This module is deliberately decoupled from the Surya OCR text pipeline.
It accepts simple data structures (pdf_path, list of blocks with bboxes)
and returns a mapping of {(page_num, block_idx): saved_image_path}.
"""

from collections import defaultdict
import os
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple


def _parse_xref_from_filename(filename: str) -> Optional[int]:
    """
    Fallback parser for xref numbers when reading a pre_extract_dir or legacy extractor output.
    Expected patterns:
      page_0001_xref42.png   → 42
      page_0001_xref42.tif   → 42
    """
    m = re.search(r'xref(\d+)', filename)
    if m:
        return int(m.group(1))
    return None


def _import_extract_images_module():
    """Import extract_images module across supported package layouts."""
    try:
        from src.scripts import extract_images as mod
        return mod
    except ImportError:
        try:
            from scripts import extract_images as mod
            return mod
        except ImportError:
            import extract_images as mod
            return mod


def _build_xref_lookup_from_manifest(
    manifest: List[Dict[str, Any]],
) -> Tuple[
    Dict[Tuple[int, int], str],
    Dict[int, str],
    Dict[Tuple[int, int], List[Tuple[float, float, float, float]]],
]:
    """Build (page_num, xref) -> path, xref -> path, and bbox fallback lookups from manifest."""
    page_xref_to_file: Dict[Tuple[int, int], str] = {}
    xref_to_file: Dict[int, str] = {}
    manifest_bboxes: Dict[Tuple[int, int], List[Tuple[float, float, float, float]]] = defaultdict(list)

    for item in manifest:
        filepath = item.get("path")
        xref = item.get("xref")
        page_num = item.get("page_num")
        bbox = item.get("bbox")
        if not filepath or xref is None or not os.path.exists(filepath):
            continue

        fsize = os.path.getsize(filepath)
        if fsize == 0:
            continue

        xref_int = int(xref)
        if page_num is not None:
            key = (int(page_num), xref_int)
            if key not in page_xref_to_file or os.path.getsize(page_xref_to_file[key]) < fsize:
                page_xref_to_file[key] = filepath
            if bbox is not None:
                manifest_bboxes[key].append((float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])))

        if xref_int not in xref_to_file or os.path.getsize(xref_to_file[xref_int]) < fsize:
            xref_to_file[xref_int] = filepath

    return page_xref_to_file, xref_to_file, manifest_bboxes


def _build_xref_lookup_from_dir(extract_dir: str) -> Dict[int, str]:
    """Fallback lookup using filename xref regex when pre_extract_dir or legacy extractor is used."""
    xref_to_file: Dict[int, str] = {}
    for fname in os.listdir(extract_dir):
        filepath = os.path.join(extract_dir, fname)
        if not os.path.isfile(filepath):
            continue
        fsize = os.path.getsize(filepath)
        if fsize == 0:
            continue

        xref = _parse_xref_from_filename(fname)
        if xref is not None:
            if xref not in xref_to_file or os.path.getsize(xref_to_file[xref]) < fsize:
                xref_to_file[xref] = filepath
    return xref_to_file


def extract_pdf_images(
    pdf_path: str,
    image_blocks: list,
    output_dir: str,
    pre_extract_dir: Optional[str] = None,
    progress_callback = None
) -> dict:
    """
    Extract images from a PDF, one per detected image block.

    Uses extract_images.extract_from_pdf_with_manifest() to handle all colour-space
    edge cases (negative masks, CMYK, SMask transparency), matches extracted images
    to layout blocks by bounding-box overlap, and falls back to 300 DPI clip rendering
    for vector/composite figures. Output files are named sequentially per page in reading
    order as `image_p{page_num:04d}_{seq:03d}.{ext}`.

    Parameters
    ----------
    pdf_path : str
        Absolute path to the source PDF.
    image_blocks : list of dicts
        Each dict must have:
          - "page_num"   : int  (1-indexed)
          - "block_idx"  : int  (index within that page's block list)
          - "bbox"       : [x0, y0, x1, y1]  in layout coordinates
          - "page_w"     : float  (layout page width, for coordinate scaling)
          - "page_h"     : float  (layout page height, for coordinate scaling)
    output_dir : str
        Directory where extracted image files will be saved.

    Returns
    -------
    dict
        Mapping of (page_num, block_idx) -> saved absolute image path.
    """
    import fitz  # PyMuPDF

    os.makedirs(output_dir, exist_ok=True)
    results: dict = {}

    if not image_blocks:
        return results

    needed_pages = set(blk["page_num"] for blk in image_blocks)

    # ── Phase A: Extract ALL images via mature module (handles neg/CMYK/SMask) ──
    temp_extract_dir = pre_extract_dir
    cleanup_temp = False
    manifest: Optional[List[Dict[str, Any]]] = None

    if not temp_extract_dir:
        temp_extract_dir = tempfile.mkdtemp(prefix="pdfimg_extract_")
        cleanup_temp = True

        try:
            extract_mod = _import_extract_images_module()
            if hasattr(extract_mod, "extract_from_pdf_with_manifest"):
                _, manifest = extract_mod.extract_from_pdf_with_manifest(
                    pdf_path,
                    temp_extract_dir,
                    to_grayscale=False,
                    progress_callback=progress_callback,
                    target_pages=needed_pages,
                )
            else:
                extract_mod.extract_from_pdf(
                    pdf_path,
                    temp_extract_dir,
                    to_grayscale=False,
                    progress_callback=progress_callback,
                    target_pages=needed_pages,
                )
        except Exception:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            raise

    try:
        if manifest is not None:
            page_xref_to_file, xref_to_file, manifest_bboxes = _build_xref_lookup_from_manifest(manifest)
        else:
            page_xref_to_file = {}
            xref_to_file = _build_xref_lookup_from_dir(temp_extract_dir)
            manifest_bboxes = {}

        # ── Phase B: Match extracted images to layout blocks via bbox overlap ──
        doc = fitz.open(pdf_path)
        try:
            # Pre-index: for each page, collect all image xrefs and their rects
            page_image_rects: dict[int, list] = {}
            for page_num in needed_pages:
                page_idx = page_num - 1
                if page_idx < 0 or page_idx >= len(doc):
                    continue
                page: Any = doc[page_idx]
                page_images = page.get_images(full=True)
                rects_list = []
                seen_page_xrefs = set()
                for img_info in page_images:
                    xref = img_info[0]
                    if xref in seen_page_xrefs:
                        continue
                    seen_page_xrefs.add(xref)
                    if (page_num, xref) not in page_xref_to_file and xref not in xref_to_file:
                        continue
                    added_from_page = False
                    try:
                        img_rects = page.get_image_rects(xref)
                        for img_rect in img_rects:
                            rects_list.append((xref, img_rect))
                            added_from_page = True
                    except Exception:
                        pass
                    if not added_from_page and (page_num, xref) in manifest_bboxes:
                        for mbbox in manifest_bboxes[(page_num, xref)]:
                            rects_list.append((xref, fitz.Rect(mbbox)))

                for (m_page, m_xref), mbboxes in manifest_bboxes.items():
                    if m_page == page_num and m_xref not in seen_page_xrefs:
                        if (m_page, m_xref) in page_xref_to_file or m_xref in xref_to_file:
                            for mbbox in mbboxes:
                                rects_list.append((m_xref, fitz.Rect(mbbox)))

                page_image_rects[page_num] = rects_list

            # Scale and group valid blocks per page
            blocks_by_page: Dict[int, List[Tuple[Any, Dict[str, Any]]]] = defaultdict(list)
            for blk in image_blocks:
                page_num: int = blk["page_num"]
                page_idx = page_num - 1
                if page_idx < 0 or page_idx >= len(doc):
                    continue

                page = doc[page_idx]
                pdf_w = page.rect.width
                pdf_h = page.rect.height
                bbox: list = blk["bbox"]
                page_w: float = blk.get("page_w", 1000.0) or 1000.0
                page_h: float = blk.get("page_h", 1000.0) or 1000.0

                # Scale bounding box from layout coords to PDF point coords with cropbox offset
                scale_x = pdf_w / page_w
                scale_y = pdf_h / page_h
                clip = fitz.Rect(
                    page.rect.x0 + bbox[0] * scale_x,
                    page.rect.y0 + bbox[1] * scale_y,
                    page.rect.x0 + bbox[2] * scale_x,
                    page.rect.y0 + bbox[3] * scale_y,
                ).intersect(page.rect)

                if not clip.is_valid or clip.width < 5 or clip.height < 5:
                    continue

                blocks_by_page[page_num].append((clip, blk))

            # Match each block in reading order (y0, x0, block_idx) and assign contiguous per-page seq
            for page_num in sorted(blocks_by_page.keys()):
                page_idx = page_num - 1
                page = doc[page_idx]
                pdf_w = page.rect.width
                pdf_h = page.rect.height
                rects_for_page = page_image_rects.get(page_num, [])

                sorted_blocks = sorted(
                    blocks_by_page[page_num],
                    key=lambda item: (item[0].y0, item[0].x0, item[1]["block_idx"]),
                )

                seq = 0
                for clip, blk in sorted_blocks:
                    block_idx: int = blk["block_idx"]

                    # Find best matching extracted image by overlap
                    best_xref: Optional[int] = None
                    best_overlap: float = 0.0

                    for xref, img_rect in rects_for_page:
                        ix0, iy0, ix1, iy1 = img_rect.x0, img_rect.y0, img_rect.x1, img_rect.y1
                        cx0, cy0, cx1, cy1 = clip.x0, clip.y0, clip.x1, clip.y1

                        inter_x0 = max(ix0, cx0)
                        inter_y0 = max(iy0, cy0)
                        inter_x1 = min(ix1, cx1)
                        inter_y1 = min(iy1, cy1)

                        if inter_x1 <= inter_x0 or inter_y1 <= inter_y0:
                            continue

                        inter_area = (inter_x1 - inter_x0) * (inter_y1 - inter_y0)
                        img_area = max((ix1 - ix0) * (iy1 - iy0), 1.0)
                        clip_area = max(clip.width * clip.height, 1.0)

                        # 避免將整頁掃描底圖誤判為局部插圖
                        is_full_page_scan = img_area >= 0.85 * (pdf_w * pdf_h)
                        if is_full_page_scan and clip_area < 0.80 * img_area:
                            continue

                        overlap_ratio = inter_area / img_area

                        if overlap_ratio >= 0.40 and overlap_ratio > best_overlap:
                            best_overlap = overlap_ratio
                            best_xref = xref

                    src_path: Optional[str] = None
                    if best_xref is not None:
                        src_path = page_xref_to_file.get((page_num, best_xref)) or xref_to_file.get(best_xref)

                    if src_path is not None:
                        seq += 1
                        src_ext = os.path.splitext(src_path)[1]  # e.g. .png, .tif
                        img_filename = f"image_p{page_num:04d}_{seq:03d}{src_ext}"
                        dst_path = os.path.join(output_dir, img_filename)
                        shutil.copy2(src_path, dst_path)
                        results[(page_num, block_idx)] = dst_path
                    elif clip.width >= 30 and clip.height >= 30:
                        # Fallback for vector charts / composite figures without a single matching raster xref
                        try:
                            candidate_seq = seq + 1
                            img_filename = f"image_p{page_num:04d}_{candidate_seq:03d}.png"
                            dst_path = os.path.join(output_dir, img_filename)
                            pix = page.get_pixmap(clip=clip, dpi=300, alpha=False)
                            pix.save(dst_path)
                            seq = candidate_seq
                            results[(page_num, block_idx)] = dst_path
                        except Exception:
                            pass

        finally:
            doc.close()

    finally:
        # Clean up temp directory
        if cleanup_temp and temp_extract_dir:
            try:
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
            except Exception:
                pass

    return results

