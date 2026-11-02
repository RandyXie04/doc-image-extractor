import json
import pytest
from unittest.mock import MagicMock, patch

from src.utils.ollama_client import (
    validate_local_host,
    clean_llm_output,
    ollama_chat,
    async_ollama_chat,
    ollama_structured_chat,
    is_ollama_available,
    OllamaConnectionError,
    OllamaResponseError,
)


def test_validate_local_host_allowed():
    assert validate_local_host("http://localhost:11434") == "http://localhost:11434"
    assert validate_local_host("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    assert validate_local_host("http://192.168.1.100:11434") == "http://192.168.1.100:11434"
    assert validate_local_host("http://10.0.0.5:11434") == "http://10.0.0.5:11434"


def test_validate_local_host_blocks_external():
    with pytest.raises(OllamaConnectionError) as exc_info:
        validate_local_host("https://api.external-cloud.com")
    assert "安全攔截" in str(exc_info.value)

    with pytest.raises(OllamaConnectionError):
        validate_local_host("http://8.8.8.8:11434")


def test_clean_llm_output():
    raw_thinking = "<think>\nThinking about layout...\nHere is step 1.\n</think># Title\nBody text."
    assert clean_llm_output(raw_thinking) == "# Title\nBody text."

    raw_fence = "```markdown\n# Hello World\n```"
    assert clean_llm_output(raw_fence) == "# Hello World"

    raw_both = "<think>abc</think>```json\n{\"font\": \"kaiti\"}\n```"
    assert clean_llm_output(raw_both) == '{"font": "kaiti"}'

    assert clean_llm_output("") == ""


def test_is_ollama_available_offline():
    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        mock_open.return_value = mock_resp

        assert is_ollama_available("http://localhost:11434") is True


def test_is_ollama_available_failed():
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        assert is_ollama_available("http://localhost:11434") is False


def test_ollama_chat_payload_and_options():
    recorded_req = None

    def fake_urlopen(req, timeout=None):
        nonlocal recorded_req
        recorded_req = req
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "message": {
                "role": "assistant",
                "content": "<think>reason</think>```markdown\n# Generated Markdown\n```"
            }
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = ollama_chat(
            prompt="Translate this section",
            images=[b"fake_image_bytes"],
            model="qwen3.5:4b",
            num_ctx=8192,
            think=False,
            keep_alive="5m",
        )

        assert result == "# Generated Markdown"
        assert recorded_req is not None
        assert recorded_req.full_url == "http://localhost:11434/api/chat"

        payload = json.loads(recorded_req.data.decode("utf-8"))
        assert payload["model"] == "qwen3.5:4b"
        assert payload["stream"] is False
        assert payload["think"] is False
        assert payload["keep_alive"] == "5m"
        assert payload["options"]["num_ctx"] == 8192
        assert len(payload["messages"]) == 1
        assert "images" in payload["messages"][0]
        assert len(payload["messages"][0]["images"]) == 1


@pytest.mark.asyncio
async def test_async_ollama_chat():
    def fake_urlopen(req, timeout=None):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "message": {"role": "assistant", "content": "Async Response"}
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        res = await async_ollama_chat(prompt="Hello async", model="qwen3.5:4b")
        assert res == "Async Response"


def test_ollama_structured_chat():
    def fake_urlopen(req, timeout=None):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "message": {
                "role": "assistant",
                "content": '{"font": "kaiti", "confidence": 0.95}'
            }
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    schema = {
        "type": "object",
        "properties": {
            "font": {"type": "string"},
            "confidence": {"type": "number"}
        }
    }

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        res = ollama_structured_chat(prompt="Classify font", schema=schema)
        assert isinstance(res, dict)
        assert res["font"] == "kaiti"
        assert res["confidence"] == 0.95
