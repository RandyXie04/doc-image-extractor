# -*- coding: utf-8 -*-
"""
Mathematical Formula Multi-Format Exporter (src/extraction/formula_exporter.py)
==============================================================================
Generates three standardized deliverables for extracted formulas:
  1. Sanitized LaTeX strings (stripped fences, normalized CJK in \\text{...}).
  2. Parseable MathML XML (latex2mathml with W3C <merror> fallback, validated by ElementTree).
  3. High-resolution PNG crops exported at imgsz=1600 (vector PyMuPDF or raster Lanczos).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
import xml.etree.ElementTree as ET

from src.utils.safe_xml import fromstring as safe_xml_fromstring

import fitz  # PyMuPDF
from PIL import Image

from src.extraction.contracts import (
    FormulaCategory,
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaResultContract,
)

logger = logging.getLogger(__name__)

_XML_ILLEGAL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def sanitize_latex(raw_latex: str) -> str:
    """
    Sanitizes raw LaTeX strings from formula recognition:
      1. Strips leading/trailing whitespaces and newlines.
      2. Strips markdown code blocks (```latex ... ```).
      3. Strips outer math delimiters ($$, $, \\[ \\], \\( \\)).
      4. Normalizes spurious internal whitespaces (e.g., 'x ^2' -> 'x^2').
      5. Wraps unwrapped CJK character sequences in \\text{...} while preserving
         existing \\text{...}, \\mbox{...}, or \\operatorname{...} blocks.
    """
    if not raw_latex:
        return ""

    s = raw_latex.strip()

    # 1. Strip markdown code fences (both triple/quadruple+ and single backticks, iteratively)
    while True:
        prev = s
        s = re.sub(r"^`{3,}(?:latex|math|markdown)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*`{3,}$", "", s)
        s = s.strip()
        if s.startswith("`") and s.endswith("`") and len(s) >= 2 and not s.startswith("```"):
            s = s[1:-1].strip()
        if s == prev:
            break

    # 2. Strip outer math delimiters
    if s.startswith("$$") and s.endswith("$$") and len(s) >= 4:
        s = s[2:-2].strip()
    elif s.startswith("\\[") and s.endswith("\\]") and len(s) >= 4:
        s = s[2:-2].strip()
    elif s.startswith("\\(") and s.endswith("\\)") and len(s) >= 4:
        s = s[2:-2].strip()
    elif s.startswith("$") and s.endswith("$") and len(s) >= 2 and not s.startswith("$$"):
        s = s[1:-1].strip()

    # 3. Normalize internal whitespace
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"([a-zA-Z0-9_\)\]\}])\s+([\^_])\s*", r"\1\2", s)
    s = re.sub(r"([\^_])\s+", r"\1", s)

    # 4. State-preserving CJK wrapping in \text{...}
    # Depth-aware balanced brace protection for \text{...}, \mbox{...}, \mathrm{...}, \operatorname{...}
    protected_blocks: List[str] = []
    cmd_pattern = re.compile(r"\\(?:text|mbox|mathrm|operatorname\*?)\{")

    out_parts: List[str] = []
    idx = 0
    n = len(s)

    while idx < n:
        m = cmd_pattern.search(s, idx)
        if not m:
            out_parts.append(s[idx:])
            break

        out_parts.append(s[idx:m.start()])

        depth = 1
        pos = m.end()

        while pos < n and depth > 0:
            char = s[pos]
            if char in ("{", "}"):
                # Count consecutive backslashes immediately preceding pos
                bs_count = 0
                k = pos - 1
                while k >= 0 and s[k] == "\\":
                    bs_count += 1
                    k -= 1
                if bs_count % 2 == 0:
                    if char == "{":
                        depth += 1
                    elif char == "}":
                        depth -= 1
            pos += 1

        if depth == 0:
            block = s[m.start():pos]
            block_idx = len(protected_blocks)
            protected_blocks.append(block)
            out_parts.append(f"__PROTECTED_BLOCK_{block_idx}__")
            idx = pos
        else:
            out_parts.append(s[m.start():m.end()])
            idx = m.end()

    s = "".join(out_parts)

    # Wrap unprotected CJK character runs
    cjk_pattern = re.compile(
        r"([\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3000-\u303f\uff00-\uffef]+)"
    )
    s = cjk_pattern.sub(r"\\text{\1}", s)

    # Restore protected blocks
    for block_idx, block in enumerate(protected_blocks):
        s = s.replace(f"__PROTECTED_BLOCK_{block_idx}__", block)

    return s.strip()


def normalize_katex_fences(latex: str, category: Literal["inline", "isolated"]) -> str:
    """
    Wraps bare sanitized LaTeX in standard KaTeX delimiters:
      - inline: '$' + latex + '$'
      - isolated: '$$\\n' + latex + '\\n$$'
    """
    clean = latex.strip()
    if not clean:
        return ""
    if category == "inline":
        return f"${clean}$"
    return f"$$\n{clean}\n$$"


def latex_to_mathml(
    latex_str: str,
    display: Literal["inline", "block"] = "inline",
) -> str:
    """
    Converts sanitized LaTeX into W3C Presentation MathML XML via latex2mathml.
    Validates parseability via xml.etree.ElementTree.
    If parsing fails (due to non-standard or malformed OCR LaTeX), returns a valid
    W3C MathML wrapper containing <semantics>, <merror>, and <annotation encoding="application/x-tex">.
    """
    clean_latex = latex_str.strip()
    if not clean_latex:
        return f'<math xmlns="http://www.w3.org/1998/Math/MathML" display="{display}"/>'

    try:
        import latex2mathml.converter

        mathml_str = latex2mathml.converter.convert(clean_latex, display=display)
        # Validate XML parseability
        safe_xml_fromstring(mathml_str)
        return mathml_str
    except Exception as exc:
        logger.warning(
            "latex2mathml conversion failed for '%s' (%s: %s). Generating W3C <merror> fallback.",
            clean_latex,
            type(exc).__name__,
            exc,
        )
        # Construct deterministic W3C MathML error structure
        math = ET.Element(
            "math",
            {
                "xmlns": "http://www.w3.org/1998/Math/MathML",
                "display": display,
            },
        )
        semantics = ET.SubElement(math, "semantics")
        merror = ET.SubElement(semantics, "merror")
        mtext = ET.SubElement(merror, "mtext")
        mtext.text = _XML_ILLEGAL_CHARS.sub(
            "", f"MathML conversion failed: {type(exc).__name__}: {str(exc)}"
        )
        annotation = ET.SubElement(semantics, "annotation", {"encoding": "application/x-tex"})
        annotation.text = _XML_ILLEGAL_CHARS.sub("", clean_latex)
        return ET.tostring(math, encoding="unicode")


def export_highres_png(
    output_path: Union[str, Path],
    crop: Image.Image,
    padded_box: Tuple[int, int, int, int],
    pdf_page: Optional[fitz.Page] = None,
    imgsz: int = 1600,
    dpi: float = 150.0,
) -> Path:
    """
    Renders and exports a high-resolution PNG image of the formula crop with
    longest dimension scaled to exactly `imgsz` (1600px).
    Prioritizes vector rendering from `pdf_page` via `fitz.Matrix(scale, scale)`.
    Falls back to raster Lanczos resampling if `pdf_page` is None or vector rendering fails.
    Enforces exact 1600px constraint against float grid rounding errors.
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    success = False
    if pdf_page is not None:
        try:
            effective_dpi = float(dpi) if (dpi is not None and float(dpi) > 0) else 150.0
            scale_to_points = 72.0 / effective_dpi

            x1, y1, x2, y2 = padded_box
            pt_x1 = pdf_page.rect.x0 + x1 * scale_to_points
            pt_y1 = pdf_page.rect.y0 + y1 * scale_to_points
            pt_x2 = pdf_page.rect.x0 + x2 * scale_to_points
            pt_y2 = pdf_page.rect.y0 + y2 * scale_to_points

            clip_rect = fitz.Rect(pt_x1, pt_y1, pt_x2, pt_y2).intersect(pdf_page.rect)
            if not clip_rect.is_empty and clip_rect.width > 0 and clip_rect.height > 0:
                max_point_dim = max(clip_rect.width, clip_rect.height)
                scale = float(imgsz) / max_point_dim
                pix = pdf_page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip_rect, alpha=False)
                # Check 1-pixel rounding guard
                if max(pix.width, pix.height) != imgsz:
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    scale_adj = float(imgsz) / max(img.width, img.height)
                    if img.width >= img.height:
                        new_w = imgsz
                        new_h = max(1, int(round(img.height * scale_adj)))
                    else:
                        new_h = imgsz
                        new_w = max(1, int(round(img.width * scale_adj)))
                    img = img.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)
                    img.save(out_p, format="PNG", optimize=True)
                else:
                    pix.save(str(out_p))
                success = True
        except Exception as exc:
            logger.warning("Vector high-res rendering failed (%s). Falling back to raster.", exc)
            success = False

    if not success:
        orig_w, orig_h = crop.size
        max_dim = max(orig_w, orig_h)
        if max_dim <= 0:
            res = Image.new("RGB", (imgsz, imgsz), (255, 255, 255))
        else:
            scale = float(imgsz) / max_dim
            if orig_w >= orig_h:
                new_w = imgsz
                new_h = max(1, int(round(orig_h * scale)))
            else:
                new_h = imgsz
                new_w = max(1, int(round(orig_w * scale)))
            res = crop.convert("RGB").resize((new_w, new_h), resample=Image.Resampling.LANCZOS)
        res.save(out_p, format="PNG", optimize=True)

    return out_p


def export_formula_result(
    crop: Image.Image,
    item: FormulaCroppedItemContract,
    latex_raw: str,
    output_dir: Union[str, Path],
    pdf_page: Optional[fitz.Page] = None,
    imgsz: int = 1600,
    confidence: float = 1.0,
    page_idx: Optional[int] = None,
    dpi: float = 150.0,
) -> FormulaResultContract:
    """
    Exports a single formula crop into Format 1 (LaTeX), Format 2 (MathML), and Format 3 (PNG).
    Returns a validated, immutable FormulaResultContract.
    """
    out_dir = Path(output_dir)
    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    img_path = img_dir / f"{item.item_id}.png"

    # Format 3: High-resolution PNG
    export_highres_png(
        img_path,
        crop,
        item.padded_box,
        pdf_page=pdf_page,
        imgsz=imgsz,
        dpi=dpi,
    )

    # Format 1: Sanitized LaTeX
    clean_latex = sanitize_latex(latex_raw)

    # Format 2: Parseable MathML XML
    display_mode: Literal["inline", "block"] = (
        "inline" if item.detection.category == "inline" else "block"
    )
    mathml_xml = latex_to_mathml(clean_latex, display=display_mode)

    return FormulaResultContract(
        item_id=item.item_id,
        original_index=item.original_index,
        category=item.detection.category,
        box=item.detection.box,
        padded_box=item.padded_box,
        latex=clean_latex,
        mathml=mathml_xml,
        image_path=str(img_path.resolve()),
        confidence=round(confidence, 4),
        page_idx=page_idx,
    )


def export_formula_results(
    crops: List[Image.Image],
    items: List[FormulaCroppedItemContract],
    raw_predictions: List[Tuple[str, float]],
    output_dir: Union[str, Path],
    pdf_page: Optional[fitz.Page] = None,
    imgsz: int = 1600,
    save_manifest: bool = True,
    page_idx: Optional[int] = None,
    dpi: float = 150.0,
) -> List[FormulaResultContract]:
    """
    Batch-exports formula results, writes images to <output_dir>/images/{item_id}.png,
    and optionally writes JSON manifest <output_dir>/formulas.json.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[FormulaResultContract] = []
    for crop, item, (latex_raw, conf) in zip(crops, items, raw_predictions):
        res = export_formula_result(
            crop=crop,
            item=item,
            latex_raw=latex_raw,
            output_dir=out_dir,
            pdf_page=pdf_page,
            imgsz=imgsz,
            confidence=conf,
            page_idx=page_idx,
            dpi=dpi,
        )
        results.append(res)

    if save_manifest:
        manifest_path = out_dir / "formulas.json"
        manifest_data = [res.model_dump() for res in results]
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    return results
