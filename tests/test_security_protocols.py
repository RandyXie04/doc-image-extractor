# -*- coding: utf-8 -*-
import base64
import unittest
from contextlib import contextmanager
from fastapi.testclient import TestClient

from config.settings import CFG
from src.web.app import app


@contextmanager
def patch_cfg(**kwargs):
    old_values = {}
    for k, v in kwargs.items():
        old_values[k] = getattr(CFG, k)
        object.__setattr__(CFG, k, v)
    try:
        yield
    finally:
        for k, v in old_values.items():
            object.__setattr__(CFG, k, v)


class TestSecurityProtocols(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_auth_disabled_by_default_allows_requests(self):
        """當 auth_enabled 為 False 時，請求無需驗證即可正常存取"""
        with patch_cfg(auth_enabled=False):
            resp = self.client.get("/")
            self.assertNotEqual(resp.status_code, 401)

    def test_auth_enabled_rejects_unauthenticated_request(self):
        """當 auth_enabled 為 True 時，未提供認證之請求應回傳 401 並附帶 WWW-Authenticate"""
        with patch_cfg(auth_enabled=True, auth_username="admin", auth_password="test_pass_123"):
            resp = self.client.get("/api/queue/tasks")
            self.assertEqual(resp.status_code, 401)
            self.assertIn("WWW-Authenticate", resp.headers)
            self.assertIn("Basic", resp.headers["WWW-Authenticate"])

    def test_auth_enabled_rejects_invalid_basic_credentials(self):
        """錯誤的 Basic Auth 帳密應被拒絕 401"""
        with patch_cfg(auth_enabled=True, auth_username="admin", auth_password="test_pass_123"):
            bad_token = base64.b64encode(b"admin:wrong_password").decode("utf-8")
            resp = self.client.get("/api/queue/tasks", headers={"Authorization": f"Basic {bad_token}"})
            self.assertEqual(resp.status_code, 401)

    def test_auth_enabled_accepts_valid_basic_credentials(self):
        """正確的 Basic Auth 應順利通過 200"""
        with patch_cfg(auth_enabled=True, auth_username="admin", auth_password="test_pass_123"):
            good_token = base64.b64encode(b"admin:test_pass_123").decode("utf-8")
            resp = self.client.get("/api/queue/tasks", headers={"Authorization": f"Basic {good_token}"})
            self.assertEqual(resp.status_code, 200)

    def test_auth_enabled_accepts_valid_api_key(self):
        """使用 X-API-Key 提供正確密碼應順利通過 200"""
        with patch_cfg(auth_enabled=True, auth_username="admin", auth_password="test_pass_123"):
            resp = self.client.get("/api/queue/tasks", headers={"X-API-Key": "test_pass_123"})
            self.assertEqual(resp.status_code, 200)

    def test_auth_enabled_rejects_invalid_api_key(self):
        """使用錯誤的 X-API-Key 應回傳 401"""
        with patch_cfg(auth_enabled=True, auth_username="admin", auth_password="test_pass_123"):
            resp = self.client.get("/api/queue/tasks", headers={"X-API-Key": "wrong_key"})
            self.assertEqual(resp.status_code, 401)

    def test_cors_preflight_bypasses_auth(self):
        """OPTIONS 預檢請求即使在啟用鑑權時也應放行並回傳 200"""
        with patch_cfg(auth_enabled=True, auth_username="admin", auth_password="test_pass_123"):
            resp = self.client.options(
                "/api/queue/tasks",
                headers={
                    "Origin": "http://192.168.1.55:8000",
                    "Access-Control-Request-Method": "GET"
                }
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("access-control-allow-origin"), "http://192.168.1.55:8000")

    def test_cors_allows_lan_and_localhost_origins(self):
        """Localhost 與私有區網（192.168.x.x、10.x.x.x）應符合 CORS Regex 允許通過"""
        lan_origins = [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://192.168.0.10:3000",
            "http://10.1.2.3:8080"
        ]
        for origin in lan_origins:
            resp = self.client.get("/api/queue/tasks", headers={"Origin": origin})
            self.assertEqual(
                resp.headers.get("access-control-allow-origin"),
                origin,
                f"Origin {origin} should be allowed by CORS regex"
            )

    def test_cors_blocks_untrusted_public_origins(self):
        """非私有區網之公開網域名稱（如 evil.com）應被 CORS 阻擋"""
        bad_origin = "http://evil-attacker-site.com"
        resp = self.client.get("/api/queue/tasks", headers={"Origin": bad_origin})
        self.assertIsNone(
            resp.headers.get("access-control-allow-origin"),
            "Public non-LAN origin must NOT be present in Access-Control-Allow-Origin"
        )


if __name__ == "__main__":
    unittest.main()