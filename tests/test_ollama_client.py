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


def test_find_ollama_executable():
    from src.utils.ollama_client import find_ollama_executable
    with patch("shutil.which", return_value="C:\\FakePath\\ollama.exe"):
        assert find_ollama_executable() == "C:\\FakePath\\ollama.exe"

    with patch("shutil.which", return_value=None), \
         patch("os.name", "nt"), \
         patch("os.path.exists", return_value=True):
        exe = find_ollama_executable()
        assert exe is not None
        assert "ollama.exe" in exe


def test_list_and_check_local_models():
    from src.utils.ollama_client import list_local_models, is_model_installed

    fake_tags_json = json.dumps({
        "models": [
            {"name": "qwen2.5vl:7b"},
            {"name": "qwen3.5:4b"},
            {"name": "llama3.2:latest"}
        ]
    }).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = fake_tags_json
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        models = list_local_models()
        assert "qwen3.5:4b" in models
        assert "qwen2.5vl:7b" in models
        assert is_model_installed("qwen3.5:4b") is True
        assert is_model_installed("qwen3.5:4b:latest") is True
        assert is_model_installed("llama3.2") is True
        assert is_model_installed("non_existent_model") is False


def test_ensure_ollama_service_already_running():
    from src.utils.ollama_client import ensure_ollama_service
    with patch("src.utils.ollama_client.is_ollama_available", return_value=True):
        assert ensure_ollama_service() is True


def test_zero_silent_fallback_in_propagation():
    from src.pod_studio import BookBlueprint, PropagationEngine

    blueprint = BookBlueprint(
        book_name="Test Doc",
        template_styles_used=["Normal", "Heading 1"],
    )
    engine = PropagationEngine(blueprint=blueprint)

    # 1. When Ollama is offline and an Ollama model is requested, must raise RuntimeError, NO silent fallback
    with patch("src.utils.ollama_client.is_ollama_available", return_value=False):
        with pytest.raises(RuntimeError) as exc_info:
            engine.classify_paragraphs_hybrid(
                paragraphs=[(1, "測試段落文字")],
                model="qwen3.5:4b",
                ai_client=MagicMock()  # Even if Gemini ai_client is provided, it must NOT fallback
            )
        assert "Ollama 服務未啟動" in str(exc_info.value)
        assert "拒絕私自降級" in str(exc_info.value)

    # 2. When Ollama is online but model is not installed, must raise RuntimeError
    with patch("src.utils.ollama_client.is_ollama_available", return_value=True), \
         patch("src.utils.ollama_client.is_model_installed", return_value=False):
        with pytest.raises(RuntimeError) as exc_info:
            engine.classify_paragraphs_hybrid(
                paragraphs=[(1, "測試段落文字")],
                model="qwen3.5:4b",
                ai_client=MagicMock()
            )
        assert "尚未於 Ollama 中安裝" in str(exc_info.value)
        assert "拒絕私自降級" in str(exc_info.value)

