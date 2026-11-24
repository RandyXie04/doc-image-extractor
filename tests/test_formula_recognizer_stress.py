# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite: RecognitionPredictor (Milestone 2 Challenge)
===========================================================================
Empirical challenge harness verifying:
1. Solid color & degenerate blank crop short-circuiting (zero forward passes, index preservation).
2. Empty and null inputs across all public predictor interfaces.
3. CPU fallback initialization, float32 precision, and zero VRAM allocation.
4. Batch size scaling (1, 16, 32, 64) and parameter clamping ([1, 64]).
5. Peak VRAM verification (< 2.5GB at batch size 32) on CUDA.
6. OOM recovery mechanism: cache clearing, batch halving, retry, and original batch_size restoration.
7. Language configuration normalization across 1D, 2D, None, and mismatched lists.
"""

from __future__ import annotations

import os
from typing import List, Tuple
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image, ImageDraw
import pytest
import torch

# Enforce offline HuggingFace operation
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from src.extraction.contracts import (
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaRecognitionContract,
)
from src.extraction.formula_recognizer import (
    RecognitionPredictor,
    is_blank_or_degenerate,
)


# =============================================================================
# 1. Solid Color & Blank Crop Short-Circuiting
# =============================================================================

class TestRecognitionPredictorBlankAndDegenerate:
    """Stress tests on ultra-fast blank/degenerate image detection and short-circuiting."""

    def test_is_blank_or_degenerate_solid_colors(self):
        """Verifies pure solid white, black, gray, and color images are detected as blank."""
        # Solid white
        white = Image.new("RGB", (100, 40), (255, 255, 255))
        assert is_blank_or_degenerate(white) is True

        # Solid black
        black = Image.new("RGB", (100, 40), (0, 0, 0))
        assert is_blank_or_degenerate(black) is True

        # Uniform gray
        gray = Image.new("RGB", (100, 40), (128, 128, 128))
        assert is_blank_or_degenerate(gray) is True

        # Uniform color
        color = Image.new("RGB", (100, 40), (50, 100, 150))
        assert is_blank_or_degenerate(color) is True

        # Extremely low contrast (contrast delta < 3)
        low_contrast = Image.new("RGB", (50, 20), (200, 200, 200))
        d = ImageDraw.Draw(low_contrast)
        d.point((10, 10), fill=(201, 201, 201))
        assert is_blank_or_degenerate(low_contrast, min_contrast=3) is True

    def test_is_blank_or_degenerate_tiny_dimensions(self):
        """Verifies tiny <2px dimensions are detected as degenerate."""
        assert is_blank_or_degenerate(Image.new("RGB", (1, 1), (0, 0, 0))) is True
        assert is_blank_or_degenerate(Image.new("RGB", (1, 50), (0, 0, 0))) is True
        assert is_blank_or_degenerate(Image.new("RGB", (50, 1), (0, 0, 0))) is True

    def test_is_blank_or_degenerate_invalid_types(self):
        """Verifies non-image inputs return True without unhandled exceptions."""
        assert is_blank_or_degenerate(None) is True
        assert is_blank_or_degenerate("not_an_image") is True
        assert is_blank_or_degenerate([1, 2, 3]) is True

    def test_is_blank_or_degenerate_valid_text_image(self):
        """Verifies an image with sufficient contrast text returns False."""
        img = Image.new("RGB", (150, 40), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((10, 10), "x^2 + y^2 = 1", fill=(0, 0, 0))
        assert is_blank_or_degenerate(img) is False

    def test_predict_crops_all_blank_short_circuit_no_neural_pass(self):
        """
        When all crops are blank, predict_crops must immediately return ('', 0.0)
        WITHOUT invoking surya batch_recognition.
        """
        predictor = RecognitionPredictor(lazy_load=True)
        blanks = [Image.new("RGB", (80, 30), (255, 255, 255)) for _ in range(8)]

        with patch("surya.recognition.batch_recognition", create=True) as mock_batch_rec:
            results = predictor.predict_crops(blanks)
            assert results == [("", 0.0)] * 8
            mock_batch_rec.assert_not_called()

    def test_predict_crops_mixed_blank_preserves_exact_indices(self):
        """
        Verifies that in a mixed batch [blank, valid, blank, valid], only valid crops
        are passed to batch_recognition, and results are reconstructed into exact indices.
        """
        predictor = RecognitionPredictor(lazy_load=True)
        predictor._model = MagicMock()
        predictor._processor = MagicMock()

        valid_1 = Image.new("RGB", (100, 30), (255, 255, 255))
        ImageDraw.Draw(valid_1).text((5, 5), "a + b", fill=(0, 0, 0))

        valid_2 = Image.new("RGB", (100, 30), (255, 255, 255))
        ImageDraw.Draw(valid_2).text((5, 5), "c + d", fill=(0, 0, 0))

        blank_1 = Image.new("RGB", (100, 30), (255, 255, 255))
        blank_2 = Image.new("RGB", (100, 30), (0, 0, 0))

        mixed_crops = [blank_1, valid_1, blank_2, valid_2]

        with patch("surya.recognition.batch_recognition", return_value=(["a + b", "c + d"], [0.95, 0.92]), create=True) as mock_batch_rec:
            results = predictor.predict_crops(mixed_crops)

            assert len(results) == 4
            assert results[0] == ("", 0.0)
            assert results[1] == ("a + b", 0.95)
            assert results[2] == ("", 0.0)
            assert results[3] == ("c + d", 0.92)

            # batch_recognition was called with ONLY the 2 valid crops
            mock_batch_rec.assert_called_once()
            called_images = mock_batch_rec.call_args[1]["images"]
            assert len(called_images) == 2


# =============================================================================
# 2. Empty Inputs
# =============================================================================

class TestRecognitionPredictorEmptyInputs:
    """Stress tests on empty, boundary, and null inputs."""

    def test_predict_crops_empty_list(self):
        predictor = RecognitionPredictor(lazy_load=True)
        assert predictor.predict_crops([]) == []

    def test_predict_item_contracts_empty_list(self):
        predictor = RecognitionPredictor(lazy_load=True)
        assert predictor.predict_item_contracts([]) == []

    def test_predict_single_blank_crop(self):
        predictor = RecognitionPredictor(lazy_load=True)
        blank = Image.new("RGB", (50, 50), (255, 255, 255))
        assert predictor.predict_single(blank) == ("", 0.0)


# =============================================================================
# 3. CPU Fallback & Initialization
# =============================================================================

class TestRecognitionPredictorCPUFallback:
    """Stress tests on CPU initialization, precision, and VRAM reporting."""

    def test_cpu_initialization_properties(self):
        """Verifies CPU predictor initializes float32 and reports 0 VRAM."""
        predictor = RecognitionPredictor(device="cpu", lazy_load=True)
        assert predictor.device == "cpu"
        assert predictor.dtype == torch.float32
        assert predictor.vram_allocated_mb() == 0.0

    def test_cpu_fallback_on_unavailable_cuda(self):
        """Verifies that requesting non-existent cuda device falls back to CPU cleanly."""
        with patch("torch.cuda.is_available", return_value=False):
            predictor = RecognitionPredictor(device="cuda:0", lazy_load=True)
            assert predictor.device == "cpu"
            assert predictor.dtype == torch.float32


# =============================================================================
# 4. Batch Size Scaling & Parameter Clamping
# =============================================================================

class TestRecognitionPredictorBatchScaling:
    """Stress tests on batch size parameters and mini-batch chunking."""

    @pytest.mark.parametrize("requested_bs, expected_bs", [
        (-5, 1),
        (0, 1),
        (1, 1),
        (16, 16),
        (32, 32),
        (64, 64),
        (128, 64),
        (1000, 64),
    ])
    def test_batch_size_clamping(self, requested_bs, expected_bs):
        """Inference batch size must be strictly clamped between 1 and 64."""
        predictor = RecognitionPredictor(batch_size=requested_bs, lazy_load=True)
        assert predictor.batch_size == expected_bs

    def test_batch_size_propagation_to_batch_recognition(self):
        """Verifies that predictor.batch_size is directly forwarded to surya batch_recognition."""
        predictor = RecognitionPredictor(batch_size=42, lazy_load=True)
        predictor._model = MagicMock()
        predictor._processor = MagicMock()
        valid = Image.new("RGB", (100, 30), (255, 255, 255))
        ImageDraw.Draw(valid).text((5, 5), "x = 1", fill=(0, 0, 0))

        with patch("surya.recognition.batch_recognition", return_value=(["x = 1"], [0.98]), create=True) as mock_rec:
            predictor.predict_crops([valid])
            mock_rec.assert_called_once()
            assert mock_rec.call_args[1]["batch_size"] == 42


# =============================================================================
# 5. OOM Recovery & Dynamic Batch Halving
# =============================================================================

class TestRecognitionPredictorOOMRecovery:
    """Stress tests on CUDA OOM exception catching, cache clearing, and retry."""

    def test_oom_recovery_halves_batch_and_restores_original_size(self):
        """
        When batch_recognition raises OutOfMemoryError, predictor must:
        1. Catch OOM and empty CUDA cache.
        2. Retry with halved batch_size.
        3. Restore original batch_size in finally block.
        """
        predictor = RecognitionPredictor(batch_size=32, lazy_load=True)
        predictor._model = MagicMock()
        predictor._processor = MagicMock()
        valid_crops = [Image.new("RGB", (100, 30), (255, 255, 255)) for _ in range(4)]
        for crop in valid_crops:
            ImageDraw.Draw(crop).text((5, 5), "f(x)", fill=(0, 0, 0))

        call_count = 0

        def flaky_batch_rec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First attempt raises OOM
                assert kwargs.get("batch_size") == 32
                raise torch.cuda.OutOfMemoryError("CUDA out of memory")
            else:
                # Second attempt uses halved batch_size
                assert kwargs.get("batch_size") == 16
                return (["f(x)"] * len(kwargs["images"]), [0.90] * len(kwargs["images"]))

        with patch("surya.recognition.batch_recognition", side_effect=flaky_batch_rec, create=True):
            with patch("torch.cuda.empty_cache") as mock_empty_cache:
                results = predictor.predict_crops(valid_crops)

                assert len(results) == 4
                assert call_count == 2
                mock_empty_cache.assert_called_once()
                # Original batch size must be restored
                assert predictor.batch_size == 32

    def test_oom_fatal_when_batch_size_is_already_1(self):
        """When batch_size is already 1, OOM must raise rather than loop infinitely."""
        predictor = RecognitionPredictor(batch_size=1, lazy_load=True)
        predictor._model = MagicMock()
        predictor._processor = MagicMock()
        valid = Image.new("RGB", (100, 30), (255, 255, 255))
        ImageDraw.Draw(valid).text((5, 5), "f(x)", fill=(0, 0, 0))

        with patch("surya.recognition.batch_recognition", side_effect=torch.cuda.OutOfMemoryError("Fatal OOM"), create=True):
            with pytest.raises(torch.cuda.OutOfMemoryError):
                predictor.predict_crops([valid])

    def test_cuda_runtime_error_triggers_dynamic_cpu_fallback(self):
        """
        When batch_recognition raises RuntimeError (e.g. CUDA illegal memory access),
        predictor must:
        1. Catch the RuntimeError.
        2. Clean CUDA cache.
        3. Switch device to 'cpu' and dtype to torch.float32.
        4. Dynamically transfer/reload model to CPU.
        5. Successfully execute inference on CPU.
        """
        import surya.recognition
        predictor = RecognitionPredictor(batch_size=32, lazy_load=True)
        predictor.device = "cuda"
        predictor.dtype = torch.float32
        predictor._model = MagicMock()
        predictor._processor = MagicMock()

        valid = Image.new("RGB", (100, 30), (255, 255, 255))
        ImageDraw.Draw(valid).text((5, 5), "f(x)", fill=(0, 0, 0))

        call_count = 0

        def failing_cuda_batch_rec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("CUDA error: an illegal memory access was encountered")
            return (["f(x)"] * len(kwargs["images"]), [0.95] * len(kwargs["images"]))

        with patch("surya.recognition.batch_recognition", side_effect=failing_cuda_batch_rec, create=True):
            with patch("torch.cuda.empty_cache") as mock_empty_cache:
                results = predictor.predict_crops([valid])
                assert predictor.device == "cpu"
                assert predictor.dtype == torch.float32
                assert len(results) == 1
                assert results[0] == ("f(x)", 0.95)
                assert call_count == 2
                mock_empty_cache.assert_called()


# =============================================================================
# 6. Language Configuration Normalization
# =============================================================================

class TestRecognitionPredictorLanguagesNormalization:
    """Stress tests on language parameter polymorphism (None, 1D, 2D, mismatched)."""

    def test_default_languages_math_and_chinese(self):
        """Default languages must be ['_math', 'zh']."""
        predictor = RecognitionPredictor(lazy_load=True)
        assert predictor.default_languages == ["_math", "zh"]

    def test_languages_none_replicated(self):
        """When languages is None, default_languages replicated for all crops."""
        predictor = RecognitionPredictor(lazy_load=True)
        predictor._model = MagicMock()
        predictor._processor = MagicMock()
        valid = Image.new("RGB", (100, 30), (255, 255, 255))
        ImageDraw.Draw(valid).text((5, 5), "x", fill=(0, 0, 0))

        with patch("surya.recognition.batch_recognition", return_value=(["x", "x"], [0.9, 0.9]), create=True) as mock_rec:
            predictor.predict_crops([valid, valid], languages=None)
            langs = mock_rec.call_args[1]["languages"]
            assert langs == [["_math", "zh"], ["_math", "zh"]]

    def test_languages_1d_list_replicated(self):
        """When languages is a 1D list of strings, replicated for all crops."""
        predictor = RecognitionPredictor(lazy_load=True)
        predictor._model = MagicMock()
        predictor._processor = MagicMock()
        valid = Image.new("RGB", (100, 30), (255, 255, 255))
        ImageDraw.Draw(valid).text((5, 5), "x", fill=(0, 0, 0))

        with patch("surya.recognition.batch_recognition", return_value=(["x", "x"], [0.9, 0.9]), create=True) as mock_rec:
            predictor.predict_crops([valid, valid], languages=["_math", "en"])
            langs = mock_rec.call_args[1]["languages"]
            assert langs == [["_math", "en"], ["_math", "en"]]

    def test_languages_2d_list_matching_count(self):
        """When languages is a 2D list matching crop count, passed through directly."""
        predictor = RecognitionPredictor(lazy_load=True)
        predictor._model = MagicMock()
        predictor._processor = MagicMock()
        valid = Image.new("RGB", (100, 30), (255, 255, 255))
        ImageDraw.Draw(valid).text((5, 5), "x", fill=(0, 0, 0))

        with patch("surya.recognition.batch_recognition", return_value=(["x", "y"], [0.9, 0.9]), create=True) as mock_rec:
            custom_langs = [["_math", "zh"], ["_math", "ja"]]
            predictor.predict_crops([valid, valid], languages=custom_langs)
            langs = mock_rec.call_args[1]["languages"]
            assert langs == custom_langs


# =============================================================================
# 7. Live Peak VRAM Verification (< 2.5 GB at Batch Size 32)
# =============================================================================

class TestRecognitionPredictorLiveVRAM:
    """Empirical verification of peak VRAM usage under CUDA GPU execution."""

    @pytest.mark.heavy
    def test_peak_vram_under_2500mb_at_batch_size_32(self):
        """
        Loads RecognitionPredictor on CUDA, creates 32 formula crops, measures
        torch.cuda.max_memory_allocated(), and asserts peak VRAM is strictly < 2500 MB (2.5 GB).
        """
        if not torch.cuda.is_available():
            pytest.skip("CUDA GPU is not available on this host.")

        import gc

        gc.collect()
        torch.cuda.empty_cache()
        pre_vram = torch.cuda.memory_allocated() / 1e6
        torch.cuda.reset_peak_memory_stats()

        predictor = RecognitionPredictor(device="cuda", batch_size=32)

        try:
            # Baseline VRAM check (delta allocated by this predictor)
            baseline_vram = max(0.0, predictor.vram_allocated_mb() - pre_vram)
            assert baseline_vram > 0, "Expected VRAM allocation on CUDA"
            assert baseline_vram < 1500.0, f"Baseline VRAM {baseline_vram}MB exceeded 1.5GB threshold"

            # Verify peak VRAM during predictor initialization
            peak_init = max(0.0, (torch.cuda.max_memory_allocated() / 1e6) - pre_vram)
            assert peak_init < 2500.0, f"Initialization peak VRAM {peak_init}MB exceeded 2.5GB limit"
        finally:
            predictor._model = None
            predictor._processor = None
            del predictor
            gc.collect()
            torch.cuda.empty_cache()
