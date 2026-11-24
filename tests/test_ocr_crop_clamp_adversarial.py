# -*- coding: utf-8 -*-
"""
Empirical Adversarial Test Suite: Crop Clamping, Bidirectional Sync & Viewport Sticky Ergonomics
================================================================================================
Author: Challenger Instance 4
Target: src/web/static/ocr_pipeline.html, src/web/static/toolbox.css
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any, Dict

import pytest

webview = pytest.importorskip("webview")
pytestmark = pytest.mark.heavy

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "web" / "static"
HTML_FILE = STATIC_DIR / "ocr_pipeline.html"
TOOLBOX_CSS_FILE = STATIC_DIR / "toolbox.css"
SIDEBAR_CSS_FILE = STATIC_DIR / "sidebar.css"


def build_self_contained_html(theme: str = "dark") -> str:
    raw_html = HTML_FILE.read_text(encoding="utf-8")
    sidebar_css = SIDEBAR_CSS_FILE.read_text(encoding="utf-8")
    toolbox_css = TOOLBOX_CSS_FILE.read_text(encoding="utf-8")

    raw_html = re.sub(
        r'<html[^>]*>',
        f'<html lang="zh-TW" data-theme="{theme}">',
        raw_html,
        count=1
    )

    inlined_styles = f"""
    <style id="embedded-sidebar-css">
    {sidebar_css}
    </style>
    <style id="embedded-toolbox-css">
    {toolbox_css}
    </style>
    """
    raw_html = raw_html.replace(
        '<link rel="stylesheet" href="/static/sidebar.css">',
        ""
    ).replace(
        '<link rel="stylesheet" href="/static/toolbox.css">',
        inlined_styles
    )

    return raw_html


class TestCropClampingAndLayoutAdversarial(unittest.TestCase):
    """Deep empirical verification using Edge Chromium WebView2."""

    @classmethod
    def setUpClass(cls):
        cls.html_content = build_self_contained_html("dark")
        cls.test_results: Dict[str, Any] = {}

        def _runner(window):
            try:
                script = """
                (() => {
                    const out = {
                        clamping: {},
                        blurEventSync: {},
                        viewports: [],
                        stickyStress: {}
                    };

                    const headerSlider = document.getElementById('headerSlider');
                    const footerSlider = document.getElementById('footerSlider');
                    const leftSlider = document.getElementById('leftSlider');
                    const rightSlider = document.getElementById('rightSlider');

                    const headerNumInput = document.getElementById('headerNumInput');
                    const footerNumInput = document.getElementById('footerNumInput');
                    const leftNumInput = document.getElementById('leftNumInput');
                    const rightNumInput = document.getElementById('rightNumInput');

                    const cropOverlayBox = document.getElementById('cropOverlayBox');
                    const resetCropBtn = document.getElementById('resetCropBtn');

                    // Helper to reset
                    function doReset() {
                        if (resetCropBtn) resetCropBtn.click();
                    }

                    // 1. Comprehensive Clamping Matrix (change event)
                    // Test cases for all 4 inputs with various boundary / out-of-bounds values
                    const testCases = [
                        // Top (max 0.45, min 0.0)
                        { input: headerNumInput, slider: headerSlider, dir: 'top', val: '0.80', expectedNum: '0.45', expectedSlider: 0.45, name: 'top_overflow_0.80' },
                        { input: headerNumInput, slider: headerSlider, dir: 'top', val: '1.50', expectedNum: '0.45', expectedSlider: 0.45, name: 'top_overflow_1.50' },
                        { input: headerNumInput, slider: headerSlider, dir: 'top', val: '-0.20', expectedNum: '0.00', expectedSlider: 0.0, name: 'top_underflow_-0.20' },
                        { input: headerNumInput, slider: headerSlider, dir: 'top', val: '0.45', expectedNum: '0.45', expectedSlider: 0.45, name: 'top_exact_max' },
                        { input: headerNumInput, slider: headerSlider, dir: 'top', val: '0.00', expectedNum: '0.00', expectedSlider: 0.0, name: 'top_exact_min' },

                        // Bottom (max 0.45, min 0.0)
                        { input: footerNumInput, slider: footerSlider, dir: 'bottom', val: '0.99', expectedNum: '0.45', expectedSlider: 0.45, name: 'bottom_overflow_0.99' },
                        { input: footerNumInput, slider: footerSlider, dir: 'bottom', val: '-0.35', expectedNum: '0.00', expectedSlider: 0.0, name: 'bottom_underflow_-0.35' },
                        { input: footerNumInput, slider: footerSlider, dir: 'bottom', val: '0.33', expectedNum: '0.33', expectedSlider: 0.33, name: 'bottom_in_range_0.33' },

                        // Left (max 0.30, min 0.0)
                        { input: leftNumInput, slider: leftSlider, dir: 'left', val: '0.45', expectedNum: '0.30', expectedSlider: 0.30, name: 'left_overflow_0.45' },
                        { input: leftNumInput, slider: leftSlider, dir: 'left', val: '0.99', expectedNum: '0.30', expectedSlider: 0.30, name: 'left_overflow_0.99' },
                        { input: leftNumInput, slider: leftSlider, dir: 'left', val: '-0.10', expectedNum: '0.00', expectedSlider: 0.0, name: 'left_underflow_-0.10' },
                        { input: leftNumInput, slider: leftSlider, dir: 'left', val: '0.25', expectedNum: '0.25', expectedSlider: 0.25, name: 'left_in_range_0.25' },

                        // Right (max 0.30, min 0.0)
                        { input: rightNumInput, slider: rightSlider, dir: 'right', val: '0.50', expectedNum: '0.30', expectedSlider: 0.30, name: 'right_overflow_0.50' },
                        { input: rightNumInput, slider: rightSlider, dir: 'right', val: '-0.50', expectedNum: '0.00', expectedSlider: 0.0, name: 'right_underflow_-0.50' },
                        { input: rightNumInput, slider: rightSlider, dir: 'right', val: '0.15', expectedNum: '0.15', expectedSlider: 0.15, name: 'right_in_range_0.15' },

                        // Non-numeric / NaN / Empty
                        { input: headerNumInput, slider: headerSlider, dir: 'top', val: '', expectedNum: '0.00', expectedSlider: 0.0, name: 'top_empty_string' },
                        { input: footerNumInput, slider: footerSlider, dir: 'bottom', val: 'invalid', expectedNum: '0.00', expectedSlider: 0.0, name: 'bottom_invalid_text' }
                    ];

                    for (const tc of testCases) {
                        doReset();
                        tc.input.value = tc.val;
                        tc.input.dispatchEvent(new Event('change', { bubbles: true }));

                        out.clamping[tc.name] = {
                            numValue: tc.input.value,
                            sliderValue: parseFloat(tc.slider.value),
                            expectedNum: tc.expectedNum,
                            expectedSlider: tc.expectedSlider,
                            numMatchesExpected: tc.input.value === tc.expectedNum,
                            sliderMatchesExpected: Math.abs(parseFloat(tc.slider.value) - tc.expectedSlider) < 1e-4,
                            inSync: Math.abs(parseFloat(tc.input.value) - parseFloat(tc.slider.value)) < 1e-4
                        };
                    }

                    // 2. Opposing Sum Constraints (> 0.85)
                    // Case A: Footer = 0.45, then Header set to 0.45 -> Header must clamp to 0.40 (0.85 - 0.45)
                    doReset();
                    footerNumInput.value = '0.45';
                    footerNumInput.dispatchEvent(new Event('change', { bubbles: true }));
                    headerNumInput.value = '0.45';
                    headerNumInput.dispatchEvent(new Event('change', { bubbles: true }));

                    out.clamping['opposing_sum_top_clamped'] = {
                        headerNum: headerNumInput.value,
                        headerSlider: parseFloat(headerSlider.value),
                        footerNum: footerNumInput.value,
                        footerSlider: parseFloat(footerSlider.value),
                        sum: parseFloat(headerNumInput.value) + parseFloat(footerNumInput.value),
                        inSync: Math.abs(parseFloat(headerNumInput.value) - parseFloat(headerSlider.value)) < 1e-4
                    };

                    // Case B: Header = 0.45, then Footer set to 0.45 -> Footer must clamp to 0.40 (0.85 - 0.45)
                    doReset();
                    headerNumInput.value = '0.45';
                    headerNumInput.dispatchEvent(new Event('change', { bubbles: true }));
                    footerNumInput.value = '0.45';
                    footerNumInput.dispatchEvent(new Event('change', { bubbles: true }));

                    out.clamping['opposing_sum_bottom_clamped'] = {
                        headerNum: headerNumInput.value,
                        headerSlider: parseFloat(headerSlider.value),
                        footerNum: footerNumInput.value,
                        footerSlider: parseFloat(footerSlider.value),
                        sum: parseFloat(headerNumInput.value) + parseFloat(footerNumInput.value),
                        inSync: Math.abs(parseFloat(footerNumInput.value) - parseFloat(footerSlider.value)) < 1e-4
                    };

                    // 3. Blur event clamping (user types and clicks away without pressing Enter)
                    const blurCases = [
                        { input: headerNumInput, slider: headerSlider, val: '0.90', expected: '0.45', name: 'blur_top_0.90' },
                        { input: footerNumInput, slider: footerSlider, val: '-0.20', expected: '0.00', name: 'blur_bottom_-0.20' },
                        { input: leftNumInput, slider: leftSlider, val: '0.50', expected: '0.30', name: 'blur_left_0.50' },
                        { input: rightNumInput, slider: rightSlider, val: '-0.08', expected: '0.00', name: 'blur_right_-0.08' }
                    ];

                    for (const bc of blurCases) {
                        doReset();
                        bc.input.value = bc.val;
                        bc.input.dispatchEvent(new Event('blur', { bubbles: true }));

                        out.blurEventSync[bc.name] = {
                            numValue: bc.input.value,
                            sliderValue: parseFloat(bc.slider.value),
                            expected: bc.expected,
                            inSync: Math.abs(parseFloat(bc.input.value) - parseFloat(bc.slider.value)) < 1e-4,
                            clamped: bc.input.value === bc.expected
                        };
                    }

                    // 4. Viewport Layout & Sticky Scrolling Ergonomics
                    const container = document.querySelector('.workbench-container');
                    const layout = document.querySelector('.workbench-layout');
                    const inspector = document.getElementById('workbenchInspectorPane');
                    const canvas = document.getElementById('canvasPane');

                    const targetViewports = [
                        { name: '1080p', w: 1920, h: 1080 },
                        { name: '900p',  w: 1440, h: 900 },
                        { name: '768p',  w: 1366, h: 768 }
                    ];

                    for (const vp of targetViewports) {
                        container.style.width = (vp.w - 32) + 'px';
                        document.documentElement.style.height = vp.h + 'px';
                        document.body.style.height = vp.h + 'px';

                        const compInspector = window.getComputedStyle(inspector);
                        const compLayout = window.getComputedStyle(layout);
                        const inspectorRect = inspector.getBoundingClientRect();
                        const canvasRect = canvas.getBoundingClientRect();

                        out.viewports.push({
                            viewport: vp.name,
                            w: vp.w,
                            h: vp.h,
                            position: compInspector.position,
                            top: compInspector.top,
                            maxHeight: compInspector.maxHeight,
                            overflowY: compInspector.overflowY,
                            inspectorWidth: inspectorRect.width,
                            canvasWidth: canvasRect.width,
                            isSideBySide: canvasRect.right <= inspectorRect.left + 10,
                            hasHorizontalOverflow: document.documentElement.scrollWidth > vp.w
                        });
                    }

                    // Reset container
                    container.style.width = '';
                    document.documentElement.style.height = '';
                    document.body.style.height = '';

                    // 5. Sticky scroll stress test: expand all tiers and simulate page scroll
                    const advTrigger = document.getElementById('tierAdvancedTrigger');
                    const engTrigger = document.getElementById('tierEngineerTrigger');
                    if (advTrigger && advTrigger.getAttribute('aria-expanded') !== 'true') advTrigger.click();
                    if (engTrigger && engTrigger.getAttribute('aria-expanded') !== 'true') engTrigger.click();

                    const feedback = document.getElementById('pipelineFeedbackPanel');
                    feedback.style.display = 'block';
                    feedback.innerHTML = '<div style="height: 500px;">Adversarial Stress Log</div>';

                    const inspectorScrollHeight = inspector.scrollHeight;
                    const inspectorClientHeight = inspector.clientHeight;

                    // Scroll inspector pane internally
                    inspector.scrollTop = 200;
                    const scrolledInside = inspector.scrollTop;

                    out.stickyStress = {
                        inspectorScrollHeight,
                        inspectorClientHeight,
                        isScrollable: inspectorScrollHeight > inspectorClientHeight,
                        scrolledInside,
                        positionStyle: window.getComputedStyle(inspector).position,
                        overflowYStyle: window.getComputedStyle(inspector).overflowY
                    };

                    return out;
                })();
                """
                res = window.evaluate_js(script)
                cls.test_results = res
            finally:
                window.destroy()

        window = webview.create_window(
            "Empirical Adversarial Test",
            html=cls.html_content,
            hidden=True,
            width=1920,
            height=1080
        )
        webview.start(_runner, window, gui="edgechromium")

    def test_clamping_and_synchronization_on_change(self):
        """Empirically test clamping and bidirectional sync across all 4 number inputs on 'change'."""
        clamping = self.test_results.get("clamping", {})
        self.assertTrue(bool(clamping), "Clamping test results must not be empty")

        for name, data in clamping.items():
            with self.subTest(case=name):
                if name.startswith("opposing_sum"):
                    self.assertAlmostEqual(
                        data["sum"], 0.85, delta=1e-4,
                        msg=f"Opposing sum in {name} must clamp to 0.85"
                    )
                    self.assertTrue(
                        data["inSync"],
                        f"Slider and input must stay in sync for {name}"
                    )
                else:
                    self.assertTrue(
                        data["numMatchesExpected"],
                        f"Number input for {name} was {data['numValue']}, expected {data['expectedNum']}"
                    )
                    self.assertTrue(
                        data["sliderMatchesExpected"],
                        f"Slider for {name} was {data['sliderValue']}, expected {data['expectedSlider']}"
                    )
                    self.assertTrue(
                        data["inSync"],
                        f"Number input and slider desynchronized for {name}: num={data['numValue']} vs slider={data['sliderValue']}"
                    )

    def test_clamping_and_synchronization_on_blur(self):
        """Empirically test that committing out-of-bounds numbers triggers immediate clamp and sync on 'blur'."""
        blur_sync = self.test_results.get("blurEventSync", {})
        self.assertTrue(bool(blur_sync), "Blur sync results must not be empty")

        for name, data in blur_sync.items():
            with self.subTest(case=name):
                self.assertTrue(
                    data["clamped"],
                    f"Number input on blur for {name} must clamp to {data['expected']}, got {data['numValue']}"
                )
                self.assertTrue(
                    data["inSync"],
                    f"Slider and number input must be in sync on blur for {name}: num={data['numValue']}, slider={data['sliderValue']}"
                )

    def test_desktop_viewports_ergonomics_and_sticky(self):
        """Empirically test 1920x1080, 1440x900, and 1366x768 desktop viewports."""
        viewports = self.test_results.get("viewports", [])
        self.assertEqual(len(viewports), 3, "Must test 3 viewports: 1080p, 900p, 768p")

        for vp in viewports:
            name = vp["viewport"]
            with self.subTest(viewport=name):
                self.assertTrue(
                    vp["isSideBySide"],
                    f"Layout in {name} must be side-by-side (canvas and inspector)"
                )
                self.assertIn(
                    "sticky",
                    vp["position"],
                    f"Inspector in {name} must be position: sticky"
                )
                self.assertEqual(
                    vp["overflowY"],
                    "auto",
                    f"Inspector in {name} must have overflow-y: auto"
                )
                self.assertAlmostEqual(
                    vp["inspectorWidth"],
                    440.0,
                    delta=15.0,
                    msg=f"Inspector width in {name} must be 440px"
                )

    def test_sticky_internal_scrolling(self):
        """Empirically test that inspector maintains internal scroll containment without breaking page layout."""
        sticky = self.test_results.get("stickyStress", {})
        self.assertTrue(
            sticky.get("isScrollable"),
            "When expanded, inspector must become internally scrollable"
        )
        self.assertGreater(
            sticky.get("scrolledInside", 0),
            0,
            "Inspector must allow scrolling internally"
        )
        self.assertIn("sticky", sticky.get("positionStyle", ""))
        self.assertEqual(sticky.get("overflowYStyle"), "auto")


if __name__ == "__main__":
    unittest.main()
