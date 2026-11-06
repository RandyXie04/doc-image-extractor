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

        # 3. Two Primary Categories: Settings & Documentation
        self.assertIn("iaCategorySettings", js_content)
        self.assertIn("catSettingsToggle", js_content)
        self.assertIn("catSettingsPanel", js_content)
        self.assertIn("iaCategoryDocs", js_content)
        self.assertIn("catDocsToggle", js_content)
        self.assertIn("catDocsPanel", js_content)
        self.assertIn("sidebarDocList", js_content)
        self.assertIn("docViewerModal", js_content)
        self.assertIn("openDocViewer", js_content)
        self.assertIn("loadAndRenderDocCatalogue", js_content)

    def test_sidebar_css_rules(self):
        """Verify sidebar.css includes styles for two-category IA, nav-group, sub-links, and doc viewer modal."""
        css_content = self.sidebar_css_path.read_text(encoding="utf-8")

        self.assertIn(".ia-category", css_content)
        self.assertIn(".ia-category-header", css_content)
        self.assertIn(".ia-category-panel", css_content)
        self.assertIn(".ia-subgroup", css_content)
        self.assertIn(".nav-group", css_content)
        self.assertIn(".nav-group-header", css_content)
        self.assertIn(".nav-arrow-indicator", css_content)
        self.assertIn(".nav-group-children", css_content)
        self.assertIn(".nav-sub-link", css_content)
        self.assertIn(".sidebar-doc-link", css_content)
        self.assertIn(".doc-modal-content", css_content)
        self.assertIn(".doc-modal-sidebar", css_content)
        self.assertIn(".doc-modal-article", css_content)

    def test_api_docs_list(self):
        """Verify GET /api/docs returns complete list of documentation metadata and supports audience filtering."""
        resp = self.client.get("/api/docs", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        docs = resp.json()
        doc_ids = [d["id"] for d in docs]

        expected_ids = ["workflow", "about", "modules"]
        for expected in expected_ids:
            self.assertIn(expected, doc_ids, f"Missing document ID: {expected}")

        self.assertNotIn("glossary", doc_ids, "glossary must not be in docs list")
        self.assertNotIn("decisions", doc_ids, "decisions (ADR) must not be in docs list")

        # Test mode=editor filtering (only editor and all audience docs)
        resp_editor = self.client.get("/api/docs?mode=editor", headers=self.auth_headers)
        self.assertEqual(resp_editor.status_code, 200)
        editor_ids = [d["id"] for d in resp_editor.json()]
        self.assertIn("workflow", editor_ids)
        self.assertIn("about", editor_ids)
        self.assertNotIn("modules", editor_ids)
        self.assertNotIn("decisions", editor_ids)
        self.assertNotIn("glossary", editor_ids)

        # Test mode=dev filtering (developer mode docs catalogue)
        resp_dev = self.client.get("/api/docs?mode=dev", headers=self.auth_headers)
        self.assertEqual(resp_dev.status_code, 200)
        dev_ids = [d["id"] for d in resp_dev.json()]
        for expected in expected_ids:
            self.assertIn(expected, dev_ids)
        self.assertNotIn("glossary", dev_ids, "glossary must not be in dev docs list")
        self.assertNotIn("decisions", dev_ids, "decisions must not be in dev docs list")

    def test_api_docs_content(self):
        """Verify GET /api/docs/{doc_id} returns valid HTML and Markdown content for each document."""
        expected_ids = ["workflow", "about", "modules"]
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
        # Agent-internal records (glossary, decisions) should not be reachable via web doc endpoint
        self.assertEqual(self.client.get("/api/docs/glossary", headers=self.auth_headers).status_code, 404)
        self.assertEqual(self.client.get("/api/docs/decisions", headers=self.auth_headers).status_code, 404)


if __name__ == "__main__":
    unittest.main()

