# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite: FormulaCropper (Milestone 2 Challenge)
=====================================================================
Empirical challenge harness verifying:
1. Extreme aspect ratios (100:1, 1:100, 500:1, micro-dimension, massive).
2. Boundary conditions (corners, exact canvas borders, partial overflows, total out-of-bounds).
3. Degenerate zero-pixel boxes (zero width, zero height, zero division safety in AR calculations).
4. Negative and inverted coordinates (Pydantic contract rejection, clamp_box defense).
5. Float boxes (fractional coordinates, rounding accuracy, integer contract adherence).
6. Order restoration under pseudo-random permutations across contract types and dictionaries.
"""

from __future__ import annotations

import random
from typing import List, Tuple
import numpy as np
from PIL import Image
import pytest
from pydantic import ValidationError

from src.extraction.contracts import (
    FormulaCroppedItemContract,
    FormulaDetectionContract,
    FormulaRecognitionContract,
    FormulaResultContract,
)
from src.extraction.formula_cropper import (
    FormulaCropper,
    prepare_formula_batches,
    restore_document_order,
)


# =============================================================================
# 1. Extreme Aspect Ratios
# =============================================================================

class TestFormulaCropperAspectRatios:
    """Stress tests on extreme aspect ratios (100:1, 1:100, etc.)."""

    def test_extreme_wide_aspect_ratio_100_to_1(self):
        """Tests an extreme 100:1 wide bounding box."""
        canvas_w, canvas_h = 1200, 800
        canvas = Image.new("RGB", (canvas_w, canvas_h), color=(255, 255, 255))
        # 1000 x 10 -> ratio 100:1
        det = FormulaDetectionContract(
            box=(50.0, 100.0, 1050.0, 110.0),
            score=0.95,
            category="isolated",
            class_id=1,
        )

        cropper = FormulaCropper(pad=4, batch_size=32)
        batches, all_items = cropper.crop_and_batch(canvas, [det])

        assert len(batches) == 1
        assert len(batches[0]) == 1
        crop_img, item = batches[0][0]

        # Padded box: 50-4=46, 100-4=96, 1050+4=1054, 110+4=114
        # w = 1008, h = 18. AR = 1008 / 18 = 56.0
        assert item.padded_box == (46, 96, 1054, 114)
        assert crop_img.size == (1008, 18)
        assert item.aspect_ratio == round(1008.0 / 18.0, 4)
        assert item.aspect_ratio > 50.0

    def test_extreme_tall_aspect_ratio_1_to_100(self):
        """Tests an extreme 1:100 tall bounding box."""
        canvas_w, canvas_h = 800, 1200
        canvas = Image.new("RGB", (canvas_w, canvas_h), color=(255, 255, 255))
        # 10 x 1000 -> ratio 1:100
        det = FormulaDetectionContract(
            box=(100.0, 50.0, 110.0, 1050.0),
            score=0.92,
            category="isolated",
            class_id=1,
        )

        cropper = FormulaCropper(pad=4, batch_size=32)
        batches, all_items = cropper.crop_and_batch(canvas, [det])

        assert len(batches) == 1
        crop_img, item = batches[0][0]

        # Padded box: 100-4=96, 50-4=46, 110+4=114, 1050+4=1054
        # w = 18, h = 1008. AR = 18 / 1008 = 0.0179
        assert item.padded_box == (96, 46, 114, 1054)
        assert crop_img.size == (18, 1008)
        assert item.aspect_ratio == round(18.0 / 1008.0, 4)
        assert item.aspect_ratio < 0.02

    def test_aspect_ratio_calculator_ultra_extremes(self):
        """Directly verifies calculate_aspect_ratio for 500:1, 1:500, micro-boxes."""
        # 500:1
        ar_wide = FormulaCropper.calculate_aspect_ratio((0, 0, 500, 1))
        assert ar_wide == 500.0

        # 1:500
        ar_tall = FormulaCropper.calculate_aspect_ratio((0, 0, 1, 500))
        assert ar_tall == round(1.0 / 500.0, 4)

        # Micro-box (1x1)
        ar_micro = FormulaCropper.calculate_aspect_ratio((10, 10, 11, 11))
        assert ar_micro == 1.0

    def test_aspect_ratio_sorting_ordering_guarantee(self):
        """Verifies that across mini-batches, items are strictly non-decreasing in AR."""
        canvas = Image.new("RGB", (1000, 1000), color=(255, 255, 255))
        detections: List[FormulaDetectionContract] = []

        # Generate 40 boxes with diverse widths and heights
        rng = np.random.default_rng(42)
        for i in range(40):
            w = rng.uniform(5.0, 400.0)
            h = rng.uniform(5.0, 400.0)
            x1 = rng.uniform(10.0, 500.0)
            y1 = rng.uniform(10.0, 500.0)
            detections.append(
                FormulaDetectionContract(
                    box=(x1, y1, x1 + w, y1 + h),
                    score=0.90,
                    category="inline",
                    class_id=0,
                )
            )

        cropper = FormulaCropper(pad=4, batch_size=16)
        batches, all_items = cropper.crop_and_batch(canvas, detections)

        # Flatten all items in batch order
        batch_items = [item for batch in batches for _, item in batch]
        aspect_ratios = [item.aspect_ratio for item in batch_items]

        # Verify aspect ratios are sorted in ascending order
        assert aspect_ratios == sorted(aspect_ratios)
        assert len(all_items) == 40


# =============================================================================
# 2. Boundary Conditions & Canvas Clamping
# =============================================================================

class TestFormulaCropperBoundaryConditions:
    """Stress tests on canvas corners, edges, and overflows."""

    def test_clamping_top_left_corner(self):
        """Ensures padding at (0, 0) clamps safely to 0 without negative indices."""
        box = (0.0, 0.0, 25.0, 30.0)
        clamped = FormulaCropper.clamp_box(box, width=200, height=200, pad=4)
        assert clamped == (0, 0, 29, 34)

    def test_clamping_bottom_right_corner(self):
        """Ensures padding at (W, H) clamps safely to (W, H) without exceeding boundaries."""
        box = (175.0, 170.0, 200.0, 200.0)
        clamped = FormulaCropper.clamp_box(box, width=200, height=200, pad=4)
        assert clamped == (171, 166, 200, 200)

    def test_clamping_full_canvas_box(self):
        """Ensures full-canvas box remains bounded by [0, 0, W, H]."""
        box = (0.0, 0.0, 200.0, 150.0)
        clamped = FormulaCropper.clamp_box(box, width=200, height=150, pad=5)
        assert clamped == (0, 0, 200, 150)

    def test_partially_out_of_bounds_box(self):
        """Ensures box extending outside image is clamped strictly to image bounds."""
        box = (180.0, 130.0, 250.0, 180.0)
        clamped = FormulaCropper.clamp_box(box, width=200, height=150, pad=4)
        assert clamped == (176, 126, 200, 150)
        w = clamped[2] - clamped[0]
        h = clamped[3] - clamped[1]
        assert w > 0 and h > 0

    def test_completely_out_of_bounds_box_skips_cleanly(self):
        """Ensures a detection completely outside canvas is clamped to 0-pixel and skipped."""
        canvas = Image.new("RGB", (100, 100), color=(255, 255, 255))
        det_oob = FormulaDetectionContract(
            box=(150.0, 150.0, 200.0, 200.0),
            score=0.85,
            category="isolated",
            class_id=1,
        )

        cropper = FormulaCropper(pad=4, batch_size=32)
        batches, all_items = cropper.crop_and_batch(canvas, [det_oob])

        assert batches == []
        assert all_items == []


# =============================================================================
# 3. Degenerate Zero-Pixel Boxes
# =============================================================================

class TestFormulaCropperDegenerateAndZeroPixel:
    """Stress tests on degenerate zero-pixel geometries."""

    def test_zero_width_or_height_aspect_ratio_safety(self):
        """Guarantees zero-height or zero-width does not cause ZeroDivisionError."""
        # 0x0
        assert FormulaCropper.calculate_aspect_ratio((10, 10, 10, 10)) == 0.0
        # 0 width, positive height
        assert FormulaCropper.calculate_aspect_ratio((10, 10, 10, 50)) == 0.0
        # positive width, 0 height
        assert FormulaCropper.calculate_aspect_ratio((10, 10, 50, 10)) == 40.0
        # absolute origin 0,0,0,0
        assert FormulaCropper.calculate_aspect_ratio((0, 0, 0, 0)) == 0.0

    def test_mixed_degenerate_and_valid_boxes_in_pipeline(self):
        """Verifies that degenerate boxes are skipped while valid boxes retain original indices."""
        canvas = Image.new("RGB", (200, 200), color=(255, 255, 255))
        detections = [
            # 0: Valid
            FormulaDetectionContract(box=(10.0, 10.0, 50.0, 30.0), score=0.9, category="inline", class_id=0),
            # 1: Completely outside (OOB) -> clamped to (200, 200, 200, 200) -> 0-pixel
            FormulaDetectionContract(box=(250.0, 250.0, 300.0, 300.0), score=0.9, category="inline", class_id=0),
            # 2: Valid
            FormulaDetectionContract(box=(60.0, 60.0, 100.0, 90.0), score=0.9, category="isolated", class_id=1),
            # 3: Another OOB
            FormulaDetectionContract(box=(400.0, 400.0, 450.0, 450.0), score=0.9, category="isolated", class_id=1),
            # 4: Valid
            FormulaDetectionContract(box=(110.0, 110.0, 180.0, 150.0), score=0.9, category="inline", class_id=0),
        ]

        batches, all_items = prepare_formula_batches(canvas, detections, pad=4, batch_size=32)

        # Exactly 3 valid items survive
        assert len(all_items) == 3
        surviving_original_indices = sorted([item.original_index for item in all_items])
        assert surviving_original_indices == [0, 2, 4]


# =============================================================================
# 4. Negative Coordinates & Float Boxes
# =============================================================================

class TestFormulaCropperNegativeAndFloatCoordinates:
    """Stress tests on negative coordinates and float coordinate handling."""

    def test_contract_rejection_of_negative_coordinates(self):
        """Pydantic modelvalidator must reject negative box coordinates."""
        with pytest.raises(ValidationError):
            FormulaDetectionContract(
                box=(-5.0, 10.0, 50.0, 50.0),
                score=0.9,
                category="inline",
                class_id=0,
            )

        with pytest.raises(ValidationError):
            FormulaDetectionContract(
                box=(10.0, -2.5, 50.0, 50.0),
                score=0.9,
                category="inline",
                class_id=0,
            )

    def test_contract_rejection_of_inverted_coordinates(self):
        """Pydantic modelvalidator must reject inverted boxes where x2 <= x1 or y2 <= y1."""
        with pytest.raises(ValidationError):
            FormulaDetectionContract(
                box=(50.0, 10.0, 20.0, 50.0),
                score=0.9,
                category="inline",
                class_id=0,
            )

        with pytest.raises(ValidationError):
            FormulaDetectionContract(
                box=(10.0, 50.0, 50.0, 20.0),
                score=0.9,
                category="inline",
                class_id=0,
            )

    def test_raw_clamp_box_defensive_handling_of_negative_coords(self):
        """FormulaCropper.clamp_box defensively handles negative raw input tuples."""
        # Box partially extending into negative space
        clamped = FormulaCropper.clamp_box((-10.0, -15.0, 20.0, 25.0), width=100, height=100, pad=4)
        assert clamped == (0, 0, 24, 29)

        # Box completely negative
        clamped_all_neg = FormulaCropper.clamp_box((-50.0, -50.0, -10.0, -10.0), width=100, height=100, pad=4)
        assert clamped_all_neg == (0, 0, 0, 0)

    def test_float_box_coordinates_rounding_and_contract_compliance(self):
        """Verifies that float coordinates are rounded to integers and pass strict contract validation."""
        canvas = Image.new("RGB", (300, 300), color=(255, 255, 255))
        det = FormulaDetectionContract(
            box=(10.25, 20.75, 100.33, 50.66),
            score=0.91,
            category="inline",
            class_id=0,
        )

        cropper = FormulaCropper(pad=4, batch_size=32)
        batches, all_items = cropper.crop_and_batch(canvas, [det])

        crop_img, item = batches[0][0]
        # x1 = round(10.25 - 4) = 6
        # y1 = round(20.75 - 4) = 17
        # x2 = round(100.33 + 4) = 104
        # y2 = round(50.66 + 4) = 55
        assert item.padded_box == (6, 17, 104, 55)
        assert all(isinstance(coord, int) for coord in item.padded_box)
        assert crop_img.size == (104 - 6, 55 - 17)


# =============================================================================
# 5. Order Restoration Under Random Permutations
# =============================================================================

class TestFormulaCropperOrderRestorationPermutations:
    """Stress tests on order restoration under severe random permutations."""

    def test_order_restoration_under_random_permutations(self):
        """
        Creates N=100 items with arbitrary aspect ratios.
        Sorts, partitions, randomly shuffles, and verifies restore_order exactly recovers 0..N-1.
        """
        canvas = Image.new("RGB", (1000, 1000), color=(255, 255, 255))
        N = 100
        rng = np.random.default_rng(12345)

        detections = []
        for i in range(N):
            w = rng.uniform(10.0, 300.0)
            h = rng.uniform(10.0, 300.0)
            x1 = rng.uniform(0.0, 600.0)
            y1 = rng.uniform(0.0, 600.0)
            detections.append(
                FormulaDetectionContract(
                    box=(x1, y1, x1 + w, y1 + h),
                    score=0.9,
                    category="inline" if i % 2 == 0 else "isolated",
                    class_id=0 if i % 2 == 0 else 1,
                )
            )

        cropper = FormulaCropper(pad=4, batch_size=32)
        batches, all_items = cropper.crop_and_batch(canvas, detections)

        assert len(all_items) == N

        # Severely shuffle items
        shuffled_items = list(all_items)
        random.seed(999)
        random.shuffle(shuffled_items)

        # Restore order
        restored = FormulaCropper.restore_order(shuffled_items)
        restored_helper = restore_document_order(shuffled_items)

        # Assert exact 0..N-1 sequence
        assert [item.original_index for item in restored] == list(range(N))
        assert [item.original_index for item in restored_helper] == list(range(N))

    def test_order_restoration_with_dictionaries(self):
        """Verifies restore_order handles raw dictionaries containing original_index."""
        raw_dicts = [
            {"original_index": 7, "value": "eq_7"},
            {"original_index": 2, "value": "eq_2"},
            {"original_index": 0, "value": "eq_0"},
            {"original_index": 9, "value": "eq_9"},
            {"original_index": 4, "value": "eq_4"},
        ]
        restored = restore_document_order(raw_dicts)
        assert [d["original_index"] for d in restored] == [0, 2, 4, 7, 9]

    def test_order_restoration_empty_and_single_element(self):
        """Boundary test on empty and single element lists."""
        assert restore_document_order([]) == []

        item = FormulaCroppedItemContract(
            item_id="eq_00000",
            original_index=0,
            detection=FormulaDetectionContract(box=(10.0, 10.0, 50.0, 30.0), score=0.9, category="inline", class_id=0),
            padded_box=(6, 6, 54, 34),
            aspect_ratio=1.5,
        )
        assert restore_document_order([item]) == [item]
