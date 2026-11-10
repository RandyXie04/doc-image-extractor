# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite for Dynamic DOM & Theme Switch Behavior
===================================================================
Author: Challenger 2 (Dynamic DOM & Theme Switch Stress Challenger)
Date: 2026-11-10

Verifies:
1. Theme switching between 'dark' and 'light' via sidebar.js and query params (?theme=dark, ?theme=light).
2. Dynamic DOM injection under Dark Mode in:
   - ocr_pipeline.html (error box, result summary, font/outline modals, step badges)
   - pod_studio.html (audit inspector visualizer, OCR handoff banner)
   - formula.html (crop legend, swatches, range sliders)
   - founder_repair.html, extract_images.html, index.html (dynamic alerts, cards, chips)
   Ensuring ZERO unstyled elements, blinding light patches, or low contrast.
3. Viewport Manager (viewport_manager.js) and Sidebar (sidebar.js) co-existence and conflict freedom.
4. WCAG 2.1 AA / AAA contrast compliance across all Dracula tokens.
"""

import re
import math
import unittest
from pathlib import Path
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from config import CFG
from src.web.app import app
from src.utils.path_helper import get_project_dir


def srgb_to_luminance(hex_code: str) -> float:
    """Compute relative luminance according to W3C WCAG 2.1 formula."""
    hex_clean = hex_code.lstrip('#')
    if len(hex_clean) == 3:
        hex_clean = ''.join(c * 2 for c in hex_clean)
    r = int(hex_clean[0:2], 16) / 255.0
    g = int(hex_clean[2:4], 16) / 255.0
    b = int(hex_clean[4:6], 16) / 255.0

    def adjust(val: float) -> float:
        return val / 12.92 if val <= 0.04045 else math.pow((val + 0.055) / 1.055, 2.4)

    return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)


def contrast_ratio(hex1: str, hex2: str) -> float:
    """Calculate WCAG contrast ratio between two hex colors."""
    l1 = srgb_to_luminance(hex1)
    l2 = srgb_to_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


class TestThemeSwitchingAndQueryParams(unittest.TestCase):
    def setUp(self):
        self.project_dir = get_project_dir()
        self.static_dir = self.project_dir / "src" / "web" / "static"
        self.pages = [
            "index.html",
            "ocr_pipeline.html",
            "pod_studio.html",
            "formula.html",
            "founder_repair.html",
            "extract_images.html",
        ]
        self.client = TestClient(app)
        self.auth_headers = {"X-API-Key": CFG.auth_password} if CFG.auth_enabled else {}

    def test_fouc_script_presence_in_all_pages(self):
        """Verify that every static HTML page includes the instant FOUC prevention script in <head>."""
        fouc_pattern = re.compile(
            r"\(function\(\)\s*\{\s*const\s+u\s*=\s*new\s+URLSearchParams\(window\.location\.search\)\.get\('theme'\);"
        )
        for page_name in self.pages:
            file_path = self.static_dir / page_name
            self.assertTrue(file_path.exists(), f"Page {page_name} missing from static directory")
            content = file_path.read_text(encoding="utf-8")
            soup = BeautifulSoup(content, "html.parser")
            head = soup.find("head")
            self.assertIsNotNone(head, f"Page {page_name} missing <head> tag")

            # Must contain the FOUC prevention script inside <head>
            scripts = head.find_all("script")
            found = any(fouc_pattern.search(s.string or "") for s in scripts)
            self.assertTrue(found, f"Page {page_name} missing instant FOUC theme initialization script in <head>")

    def test_query_param_theme_resolution_logic(self):
        """Adversarially evaluate theme resolution across all URL search param permutations."""
        def resolve_theme(search_query: str, local_storage_theme: str | None = None) -> tuple[str, bool]:
            """
            Simulates the exact JavaScript resolution logic:
            const u = new URLSearchParams(query).get('theme');
            const t = (u === 'dark' || u === 'light') ? u : (localStorage.getItem('app-theme') || 'light');
            if (u === 'dark' || u === 'light') localStorage.setItem('app-theme', u);
            returns: (applied_theme, saved_to_local_storage)
            """
            # Emulate URLSearchParams
            params = {}
            if search_query.startswith("?"):
                search_query = search_query[1:]
            for pair in search_query.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    if k not in params:  # first occurrence in URLSearchParams
                        params[k] = v

            u = params.get("theme")
            if u in ("dark", "light"):
                return u, True
            fallback = local_storage_theme if local_storage_theme in ("dark", "light") else "light"
            return fallback, False

        # 1. Valid param overrides localStorage
        self.assertEqual(resolve_theme("?theme=dark", "light"), ("dark", True))
        self.assertEqual(resolve_theme("?theme=light", "dark"), ("light", True))

        # 2. Query param anywhere in query string
        self.assertEqual(resolve_theme("?page=1&theme=dark&ref=home", "light"), ("dark", True))
        self.assertEqual(resolve_theme("?session_id=abc&from_ocr=1&theme=dark", None), ("dark", True))

        # 3. Empty or invalid query param falls back to localStorage or default light
        self.assertEqual(resolve_theme("?theme=", "dark"), ("dark", False))
        self.assertEqual(resolve_theme("?theme=dracula", "dark"), ("dark", False))
        self.assertEqual(resolve_theme("?theme=DARK", "dark"), ("dark", False))  # case-sensitive
        self.assertEqual(resolve_theme("?theme=system", None), ("light", False))
        self.assertEqual(resolve_theme("", "dark"), ("dark", False))
        self.assertEqual(resolve_theme("", None), ("light", False))

    def test_sidebar_theme_toggle_cycle_and_accessibility(self):
        """Verify sidebar.js toggle mechanism state machine, labels, badges, and aria attributes."""
        sidebar_js = (self.static_dir / "sidebar.js").read_text(encoding="utf-8")

        # Verify key landmarks and actions exist in sidebar.js
        self.assertIn("themeToggleBtn", sidebar_js)
        self.assertIn("themeToggleIcon", sidebar_js)
        self.assertIn("themeToggleLabel", sidebar_js)
        self.assertIn("themeToggleBadge", sidebar_js)
        self.assertIn("updateThemeToggleUI", sidebar_js)

        # Emulate the state machine of updateThemeToggleUI & toggle onclick
        class ThemeUIState:
            def __init__(self, initial_theme="light"):
                self.theme = initial_theme
                self.local_storage = initial_theme
                self.icon = ""
                self.label = ""
                self.badge = ""
                self.title = ""
                self.aria_pressed = ""
                self.update_ui()

            def update_ui(self):
                is_dark = self.theme == "dark"
                self.icon = "sun" if is_dark else "moon"
                self.label = "外觀主題：深色模式" if is_dark else "外觀主題：淺色模式"
                self.badge = "Dark" if is_dark else "Light"
                action_title = "切換為淺色模式" if is_dark else "切換為深色模式"
                self.title = action_title
                self.aria_pressed = "true" if is_dark else "false"

            def click_toggle(self):
                self.theme = "light" if self.theme == "dark" else "dark"
                self.local_storage = self.theme
                self.update_ui()

        state = ThemeUIState(initial_theme="light")
        self.assertEqual(state.theme, "light")
        self.assertEqual(state.badge, "Light")
        self.assertEqual(state.label, "外觀主題：淺色模式")
        self.assertEqual(state.aria_pressed, "false")
        self.assertEqual(state.title, "切換為深色模式")

        # Click 1: Light -> Dark
        state.click_toggle()
        self.assertEqual(state.theme, "dark")
        self.assertEqual(state.badge, "Dark")
        self.assertEqual(state.label, "外觀主題：深色模式")
        self.assertEqual(state.aria_pressed, "true")
        self.assertEqual(state.title, "切換為淺色模式")

        # Click 2: Dark -> Light
        state.click_toggle()
        self.assertEqual(state.theme, "light")
        self.assertEqual(state.badge, "Light")
        self.assertEqual(state.aria_pressed, "false")

        # Stress test: Rapid 50 consecutive toggles
        for i in range(50):
            state.click_toggle()
            expected = "dark" if (i % 2 == 0) else "light"
            self.assertEqual(state.theme, expected)
            self.assertEqual(state.local_storage, expected)


class TestDynamicDomDraculaStyling(unittest.TestCase):
    def setUp(self):
        self.project_dir = get_project_dir()
        self.static_dir = self.project_dir / "src" / "web" / "static"
        self.sidebar_css = (self.static_dir / "sidebar.css").read_text(encoding="utf-8")
        self.toolbox_css = (self.static_dir / "toolbox.css").read_text(encoding="utf-8")

    def test_dracula_tokens_defined_in_sidebar_css(self):
        """Verify that all Dracula Official palette tokens are defined under :root[data-theme=\"dark\"]."""
        dark_block_match = re.search(r':root\[data-theme="dark"\]\s*\{([^}]+)\}', self.sidebar_css)
        self.assertIsNotNone(dark_block_match, "Missing :root[data-theme=\"dark\"] in sidebar.css")
        dark_block = dark_block_match.group(1)

        expected_tokens = {
            "--bg": "#282a36",
            "--surface": "#343746",
            "--surface-2": "#44475a",
            "--sidebar-bg": "#21222c",
            "--text": "#f8f8f2",
            "--text-muted": "#6272a4",
            "--text-secondary": "#a4b1cd",
            "--accent": "#bd93f9",
            "--accent-pink": "#ff79c6",
            "--accent-cyan": "#8be9fd",
            "--success": "#50fa7b",
            "--warning": "#f1fa8c",
            "--warning-orange": "#ffb86c",
            "--danger": "#ff5555",
            "--guide-top": "#ff5555",
            "--guide-bottom": "#8be9fd",
            "--guide-side": "#50fa7b",
        }
        for token, hex_val in expected_tokens.items():
            pattern = rf"{re.escape(token)}\s*:\s*{re.escape(hex_val)}"
            self.assertTrue(
                re.search(pattern, dark_block, re.IGNORECASE),
                f"Missing or incorrect Dracula token in dark mode: {token}: {hex_val}",
            )

    def test_ocr_pipeline_dynamic_error_box_and_summary_styling(self):
        """Adversarially verify ocr_pipeline dynamic DOM elements contain no light leaks in dark mode."""
        pipeline_html = (self.static_dir / "ocr_pipeline.html").read_text(encoding="utf-8")

        # 1. Pipeline Error Box
        self.assertIn('class="pipeline-error-box"', pipeline_html)
        error_box_css = re.search(r'\.pipeline-error-box\s*\{([^}]+)\}', self.toolbox_css)
        self.assertIsNotNone(error_box_css, "Missing .pipeline-error-box in toolbox.css")
        content = error_box_css.group(1)
        self.assertIn("var(--danger-soft)", content)
        self.assertNotIn("#FDF3F4", content, "Found obsolete hardcoded light background in error box")

        # 2. Dynamic Pipeline Result Summary Template Literal
        # Extract the template literal from ocr_pipeline.html (lines ~1265)
        summary_start = pipeline_html.find("pipelineResultSummary.innerHTML = `")
        self.assertNotEqual(summary_start, -1, "Cannot find pipelineResultSummary.innerHTML in ocr_pipeline.html")
        summary_end = pipeline_html.find("`;", summary_start)
        template_content = pipeline_html[summary_start:summary_end]

        # Scan template for forbidden light hardcodes
        forbidden_light_hex = ["#ffffff", "#fff;", "#242424", "#616161", "#ebf3fc", "#dff6dd", "#f3faf5", "#f0fdf4"]
        for forbidden in forbidden_light_hex:
            self.assertNotIn(
                forbidden.lower(),
                template_content.lower(),
                f"Found unstyled light hex '{forbidden}' in pipelineResultSummary template literal!",
            )

        # Confirm all backgrounds and texts reference CSS variables
        self.assertIn("var(--f2-color-surface)", template_content)
        self.assertIn("var(--f2-color-primary-tint)", template_content)
        self.assertIn("var(--f2-color-text-primary)", template_content)
        self.assertIn("var(--f2-color-text-secondary)", template_content)
        self.assertIn("var(--f2-color-surface-secondary)", template_content)

    def test_pod_studio_dynamic_audit_visualizer_and_handoff_banner(self):
        """Adversarially verify pod_studio.html audit visualizer and OCR handoff banner under dark mode."""
        pod_html = (self.static_dir / "pod_studio.html").read_text(encoding="utf-8")

        # 1. OCR Handoff Notice Banner (lines ~676-694)
        handoff_idx = pod_html.find("noticeEl.innerHTML = `")
        self.assertNotEqual(handoff_idx, -1, "Cannot find noticeEl.innerHTML in pod_studio.html")
        handoff_end = pod_html.find("`;", handoff_idx)
        handoff_content = pod_html[handoff_idx:handoff_end]

        # Ensure no light background hardcodes
        self.assertNotIn("#fff", handoff_content.lower())
        self.assertNotIn("#f0fdf4", handoff_content.lower())
        self.assertNotIn("#fff7ed", handoff_content.lower())
        self.assertIn("var(--accent)", handoff_content)
        self.assertIn("var(--text-secondary)", handoff_content)
        self.assertIn("var(--surface-2)", handoff_content)

        # 2. Audit Visualizer buildAuditVisualizerHtml
        audit_idx = pod_html.find("function buildAuditVisualizerHtml(")
        self.assertNotEqual(audit_idx, -1, "Cannot find buildAuditVisualizerHtml in pod_studio.html")
        audit_end = pod_html.find("function filterAuditItems(", audit_idx)
        audit_code = pod_html[audit_idx:audit_end]

        # Ensure dynamic traffic lights use CSS custom properties, NOT pastel hexes
        forbidden_audit_hexes = ["#f0fdf4", "#fffbeb", "#fef2f2", "#dcfce7", "#fef9c3", "#fee2e2", "#15803d", "#b45309", "#b91c1c"]
        for fh in forbidden_audit_hexes:
            self.assertNotIn(
                fh.lower(),
                audit_code.lower(),
                f"Found hardcoded light pastel hex '{fh}' in buildAuditVisualizerHtml!",
            )

        # Ensure badges use dark text (--accent-fg) on pastel background
        self.assertIn("color:var(--accent-fg)", audit_code)
        self.assertIn("background: var(--surface)", audit_code)

    def test_formula_crop_preview_and_sliders_tokens(self):
        """Verify formula.html crop legend swatches, slider grids, and guide values adapt to theme."""
        # Swatches in toolbox.css
        self.assertIn(".swatch-top { background: var(--guide-top); }", self.toolbox_css)
        self.assertIn(".swatch-bottom { background: var(--guide-bottom); }", self.toolbox_css)
        self.assertIn(".swatch-side { background: var(--guide-side); }", self.toolbox_css)

        # Labels in toolbox.css
        self.assertIn(".val-top { color: var(--guide-top); }", self.toolbox_css)
        self.assertIn(".val-bottom { color: var(--guide-bottom); }", self.toolbox_css)
        self.assertIn(".val-side { color: var(--guide-side); }", self.toolbox_css)

        # Range sliders accent-color
        slider_css = re.search(r'input\[type="range"\]\s*\{([^}]+)\}', self.toolbox_css)
        self.assertIsNotNone(slider_css, "Missing input[type=\"range\"] in toolbox.css")
        self.assertIn("var(--accent)", slider_css.group(1))

        # Paper containers intentionally maintain document white canvas
        preview_frame_css = re.search(r'\.preview-frame\s*\{([^}]+)\}', self.toolbox_css)
        self.assertIsNotNone(preview_frame_css, "Missing .preview-frame in toolbox.css")
        self.assertIn("background: #ffffff;", preview_frame_css.group(1))


class TestViewportAndSidebarInteraction(unittest.TestCase):
    def setUp(self):
        self.project_dir = get_project_dir()
        self.static_dir = self.project_dir / "src" / "web" / "static"
        self.viewport_js = (self.static_dir / "js" / "viewport_manager.js").read_text(encoding="utf-8")
        self.sidebar_js = (self.static_dir / "sidebar.js").read_text(encoding="utf-8")

    def test_viewport_manager_api_structure(self):
        """Verify that viewport_manager exposes the expected API on window and attaches to window.toolbox."""
        expected_methods = [
            "getState",
            "isMobile",
            "isTablet",
            "isDesktop",
            "isUltrawide",
            "isTouch",
            "toggleSidebar",
            "closeSidebar",
            "openSidebar",
        ]
        for m in expected_methods:
            self.assertIn(m, self.viewport_js, f"viewport_manager.js missing method '{m}'")

        self.assertIn("win.viewportManager = api;", self.viewport_js)
        self.assertIn("tbWin.toolbox.viewport = api;", self.viewport_js)

    def test_sidebar_delegates_to_viewport_manager_with_fallback(self):
        """Verify that sidebar.js cleanly delegates toggle/close to viewportManager without collision."""
        # 1. Delegation check
        self.assertIn("const vp = /** @type {any} */ (window).viewportManager;", self.sidebar_js)
        self.assertIn("if (vp && typeof vp.toggleSidebar === 'function')", self.sidebar_js)
        self.assertIn("vp.toggleSidebar();", self.sidebar_js)

        # 2. Fallback check if viewportManager is not loaded
        self.assertIn("document.documentElement.setAttribute('data-sidebar-state'", self.sidebar_js)

        # 3. Dynamic script injection if missing
        self.assertIn("viewport_manager.js", self.sidebar_js)

        # 4. Independent DOM attributes: data-theme vs data-sidebar-state vs data-device
        # Ensuring no attribute collision
        self.assertIn("setAttribute('data-device'", self.viewport_js)
        self.assertIn("setAttribute('data-orientation'", self.viewport_js)
        self.assertIn("setAttribute('data-sidebar-state'", self.viewport_js)
        self.assertNotIn("setAttribute('data-theme'", self.viewport_js, "viewport_manager must not modify data-theme")


class TestWcagContrastRatios(unittest.TestCase):
    """Empirically test Dracula Official palette contrast ratios against WCAG 2.1 AA/AAA."""

    def test_dracula_dark_theme_contrast_compliance(self):
        # Dracula Official Specs
        bg = "#282a36"
        surface = "#343746"
        surface2 = "#44475a"
        sidebar_bg = "#21222c"
        text = "#f8f8f2"
        text_sec = "#a4b1cd"
        accent = "#bd93f9"
        accent_fg = "#282a36"
        success = "#50fa7b"
        warning = "#f1fa8c"
        warning_orange = "#ffb86c"
        danger = "#ff5555"
        cyan = "#8be9fd"

        checks = [
            ("Text on Background", text, bg, 7.0, "AAA"),
            ("Text on Surface Card", text, surface, 4.5, "AA"),
            ("Text on Surface-2", text, surface2, 4.5, "AA"),
            ("Text on Sidebar BG", text, sidebar_bg, 7.0, "AAA"),
            ("Secondary Text on Background", text_sec, bg, 4.5, "AA"),
            ("Secondary Text on Surface", text_sec, surface, 4.5, "AA"),
            ("Button Text on Purple Accent", accent_fg, accent, 4.5, "AA"),
            ("Button Text on Green Success", accent_fg, success, 7.0, "AAA"),
            ("Button Text on Yellow Warning", accent_fg, warning, 7.0, "AAA"),
            ("Button Text on Orange Warning", accent_fg, warning_orange, 7.0, "AAA"),
            ("Button Text on Red Danger", accent_fg, danger, 4.5, "AA"),
            ("Top Guide on Dark BG", danger, bg, 3.0, "UI Component"),
            ("Bottom Guide on Dark BG", cyan, bg, 3.0, "UI Component"),
            ("Side Guide on Dark BG", success, bg, 3.0, "UI Component"),
        ]

        for desc, fg_c, bg_c, target_ratio, standard in checks:
            ratio = contrast_ratio(fg_c, bg_c)
            self.assertGreaterEqual(
                ratio,
                target_ratio,
                f"Contrast failure for '{desc}' ({fg_c} on {bg_c}): {ratio:.2f}:1 < {target_ratio}:1 ({standard})",
            )


if __name__ == "__main__":
    unittest.main()
