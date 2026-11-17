# -*- coding: utf-8 -*-
"""
Unified Mathematical Formula Extraction Pipeline (src/extraction/formula_pipeline.py)
====================================================================================
Deep module encapsulating the 3-stage mathematical formula extraction and recognition
architecture:
  1. Stage 1 (FormulaDetector): YOLOv8l ONNX formula detection with letterbox padding
     and absolute size filtering.
  2. Stage 2 (FormulaCropper): Boundary safety padding (3-5px, default 4px), clamping
     to [0, 0, W, H], aspect-ratio sorting, and mini-batch packaging.
  3. Stage 3 (RecognitionPredictor): SuryaOCR batch recognition bypassing document layout.
  4. Multi-Format Exporter: Clean LaTeX, valid parseable MathML XML, and 1600px PNG crops.
  5. Order Restoration: Restoring original reading order based on original_index.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

from src.extraction.contracts import (
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaResultContract,
)
from src.extraction.formula_cropper import FormulaCropper
from src.extraction.formula_detector import FormulaDetector
from src.extraction.formula_exporter import export_formula_results
from src.extraction.formula_recognizer import RecognitionPredictor

logger = logging.getLogger(__name__)


class FormulaExtractionPipeline:
    """
    Unified 3-stage mathematical formula extraction and recognition pipeline.
    Deep module encapsulating detection, safety cropping, batch recognition,
    multi-format export, and order restoration.
    """

    def __init__(
        self,
        detector: Optional[FormulaDetector] = None,
        cropper: Optional[FormulaCropper] = None,
        recognizer: Optional[RecognitionPredictor] = None,
        pad: int = 4,
        batch_size: int = 32,
        imgsz: int = 1280,
        imgsz_export: int = 1600,
        default_languages: Optional[List[str]] = None,
    ) -> None:
        if not (1 <= pad <= 20):
            raise ValueError(f"pad must be between 1 and 20, got {pad}")
        if not (1 <= batch_size <= 256):
            raise ValueError(f"batch_size must be between 1 and 256, got {batch_size}")

        self.pad = pad
        self.batch_size = batch_size
        self.imgsz = imgsz
        self.imgsz_export = imgsz_export
        self.default_languages = default_languages or ["_math", "zh"]

        self._detector: Optional[FormulaDetector] = detector
        self._cropper: Optional[FormulaCropper] = cropper
        self._recognizer: Optional[RecognitionPredictor] = recognizer

    @property
    def detector(self) -> FormulaDetector:
        """Returns the formula detector instance, lazily initializing default if None."""
        if self._detector is None:
            self._detector = FormulaDetector(imgsz=self.imgsz)
        return self._detector

    @detector.setter
    def detector(self, value: Optional[FormulaDetector]) -> None:
        self._detector = value

    @property
    def cropper(self) -> FormulaCropper:
        """Returns the formula cropper instance, lazily initializing default if None."""
        if self._cropper is None:
            self._cropper = FormulaCropper(pad=self.pad, batch_size=self.batch_size)
        return self._cropper

    @cropper.setter
    def cropper(self, value: Optional[FormulaCropper]) -> None:
        self._cropper = value

    @property
    def recognizer(self) -> RecognitionPredictor:
        """Returns the formula recognizer instance, lazily initializing default if None."""
        if self._recognizer is None:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float32
            if device == "cuda":
                try:
                    dtype = torch.float16
                except Exception:
                    dtype = torch.float32

            self._recognizer = RecognitionPredictor(
                device=device,
                dtype=dtype,
                batch_size=self.batch_size,
                checkpoint="models/surya_rec2",
                lazy_load=False,
            )
        return self._recognizer

    @recognizer.setter
    def recognizer(self, value: Optional[RecognitionPredictor]) -> None:
        self._recognizer = value

    def process_page(
        self,
        image_or_path: Union[str, Path, Image.Image, np.ndarray, fitz.Page],
        conf_threshold: float = 0.20,
        iou_threshold: float = 0.45,
        output_dir: Optional[Union[str, Path]] = None,
        pdf_page: Optional[fitz.Page] = None,
        pad: Optional[int] = None,
        batch_size: Optional[int] = None,
        save_manifest: bool = True,
        page_idx: Optional[int] = None,
        min_width: float = 12.0,
        min_height: float = 10.0,
        extract_inline: bool = True,
        extract_isolated: bool = True,
        header_ratio: float = 0.0,
        footer_ratio: float = 0.0,
        left_ratio: float = 0.0,
        right_ratio: float = 0.0,
        dpi: int = 150,
    ) -> List[FormulaResultContract]:
        """
        Executes end-to-end 3-stage formula extraction and recognition on a single page:
          1. Normalize polymorphic input to PIL RGB Image.
          2. Stage 1: Detect formulas (FormulaDetector.detect) with margin & size filters.
          3. Stage 2: Crop & batch with safety padding (FormulaCropper.crop_and_batch).
          4. Stage 3: Predict batches (RecognitionPredictor.predict_crops).
          5. Multi-format Export: LaTeX, MathML XML, and 1600px PNG (export_formula_results).
          6. Order Restoration: Restore reading order (FormulaCropper.restore_order).
        """
        doc_to_close: Optional[fitz.Document] = None
        pdf_page_obj: Optional[fitz.Page] = pdf_page
        actual_page_idx: Optional[int] = page_idx

        try:
            # 1. Normalize input to PIL image and resolve pdf_page
            if isinstance(image_or_path, fitz.Page):
                pdf_page_obj = image_or_path
                if actual_page_idx is None:
                    actual_page_idx = pdf_page_obj.number
                pix = pdf_page_obj.get_pixmap(dpi=dpi)
                pil_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            elif isinstance(image_or_path, (str, Path)):
                p = Path(image_or_path)
                if not p.is_file():
                    raise FileNotFoundError(f"Input file not found: {p}")
                if p.suffix.lower() == ".pdf":
                    doc_to_close = fitz.open(str(p))
                    target_idx = actual_page_idx if actual_page_idx is not None else 0
                    if target_idx < 0 or target_idx >= len(doc_to_close):
                        raise IndexError(
                            f"Page index {target_idx} out of range (document has {len(doc_to_close)} pages)"
                        )
                    pdf_page_obj = doc_to_close[target_idx]
                    actual_page_idx = target_idx
                    pix = pdf_page_obj.get_pixmap(dpi=dpi)
                    pil_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                else:
                    pil_img = Image.open(str(p)).convert("RGB")

            elif isinstance(image_or_path, np.ndarray):
                if image_or_path.size == 0 or image_or_path.shape[0] < 2 or image_or_path.shape[1] < 2:
                    return []
                if image_or_path.ndim == 2:
                    pil_img = Image.fromarray(image_or_path).convert("RGB")
                elif image_or_path.ndim == 3:
                    if image_or_path.shape[2] == 4:
                        pil_img = Image.fromarray(image_or_path, "RGBA").convert("RGB")
                    elif image_or_path.shape[2] == 3:
                        pil_img = Image.fromarray(image_or_path, "RGB")
                    else:
                        raise ValueError(f"Unsupported number of image channels: {image_or_path.shape[2]}")
                else:
                    raise ValueError(f"Unsupported image array dimensions: {image_or_path.ndim}")

            elif isinstance(image_or_path, Image.Image):
                if image_or_path.width < 2 or image_or_path.height < 2:
                    return []
                pil_img = image_or_path.convert("RGB") if image_or_path.mode != "RGB" else image_or_path

            else:
                raise TypeError(f"Unsupported image input type: {type(image_or_path)}")

            if pil_img.width < 2 or pil_img.height < 2:
                return []

            # 2. Stage 1: Detect formulas
            detections = self.detector.detect(
                pil_img,
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
                min_width=min_width,
                min_height=min_height,
                extract_inline=extract_inline,
                extract_isolated=extract_isolated,
            )

            # Apply crop margin guidelines if configured
            if header_ratio > 0.0 or footer_ratio > 0.0 or left_ratio > 0.0 or right_ratio > 0.0:
                w, h = pil_img.size
                y_top = h * header_ratio
                y_bottom = h * (1.0 - footer_ratio)
                x_left = w * left_ratio
                x_right = w * (1.0 - right_ratio)
                filtered_detections: List[FormulaDetectionContract] = []
                for det in detections:
                    cx = (det.box[0] + det.box[2]) / 2.0
                    cy = (det.box[1] + det.box[3]) / 2.0
                    if x_left <= cx <= x_right and y_top <= cy <= y_bottom:
                        filtered_detections.append(det)
                detections = filtered_detections

            if not detections:
                return []

            # 3. Stage 2: Crop & batch with safety padding
            effective_pad = pad if pad is not None else self.pad
            effective_batch_size = batch_size if batch_size is not None else self.batch_size
            cropper = FormulaCropper(pad=effective_pad, batch_size=effective_batch_size)
            batches, sorted_items = cropper.crop_and_batch(pil_img, detections)
            if not batches or not sorted_items:
                return []

            # 4. Stage 3: Batch recognition
            all_crops: List[Image.Image] = []
            all_items: List[FormulaCroppedItemContract] = []
            all_preds: List[Tuple[str, float]] = []

            for batch in batches:
                batch_crops = [pair[0] for pair in batch]
                batch_items = [pair[1] for pair in batch]
                preds = self.recognizer.predict_crops(
                    batch_crops,
                    languages=self.default_languages,
                )
                all_crops.extend(batch_crops)
                all_items.extend(batch_items)
                all_preds.extend(preds)

            # Apply page index prefixing to item_id if page_idx is provided
            if actual_page_idx is not None:
                all_items = [
                    item.model_copy(
                        update={"item_id": f"p{actual_page_idx:03d}_eq_{item.original_index:05d}"}
                    )
                    for item in all_items
                ]

            # 5. Multi-format artifact generation
            if output_dir:
                out_dir = Path(output_dir)
            else:
                out_dir = Path(tempfile.mkdtemp(prefix="formula_pipeline_"))
            out_dir.mkdir(parents=True, exist_ok=True)

            results = export_formula_results(
                crops=all_crops,
                items=all_items,
                raw_predictions=all_preds,
                output_dir=out_dir,
                pdf_page=pdf_page_obj,
                imgsz=self.imgsz_export,
                save_manifest=save_manifest,
                page_idx=actual_page_idx,
                dpi=dpi,
            )

            # 6. Restore original document reading order
            return cropper.restore_order(results)

        finally:
            if doc_to_close is not None:
                try:
                    doc_to_close.close()
                except Exception:
                    pass

    def process_document(
        self,
        doc_or_path: Union[str, Path, fitz.Document],
        conf_threshold: float = 0.20,
        iou_threshold: float = 0.45,
        output_dir: Optional[Union[str, Path]] = None,
        start_page: int = 0,
        end_page: Optional[int] = None,
        pad: Optional[int] = None,
        batch_size: Optional[int] = None,
        save_manifest: bool = True,
        dpi: int = 150,
        min_width: float = 12.0,
        min_height: float = 10.0,
        extract_inline: bool = True,
        extract_isolated: bool = True,
        header_ratio: float = 0.0,
        footer_ratio: float = 0.0,
        left_ratio: float = 0.0,
        right_ratio: float = 0.0,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[FormulaResultContract]:
        """
        Processes a multi-page PDF document, extracting and recognizing formulas
        across the specified page range with aggregated deliverables.
        """
        doc_to_close: Optional[fitz.Document] = None

        try:
            if isinstance(doc_or_path, fitz.Document):
                doc = doc_or_path
            elif isinstance(doc_or_path, (str, Path)):
                p = Path(doc_or_path)
                if not p.is_file():
                    raise FileNotFoundError(f"Document file not found: {p}")
                doc_to_close = fitz.open(str(p))
                doc = doc_to_close
            else:
                raise TypeError(f"Unsupported document type: {type(doc_or_path)}")

            total_pages = len(doc)
            if total_pages == 0:
                return []

            s_idx = max(0, start_page)
            e_idx = (
                min(total_pages - 1, end_page)
                if (end_page is not None and end_page >= 0)
                else total_pages - 1
            )
            if s_idx > e_idx:
                return []

            num_pages_to_process = e_idx - s_idx + 1

            if output_dir:
                out_dir = Path(output_dir)
            else:
                out_dir = Path(tempfile.mkdtemp(prefix="formula_pipeline_doc_"))
            out_dir.mkdir(parents=True, exist_ok=True)

            all_results: List[FormulaResultContract] = []

            for offset, page_idx in enumerate(range(s_idx, e_idx + 1)):
                if progress_callback:
                    progress_callback(
                        offset + 1,
                        num_pages_to_process,
                        f"處理第 {page_idx + 1} 頁公式 ({offset + 1}/{num_pages_to_process})...",
                    )

                page = doc[page_idx]
                pix = page.get_pixmap(dpi=dpi)
                pil_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                page_results = self.process_page(
                    image_or_path=pil_img,
                    conf_threshold=conf_threshold,
                    iou_threshold=iou_threshold,
                    output_dir=out_dir,
                    pdf_page=page,
                    pad=pad,
                    batch_size=batch_size,
                    save_manifest=False,
                    page_idx=page_idx,
                    min_width=min_width,
                    min_height=min_height,
                    extract_inline=extract_inline,
                    extract_isolated=extract_isolated,
                    header_ratio=header_ratio,
                    footer_ratio=footer_ratio,
                    left_ratio=left_ratio,
                    right_ratio=right_ratio,
                    dpi=dpi,
                )
                all_results.extend(page_results)

            ordered_results = self.cropper.restore_order(all_results)

            if save_manifest and out_dir:
                manifest_path = out_dir / "formulas.json"
                manifest_data = [res.model_dump() for res in ordered_results]
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest_data, f, ensure_ascii=False, indent=2)

            return ordered_results

        finally:
            if doc_to_close is not None:
                try:
                    doc_to_close.close()
                except Exception:
                    pass
