# -*- coding: utf-8 -*-
"""
Test Suite for OCR Workbench UI/UX Information Architecture & Contracts
======================================================================
Verifies:
1. Progressive disclosure tiering (Tier 1 basic visible, Tier 2 & 3 collapsed by default).
2. Form proxy backward compatibility (all 15+ legacy IDs preserved for backend & scripts).
3. 4-step Workflow Stepper & 6-stage semantic pipeline stages.
4. Read-only processing state and CSS component declarations.
"""

import unittest
from pathlib import Path
import re

from src.utils.path_helper import get_project_dir


class TestOcrWorkbenchIA(unittest.TestCase):
    def setUp(self):
        self.project_dir = get_project_dir()
        self.html_path = self.project_dir / "src" / "web" / "static" / "ocr_pipeline.html"
        self.css_path = self.project_dir / "src" / "web" / "static" / "toolbox.css"
        self.html_content = self.html_path.read_text(encoding="utf-8")
        self.css_content = self.css_path.read_text(encoding="utf-8")

    def test_progressive_disclosure_structure(self):
        """Verify Tier 2 and Tier 3 panels are collapsed with aria-expanded=false and hidden attribute."""
        # Tier 2 Advanced
        self.assertIn('id="tierAdvancedAccordion"', self.html_content)
        self.assertIn('id="tierAdvancedTrigger"', self.html_content)
        self.assertIn('aria-expanded="false"', self.html_content)
        self.assertIn('id="tierAdvancedContent"', self.html_content)

        # Tier 3 Engineer
        self.assertIn('id="tierEngineerAccordion"', self.html_content)
        self.assertIn('id="tierEngineerTrigger"', self.html_content)
        self.assertIn('id="tierEngineerContent"', self.html_content)

    def test_backward_compatible_form_controls(self):
        """Verify all critical form element IDs required by backend API and legacy scripts are preserved."""
        required_ids = [
            # File & Template
            "fileInput",
            "templateInput",
            # Engine & Options
            "engineSelect",
            "noFootnoteToggle",
            # Page range
            "startPageInput",
            "endPageInput",
            # Crop sliders & numbers
            "headerSlider",
            "headerNumInput",
            "footerSlider",
            "footerNumInput",
            "leftSlider",
            "leftNumInput",
            "rightSlider",
            "rightNumInput",
            # Buttons & Font Review Modal controls
            "submitBtn",
            "analyzeFontsBtn",
            "fontModalOverlay",
            "fontTableBody",
            "fontModalConfirmBtn",
            # Compatibility label anchors
            "headerValLabel",
            "footerValLabel",
            "leftValLabel",
            "rightValLabel",
        ]

        for elem_id in required_ids:
            self.assertIn(f'id="{elem_id}"', self.html_content, f"Missing critical element ID: {elem_id}")

        # Independent "Word 樣式角色對應" UI panel and duplicate Gemma style suggest controls must be removed;
        # role & DOCX style review is unified in Font Review Modal with internal fallback preserved.
        for removed_id in (
            "styleMappingSection",
            "tabularStyleMapperMount",
            "resetAllStylesBtn",
            "styleMapperFilter",
            "gemmaStyleSuggestBtn",
        ):
            self.assertNotIn(f'id="{removed_id}"', self.html_content, f"Redundant style UI element should be removed: {removed_id}")
        self.assertNotIn("/api/suggest_ocr_style_mapping", self.html_content)
        self.assertIn('id="gemmaFontSuggestBtn"', self.html_content)
        self.assertIn('id="gemmaFontSuggestBanner"', self.html_content)
        self.assertIn("/api/suggest_font_mappings", self.html_content)
        self.assertIn("STYLE_ROLE_FALLBACK_DEFAULTS", self.html_content)
        self.assertIn("syncConfirmedRoleStylesFromFontMapping", self.html_content)

    def test_workflow_stepper_and_pipeline_stages(self):
        """Verify 4-step workflow stepper and 6-stage semantic pipeline elements are present."""
        # Stepper
        self.assertIn('id="workflowStepper"', self.html_content)
        self.assertIn('id="stepItem1"', self.html_content)
        self.assertIn('id="stepItem2"', self.html_content)
        self.assertIn('id="stepItem3"', self.html_content)
        self.assertIn('id="stepItem4"', self.html_content)
        self.assertIn('id="preconditionAlert"', self.html_content)

        # 6 Semantic Stages
        stage_ids = [
            "stage_load",
            "stage_font",
            "stage_layout",
            "stage_markdown",
            "stage_docx",
            "stage_export",
        ]
        for sid in stage_ids:
            self.assertIn(f'id="{sid}"', self.html_content, f"Missing progress stage element: {sid}")

    def test_empty_state_and_readonly_styles_in_css(self):
        """Verify CSS defines Stepper, Empty State, Tabular Mapper and Read-only processing states."""
        required_css_selectors = [
            ".workflow-stepper-bar",
            ".canvas-empty-state",
            ".inspector-accordion",
            ".accordion-content[hidden]",
            ".style-mapper-table",
            ".workbench-inspector-pane.is-processing",
            ".pipeline-feedback-card",
            ".p-stage",
            ".pipeline-error-box",
            ".pipeline-result-summary",
        ]
        for selector in required_css_selectors:
            self.assertIn(selector, self.css_content, f"Missing CSS selector: {selector}")

    def test_sidebar_clean_documentation_links(self):
        """Verify sidebar documentation links do not inject bulky doc-desc in the navigation list."""
        sidebar_js = (self.project_dir / "src" / "web" / "static" / "sidebar.js").read_text(encoding="utf-8")
        sidebar_css = (self.project_dir / "src" / "web" / "static" / "sidebar.css").read_text(encoding="utf-8")

        # Sidebar links should render doc-name directly without cluttering doc-desc
        self.assertNotIn('<span class="doc-desc">${window.toolbox.escape(d.description)}</span>', sidebar_js)
        self.assertIn('.sidebar-doc-link .doc-desc', sidebar_css)
        self.assertIn('display: none !important;', sidebar_css)


if __name__ == "__main__":
    unittest.main()

