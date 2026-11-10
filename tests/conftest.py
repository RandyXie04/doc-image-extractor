# -*- coding: utf-8 -*-
"""
tests/conftest.py: Central pytest configuration and hermetic isolation fixtures.

Provides:
- isolate_config_fonts_json (autouse=True): Protects config/fonts.json from modification or corruption.
- isolate_production_paths (autouse=True): Redirects PATHS.input_dir & PATHS.output_dir to tmp_path.
- block_external_network_and_mock_ollama (autouse=True): Blocks unmocked external requests & intercepts Ollama 11434.
- dummy_pdf_factory: Reusable factory fixture for creating lightweight test PDFs.
- sample_vector_pdf: Standard 2-page sample PDF fixture.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional, Union
from unittest.mock import MagicMock

import fitz
import pytest

# ── Windows Hermetic Event Loop & Self-Pipe Patch (Sandbox Compatible) ──────
if sys.platform == "win32":
    import ctypes
    from asyncio.windows_events import IocpProactor
    from asyncio.proactor_events import BaseProactorEventLoop

    kernel32 = ctypes.windll.kernel32

    def _hermetic_make_self_pipe(self: Any) -> None:
        self._ssock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._csock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._ssock.setblocking(False)
        self._csock.setblocking(False)
        self._internal_fds += 1

    def _hermetic_close_self_pipe(self: Any) -> None:
        for s in (getattr(self, "_ssock", None), getattr(self, "_csock", None)):
            if s:
                try:
                    s.close()
                except Exception:
                    pass

    def _hermetic_write_to_self(self: Any) -> None:
        iocp = getattr(getattr(self, "_proactor", None), "_iocp", None)
        if iocp:
            kernel32.PostQueuedCompletionStatus(iocp, 0, 0, None)

    orig_poll = IocpProactor._poll

    def _safe_poll(self: Any, timeout: Any = None) -> Any:
        try:
            return orig_poll(self, timeout)
        except OSError as e:
            if getattr(e, "winerror", None) in (0, 258) or getattr(e, "errno", None) == 0:
                return []
            raise

    IocpProactor._poll = _safe_poll
    BaseProactorEventLoop._make_self_pipe = _hermetic_make_self_pipe
    BaseProactorEventLoop._close_self_pipe = _hermetic_close_self_pipe
    BaseProactorEventLoop._loop_self_reading = lambda self, f=None: None
    BaseProactorEventLoop._write_to_self = _hermetic_write_to_self


# ── 1. Production config/fonts.json Protection Fixture ───────────────────────

@pytest.fixture(autouse=True)
def isolate_config_fonts_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Guarantees production config/fonts.json is never modified, deleted, or polluted.
    Snapshots pre-test content, creates an isolated temp copy in tmp_path,
    monkeypatches configuration references, and strictly verifies immutability in teardown.
    """
    real_fonts_path = Path("config/fonts.json").resolve()
    original_bytes = real_fonts_path.read_bytes() if real_fonts_path.exists() else None

    # Create isolated copy in tmp_path
    fake_fonts = tmp_path / "isolated_fonts.json"
    fake_fonts.write_text(
        original_bytes.decode("utf-8") if original_bytes is not None else "{}",
        encoding="utf-8",
    )

    # Monkeypatch book_layout_extractor._fonts_json
    monkeypatch.setattr(
        "src.scripts.book_layout_extractor._fonts_json",
        str(fake_fonts),
        raising=False,
    )

    # Monkeypatch config.settings._Paths.fonts_json_path property
    try:
        from config.settings import _Paths
        monkeypatch.setattr(_Paths, "fonts_json_path", property(lambda self: fake_fonts))
    except (ImportError, AttributeError):
        pass

    yield fake_fonts

    # Teardown assertion: verify real config/fonts.json was untouched on disk
    if original_bytes is not None:
        if not real_fonts_path.exists():
            real_fonts_path.write_bytes(original_bytes)
            assert False, "config/fonts.json was deleted by test!"
        current_bytes = real_fonts_path.read_bytes()
        if current_bytes != original_bytes:
            real_fonts_path.write_bytes(original_bytes)
            assert False, "config/fonts.json was modified on disk by test!"
    else:
        if real_fonts_path.exists():
            real_fonts_path.unlink()
            assert False, "config/fonts.json was created on disk in production dir by test!"


# ── 2. Production PATHS Isolation Fixture ─────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_production_paths(tmp_path: Path) -> Any:
    """
    Redirects PATHS.input_dir and PATHS.output_dir to tmp_path to prevent
    tests from writing or littering into repository data/ directories.
    """
    from config import PATHS

    fake_input = tmp_path / "input"
    fake_output = tmp_path / "output"
    fake_input.mkdir(parents=True, exist_ok=True)
    fake_output.mkdir(parents=True, exist_ok=True)

    orig_input = PATHS.input_dir
    orig_output = PATHS.output_dir

    # PATHS is a frozen dataclass instance; use object.__setattr__ to redirect safely
    object.__setattr__(PATHS, "input_dir", fake_input)
    object.__setattr__(PATHS, "output_dir", fake_output)

    try:
        yield
    finally:
        object.__setattr__(PATHS, "input_dir", orig_input)
        object.__setattr__(PATHS, "output_dir", orig_output)


# ── 3. Global Socket Interceptor & Ollama Mock Fixture ───────────────────────

@pytest.fixture(autouse=True)
def block_external_network_and_mock_ollama(monkeypatch: pytest.MonkeyPatch) -> Any:
    """
    Blocks unmocked external network calls and intercepts Ollama 11434 requests
    to prevent 180s hangs on offline/missing local LLM services.
    """
    orig_urlopen = urllib.request.urlopen

    def safe_urlopen(url_or_req: Any, *args: Any, **kwargs: Any) -> Any:
        url_str = url_or_req.full_url if hasattr(url_or_req, "full_url") else str(url_or_req)

        # Intercept Ollama daemon requests
        if "11434" in url_str:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.code = 200
            mock_resp.getcode.return_value = 200
            mock_resp.headers = {"content-type": "application/json"}

            if "api/tags" in url_str:
                body = {
                    "models": [
                        {"name": "mock_test_model"},
                        {"name": "qwen3.5:4b"},
                        {"name": "qwen2.5vl:7b"},
                    ]
                }
            else:
                body = {
                    "models": [{"name": "mock_test_model"}],
                    "message": {
                        "role": "assistant",
                        "content": "# Mock Title\nMock response text for offline testing.",
                    },
                    "response": "# Mock Title\nMock response text for offline testing.",
                }
            mock_resp.read.return_value = json.dumps(body).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        # Intercept Google Gemini API requests
        if "generativelanguage.googleapis.com" in url_str:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.code = 200
            mock_resp.getcode.return_value = 200
            mock_resp.headers = {"content-type": "application/json"}
            gemini_body = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "[]"}],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                    }
                ]
            }
            mock_resp.read.return_value = json.dumps(gemini_body).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        # Intercept external network calls (allow local loopback)
        parsed = urllib.parse.urlparse(url_str)
        host = (parsed.hostname or "").lower()
        if host and host not in ("localhost", "127.0.0.1", "::1", "0.0.0.0", "testserver"):
            raise urllib.error.URLError(f"External network access blocked by pytest fixture: {url_str}")

        return orig_urlopen(url_or_req, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", safe_urlopen)

    # Intercept raw socket create_connection to port 11434 to immediately fail fast
    orig_create_connection = socket.create_connection

    def safe_create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        host, port = address[:2]
        if str(port) == "11434":
            raise ConnectionRefusedError(f"Connection to Ollama (port 11434) blocked by pytest fixture.")
        if host and str(host).lower() not in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            raise socket.error(f"External network connection to {host}:{port} blocked by pytest fixture.")
        return orig_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", safe_create_connection)

    # Intercept httpx if available
    try:
        import httpx
        orig_httpx_send = httpx.Client.send

        def safe_httpx_send(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
            url_str = str(request.url)
            if "11434" in url_str:
                return httpx.Response(
                    status_code=200,
                    json={
                        "models": [{"name": "mock_test_model"}, {"name": "qwen3.5:4b"}],
                        "message": {"role": "assistant", "content": "# Mock Title\nMock response text."},
                        "response": "# Mock Title\nMock response text.",
                    },
                    request=request,
                )
            if "generativelanguage.googleapis.com" in url_str:
                return httpx.Response(
                    status_code=200,
                    json={
                        "candidates": [
                            {
                                "content": {
                                    "parts": [{"text": "[]"}],
                                    "role": "model",
                                },
                                "finishReason": "STOP",
                            }
                        ]
                    },
                    request=request,
                )
            from httpx import ASGITransport
            if isinstance(getattr(self, "_transport", None), ASGITransport):
                return orig_httpx_send(self, request, *args, **kwargs)
            if request.url.host and request.url.host not in ("testserver", "localhost", "127.0.0.1", "::1"):
                raise httpx.ConnectError(f"External network access blocked by pytest fixture: {url_str}")
            return orig_httpx_send(self, request, *args, **kwargs)

        monkeypatch.setattr(httpx.Client, "send", safe_httpx_send)
    except (ImportError, AttributeError):
        pass

    yield


# ── 4. Reusable Dummy PDF Factory Fixture ─────────────────────────────────────

@pytest.fixture
def dummy_pdf_factory(tmp_path: Path) -> Callable[..., Path]:
    """
    Reusable factory fixture to generate lightweight test PDFs with custom pages.
    Eliminates duplicated fitz.open() / page setup boilerplate across tests.
    """
    def _create_pdf(
        filename: str = "sample.pdf",
        pages: Optional[List[Union[Dict[str, Any], List[Dict[str, Any]]]]] = None,
        toc: Optional[List[List[Any]]] = None,
    ) -> Path:
        if pages is None:
            pages = [
                [{"text": "Sample Body Text for Testing", "fontsize": 12.0, "pos": (50, 100), "fontname": "helv"}]
            ]

        pdf_path = tmp_path / filename
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        doc = fitz.open()
        for page_spec in pages:
            if isinstance(page_spec, dict):
                lines = [page_spec]
                width = page_spec.get("width", 500)
                height = page_spec.get("height", 700)
            elif isinstance(page_spec, list):
                lines = page_spec
                width = lines[0].get("page_width", 500) if lines else 500
                height = lines[0].get("page_height", 700) if lines else 700
            else:
                lines = []
                width, height = 500, 700

            page = doc.new_page(width=width, height=height)
            for line in lines:
                text = line.get("text", "")
                if text:
                    pos = line.get("pos", (50, 100))
                    fontsize = line.get("fontsize", 12.0)
                    fontname = line.get("fontname", "helv")
                    page.insert_text(
                        fitz.Point(pos[0], pos[1]),
                        text,
                        fontsize=fontsize,
                        fontname=fontname,
                    )

        if toc:
            doc.set_toc(toc)

        doc.save(str(pdf_path))
        doc.close()
        return pdf_path

    return _create_pdf


@pytest.fixture
def sample_vector_pdf(dummy_pdf_factory: Callable[..., Path]) -> Path:
    """Convenience fixture returning a standard 2-page sample vector PDF with headings and TOC."""
    return dummy_pdf_factory(
        filename="sample_vector.pdf",
        pages=[
            [
                {"text": "第一章 導論", "pos": (50, 80), "fontsize": 16.0},
                {"text": "這是第一章的導論正文內容，用於測試段落排版與版面識別。", "pos": (50, 120), "fontsize": 11.0},
            ],
            [
                {"text": "第二章 方法論", "pos": (50, 80), "fontsize": 16.0},
                {"text": "這是第二章的方法論正文段落，用於跨頁測試。", "pos": (50, 120), "fontsize": 11.0},
            ],
        ],
        toc=[
            [1, "第一章 導論", 1],
            [1, "第二章 方法論", 2],
        ],
    )
