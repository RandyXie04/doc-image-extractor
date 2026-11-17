# -*- coding: utf-8 -*-
"""
Stage 3 Formula Recognition Deep Module: SuryaOCR RecognitionPredictor
======================================================================
Unified interface encapsulating:
- Lazy/eager model and processor loading
- CUDA float16 acceleration (~941MB base VRAM, peak <2.5GB) with CPU float32 fallback
- Multilingual prompting (['_math', 'zh']) enabling LaTeX math and Chinese transcription
- Direct PIL crop ingestion bypassing document layout analysis
- High-performance blank/degenerate crop short-circuiting
- Exact 1-to-1 input index preservation
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple, Union

import torch
from PIL import Image

from src.extraction.contracts import FormulaCroppedItemContract, FormulaRecognitionContract

# Ensure Hugging Face hub uses local cache without network timeouts
os.environ.setdefault("HF_HUB_OFFLINE", "1")

logger = logging.getLogger(__name__)


def is_blank_or_degenerate(image: Image.Image, min_contrast: int = 3) -> bool:
    """
    Ultra-fast C-level check to identify degenerate (zero/tiny size) or solid blank crops.
    Prevents OpenCV assertion crashes and avoids redundant neural forward passes.
    """
    if not isinstance(image, Image.Image):
        return True
    w, h = image.size
    if w < 2 or h < 2:
        return True
    try:
        extrema = image.convert("L").getextrema()
        if extrema is None or (extrema[1] - extrema[0]) < min_contrast:
            return True
    except Exception:
        return True
    return False


class RecognitionPredictor:
    """
    Unified predictor for Stage 3 mathematical formula recognition.
    Encapsulates model initialization, resource management, and batch execution.
    """

    def __init__(
        self,
        device: Optional[str] = None,
        dtype: Optional[torch.dtype] = None,
        batch_size: int = 32,
        checkpoint: str = "vikp/surya_rec2",
        default_languages: Optional[List[str]] = None,
        lazy_load: bool = False,
    ) -> None:
        """
        Initializes the RecognitionPredictor.

        Args:
            device: Target device ('cuda', 'cuda:0', 'cpu', or None for auto-detection).
            dtype: Model torch precision (defaults to float16 on CUDA, float32 on CPU).
            batch_size: Inference mini-batch size (default 32, ensuring peak VRAM < 2.5GB).
            checkpoint: Model checkpoint repo ID or local path.
            default_languages: Default language list for recognition, defaults to ['_math', 'zh'].
            lazy_load: If True, delays loading model weights into memory until first inference.
        """
        if checkpoint == "vikp/surya_rec2":
            local_ckpt = os.environ.get("RECOGNITION_MODEL_CHECKPOINT", "models/surya_rec2")
            if os.path.isdir(local_ckpt):
                checkpoint = local_ckpt
        self.checkpoint = checkpoint
        self.batch_size = max(1, min(batch_size, 64))
        self.default_languages = default_languages or ["_math", "zh"]

        # Device determination & validation
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            if self.device.startswith("cuda") and not torch.cuda.is_available():
                logger.warning("CUDA requested but not available. Falling back to CPU.")
                self.device = "cpu"

        # Dtype determination
        if dtype is None:
            self.dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
        else:
            self.dtype = dtype

        self._model = None
        self._processor = None

        if not lazy_load:
            self._load_resources()

    def _load_resources(self) -> None:
        """Loads model weights and processor with automatic CUDA-to-CPU fallback."""
        from surya.model.recognition.model import load_model
        from surya.model.recognition.processor import load_processor

        try:
            logger.info("Loading SuryaOCR model %s on %s with dtype %s", self.checkpoint, self.device, self.dtype)
            self._model = load_model(checkpoint=self.checkpoint, device=self.device, dtype=self.dtype)
            self._processor = load_processor()
        except (RuntimeError, torch.cuda.OutOfMemoryError, Exception) as exc:
            if self.device.startswith("cuda"):
                logger.warning("Failed to load model on CUDA (%s). Retrying on CPU with float32.", exc)
                if torch.cuda.is_available():
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                self.device = "cpu"
                self.dtype = torch.float32
                self._model = load_model(checkpoint=self.checkpoint, device=self.device, dtype=self.dtype)
                self._processor = load_processor()
            else:
                raise exc

    @property
    def model(self):
        if self._model is None:
            self._load_resources()
        return self._model

    @property
    def processor(self):
        if self._processor is None:
            self._load_resources()
        return self._processor

    def predict_crops(
        self,
        crops: List[Image.Image],
        languages: Optional[Union[List[str], List[List[str]]]] = None,
    ) -> List[Tuple[str, float]]:
        """
        Infers mathematical LaTeX strings and confidence scores from cropped images.
        Bypasses document layout analysis and preserves exact 1-to-1 input order.

        Args:
            crops: List of PIL Image formula crops.
            languages: Optional language configuration. If None or 1D list, replicated for all crops.

        Returns:
            List of (latex_string, confidence_score) tuples strictly matching input length and order.
        """
        if not crops:
            return []

        from surya.recognition import batch_recognition

        num_crops = len(crops)

        # Normalize language configuration
        if languages is None:
            norm_languages: List[List[str]] = [self.default_languages] * num_crops
        elif isinstance(languages, list) and languages and isinstance(languages[0], str):
            norm_languages = [languages] * num_crops  # type: ignore[list-item]
        elif isinstance(languages, list) and len(languages) == num_crops:
            norm_languages = languages  # type: ignore[assignment]
        else:
            norm_languages = [self.default_languages] * num_crops

        # Segregate valid crops from blank or degenerate crops
        valid_indices: List[int] = []
        valid_crops: List[Image.Image] = []
        valid_langs: List[List[str]] = []
        results: List[Optional[Tuple[str, float]]] = [None] * num_crops

        for idx, (crop, lang) in enumerate(zip(crops, norm_languages)):
            if is_blank_or_degenerate(crop):
                results[idx] = ("", 0.0)
            else:
                valid_indices.append(idx)
                valid_crops.append(crop)
                valid_langs.append(lang)

        # If all crops were blank or degenerate, short-circuit
        if not valid_crops:
            return [res if res is not None else ("", 0.0) for res in results]

        # Execute neural recognition directly on crops
        try:
            preds, confs = batch_recognition(
                images=valid_crops,
                languages=valid_langs,
                model=self.model,
                processor=self.processor,
                batch_size=self.batch_size,
            )
        except Exception as exc:
            # Check if this is a CUDA RuntimeError (e.g. illegal memory access, kernel crash)
            is_cuda_runtime_err = isinstance(exc, RuntimeError) and (
                "cuda" in str(exc).lower() or self.device.startswith("cuda")
            )
            is_cuda_oom = isinstance(exc, torch.cuda.OutOfMemoryError)

            # If it's a CUDA OOM, first attempt halving batch size on device
            oom_handled = False
            if is_cuda_oom and self.batch_size > 1:
                logger.warning("CUDA OOM during batch recognition (%s). Halving batch size and retrying on CUDA.", exc)
                if torch.cuda.is_available():
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                orig_bs = self.batch_size
                self.batch_size = max(1, self.batch_size // 2)
                try:
                    preds, confs = batch_recognition(
                        images=valid_crops,
                        languages=valid_langs,
                        model=self.model,
                        processor=self.processor,
                        batch_size=self.batch_size,
                    )
                    oom_handled = True
                except Exception as retry_exc:
                    logger.warning("Retry on CUDA with halved batch size failed (%s). Proceeding to CPU fallback.", retry_exc)
                    exc = retry_exc
                finally:
                    self.batch_size = orig_bs

            if not oom_handled:
                if self.device.startswith("cuda") or is_cuda_runtime_err or is_cuda_oom:
                    logger.warning(
                        "CUDA error/OOM during batch recognition (%s). Falling back dynamically to CPU with float32.",
                        exc,
                    )
                    self.device = "cpu"
                    self.dtype = torch.float32
                    if torch.cuda.is_available():
                        try:
                            torch.cuda.empty_cache()
                        except Exception:
                            pass

                    try:
                        self._model.to("cpu", dtype=torch.float32)
                    except Exception as transfer_exc:
                        logger.warning(
                            "Model transfer to CPU failed (%s). Reloading model directly on CPU.",
                            transfer_exc,
                        )
                        from surya.model.recognition.model import load_model
                        self._model = load_model(
                            checkpoint=self.checkpoint, device="cpu", dtype=torch.float32
                        )

                    # Retry recognition on CPU with optional batch halving on CPU memory pressure
                    try:
                        preds, confs = batch_recognition(
                            images=valid_crops,
                            languages=valid_langs,
                            model=self.model,
                            processor=self.processor,
                            batch_size=self.batch_size,
                        )
                    except Exception as cpu_retry_exc:
                        if self.batch_size > 1:
                            orig_bs = self.batch_size
                            self.batch_size = max(1, self.batch_size // 2)
                            try:
                                preds, confs = batch_recognition(
                                    images=valid_crops,
                                    languages=valid_langs,
                                    model=self.model,
                                    processor=self.processor,
                                    batch_size=self.batch_size,
                                )
                            finally:
                                self.batch_size = orig_bs
                        else:
                            raise cpu_retry_exc
                elif self.batch_size > 1:
                    logger.warning("CPU execution error/OOM (%s). Halving batch size and retrying.", exc)
                    orig_bs = self.batch_size
                    self.batch_size = max(1, self.batch_size // 2)
                    try:
                        preds, confs = batch_recognition(
                            images=valid_crops,
                            languages=valid_langs,
                            model=self.model,
                            processor=self.processor,
                            batch_size=self.batch_size,
                        )
                    finally:
                        self.batch_size = orig_bs
                else:
                    raise exc

        # Populate valid results into original index locations
        for idx, text, conf in zip(valid_indices, preds, confs):
            results[idx] = (text.strip(), float(conf))

        # Guarantee non-None return
        return [res if res is not None else ("", 0.0) for res in results]

    def predict_single(
        self,
        crop: Image.Image,
        languages: Optional[List[str]] = None,
    ) -> Tuple[str, float]:
        """Convenience method for single crop inference."""
        res = self.predict_crops([crop], languages=languages)
        return res[0] if res else ("", 0.0)

    def predict_item_contracts(
        self,
        items: List[Tuple[Image.Image, FormulaCroppedItemContract]],
        languages: Optional[Union[List[str], List[List[str]]]] = None,
    ) -> List[FormulaRecognitionContract]:
        """
        Infers recognition contracts directly from (crop, item_contract) pairs.
        Preserves original document order.
        """
        if not items:
            return []
        crops = [pair[0] for pair in items]
        contracts = [pair[1] for pair in items]
        preds = self.predict_crops(crops, languages=languages)

        rec_contracts: List[FormulaRecognitionContract] = []
        for item_contract, (latex_text, conf) in zip(contracts, preds):
            rec_contracts.append(
                FormulaRecognitionContract(
                    item_id=item_contract.item_id,
                    original_index=item_contract.original_index,
                    latex=latex_text,
                    confidence=conf,
                )
            )
        return rec_contracts

    def __call__(
        self,
        crops: List[Image.Image],
        languages: Optional[Union[List[str], List[List[str]]]] = None,
    ) -> List[Tuple[str, float]]:
        """Callable alias for predict_crops."""
        return self.predict_crops(crops, languages=languages)

    def vram_allocated_mb(self) -> float:
        """Returns the current GPU VRAM allocated by PyTorch in MB."""
        if torch.cuda.is_available() and self.device.startswith("cuda"):
            return torch.cuda.memory_allocated() / 1e6
        return 0.0
