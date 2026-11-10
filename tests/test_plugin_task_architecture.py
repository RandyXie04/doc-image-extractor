# -*- coding: utf-8 -*-
"""
tests/test_plugin_task_architecture.py
======================================
Comprehensive test suite verifying the Pluggable Task Foundation:
- TaskPluginSpec schema and category validation
- BaseTaskPlugin input validation and execution lifecycle hooks
- TaskPluginRegistry singleton, builtins, dynamic registration, unregistration
- GET /api/system/plugins FastAPI endpoint filtering & dynamic capability exposure
"""

import pytest
from fastapi.testclient import TestClient

from config import CFG
from src.plugins.base import BaseTaskPlugin, TaskPluginSpec
from src.plugins.registry import TaskPluginRegistry, get_plugin_registry
from src.web.app import app


@pytest.fixture
def client():
    headers = {"X-API-Key": CFG.auth_password} if CFG.auth_enabled else {}
    return TestClient(app, headers=headers)


def test_01_spec_validation():
    """Validates TaskPluginSpec creation and category constraints."""
    # Valid spec
    spec = TaskPluginSpec(
        id="test_subtask",
        name="測試專項任務",
        category="auxiliary_task",
        description="專屬測試任務說明",
        entry_url="/static/test.html",
        api_prefix="/api/test_task",
        allowed_input_exts=[".pdf", ".docx"],
        output_types=["docx"],
    )
    assert spec.id == "test_subtask"
    assert spec.category == "auxiliary_task"
    d = spec.to_dict()
    assert d["id"] == "test_subtask"
    assert d["allowed_input_exts"] == [".pdf", ".docx"]

    # Invalid category
    with pytest.raises(ValueError, match="Invalid plugin category"):
        TaskPluginSpec(
            id="bad_category",
            name="錯誤分類",
            category="unsupported_category",
            description="",
            entry_url="",
            api_prefix="",
        )


def test_02_base_plugin_input_validation():
    """Validates BaseTaskPlugin input file format checking."""
    spec = TaskPluginSpec(
        id="validator_plugin",
        name="副檔名驗證外掛",
        category="auxiliary_task",
        description="驗證副檔名",
        entry_url="/static/validator.html",
        api_prefix="/api/validator",
        allowed_input_exts=[".pdf", ".docx"],
    )

    class DummyPlugin(BaseTaskPlugin):
        @property
        def spec(self) -> TaskPluginSpec:
            return spec

    plugin = DummyPlugin()
    valid, msg = plugin.validate_input("book.pdf")
    assert valid is True
    assert msg == ""

    valid, msg = plugin.validate_input("chapter.DOCX")
    assert valid is True

    valid, msg = plugin.validate_input("bad_file.exe")
    assert valid is False
    assert "不支援的檔案格式" in msg


def test_03_registry_singleton_and_builtins():
    """Validates TaskPluginRegistry singleton and default builtins."""
    registry1 = get_plugin_registry()
    registry2 = TaskPluginRegistry.get_instance()
    assert registry1 is registry2

    # Check builtins are pre-registered
    ocr = registry1.get("ocr_pipeline")
    assert ocr is not None
    assert ocr.spec.name == "全自動整稿"
    assert ocr.spec.category == "core_typesetting"

    pod = registry1.get("pod_studio")
    assert pod is not None
    assert pod.spec.name == "POD 整稿"

    proofreading = registry1.get("proofreading")
    assert proofreading is not None
    assert proofreading.spec.category == "core_proofreading"
    assert proofreading.spec.is_enabled is False  # anchor for future pipeline

    founder = registry1.get("founder_repair")
    assert founder is not None
    assert founder.spec.category == "auxiliary_task"

    # Enabled-only list does not include proofreading
    enabled_specs = registry1.list_specs(only_enabled=True)
    assert not any(s.id == "proofreading" for s in enabled_specs)
    assert any(s.id == "ocr_pipeline" for s in enabled_specs)

    # All specs include proofreading
    all_specs = registry1.list_specs(only_enabled=False)
    assert any(s.id == "proofreading" for s in all_specs)


def test_04_dynamic_task_registration_and_unregistration():
    """Validates dynamic hot-plugging of new specialized publishing sub-tasks."""
    registry = get_plugin_registry()

    custom_spec = TaskPluginSpec(
        id="isbn_copyright_checker",
        name="版權頁與 ISBN 校驗",
        category="auxiliary_task",
        description="出版社專用：比對版權頁條碼與 CIP 編號正確性。",
        entry_url="/static/custom_isbn.html",
        api_prefix="/api/custom_isbn",
        allowed_input_exts=[".pdf"],
        output_types=["json"],
        order=150,
    )

    class CustomIsbnPlugin(BaseTaskPlugin):
        @property
        def spec(self) -> TaskPluginSpec:
            return custom_spec

    plugin = CustomIsbnPlugin()
    registry.register(plugin)

    # Check registered
    retrieved = registry.get("isbn_copyright_checker")
    assert retrieved is not None
    assert retrieved.spec.name == "版權頁與 ISBN 校驗"

    # Unregister and verify cleanup
    unregistered = registry.unregister("isbn_copyright_checker")
    assert unregistered is plugin
    assert registry.get("isbn_copyright_checker") is None


def test_05_system_plugins_api_endpoint(client):
    """Integration test: GET /api/system/plugins FastAPI endpoint."""
    # 1. Default query (enabled only)
    res = client.get("/api/system/plugins")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["total"] > 0
    ids = [p["id"] for p in data["plugins"]]
    assert "ocr_pipeline" in ids
    assert "pod_studio" in ids
    assert "founder_repair" in ids
    assert "extract_images" in ids
    assert "formula_extraction" in ids
    assert "proofreading" not in ids  # disabled by default

    # 2. Include disabled
    res_all = client.get("/api/system/plugins?include_disabled=true")
    assert res_all.status_code == 200
    all_ids = [p["id"] for p in res_all.json()["plugins"]]
    assert "proofreading" in all_ids

    # 3. Filter by category: core_typesetting
    res_core = client.get("/api/system/plugins?category=core_typesetting")
    assert res_core.status_code == 200
    core_items = res_core.json()["plugins"]
    assert len(core_items) >= 2
    for item in core_items:
        assert item["category"] == "core_typesetting"

    # 4. Filter by category: auxiliary_task
    res_aux = client.get("/api/system/plugins?category=auxiliary_task")
    assert res_aux.status_code == 200
    aux_items = res_aux.json()["plugins"]
    assert len(aux_items) >= 3
    for item in aux_items:
        assert item["category"] == "auxiliary_task"


def test_06_dynamic_hot_plugging_reflected_in_api(client):
    """Integration test: dynamically registered plugin is immediately reflected in API."""
    registry = get_plugin_registry()

    dynamic_spec = TaskPluginSpec(
        id="hot_plugged_catalog_sync",
        name="目錄章節校驗器",
        category="auxiliary_task",
        description="即時熱插拔外掛：對比 PDF 目錄與內文真實標題。",
        entry_url="/static/catalog_sync.html",
        api_prefix="/api/catalog_sync",
        allowed_input_exts=[".pdf"],
        output_types=["json", "docx"],
        order=200,
    )

    class DynamicPlugin(BaseTaskPlugin):
        @property
        def spec(self) -> TaskPluginSpec:
            return dynamic_spec

    registry.register(DynamicPlugin())

    try:
        # API should immediately show the new plugin
        res = client.get("/api/system/plugins?category=auxiliary_task")
        assert res.status_code == 200
        plugin_ids = [p["id"] for p in res.json()["plugins"]]
        assert "hot_plugged_catalog_sync" in plugin_ids

        new_plugin_item = next(p for p in res.json()["plugins"] if p["id"] == "hot_plugged_catalog_sync")
        assert new_plugin_item["name"] == "目錄章節校驗器"
        assert new_plugin_item["output_types"] == ["json", "docx"]
    finally:
        registry.unregister("hot_plugged_catalog_sync")

    # API should no longer show it after unregister
    res_after = client.get("/api/system/plugins?category=auxiliary_task")
    after_ids = [p["id"] for p in res_after.json()["plugins"]]
    assert "hot_plugged_catalog_sync" not in after_ids
