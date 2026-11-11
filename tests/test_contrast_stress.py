# -*- coding: utf-8 -*-
"""
Empirical Quantitative Contrast & Color Stress Testing Suite
============================================================
Author: Challenger Instance 1
Date: 2026-11-11

Mathematical WCAG 2.1 AA/AAA luminance oracle and adversarial stress harness.
"""

import math
import re
import unittest
from pathlib import Path

from src.utils.path_helper import get_project_dir


def srgb_channel_to_linear(c_byte: int) -> float:
    c = c_byte / 255.0
    return c / 12.92 if c <= 0.04045 else math.pow((c + 0.055) / 1.055, 2.4)


def hex_to_rgb(hex_code: str) -> tuple[int, int, int]:
    h = hex_code.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (srgb_channel_to_linear(val) for val in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(color_a: tuple[int, int, int], color_b: tuple[int, int, int]) -> float:
    l1 = relative_luminance(color_a)
    l2 = relative_luminance(color_b)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def alpha_blend(fg_rgb: tuple[int, int, int], alpha: float, bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Simulate CSS standard alpha blending over opaque solid background."""
    return tuple(round(alpha * fg_rgb[i] + (1.0 - alpha) * bg_rgb[i]) for i in range(3))


class TestMathematicalWcagOracle(unittest.TestCase):
    """Oracle tests for exact WCAG 2.1 AA mathematical compliance required by Dispatch."""

    def setUp(self):
        self.bg_rgb = hex_to_rgb("282a36")         # Dracula Background
        self.surf1_rgb = hex_to_rgb("343746")      # Dracula Surface-1
        self.surf2_rgb = hex_to_rgb("44475a")      # Dracula Surface-2
        self.hint_rgb = hex_to_rgb("b8c0d9")       # Dracula High-contrast Hint
        self.cyan_rgb = hex_to_rgb("8be9fd")       # Dracula Cyan
        self.purple_rgb = hex_to_rgb("bd93f9")     # Dracula Purple
        self.fg_white = hex_to_rgb("f8f8f2")       # Dracula Foreground
        self.muted_rgb = hex_to_rgb("6272a4")      # Dracula Comment / Muted

    def test_mandated_contrast_targets(self):
        """Verify mathematical contrast for all 4 targets explicitly listed in prompt."""
        # Target 1: #b8c0d9 on #44475a (Surface-2, should be >= 4.5:1)
        cr_1 = contrast_ratio(self.hint_rgb, self.surf2_rgb)
        self.assertGreaterEqual(cr_1, 4.5, f"#b8c0d9 on #44475a got {cr_1:.2f}:1")
        self.assertAlmostEqual(cr_1, 5.05, delta=0.05)

        # Target 2: #b8c0d9 on #343746 (Surface-1, should be >= 4.5:1)
        cr_2 = contrast_ratio(self.hint_rgb, self.surf1_rgb)
        self.assertGreaterEqual(cr_2, 4.5, f"#b8c0d9 on #343746 got {cr_2:.2f}:1")
        self.assertAlmostEqual(cr_2, 6.50, delta=0.05)

        # Target 3: #b8c0d9 on #282a36 (Background, should be >= 7.0:1)
        cr_3 = contrast_ratio(self.hint_rgb, self.bg_rgb)
        self.assertGreaterEqual(cr_3, 7.0, f"#b8c0d9 on #282a36 got {cr_3:.2f}:1")
        self.assertAlmostEqual(cr_3, 7.85, delta=0.05)

        # Target 4: #8be9fd (Cyan) on #44475a and cyan tint (should be >= 4.5:1)
        cr_4a = contrast_ratio(self.cyan_rgb, self.surf2_rgb)
        self.assertGreaterEqual(cr_4a, 4.5, f"#8be9fd on #44475a got {cr_4a:.2f}:1")
        self.assertAlmostEqual(cr_4a, 6.61, delta=0.05)

        cyan_tint_surf2 = alpha_blend(self.cyan_rgb, 0.14, self.surf2_rgb)
        cr_4b = contrast_ratio(self.cyan_rgb, cyan_tint_surf2)
        self.assertGreaterEqual(cr_4b, 4.5, f"#8be9fd on cyan tint/surf2 got {cr_4b:.2f}:1")
        self.assertAlmostEqual(cr_4b, 4.80, delta=0.05)

    def test_mathematical_proof_of_purple_on_purple_failure(self):
        """Mathematically prove that old purple-on-purple design failed WCAG AA."""
        # Old design: purple #bd93f9 on purple tint (0.15) over Surface-2 #44475a
        old_tint_surf2 = alpha_blend(self.purple_rgb, 0.15, self.surf2_rgb)
        cr_old_surf2 = contrast_ratio(self.purple_rgb, old_tint_surf2)
        self.assertLess(
            cr_old_surf2, 4.5,
            f"Expected old purple-on-purple on Surface-2 to fail WCAG AA, got {cr_old_surf2:.2f}:1"
        )
        self.assertAlmostEqual(cr_old_surf2, 3.06, delta=0.05)

        # Old design: purple #bd93f9 on purple tint (0.15) over Surface-1 #343746
        old_tint_surf1 = alpha_blend(self.purple_rgb, 0.15, self.surf1_rgb)
        cr_old_surf1 = contrast_ratio(self.purple_rgb, old_tint_surf1)
        self.assertLess(
            cr_old_surf1, 4.5,
            f"Expected old purple-on-purple on Surface-1 to fail WCAG AA, got {cr_old_surf1:.2f}:1"
        )
        self.assertAlmostEqual(cr_old_surf1, 3.77, delta=0.05)

    def test_new_components_pass_wcag_aa(self):
        """Verify new active stage and cyan notice components pass WCAG AA."""
        # Active stage in Dark Theme: White #f8f8f2 on Purple Tint (0.28) over Surface-2 #44475a
        stage_bg = alpha_blend(self.purple_rgb, 0.28, self.surf2_rgb)
        stage_cr = contrast_ratio(self.fg_white, stage_bg)
        self.assertGreaterEqual(stage_cr, 4.5, f"Stage got {stage_cr:.2f}:1")
        self.assertAlmostEqual(stage_cr, 5.72, delta=0.1)

        # Result head ok: Cyan #8be9fd on Cyan Tint (0.14) over Surface-1 #343746
        res_bg = alpha_blend(self.cyan_rgb, 0.14, self.surf1_rgb)
        res_cr = contrast_ratio(self.cyan_rgb, res_bg)
        self.assertGreaterEqual(res_cr, 4.5, f"Result head got {res_cr:.2f}:1")
        self.assertAlmostEqual(res_cr, 5.99, delta=0.1)


class TestAdversarialStressAnalysis(unittest.TestCase):
    """Stress tests seeking out latent low-contrast vulnerabilities across web artifacts."""

    def setUp(self):
        self.project_dir = get_project_dir()
        self.static_dir = self.project_dir / "src" / "web" / "static"
        self.toolbox_css = (self.static_dir / "toolbox.css").read_text(encoding="utf-8")
        self.sidebar_css = (self.static_dir / "sidebar.css").read_text(encoding="utf-8")
        self.ocr_pipeline_html = (self.static_dir / "ocr_pipeline.html").read_text(encoding="utf-8")
        self.pod_studio_html = (self.static_dir / "pod_studio.html").read_text(encoding="utf-8")

    def test_ocr_pipeline_purged_purple_on_purple(self):
        """Confirm that ocr_pipeline.html has NO purple-on-purple result badges or callouts."""
        # The old pattern was inline style with background rgba(189,147,249,0.15) and color #bd93f9
        self.assertNotIn("rgba(189, 147, 249, 0.15)", self.ocr_pipeline_html)
        self.assertNotIn("rgba(189,147,249,0.15)", self.ocr_pipeline_html)
        self.assertIn("class=\"result-head is-ok\"", self.ocr_pipeline_html)
        self.assertIn("class=\"notice-box\"", self.ocr_pipeline_html)

    def test_detect_pod_studio_ocr_handoff_purple_leak(self):
        """
        Adversarial Probe: Check whether pod_studio.html's OCR handoff banner
        (triggered by ocr_pipeline.html handoff button) still contains purple-on-purple.
        """
        handoff_banner_match = re.search(
            r"noticeEl\.style\.cssText\s*=\s*'([^']+)'.*?noticeEl\.innerHTML\s*=\s*`([^`]+)`",
            self.pod_studio_html,
            re.DOTALL
        )
        self.assertIsNotNone(handoff_banner_match, "noticeEl injection block not found in pod_studio.html")
        style_text = handoff_banner_match.group(1)
        inner_html = handoff_banner_match.group(2)

        has_accent_soft_bg = "background: var(--accent-soft)" in style_text or "var(--accent-soft)" in style_text
        has_accent_text = "color: var(--accent);" in inner_html or (re.search(r'color:\s*var\(--accent\b[^-]', inner_html) is not None)

        # Verified: pod_studio.html noticeEl now uses .notice-box and Dracula Cyan tokens
        is_vulnerable = has_accent_soft_bg and has_accent_text
        self.assertFalse(
            is_vulnerable,
            "pod_studio.html noticeEl must NOT exhibit purple-on-purple vulnerability"
        )
        self.assertIn("notice-box", self.pod_studio_html)
        self.assertIn("var(--accent-cyan)", inner_html)

    def test_detect_dropzone_sub_unupgraded_in_dark_mode(self):
        """
        Adversarial Probe: Check whether .dropzone-sub is included in
        [data-theme='dark'] high-contrast secondary text upgrade list.
        """
        dark_text_rule = re.search(
            r'\[data-theme="dark"\]\s*([^\{]+)\{\s*color:\s*var\(--text-hint[^;]*\);?\s*\}',
            self.toolbox_css
        )
        self.assertIsNotNone(dark_text_rule, "Dark theme hint rule not found in toolbox.css")
        selector_group = dark_text_rule.group(1)

        # Check if .dropzone-sub is covered
        is_covered = ".dropzone-sub" in selector_group
        self.assertTrue(
            is_covered,
            ".dropzone-sub must be included in dark theme high-contrast rule"
        )

    def test_theme_switch_isolation_and_no_bleed(self):
        """Verify theme switcher state machine and FOUC prevention across all static pages."""
        pages = [
            "index.html",
            "ocr_pipeline.html",
            "pod_studio.html",
            "formula.html",
            "founder_repair.html",
            "extract_images.html",
        ]
        fouc_regex = re.compile(
            r"\(function\(\)\s*\{\s*const\s+u\s*=\s*new\s+URLSearchParams\(window\.location\.search\)\.get\('theme'\);"
        )
        for page_name in pages:
            path = self.static_dir / page_name
            self.assertTrue(path.exists(), f"Missing page: {page_name}")
            content = path.read_text(encoding="utf-8")

            # Check FOUC script
            self.assertRegex(
                content,
                fouc_regex,
                f"{page_name} missing instant FOUC prevention script in <head>"
            )

            # Check style and script links
            self.assertIn("sidebar.css", content, f"{page_name} missing sidebar.css")
            self.assertIn("toolbox.css", content, f"{page_name} missing toolbox.css")
            self.assertIn("sidebar.js", content, f"{page_name} missing sidebar.js")


if __name__ == "__main__":
    unittest.main()
