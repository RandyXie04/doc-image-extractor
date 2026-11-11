# -*- coding: utf-8 -*-
"""
Empirical Stress Test Suite: OCR Workbench Layout Ergonomics, DOM Anchoring,
2x2 Crop Grid Synchronization & Processing State Interactivity
=============================================================================
Author: Challenger Instance 2
Target: src/web/static/ocr_pipeline.html, src/web/static/toolbox.css, src/web/static/sidebar.css
"""

from __future__ import annotations

import json
import math
import re
import unittest
from pathlib import Path
from typing import Any, Dict

import webview


REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "src" / "web" / "static"
HTML_FILE = STATIC_DIR / "ocr_pipeline.html"
TOOLBOX_CSS_FILE = STATIC_DIR / "toolbox.css"
SIDEBAR_CSS_FILE = STATIC_DIR / "sidebar.css"


def build_self_contained_html(theme: str = "dark") -> str:
    """Build self-contained HTML embedding stylesheets and test helpers."""
    raw_html = HTML_FILE.read_text(encoding="utf-8")
    sidebar_css = SIDEBAR_CSS_FILE.read_text(encoding="utf-8")
    toolbox_css = TOOLBOX_CSS_FILE.read_text(encoding="utf-8")

    # Force theme
    raw_html = re.sub(
        r'<html[^>]*>',
        f'<html lang="zh-TW" data-theme="{theme}">',
        raw_html,
        count=1
    )

    # Inline styles to avoid file:// protocol origin issues
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


class TestOcrWorkbenchEmpiricalStress(unittest.TestCase):
    """Empirical verification harness executing via Microsoft Edge WebView2."""

    @classmethod
    def setUpClass(cls):
        cls.html_content = build_self_contained_html("dark")
        cls.test_results: Dict[str, Any] = {}

        def _runner(window):
            try:
                # Execute layout ergonomics, scroll geometry, crop sync, and processing interactivity
                script = """
                (() => {
                    try {
                        const res = {};
                        const inspector = document.getElementById('workbenchInspectorPane');
                        const canvas = document.getElementById('canvasPane');
                        const layout = document.querySelector('.workbench-layout');
                        const container = document.querySelector('.workbench-container');

                        // 1. Viewports layout ergonomics
                        const viewports = [
                            { name: '1080p', w: 1920, h: 1080 },
                            { name: '900p',  w: 1440, h: 900 },
                            { name: '768p',  w: 1366, h: 768 }
                        ];

                        res.viewports = [];

                        for (const vp of viewports) {
                            container.style.width = (vp.w - 32) + 'px';
                            document.documentElement.style.height = vp.h + 'px';
                            document.body.style.height = vp.h + 'px';

                            const compInspector = window.getComputedStyle(inspector);
                            const compLayout = window.getComputedStyle(layout);

                            const inspectorRect = inspector.getBoundingClientRect();
                            const canvasRect = canvas.getBoundingClientRect();

                            res.viewports.push({
                                viewport: vp.name,
                                width: vp.w,
                                height: vp.h,
                                layoutGridCols: compLayout.gridTemplateColumns,
                                inspectorPosition: compInspector.position,
                                inspectorTop: compInspector.top,
                                inspectorMaxHeight: compInspector.maxHeight,
                                inspectorOverflowY: compInspector.overflowY,
                                inspectorWidth: inspectorRect.width,
                                canvasWidth: canvasRect.width,
                                inspectorClientHeight: inspector.clientHeight,
                                isSideBySide: (canvasRect.right <= inspectorRect.left + 5) && (Math.abs(canvasRect.top - inspectorRect.top) < 30)
                            });
                        }

                        // Reset container sizing
                        container.style.width = '';
                        document.documentElement.style.height = '';
                        document.body.style.height = '';

                        // 2. Scroll containment and left canvas anchoring
                        const advTrigger = document.getElementById('tierAdvancedTrigger');
                        const engTrigger = document.getElementById('tierEngineerTrigger');
                        const feedback = document.getElementById('pipelineFeedbackPanel');
                        const resultSummary = document.getElementById('pipelineResultSummary');

                        if (advTrigger && advTrigger.getAttribute('aria-expanded') !== 'true') advTrigger.click();
                        if (engTrigger && engTrigger.getAttribute('aria-expanded') !== 'true') engTrigger.click();

                        feedback.style.display = 'block';
                        resultSummary.style.display = 'block';
                        resultSummary.innerHTML = '<div style="height: 600px;">Adversarial Stress Content</div>';

                        const hugeScrollHeight = inspector.scrollHeight;
                        const constrainedClientHeight = inspector.clientHeight;
                        const compMaxHeight = window.getComputedStyle(inspector).maxHeight;

                        inspector.scrollTop = 150;
                        const scrolledTop = inspector.scrollTop;

                        const canvasBeforeScroll = canvas.getBoundingClientRect();
                        inspector.scrollTop = 350;
                        const canvasAfterScroll = canvas.getBoundingClientRect();

                        res.scrolling = {
                            hugeScrollHeight,
                            constrainedClientHeight,
                            isConstrained: constrainedClientHeight < hugeScrollHeight,
                            compMaxHeight,
                            scrolledTop,
                            canvasAnchored: (canvasBeforeScroll.top === canvasAfterScroll.top) && (canvasBeforeScroll.left === canvasAfterScroll.left)
                        };

                        // 3. Crop Controls
                        const headerSlider = document.getElementById('headerSlider');
                        const footerSlider = document.getElementById('footerSlider');
                        const leftSlider = document.getElementById('leftSlider');
                        const rightSlider = document.getElementById('rightSlider');

                        const headerNumInput = document.getElementById('headerNumInput');
                        const footerNumInput = document.getElementById('footerNumInput');
                        const leftNumInput = document.getElementById('leftNumInput');
                        const rightNumInput = document.getElementById('rightNumInput');

                        const headerVal = document.getElementById('headerVal');
                        const footerVal = document.getElementById('footerVal');
                        const leftVal = document.getElementById('leftVal');
                        const rightVal = document.getElementById('rightVal');

                        const cropOverlayBox = document.getElementById('cropOverlayBox');
                        const resetCropBtn = document.getElementById('resetCropBtn');

                        res.cropSync = {};

                        // 3A. Valid in-bounds synchronization: Sliders -> Numbers
                        headerSlider.value = '0.22';
                        headerSlider.dispatchEvent(new Event('input', { bubbles: true }));
                        footerSlider.value = '0.18';
                        footerSlider.dispatchEvent(new Event('input', { bubbles: true }));
                        leftSlider.value = '0.12';
                        leftSlider.dispatchEvent(new Event('input', { bubbles: true }));
                        rightSlider.value = '0.14';
                        rightSlider.dispatchEvent(new Event('input', { bubbles: true }));

                        res.cropSync.sliderToNumber = {
                            topNum: headerNumInput.value,
                            bottomNum: footerNumInput.value,
                            leftNum: leftNumInput.value,
                            rightNum: rightNumInput.value,
                            topValText: headerVal.textContent,
                            bottomValText: footerVal.textContent,
                            leftValText: leftVal.textContent,
                            rightValText: rightVal.textContent,
                            overlayTop: cropOverlayBox.style.top,
                            overlayBottom: cropOverlayBox.style.bottom,
                            overlayLeft: cropOverlayBox.style.left,
                            overlayRight: cropOverlayBox.style.right
                        };

                        // 3B. Valid in-bounds synchronization: Numbers -> Sliders
                        headerNumInput.value = '0.30';
                        headerNumInput.dispatchEvent(new Event('change', { bubbles: true }));
                        footerNumInput.value = '0.25';
                        footerNumInput.dispatchEvent(new Event('change', { bubbles: true }));
                        leftNumInput.value = '0.20';
                        leftNumInput.dispatchEvent(new Event('change', { bubbles: true }));
                        rightNumInput.value = '0.08';
                        rightNumInput.dispatchEvent(new Event('change', { bubbles: true }));

                        res.cropSync.numberToSlider = {
                            topSlider: headerSlider.value,
                            bottomSlider: footerSlider.value,
                            leftSlider: leftSlider.value,
                            rightSlider: rightSlider.value,
                            topValText: headerVal.textContent,
                            bottomValText: footerVal.textContent,
                            leftValText: leftVal.textContent,
                            rightValText: rightVal.textContent
                        };

                        // 3C. Reset Crop Button
                        resetCropBtn.click();
                        res.cropSync.reset = {
                            topNum: headerNumInput.value,
                            bottomNum: footerNumInput.value,
                            leftNum: leftNumInput.value,
                            rightNum: rightNumInput.value,
                            topSlider: headerSlider.value,
                            bottomSlider: footerSlider.value,
                            leftSlider: leftSlider.value,
                            rightSlider: rightSlider.value
                        };

                        // 3D. Adversarial Constraint Testing (Clamping and Sync Verification)
                        // Case I: Upper bound violation (0.80 > 0.45)
                        headerNumInput.value = '0.80';
                        headerNumInput.dispatchEvent(new Event('change', { bubbles: true }));
                        const case1_hNum = headerNumInput.value;
                        const case1_hSlider = headerSlider.value;
                        const case1_desync = Math.abs(parseFloat(case1_hNum) - parseFloat(case1_hSlider)) > 1e-4;

                        // Case II: Negative number input (-0.15 < 0)
                        footerNumInput.value = '-0.15';
                        footerNumInput.dispatchEvent(new Event('change', { bubbles: true }));
                        const case2_fNum = footerNumInput.value;
                        const case2_fSlider = footerSlider.value;
                        const case2_desync = Math.abs(parseFloat(case2_fNum) - parseFloat(case2_fSlider)) > 1e-4;

                        // Case III: Opposing sum constraint (top 0.45 + bottom 0.45 = 0.90 > 0.85)
                        headerNumInput.value = '0.45';
                        headerNumInput.dispatchEvent(new Event('change', { bubbles: true }));
                        footerNumInput.value = '0.45';
                        footerNumInput.dispatchEvent(new Event('change', { bubbles: true }));
                        const case3_fNum = footerNumInput.value;
                        const case3_fSlider = footerSlider.value;
                        const case3_desync = Math.abs(parseFloat(case3_fNum) - parseFloat(case3_fSlider)) > 1e-4;

                        res.cropSync.adversarial = {
                            case1: { num: case1_hNum, slider: case1_hSlider, desynced: case1_desync },
                            case2: { num: case2_fNum, slider: case2_fSlider, desynced: case2_desync },
                            case3: { num: case3_fNum, slider: case3_fSlider, desynced: case3_desync }
                        };

                        // 4. Read-only processing state and interactivity test
                        const cancelBtn = document.getElementById('cancelTaskBtn');
                        cancelBtn.style.display = 'inline-block';

                        let cancelClicked = false;
                        cancelBtn.onclick = () => { cancelClicked = true; };

                        // Enter processing mode
                        setInspectorReadonly(true);

                        const sectionPointerEvents = window.getComputedStyle(document.querySelector('.inspector-section.tier-basic')).pointerEvents;
                        const feedbackPointerEvents = window.getComputedStyle(feedback).pointerEvents;
                        const cancelBtnPointerEvents = window.getComputedStyle(cancelBtn).pointerEvents;

                        const submitBtn = document.getElementById('submitBtn');
                        const isSubmitDisabled = submitBtn.disabled;
                        const isCancelDisabled = cancelBtn.disabled;

                        // Click cancel button while in processing state
                        cancelBtn.click();

                        const inspectorHasProcessingClass = inspector.classList.contains('is-processing');

                        // Revert processing state
                        setInspectorReadonly(false);
                        const revertedSubmitDisabled = submitBtn.disabled;

                        res.processingState = {
                            inspectorHasProcessingClass,
                            sectionPointerEvents,
                            feedbackPointerEvents,
                            cancelBtnPointerEvents,
                            isSubmitDisabled,
                            isCancelDisabled,
                            cancelClicked,
                            revertedSubmitDisabled
                        };

                        return res;
                    } catch (err) {
                        return { error: err.stack || err.toString() };
                    }
                })();
                """

                res = window.evaluate_js(script)
                cls.test_results = res
            finally:
                window.destroy()

        window = webview.create_window(
            "Empirical Stress Test",
            html=cls.html_content,
            hidden=True,
            width=1920,
            height=1080
        )
        webview.start(_runner, window, gui="edgechromium")

    def test_viewports_layout_ergonomics(self):
        """Stress test 1920x1080, 1440x900, and 1366x768 desktop viewports."""
        vp_results = self.test_results.get("viewports", [])
        self.assertEqual(len(vp_results), 3, "All 3 viewports must be evaluated")

        for vp in vp_results:
            name = vp["viewport"]
            with self.subTest(viewport=name):
                # Verify 2-column side-by-side grid
                self.assertTrue(
                    vp["isSideBySide"],
                    f"Canvas and Inspector must be side-by-side in {name}"
                )
                self.assertAlmostEqual(
                    vp["inspectorWidth"],
                    440.0,
                    delta=15.0,
                    msg=f"Inspector width in {name} should be ~440px"
                )
                self.assertIn(
                    "sticky",
                    vp["inspectorPosition"],
                    f"Inspector in {name} must have position: sticky"
                )
                self.assertEqual(
                    vp["inspectorOverflowY"],
                    "auto",
                    f"Inspector in {name} must have overflow-y: auto"
                )

    def test_scroll_containment_and_canvas_anchoring(self):
        """Empirically verify inspector scrolling doesn't break canvas anchoring."""
        scrolling = self.test_results.get("scrolling", {})
        self.assertTrue(
            scrolling.get("isConstrained"),
            "When content exceeds viewport, inspector clientHeight must be constrained by maxHeight"
        )
        self.assertGreater(
            scrolling.get("hugeScrollHeight", 0),
            scrolling.get("constrainedClientHeight", 0),
            "scrollHeight must exceed clientHeight when content is large"
        )
        self.assertGreater(
            scrolling.get("scrolledTop", 0),
            0,
            "Inspector internal scrollbar must be scrollable"
        )
        self.assertTrue(
            scrolling.get("canvasAnchored"),
            "Left canvas pane must remain anchored and motionless when inspector scrolls"
        )

    def test_crop_grid_bidirectional_sync_in_bounds(self):
        """Verify 2x2 crop grid bidirectional synchronization for valid within-bounds inputs."""
        crop = self.test_results.get("cropSync", {})

        # Slider -> Number
        s2n = crop.get("sliderToNumber", {})
        self.assertEqual(s2n.get("topNum"), "0.22")
        self.assertEqual(s2n.get("bottomNum"), "0.18")
        self.assertEqual(s2n.get("leftNum"), "0.12")
        self.assertEqual(s2n.get("rightNum"), "0.14")
        self.assertEqual(s2n.get("topValText"), "0.22")
        self.assertEqual(s2n.get("overlayTop"), "22%")
        self.assertEqual(s2n.get("overlayBottom"), "18%")

        # Number -> Slider
        n2s = crop.get("numberToSlider", {})
        self.assertEqual(float(n2s.get("topSlider")), 0.30)
        self.assertEqual(float(n2s.get("bottomSlider")), 0.25)
        self.assertEqual(float(n2s.get("leftSlider")), 0.20)
        self.assertEqual(float(n2s.get("rightSlider")), 0.08)
        self.assertEqual(n2s.get("topValText"), "0.30")

        # Reset button
        rst = crop.get("reset", {})
        self.assertEqual(rst.get("topNum"), "0.10")
        self.assertEqual(rst.get("bottomNum"), "0.10")
        self.assertEqual(rst.get("leftNum"), "0.00")
        self.assertEqual(rst.get("rightNum"), "0.00")

    def test_adversarial_crop_desync_on_out_of_bounds_inputs(self):
        """
        Verify that out-of-bounds inputs in number inputs are properly clamped
        and synchronized with sliders, completely eliminating desynchronization.
        """
        crop = self.test_results.get("cropSync", {})
        adv = crop.get("adversarial", {})

        # Case 1: Upper bound overflow (0.80 > 0.45) clamped to 0.45
        case1 = adv.get("case1", {})
        self.assertEqual(case1.get("num"), "0.45")
        self.assertEqual(case1.get("slider"), "0.45")
        self.assertFalse(
            case1.get("desynced"),
            "Number input and slider must both be clamped to 0.45"
        )

        # Case 2: Negative input (-0.15 < 0) clamped to 0.00
        case2 = adv.get("case2", {})
        self.assertEqual(case2.get("num"), "0.00")
        self.assertEqual(float(case2.get("slider")), 0.0)
        self.assertFalse(
            case2.get("desynced"),
            "Number input and slider must both be clamped to 0.00"
        )

        # Case 3: Opposing sum constraint (0.45 + 0.45 = 0.90 > 0.85) clamped to 0.40
        case3 = adv.get("case3", {})
        self.assertEqual(case3.get("num"), "0.40")
        self.assertEqual(float(case3.get("slider")), 0.40)
        self.assertFalse(
            case3.get("desynced"),
            "Number input and slider must both be clamped to 0.40"
        )

    def test_processing_state_interactivity(self):
        """Verify #cancelTaskBtn and #pipelineFeedbackPanel remain interactable during processing."""
        proc = self.test_results.get("processingState", {})
        self.assertEqual(
            proc.get("sectionPointerEvents"),
            "none",
            "Form settings sections must be pointer-events: none during processing"
        )
        self.assertEqual(
            proc.get("feedbackPointerEvents"),
            "auto",
            "Feedback panel MUST remain pointer-events: auto"
        )
        self.assertEqual(
            proc.get("cancelBtnPointerEvents"),
            "auto",
            "Cancel button MUST remain pointer-events: auto"
        )
        self.assertTrue(
            proc.get("isSubmitDisabled"),
            "Settings submit button must be disabled during processing"
        )
        self.assertFalse(
            proc.get("isCancelDisabled"),
            "Cancel button must NEVER be disabled during processing"
        )
        self.assertTrue(
            proc.get("cancelClicked"),
            "Cancel button MUST successfully trigger click handler during processing"
        )


if __name__ == "__main__":
    unittest.main()
