# -*- coding: utf-8 -*-
"""
Test Suite for OCR Workbench UI/UX Information Architecture & Contracts
======================================================================
Verifies:
1. Progressive disclosure tiering (Tier 1 basic visible, Tier 2 & 3 collapsed by default).
2. Form proxy backward compatibility (legacy IDs preserved for backend & scripts).
3. 4-step Workflow Stepper & 6-stage semantic pipeline stages.
4. Read-only processing state and CSS component declarations served via TestClient.
"""

from __future__ import annotations

import unittest
from fastapi.testclient import TestClient

from config import CFG
from src.web.app import app


class TestOcrWorkbenchIA(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.auth_headers = {"X-API-Key": CFG.auth_password} if CFG.auth_enabled else {}

        resp_html = self.client.get("/ocr_pipeline.html", headers=self.auth_headers)
        self.assertEqual(resp_html.status_code, 200)
        self.html_content = resp_html.text

        resp_css = self.client.get("/static/toolbox.css", headers=self.auth_headers)
        self.assertEqual(resp_css.status_code, 200)
        self.css_content = resp_css.text

    def test_progressive_disclosure_structure(self):
        """Verify Tier 2 and Tier 3 panels are collapsed with aria-expanded=false and hidden attribute."""
        self.assertIn('id="tierAdvancedAccordion"', self.html_content)
        self.assertIn('id="tierAdvancedTrigger"', self.html_content)
        self.assertIn('aria-expanded="false"', self.html_content)
        self.assertIn('id="tierAdvancedContent"', self.html_content)

        self.assertIn('id="tierEngineerAccordion"', self.html_content)
        self.assertIn('id="tierEngineerTrigger"', self.html_content)
        self.assertIn('id="tierEngineerContent"', self.html_content)

    def test_backward_compatible_form_controls(self):
        """Verify all critical form element IDs required by backend API and legacy scripts are preserved."""
        required_ids = [
            "fileInput",
            "templateInput",
            "engineSelect",
            "noFootnoteToggle",
            "startPageInput",
            "endPageInput",
            "submitBtn",
            "analyzeFontsBtn",
            "fontModalOverlay",
        ]

        for elem_id in required_ids:
            self.assertIn(f'id="{elem_id}"', self.html_content, f"Missing critical element ID: {elem_id}")

        for removed_id in (
            "styleMappingSection",
            "tabularStyleMapperMount",
            "resetAllStylesBtn",
            "styleMapperFilter",
            "gemmaStyleSuggestBtn",
        ):
            self.assertNotIn(f'id="{removed_id}"', self.html_content)

        self.assertIn('id="gemmaFontSuggestBtn"', self.html_content)
        self.assertIn("/api/suggest_font_mappings", self.html_content)

    def test_workflow_stepper_and_pipeline_stages(self):
        """Verify 4-step workflow stepper and semantic pipeline elements are present."""
        self.assertIn('id="workflowStepper"', self.html_content)
        self.assertIn('id="preconditionAlert"', self.html_content)

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
        """Verify CSS defines Stepper, Empty State, and Read-only processing states."""
        required_css_selectors = [
            ".workflow-stepper-bar",
            ".canvas-empty-state",
            ".inspector-accordion",
            ".workbench-inspector-pane.is-processing",
            ".pipeline-feedback-card",
        ]
        for selector in required_css_selectors:
            self.assertIn(selector, self.css_content, f"Missing CSS selector: {selector}")


if __name__ == "__main__":
    unittest.main()
