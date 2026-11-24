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

    def tearDown(self):
        self.client.close()

    def test_sidebar_static_assets(self):
        """Verify sidebar JS, modular sub-components, and CSS assets are served with 3-zone landmarks."""
        resp_js = self.client.get("/static/sidebar.js", headers=self.auth_headers)
        self.assertEqual(resp_js.status_code, 200)
        js_text = resp_js.text
        for landmark in (
            "sidebarPrimaryNav",
            "sidebarWorkspaceTools",
            "sidebarSystemFooter",
            "systemStatusPopover",
            "docViewerModal",
            "document.createElement('main')",
        ):
            self.assertIn(landmark, js_text)

        for mod_name in ("system_store.js", "theme_manager.js", "doc_modal.js", "dev_telemetry.js"):
            resp_mod = self.client.get(f"/static/js/sidebar/{mod_name}", headers=self.auth_headers)
            self.assertEqual(resp_mod.status_code, 200, f"Missing sidebar module: {mod_name}")

        resp_css = self.client.get("/static/sidebar.css", headers=self.auth_headers)
        self.assertEqual(resp_css.status_code, 200)
        css_text = resp_css.text
        for selector in (".sidebar-nav-zone", ".sidebar-tools-zone", ".sidebar-system-footer", ".nav-group"):
            self.assertIn(selector, css_text)

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

    def test_single_start_app_bat_and_dev_mode_ip_guard(self):
        """Verify start_app_dev.bat is consolidated into start_app.bat and dev mode requires local dev IP."""
        from unittest.mock import patch

        self.assertTrue((self.project_dir / "start_app.bat").exists(), "start_app.bat must exist")
        self.assertFalse((self.project_dir / "start_app_dev.bat").exists(), "start_app_dev.bat must be removed")

        # 1. Local dev client (TestClient default 'testclient') is allowed to switch to dev mode
        resp_dev = self.client.post("/api/set_app_mode", json={"mode": "dev"}, headers=self.auth_headers)
        self.assertEqual(resp_dev.status_code, 200)
        data_dev = resp_dev.json()
        self.assertEqual(data_dev["mode"], "dev")
        self.assertTrue(data_dev["is_local_dev"])

        # 2. Non-local LAN IP must be blocked (403) when attempting to switch to dev mode
        with patch("src.web.routers.system_router.is_local_dev_request", return_value=False):
            resp_forbidden = self.client.post("/api/set_app_mode", json={"mode": "dev"}, headers=self.auth_headers)
            self.assertEqual(resp_forbidden.status_code, 403)

            # Non-local LAN IP querying /api/app_mode receives editor mode and is_local_dev=False
            resp_mode = self.client.get("/api/app_mode", headers=self.auth_headers)
            self.assertEqual(resp_mode.status_code, 200)
            self.assertEqual(resp_mode.json()["mode"], "editor")
            self.assertFalse(resp_mode.json()["is_local_dev"])

        # 3. Invalid mode returns HTTP 400
        resp_bad = self.client.post("/api/set_app_mode", json={"mode": "invalid"}, headers=self.auth_headers)
        self.assertEqual(resp_bad.status_code, 400)

        # Restore editor mode
        self.client.post("/api/set_app_mode", json={"mode": "editor"}, headers=self.auth_headers)

    def test_api_system_bootstrap_and_removed_report_issue(self):
        """Verify unified /api/system/bootstrap contract and deletion of dead /api/report_issue."""
        from unittest.mock import patch

        resp_boot = self.client.get("/api/system/bootstrap", headers=self.auth_headers)
        self.assertEqual(resp_boot.status_code, 200)
        data = resp_boot.json()
        self.assertEqual(
            set(data.keys()),
            {"version", "config", "hardware", "app_mode", "plugins", "docs"},
        )
        self.assertIn("app_version", data["version"])
        self.assertIn("max_upload_size_mb", data["config"])
        self.assertIn("gpu_name", data["hardware"])
        self.assertIn(data["app_mode"]["mode"], ("editor", "dev"))
        plugin_ids = {p["id"] for p in data["plugins"]}
        self.assertTrue({"ocr_pipeline", "pod_studio", "founder_repair", "extract_images", "formula_extraction"}.issubset(plugin_ids))

        # Non-local LAN IP gets editor mode and editor-safe docs only
        with patch("src.web.routers.system_router.is_local_dev_request", return_value=False):
            resp_lan = self.client.get("/api/system/bootstrap", headers=self.auth_headers)
            self.assertEqual(resp_lan.status_code, 200)
            lan_data = resp_lan.json()
            self.assertEqual(lan_data["app_mode"]["mode"], "editor")
            self.assertFalse(lan_data["app_mode"]["is_local_dev"])
            lan_doc_ids = {d["id"] for d in lan_data["docs"]}
            self.assertNotIn("modules", lan_doc_ids)

        # Dead /api/report_issue endpoint must be removed
        resp_dead = self.client.post("/api/report_issue", json={"description": "test"}, headers=self.auth_headers)
        self.assertEqual(resp_dead.status_code, 404)


if __name__ == "__main__":
    unittest.main()

