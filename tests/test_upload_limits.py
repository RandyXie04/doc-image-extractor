# -*- coding: utf-8 -*-
import io
import pytest
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from src.utils.file_guard import MaxBodySizeMiddleware, save_upload_file_safely
from src.web.app import app


def test_max_body_size_middleware_rejects_large_content_length():
    """驗證第一道防線：Middleware 早篩 Content-Length 大於限制時立即返回 413"""
    test_app = FastAPI()
    test_app.add_middleware(
        MaxBodySizeMiddleware,
        max_upload_bytes=10 * 1024 * 1024,      # 10 MB
        max_template_bytes=2 * 1024 * 1024       # 2 MB
    )

    @test_app.post("/test_upload")
    async def handle_test():
        return {"ok": True}

    client = TestClient(test_app)

    # 1. 超過 10MB 的 Content-Length -> 413
    resp = client.post("/test_upload", headers={"Content-Length": str(15 * 1024 * 1024)})
    assert resp.status_code == 413
    assert "超過單次大小限制" in resp.json()["detail"]

    # 2. 合格的 Content-Length -> 200
    resp = client.post("/test_upload", headers={"Content-Length": str(5 * 1024 * 1024)})
    assert resp.status_code == 200

    # 3. 範本專用端點超過 2MB -> 413
    @test_app.post("/api/upload_template")
    async def handle_template():
        return {"ok": True}

    resp = client.post("/api/upload_template", headers={"Content-Length": str(3 * 1024 * 1024)})
    assert resp.status_code == 413
    assert "超過單次大小限制" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_save_upload_file_safely_streaming_limit(tmp_path: Path):
    """驗證第二道防線：串流分塊累加檢測，超標時中止拋出 413 並徹底刪除殘留檔案"""
    target_file = tmp_path / "test_file.bin"

    # 建立 2MB 假資料，但限制上限 1MB
    big_data = b"X" * (2 * 1024 * 1024)
    upload_file = UploadFile(
        file=io.BytesIO(big_data),
        filename="big_sample.bin",
        headers=Headers({"content-type": "application/octet-stream"})
    )

    with pytest.raises(HTTPException) as exc_info:
        await save_upload_file_safely(upload_file, target_file, max_mb=1)

    assert exc_info.value.status_code == 413
    assert "超過單次上傳限制" in exc_info.value.detail
    # 確保殘留半成品檔案已被清除
    assert not target_file.exists()


@pytest.mark.asyncio
async def test_save_upload_file_safely_success(tmp_path: Path):
    """驗證在限制內之檔案正常寫入"""
    target_file = tmp_path / "good_file.bin"
    sample_data = b"Hello, World! " * 100
    upload_file = UploadFile(
        file=io.BytesIO(sample_data),
        filename="good.bin",
        headers=Headers({"content-type": "application/octet-stream"})
    )

    written = await save_upload_file_safely(upload_file, target_file, max_mb=10)
    assert written == len(sample_data)
    assert target_file.exists()
    assert target_file.read_bytes() == sample_data


def test_system_config_endpoint():
    """驗證 /api/system_config 端點回傳各項上限與留存週期配置"""
    from config.settings import CFG
    client = TestClient(app)
    if CFG.auth_enabled and CFG.auth_password:
        client.headers["X-API-Key"] = CFG.auth_password
    resp = client.get("/api/system_config")
    assert resp.status_code == 200
    data = resp.json()
    assert "max_upload_size_mb" in data
    assert "max_template_size_mb" in data
    assert "file_retention_hours" in data
    assert data["max_upload_size_mb"] >= 1
    assert data["file_retention_hours"] == 24
