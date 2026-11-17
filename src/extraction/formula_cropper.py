# -*- coding: utf-8 -*-
"""
Stage 2: Formula Cropping, Safety Padding & Batch Packaging Module
==================================================================
Deep module encapsulating boundary safety padding (3-5px, default 4px),
strict clamping to [0, 0, W, H], aspect ratio calculation with zero-height safety,
aspect ratio sorting, mini-batch chunking (32-64), and document order restoration.
"""

from __future__ import annotations
import logging
from typing import Any, List, Optional, Tuple, TypeVar, Union
import numpy as np
from PIL import Image

from src.extraction.contracts import (
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    PaddedBoxTuple,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


class FormulaCropper:
    """
    Stage 2 Deep Cropping & Batch Packaging Module.
    """

    def __init__(self, pad: int = 4, batch_size: int = 32):
        if not (1 <= pad <= 20):
            raise ValueError(f"pad must be between 1 and 20, got {pad}")
        if not (1 <= batch_size <= 256):
            raise ValueError(f"batch_size must be between 1 and 256, got {batch_size}")
        self.pad = pad
        self.batch_size = batch_size

    @staticmethod
    def clamp_box(
        box: Tuple[float, float, float, float],
        width: int,
        height: int,
        pad: int = 4,
    ) -> PaddedBoxTuple:
        """
        Applies safety padding and strictly clamps bounding box to [0, 0, width, height].
        """
        x1, y1, x2, y2 = box
        pad_x1 = int(round(x1 - pad))
        pad_y1 = int(round(y1 - pad))
        pad_x2 = int(round(x2 + pad))
        pad_y2 = int(round(y2 + pad))

        clamped_x1 = max(0, min(width, pad_x1))
        clamped_y1 = max(0, min(height, pad_y1))
        clamped_x2 = max(0, min(width, pad_x2))
        clamped_y2 = max(0, min(height, pad_y2))

        return (clamped_x1, clamped_y1, clamped_x2, clamped_y2)

    @staticmethod
    def calculate_aspect_ratio(padded_box: PaddedBoxTuple) -> float:
        """
        Calculates aspect ratio w / max(1, h) with absolute zero-height division safety.
        """
        x1, y1, x2, y2 = padded_box
        w = max(0, x2 - x1)
        h = max(0, y2 - y1)
        return round(float(w) / max(1, h), 4)

    def crop_and_batch(
        self,
        page_image: Union[Image.Image, np.ndarray],
        detections: List[FormulaDetectionContract],
    ) -> Tuple[List[List[Tuple[Image.Image, FormulaCroppedItemContract]]], List[FormulaCroppedItemContract]]:
        """
        Crops detections with safety padding, calculates AR, sorts by AR,
        and packages into mini-batches while preserving document order index.

        Returns:
            Tuple of:
            1. batches: List of mini-batches, each containing tuples of (crop_image, item_contract)
            2. all_items: List of all FormulaCroppedItemContract items in sorted order
        """
        if not detections:
            return [], []

        # 1. Normalize image to RGB PIL Image
        if isinstance(page_image, np.ndarray):
            pil_image = Image.fromarray(page_image).convert("RGB")
        elif isinstance(page_image, Image.Image):
            pil_image = page_image.convert("RGB") if page_image.mode != "RGB" else page_image
        else:
            raise TypeError(f"page_image must be PIL.Image.Image or np.ndarray, got {type(page_image)}")

        img_w, img_h = pil_image.size
        if img_w <= 0 or img_h <= 0:
            raise ValueError(f"Invalid image dimensions: {img_w}x{img_h}")

        # 2. Pad, clamp, crop, and build contracts
        items_with_crops: List[Tuple[Image.Image, FormulaCroppedItemContract]] = []
        for idx, det in enumerate(detections):
            padded_box = self.clamp_box(det.box, img_w, img_h, pad=self.pad)
            w = padded_box[2] - padded_box[0]
            h = padded_box[3] - padded_box[1]

            # Reject degenerate zero-pixel boxes
            if w <= 0 or h <= 0:
                logger.warning(
                    f"Skipping degenerate crop at index {idx}: original box {det.box} clamped to {padded_box}"
                )
                continue

            ar = self.calculate_aspect_ratio(padded_box)
            crop_img = pil_image.crop(padded_box)
            if crop_img.mode != "RGB":
                crop_img = crop_img.convert("RGB")

            item_contract = FormulaCroppedItemContract(
                item_id=f"eq_{idx:05d}",
                original_index=idx,
                detection=det,
                padded_box=padded_box,
                aspect_ratio=ar,
            )
            items_with_crops.append((crop_img, item_contract))

        if not items_with_crops:
            return [], []

        # 3. Sort by aspect ratio for optimal GPU tensor batch collation
        sorted_pairs = sorted(items_with_crops, key=lambda pair: pair[1].aspect_ratio)
        sorted_items = [pair[1] for pair in sorted_pairs]

        # 4. Partition into mini-batches of size batch_size (32-64)
        batches = [
            sorted_pairs[i : i + self.batch_size]
            for i in range(0, len(sorted_pairs), self.batch_size)
        ]

        return batches, sorted_items

    @staticmethod
    def restore_order(items: List[T]) -> List[T]:
        """
        Restores processed formula items to original document reading order
        based on compound key (page_idx, original_index), gracefully handling None values.
        """
        def _sort_key(item: Any) -> Tuple[int, int]:
            if isinstance(item, dict):
                p = item.get("page_idx")
                idx = item.get("original_index")
            else:
                p = getattr(item, "page_idx", 0)
                idx = getattr(item, "original_index", 0)
            safe_page = 0 if p is None else int(p)
            safe_idx = 0 if idx is None else int(idx)
            return (safe_page, safe_idx)

        return sorted(items, key=_sort_key)


# Standalone functional convenience helpers
def prepare_formula_batches(
    page_image: Union[Image.Image, np.ndarray],
    detections: List[FormulaDetectionContract],
    pad: int = 4,
    batch_size: int = 32,
) -> Tuple[List[List[Tuple[Image.Image, FormulaCroppedItemContract]]], List[FormulaCroppedItemContract]]:
    """Convenience wrapper for FormulaCropper.crop_and_batch."""
    cropper = FormulaCropper(pad=pad, batch_size=batch_size)
    return cropper.crop_and_batch(page_image, detections)


def restore_document_order(items: List[T]) -> List[T]:
    """Convenience wrapper for FormulaCropper.restore_order."""
    return FormulaCropper.restore_order(items)
