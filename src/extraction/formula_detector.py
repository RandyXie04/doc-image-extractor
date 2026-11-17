# -*- coding: utf-8 -*-
"""
Stage 1: Mathematical Formula Detector Module
=============================================
Deep module encapsulating YOLOv8l MFD ONNX Runtime inference, hardware acceleration
fallback, letterbox transformation, absolute short-formula retention filtering,
and contract-enforced schema validation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image

from config import PATHS
from src.extraction.contracts import FormulaDetectionContract

logger = logging.getLogger(__name__)

DEFAULT_PROVIDERS = ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
DEFAULT_MODEL_CANDIDATES = (
    PATHS.models_dir / "pdf_extract_mfd.onnx",
    PATHS.models_dir / "yolo_v8_ft.onnx",
    Path("models/pdf_extract_mfd.onnx"),
    Path("models/yolo_v8_ft.onnx"),
)

_SESSION_CACHE: Dict[Tuple[str, Tuple[str, ...]], ort.InferenceSession] = {}


class FormulaDetector:
    """
    Stage 1 Deep Module for Mathematical Formula Detection.

    Provides end-to-end detection of mathematical formulas (inline and isolated)
    from document page images using YOLOv8l MFD in ONNX format.
    """

    def __init__(
        self,
        model_path: Optional[Union[str, Path]] = None,
        providers: Optional[Sequence[str]] = None,
        imgsz: int = 1280,
        intra_op_num_threads: int = 4,
    ) -> None:
        self.imgsz = imgsz
        self.model_path = self._resolve_model_path(model_path)
        self.providers = tuple(providers) if providers is not None else DEFAULT_PROVIDERS
        self.intra_op_num_threads = intra_op_num_threads
        self.session = self._init_session()
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def _resolve_model_path(self, model_path: Optional[Union[str, Path]]) -> Path:
        if model_path is not None:
            p = Path(model_path).resolve()
            if not p.is_file():
                raise FileNotFoundError(f"Specified formula detection model not found: {p}")
            return p
        for candidate in DEFAULT_MODEL_CANDIDATES:
            resolved = candidate.resolve()
            if resolved.is_file():
                return resolved
        raise FileNotFoundError(
            f"No MFD model found. Looked for {[str(c) for c in DEFAULT_MODEL_CANDIDATES]}. "
            "Please run src/scripts/export_mfd_onnx.py first."
        )

    def _init_session(self) -> ort.InferenceSession:
        try:
            avail_raw = (
                ort.get_available_providers()
                if callable(getattr(ort, "get_available_providers", None))
                else []
            )
            available = set(avail_raw) if avail_raw else set()
        except Exception:
            available = set()

        if available:
            effective_providers = tuple(p for p in self.providers if p in available) or (
                "CPUExecutionProvider",
            )
        else:
            effective_providers = tuple(self.providers)

        cache_key = (str(self.model_path), effective_providers)
        if cache_key in _SESSION_CACHE:
            return _SESSION_CACHE[cache_key]

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = self.intra_op_num_threads
        options.log_severity_level = 3  # Suppress non-critical warnings

        if "DmlExecutionProvider" in effective_providers:
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

        try:
            session = ort.InferenceSession(
                str(self.model_path), sess_options=options, providers=list(effective_providers)
            )
            logger.info("FormulaDetector loaded on providers: %s", session.get_providers())
        except Exception as e:
            logger.warning(
                "Failed to initialize ORT session with providers %s: %s. Falling back to CPU.",
                effective_providers,
                e,
            )
            cpu_key = (str(self.model_path), ("CPUExecutionProvider",))
            if cpu_key in _SESSION_CACHE:
                return _SESSION_CACHE[cpu_key]
            session = ort.InferenceSession(
                str(self.model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            _SESSION_CACHE[cpu_key] = session
            return session

        _SESSION_CACHE[cache_key] = session
        return session

    @property
    def active_provider(self) -> str:
        """Returns the primary active execution provider."""
        providers = self.session.get_providers()
        return providers[0] if providers else "CPUExecutionProvider"

    def get_model_info(self) -> Dict[str, Any]:
        """Returns model metadata and runtime execution context."""
        return {
            "model_path": str(self.model_path),
            "active_provider": self.active_provider,
            "all_providers": self.session.get_providers(),
            "input_name": self.input_name,
            "output_name": self.output_name,
            "target_imgsz": self.imgsz,
        }

    def letterbox(
        self,
        img: np.ndarray,
        new_shape: Tuple[int, int] = (1280, 1280),
        color: Tuple[int, int, int] = (114, 114, 114),
    ) -> Tuple[np.ndarray, float, Tuple[float, float]]:
        """
        Resizes and letterboxes image to new_shape preserving aspect ratio with color padding.

        Returns:
            Tuple of (padded_image, scale_ratio, (dw, dh))
        """
        shape = img.shape[:2]  # [h, w]
        r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
        new_unpad = (int(round(shape[1] * r)), int(round(shape[0] * r)))
        dw = (new_shape[1] - new_unpad[0]) / 2.0
        dh = (new_shape[0] - new_unpad[1]) / 2.0

        if shape[::-1] != new_unpad:
            img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)

        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        padded = cv2.copyMakeBorder(
            img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color
        )
        return padded, r, (dw, dh)

    def preprocess(
        self,
        image: Union[Image.Image, np.ndarray, str, Path],
        is_bgr: bool = False,
    ) -> np.ndarray:
        """
        Preprocesses an input image into a normalized float32 tensor of shape (1, 3, imgsz, imgsz).
        """
        orig_img, _, _ = self._standardize_image(image, is_bgr=is_bgr)
        padded_img, _, _ = self.letterbox(orig_img, (self.imgsz, self.imgsz))
        return self._to_input_tensor(padded_img)

    @staticmethod
    def xywh2xyxy(boxes: Union[Sequence[float], np.ndarray]) -> np.ndarray:
        """
        Converts bounding box(es) from [cx, cy, w, h] to [x1, y1, x2, y2].
        Supports 1D array/sequence [4] or 2D array [N, 4].
        """
        b = np.asarray(boxes, dtype=np.float32)
        if b.ndim == 1:
            cx, cy, w, h = b[0], b[1], b[2], b[3]
            return np.array([cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0], dtype=np.float32)
        elif b.ndim == 2:
            x1 = b[:, 0] - b[:, 2] / 2.0
            y1 = b[:, 1] - b[:, 3] / 2.0
            x2 = b[:, 0] + b[:, 2] / 2.0
            y2 = b[:, 1] + b[:, 3] / 2.0
            return np.stack([x1, y1, x2, y2], axis=1)
        else:
            raise ValueError(f"Expected 1D or 2D array for boxes, got ndim={b.ndim}")

    @staticmethod
    def unmap_box(
        box: Sequence[float],
        ratio: float,
        pad: Tuple[float, float],
        orig_w: Optional[float] = None,
        orig_h: Optional[float] = None,
    ) -> Tuple[float, float, float, float]:
        """
        Unmaps a bounding box from letterbox coordinates to original image coordinates.
        Clamps to [0, orig_w] and [0, orig_h] if provided.
        """
        dw, dh = pad
        x1 = (box[0] - dw) / ratio
        y1 = (box[1] - dh) / ratio
        x2 = (box[2] - dw) / ratio
        y2 = (box[3] - dh) / ratio

        if orig_w is not None:
            x1 = max(0.0, min(float(orig_w), x1))
            x2 = max(0.0, min(float(orig_w), x2))
        if orig_h is not None:
            y1 = max(0.0, min(float(orig_h), y1))
            y2 = max(0.0, min(float(orig_h), y2))

        return (float(x1), float(y1), float(x2), float(y2))

    @staticmethod
    def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> List[int]:
        """
        Non-Maximum Suppression (NMS) in numpy.
        """
        if boxes.size == 0:
            return []

        order = np.argsort(scores)[::-1]
        keep: List[int] = []

        while order.size > 0:
            i = order[0]
            keep.append(int(i))
            if order.size == 1:
                break

            xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
            yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
            xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
            yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])

            inter_w = np.maximum(0.0, xx2 - xx1)
            inter_h = np.maximum(0.0, yy2 - yy1)
            inter = inter_w * inter_h

            area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
            area_rem = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (
                boxes[order[1:], 3] - boxes[order[1:], 1]
            )
            union = area_i + area_rem - inter
            iou = np.where(union > 0, inter / union, 0.0)

            keep_idx = np.where(iou < iou_threshold)[0]
            order = order[keep_idx + 1]

        return keep

    def detect(
        self,
        image: Union[Image.Image, np.ndarray, str, Path],
        conf_threshold: float = 0.20,
        iou_threshold: float = 0.45,
        min_width: float = 12.0,
        min_height: float = 10.0,
        extract_inline: bool = True,
        extract_isolated: bool = True,
        is_bgr: bool = False,
    ) -> List[FormulaDetectionContract]:
        """
        Executes end-to-end formula detection on a single document image.

        Parameters:
            image: Input document page (PIL Image, np.ndarray, or file path).
            conf_threshold: Minimum confidence score to retain detection (default: 0.20).
            iou_threshold: IoU threshold for Non-Maximum Suppression (default: 0.45).
            min_width: Absolute minimum bounding box width in pixels (default: 12.0).
            min_height: Absolute minimum bounding box height in pixels (default: 10.0).
            extract_inline: Whether to detect inline formulas (Class 0, default: True).
            extract_isolated: Whether to detect isolated formulas (Class 1, default: True).
            is_bgr: Whether np.ndarray input is in BGR format (e.g. from cv2.imread).

        Returns:
            List of validated FormulaDetectionContract items sorted in reading order.
        """
        orig_img, orig_w, orig_h = self._standardize_image(image, is_bgr=is_bgr)
        if orig_w == 0 or orig_h == 0:
            return []

        # 1. Preprocessing
        padded_img, ratio, (dw, dh) = self.letterbox(orig_img, (self.imgsz, self.imgsz))
        tensor = self._to_input_tensor(padded_img)

        # 2. Inference
        outputs = self.session.run([self.output_name], {self.input_name: tensor})
        raw_preds = outputs[0]  # Shape: (1, 6, 33600)

        # 3. Postprocessing & NMS
        detections = self.postprocess(
            preds=raw_preds,
            orig_w=orig_w,
            orig_h=orig_h,
            ratio=ratio,
            pad=(dw, dh),
            conf_threshold=conf_threshold,
            iou_threshold=iou_threshold,
            min_width=min_width,
            min_height=min_height,
            extract_inline=extract_inline,
            extract_isolated=extract_isolated,
        )

        return detections

    def postprocess(
        self,
        preds: np.ndarray,
        orig_w: int,
        orig_h: int,
        ratio: float,
        pad: Tuple[float, float],
        conf_threshold: float = 0.20,
        iou_threshold: float = 0.45,
        min_width: float = 12.0,
        min_height: float = 10.0,
        extract_inline: bool = True,
        extract_isolated: bool = True,
    ) -> List[FormulaDetectionContract]:
        """
        Decodes raw model outputs, runs NMS, unmaps coordinates, filters by size,
        and returns validated FormulaDetectionContract items in reading order.
        """
        # Squeeze batch dimension if present and transpose from (6, 33600) to (33600, 6)
        if preds.ndim == 3:
            matrix = np.squeeze(preds, axis=0).T  # Shape: (33600, 6)
        elif preds.ndim == 2:
            matrix = preds.T if preds.shape[0] == 6 else preds
        else:
            raise ValueError(f"Unexpected prediction tensor dimensions: {preds.ndim}")

        class_scores = matrix[:, 4:]  # (33600, 2)
        scores = np.max(class_scores, axis=1)
        class_ids = np.argmax(class_scores, axis=1)

        mask = scores >= conf_threshold
        if not np.any(mask):
            return []

        filt_preds = matrix[mask]
        filt_scores = scores[mask]
        filt_classes = class_ids[mask]

        # Convert [cx, cy, w, h] to [x1, y1, x2, y2]
        boxes = self.xywh2xyxy(filt_preds[:, :4])

        # NMS
        keep_indices = self.nms(boxes, filt_scores, iou_threshold)

        results: List[FormulaDetectionContract] = []
        for idx in keep_indices:
            cid = int(filt_classes[idx])
            if cid == 0 and not extract_inline:
                continue
            if cid == 1 and not extract_isolated:
                continue

            score = float(filt_scores[idx])
            b = boxes[idx]

            # Coordinate unmapping
            unpad_x1, unpad_y1, unpad_x2, unpad_y2 = self.unmap_box(
                b, ratio=ratio, pad=pad, orig_w=float(orig_w), orig_h=float(orig_h)
            )

            box_w = unpad_x2 - unpad_x1
            box_h = unpad_y2 - unpad_y1

            # Absolute size filter preserving short formulas while dropping single-pixel noise
            if box_w < min_width or box_h < min_height:
                continue

            category: Literal["inline", "isolated"] = "inline" if cid == 0 else "isolated"
            class_id: Literal[0, 1] = 0 if cid == 0 else 1

            results.append(
                FormulaDetectionContract(
                    box=(round(unpad_x1, 2), round(unpad_y1, 2), round(unpad_x2, 2), round(unpad_y2, 2)),
                    score=round(score, 4),
                    category=category,
                    class_id=class_id,
                )
            )

        # Sort in reading order (top to bottom, left to right)
        results.sort(key=lambda item: (item.box[1], item.box[0]))
        return results

    def _standardize_image(
        self,
        image: Union[Image.Image, np.ndarray, str, Path],
        is_bgr: bool = False,
    ) -> Tuple[np.ndarray, int, int]:
        if isinstance(image, (str, Path)):
            p = Path(image)
            if not p.is_file():
                raise FileNotFoundError(f"Input image path does not exist: {p}")
            pil_img = Image.open(str(p)).convert("RGB")
            rgb = np.array(pil_img)
            return rgb, pil_img.width, pil_img.height

        if isinstance(image, Image.Image):
            rgb = np.array(image.convert("RGB"))
            return rgb, image.width, image.height

        if isinstance(image, np.ndarray):
            if image.ndim == 2:
                rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
            elif image.ndim == 3:
                channels = image.shape[2]
                if channels == 4:
                    rgb = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
                elif channels == 3:
                    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB) if is_bgr else image
                else:
                    raise ValueError(f"Unsupported image channel count: {channels}")
            else:
                raise ValueError(f"Unsupported image array dimensions: {image.ndim}")
            h, w = rgb.shape[:2]
            return rgb, w, h

        raise TypeError(f"Unsupported image type: {type(image)}")

    def _to_input_tensor(self, padded_img: np.ndarray) -> np.ndarray:
        tensor = np.transpose(padded_img, (2, 0, 1)).astype(np.float32) / 255.0
        tensor = np.expand_dims(tensor, axis=0)
        return np.ascontiguousarray(tensor)
