# -*- coding: utf-8 -*-
"""
Test Suite for Sidebar Navigation & Documentation System
=========================================================
Verifies:
1. Sidebar hierarchical navigation structure:
   - 全自動整稿
   - POD整稿
   - 輔助工具 (Collapsible group with 公式提取, 圖片提取, 方正修復, extensible list)
2. Sidebar bottom settings section & Doc Viewer Modal integration.
3. Backend `/api/docs` and `/api/docs/{doc_id}` documentation endpoints.
"""

import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from config import CFG
from src.web.app import app
from src.utils.path_helper import get_project_dir


class TestSidebarAndDocs(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.auth_headers = {"X-API-Key": CFG.auth_password} if CFG.auth_enabled else {}
        self.project_dir = get_project_dir()
        self.sidebar_js_path = self.project_dir / "src" / "web" / "static" / "sidebar.js"
        self.sidebar_css_path = self.project_dir / "src" / "web" / "static" / "sidebar.css"

    def test_sidebar_js_structure(self):
        """Verify sidebar.js has the required hierarchical navigation and settings section."""
        js_content = self.sidebar_js_path.read_text(encoding="utf-8")

        # 1. Main workflow items
        self.assertIn("MAIN_NAV_ITEMS", js_content)
        self.assertIn("全自動整稿", js_content)
        self.assertIn("ocr_pipeline.html", js_content)
        self.assertIn("POD 整稿", js_content)
        self.assertIn("pod_studio.html", js_content)

        # 2. Auxiliary tools expandable group
        self.assertIn("AUXILIARY_NAV_ITEMS", js_content)
        self.assertIn("輔助工具", js_content)
        self.assertIn("formula.html", js_content)
        self.assertIn("公式提取", js_content)
        self.assertIn("extract_images.html", js_content)
        self.assertIn("圖片提取", js_content)
        self.assertIn("founder_repair.html", js_content)
        self.assertIn("方正修復", js_content)
        self.assertIn("auxNavGroup", js_content)
        self.assertIn("auxNavToggle", js_content)
        self.assertIn("auxNavChildren", js_content)

        # 3. Bottom Settings & Documentation section
        self.assertIn("sidebar-settings-block", js_content)
        self.assertIn("sidebarSettingsBtn", js_content)
        self.assertIn("sidebarSettingsDropdown", js_content)
        self.assertIn("docViewerModal", js_content)
        self.assertIn("openDocViewer", js_content)
        self.assertIn("loadAndRenderDocCatalogue", js_content)

    def test_sidebar_css_rules(self):
        """Verify sidebar.css includes styles for nav-group, sub-links, settings block, and doc viewer modal."""
        css_content = self.sidebar_css_path.read_text(encoding="utf-8")

        self.assertIn(".nav-group", css_content)
        self.assertIn(".nav-group-header", css_content)
        self.assertIn(".nav-arrow-indicator", css_content)
        self.assertIn(".nav-group-children", css_content)
        self.assertIn(".nav-sub-link", css_content)
        self.assertIn(".sidebar-settings-block", css_content)
        self.assertIn(".sidebar-settings-trigger", css_content)
        self.assertIn(".sidebar-settings-dropdown", css_content)
        self.assertIn(".doc-modal-content", css_content)
        self.assertIn(".doc-modal-sidebar", css_content)
        self.assertIn(".doc-modal-article", css_content)

    def test_api_docs_list(self):
        """Verify GET /api/docs returns complete list of documentation metadata and supports audience filtering."""
        resp = self.client.get("/api/docs", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        docs = resp.json()
        doc_ids = [d["id"] for d in docs]

        expected_ids = ["workflow", "about", "modules", "glossary", "decisions"]
        for expected in expected_ids:
            self.assertIn(expected, doc_ids, f"Missing document ID: {expected}")

        # Test mode=editor filtering (only editor and all audience docs)
        resp_editor = self.client.get("/api/docs?mode=editor", headers=self.auth_headers)
        self.assertEqual(resp_editor.status_code, 200)
        editor_ids = [d["id"] for d in resp_editor.json()]
        self.assertIn("workflow", editor_ids)
        self.assertIn("about", editor_ids)
        self.assertNotIn("modules", editor_ids)
        self.assertNotIn("decisions", editor_ids)

        # Test mode=dev filtering (all docs available to developers)
        resp_dev = self.client.get("/api/docs?mode=dev", headers=self.auth_headers)
        self.assertEqual(resp_dev.status_code, 200)
        dev_ids = [d["id"] for d in resp_dev.json()]
        for expected in expected_ids:
            self.assertIn(expected, dev_ids)

    def test_api_docs_content(self):
        """Verify GET /api/docs/{doc_id} returns valid HTML and Markdown content for each document."""
        expected_ids = ["workflow", "about", "modules", "glossary", "decisions"]
        for doc_id in expected_ids:
            resp = self.client.get(f"/api/docs/{doc_id}", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 200, f"Failed loading doc: {doc_id}")
            data = resp.json()
            self.assertEqual(data["id"], doc_id)
            self.assertTrue(len(data.get("title", "")) > 0)
            self.assertTrue(len(data.get("markdown", "")) > 0)
            self.assertTrue(len(data.get("html", "")) > 0)
            self.assertIn("<", data["html"], "HTML output must contain rendered HTML tags")

    def test_api_docs_404_for_invalid_id(self):
        """Verify GET /api/docs/{invalid_id} returns 404."""
        resp = self.client.get("/api/docs/non_existent_doc_id_999", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()

