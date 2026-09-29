#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_image_extractor.py
======================
Standalone module for lossless image extraction from PDF files.

Strategy:
  Delegate actual image extraction to the mature extract_images.extract_from_pdf()
  which properly handles:
    - Negative / ImageMask (inverted masks → white-bg black-line TIFF)
    - CMYK colour space (→ RGB conversion for PNG compatibility)
    - SMask transparency compositing (→ RGBA PNG)
  Then match extracted images to Surya OCR layout blocks by bounding-box overlap,
  and copy the matched images to the final output directory.

This module is deliberately decoupled from the Surya OCR OCR text pipeline.
It accepts simple data structures (pdf_path, list of blocks with bboxes)
and returns a mapping of {(page_num, block_idx): saved_image_path}.
"""

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional


def _rect_overlap(img_bbox, clip_bbox, threshold: float = 0.40) -> bool:
    """
    Return True if the image bbox overlaps the clip bbox by more than
    `threshold` of the image area.
    img_bbox / clip_bbox: (x0, y0, x1, y1) in PDF points.
    """
    ix0, iy0, ix1, iy1 = img_bbox
    cx0, cy0, cx1, cy1 = clip_bbox

    inter_x0 = max(ix0, cx0)
    inter_y0 = max(iy0, cy0)
    inter_x1 = min(ix1, cx1)
    inter_y1 = min(iy1, cy1)

    if inter_x1 <= inter_x0 or inter_y1 <= inter_y0:
        return False

    inter_area = (inter_x1 - inter_x0) * (inter_y1 - inter_y0)
    img_area = max((ix1 - ix0) * (iy1 - iy0), 1)
    return (inter_area / img_area) >= threshold


def _parse_xref_from_filename(filename: str) -> Optional[int]:
    """
    Parse the xref number from filenames produced by extract_from_pdf().
    Expected patterns:
      page_0001_xref42.png   → 42
      page_0001_xref42.tif   → 42
    """
    m = re.search(r'xref(\d+)', filename)
    if m:
        return int(m.group(1))
    return None


def _parse_page_from_filename(filename: str) -> Optional[int]:
    """
    Parse the 1-indexed page number from filenames produced by extract_from_pdf().
    Expected pattern:  page_0003_xref42.png  → 3
    """
    m = re.search(r'page_(\d+)_', filename)
    if m:
        return int(m.group(1))
    return None


def extract_pdf_images(
    pdf_path: str,
    image_blocks: list,
    output_dir: str,
    pre_extract_dir: str = None
) -> dict:
    """
    Extract images from a PDF, one per detected image block.

    Uses the mature extract_images.extract_from_pdf() to handle all colour-space
    edge cases (negative masks, CMYK, SMask transparency), then matches extracted
    images to Surya OCR layout blocks by bounding-box overlap.

    Parameters
    ----------
    pdf_path : str
        Absolute path to the source PDF.
    image_blocks : list of dicts
        Each dict must have:
          - "page_num"   : int  (1-indexed)
          - "block_idx"  : int  (index within that page's block list)
          - "bbox"       : [x0, y0, x1, y1]  in Surya OCR layout coordinates
          - "page_w"     : float  (Surya OCR page width, for coordinate scaling)
          - "page_h"     : float  (Surya OCR page height, for coordinate scaling)
    output_dir : str
        Directory where extracted image files will be saved.

    Returns
    -------
    dict
        Mapping of (page_num, block_idx) -> saved absolute image path.
        Blocks where no embedded raster image was found are absent from the dict.
    """
    import fitz  # PyMuPDF

    os.makedirs(output_dir, exist_ok=True)
    results: dict = {}

    if not image_blocks:
        return results

    # ── Phase A: Extract ALL images via mature module (handles neg/CMYK/SMask) ──
    temp_extract_dir = pre_extract_dir
    cleanup_temp = False

    if not temp_extract_dir:
        temp_extract_dir = tempfile.mkdtemp(prefix="pdfimg_extract_")
        cleanup_temp = True
        
        try:
            try:
                from src.scripts.extract_images import extract_from_pdf
            except ImportError:
                try:
                    from scripts.extract_images import extract_from_pdf
                except ImportError:
                    from extract_images import extract_from_pdf

            extracted_count = extract_from_pdf(pdf_path, temp_extract_dir, to_grayscale=False)

            if extracted_count == 0:
                return results
        except Exception:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
            raise
    
    try:
        # Build a lookup: xref → extracted file path
        # If multiple files exist for the same xref (e.g. residual 0-byte png and valid jpeg), keep the largest
        xref_to_file: dict[int, str] = {}
        for fname in os.listdir(temp_extract_dir):
            filepath = os.path.join(temp_extract_dir, fname)
            fsize = os.path.getsize(filepath)
            if fsize == 0:
                continue
            
            xref = _parse_xref_from_filename(fname)
            if xref is not None:
                if xref not in xref_to_file or os.path.getsize(xref_to_file[xref]) < fsize:
                    xref_to_file[xref] = filepath

        # ── Phase B: Match extracted images to Surya OCR blocks via bbox overlap ──
        doc = fitz.open(pdf_path)
        try:
            # Pre-index: for each page, collect all image xrefs and their rects
            # Only for pages that have image_blocks
            needed_pages = set(blk["page_num"] for blk in image_blocks)

            # page_num (1-indexed) → list of (xref, Rect)
            page_image_rects: dict[int, list] = {}
            for page_num in needed_pages:
                page_idx = page_num - 1
                if page_idx < 0 or page_idx >= len(doc):
                    continue
                page = doc[page_idx]
                page_images = page.get_images(full=True)
                rects_list = []
                for img_info in page_images:
                    xref = img_info[0]
                    if xref not in xref_to_file:
                        continue
                    try:
                        img_rects = page.get_image_rects(xref)
                        for img_rect in img_rects:
                            rects_list.append((xref, img_rect))
                    except Exception:
                        pass
                page_image_rects[page_num] = rects_list

            # Match each block to an extracted image
            for blk in image_blocks:
                page_num: int = blk["page_num"]
                block_idx: int = blk["block_idx"]
                bbox: list = blk["bbox"]
                page_w: float = blk.get("page_w", 1000.0)
                page_h: float = blk.get("page_h", 1000.0)

                page_idx = page_num - 1
                if page_idx < 0 or page_idx >= len(doc):
                    continue

                page = doc[page_idx]
                pdf_w = page.rect.width
                pdf_h = page.rect.height

                # Scale bounding box from layout coords to PDF point coords
                scale_x = pdf_w / page_w
                scale_y = pdf_h / page_h
                clip = fitz.Rect(
                    bbox[0] * scale_x,
                    bbox[1] * scale_y,
                    bbox[2] * scale_x,
                    bbox[3] * scale_y,
                ).intersect(page.rect)

                if not clip.is_valid or clip.width < 5 or clip.height < 5:
                    continue

                # Find best matching extracted image by overlap
                rects_for_page = page_image_rects.get(page_num, [])
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
                    img_area = max((ix1 - ix0) * (iy1 - iy0), 1)
                    overlap_ratio = inter_area / img_area

                    if overlap_ratio >= 0.40 and overlap_ratio > best_overlap:
                        best_overlap = overlap_ratio
                        best_xref = xref

                if best_xref is not None and best_xref in xref_to_file:
                    src_path = xref_to_file[best_xref]
                    src_ext = os.path.splitext(src_path)[1]  # e.g. .png, .tif
                    img_filename = f"image_p{page_num}_{block_idx}{src_ext}"
                    dst_path = os.path.join(output_dir, img_filename)
                    shutil.copy2(src_path, dst_path)
                    results[(page_num, block_idx)] = dst_path

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


def collect_image_blocks_from_surya(pdf_info_list: list) -> list:
    """
    Walk Surya OCR's middle_json pdf_info list and collect all IMAGE / FIGURE blocks.

    Returns a list of dicts suitable for passing to extract_pdf_images().
    """
    try:
        from rapid_doc.utils.enum_class import BlockType
    except ImportError:
        BlockType = None

    IMAGE_LABELS = {"image", "figure", "chart", "vision_figure", "picture"}
    blocks = []

    for page_info in pdf_info_list:
        page_idx = page_info.get("page_idx", 0)
        page_num = page_idx + 1
        page_size = page_info.get("page_size", [1000, 1000])
        page_w = page_size[0] if len(page_size) >= 1 else 1000.0
        page_h = page_size[1] if len(page_size) >= 2 else 1000.0
        para_blocks = page_info.get("para_blocks", [])

        for block_idx, block in enumerate(para_blocks):
            b_type = block.get("type")
            orig_label = block.get("original_label", "").lower()
            bbox = block.get("bbox", [])

            is_image_block = (orig_label in IMAGE_LABELS) or (
                BlockType is not None
                and b_type in (BlockType.IMAGE, getattr(BlockType, "FIGURE", None))
            )

            if is_image_block and len(bbox) >= 4:
                blocks.append(
                    {
                        "page_num": page_num,
                        "block_idx": block_idx,
                        "bbox": bbox,
                        "page_w": page_w,
                        "page_h": page_h,
                    }
                )

    return blocks
