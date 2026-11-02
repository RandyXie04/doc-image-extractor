# // ==============================================================================
# // ollama_client.py: 統一本地 Ollama 推論客戶端模組
# // - 100% 離線隔離：嚴格限制本機回環 (localhost / 127.0.0.1) 或區域網路，杜絕外部出網
# // - 統一接口：支援多模態 (Vision PNG)、結構化輸出 (JSON Schema)、思考標籤抑制 (<think>)
# // - 上下文控制：強制注入 num_ctx 防止長文本無聲截斷，提供 keep_alive 保留 VRAM
# // ==============================================================================

import os
import re
import json
import base64
import urllib.request
import urllib.error
import urllib.parse
import asyncio
from typing import Any, Dict, List, Optional, Union


class OllamaClientError(Exception):
    """Ollama 客戶端基底例外。"""
    pass


class OllamaConnectionError(OllamaClientError):
    """無法連線至本機 Ollama 服務。"""
    pass


class OllamaTimeoutError(OllamaClientError):
    """Ollama 推論逾時。"""
    pass


class OllamaResponseError(OllamaClientError):
    """Ollama 回應格式異常或模型回傳錯誤。"""
    pass


# ── 本機離線白名單校驗 ──
_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def validate_local_host(url: str) -> str:
    """
    確保請求目標僅限本機回環或內網私有位址，杜絕意外出網連線外部公網。
    """
    parsed = urllib.parse.urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return "http://localhost:11434"

    # 允許 localhost 與本機回環
    if hostname in _LOCAL_HOSTNAMES:
        return url.rstrip("/")

    # 允許局域網私有網段 (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
    if (
        hostname.startswith("10.")
        or hostname.startswith("192.168.")
        or (hostname.startswith("172.") and any(hostname.startswith(f"172.{i}.") for i in range(16, 32)))
    ):
        return url.rstrip("/")

    raise OllamaConnectionError(
        f"安全攔截：目標主機 '{hostname}' 非本機回環 (127.0.0.1/localhost) 或內網私有網段，"
        f"已阻止出網請求以符合 100% 本機隔離策略。"
    )


def get_ollama_host() -> str:
    raw_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    return validate_local_host(raw_host)


def get_default_vision_model() -> str:
    return os.getenv("OLLAMA_MODEL", "qwen3.5:4b")


def get_default_text_model() -> str:
    return os.getenv("OLLAMA_TEXT_MODEL") or os.getenv("OLLAMA_MODEL", "qwen3.5:4b")


def get_default_num_ctx() -> int:
    try:
        return int(os.getenv("OLLAMA_NUM_CTX", "16384"))
    except (ValueError, TypeError):
        return 16384


def get_default_keep_alive() -> str:
    return os.getenv("OLLAMA_KEEP_ALIVE", "10m")


def clean_llm_output(text: str, strip_markdown_fence: bool = True) -> str:
    """
    清理推理模型輸出：
    1. 移除 <think>...</think> 標籤與內部思考推導內容。
    2. 若 strip_markdown_fence 為真，剝除最外層的 ```markdown 或 ```json 包裹。
    """
    if not text:
        return ""

    # 移除 <think> ... </think> 區塊 (包含未閉合的尾部思考區塊)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text)
    cleaned = re.sub(r"<think>[\s\S]*$", "", cleaned).strip()

    if strip_markdown_fence:
        # 清除開頭 ```markdown / ```json / ```text / ```
        cleaned = re.sub(r"^```(?:markdown|json|text)?\s*\n?", "", cleaned)
        # 清除結尾 ```
        cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

    return cleaned


def is_ollama_available(host: Optional[str] = None, timeout: float = 0.8) -> bool:
    """
    探測本機 Ollama 服務是否正在運作。
    自動針對 Windows loopback 優化 (localhost 與 127.0.0.1)。
    """
    target_host = validate_local_host(host or get_ollama_host())
    # 在 Windows 上優先使用 127.0.0.1 避免 IPv6 ::1 探測延遲
    probe_host = target_host.replace("://localhost:", "://127.0.0.1:") if "://localhost:" in target_host else target_host
    try:
        req = urllib.request.Request(f"{probe_host}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ollama_chat(
    prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
    model: Optional[str] = None,
    images: Optional[List[Union[bytes, str]]] = None,
    system: Optional[str] = None,
    format: Optional[Union[str, Dict[str, Any]]] = None,
    num_ctx: Optional[int] = None,
    temperature: float = 0.1,
    think: bool = False,
    keep_alive: Optional[str] = None,
    timeout: float = 180.0,
    host: Optional[str] = None,
    strip_fence: bool = True,
    check_service: bool = True,
) -> str:
    """
    發送統一的 Ollama 對話推論請求（同步），採用 /api/chat 端點。
    
    支援：
    - 多模態視覺影像（傳入 PNG/JPEG raw bytes 或 Base64 字串）
    - 思考抑制（think=False 避免延遲暴增與污染內文）
    - 上下文大小控制（num_ctx 避免預設 2048 截斷）
    - 結構化輸出（format="json" 或 JSON Schema 字典）
    """
    target_host = validate_local_host(host or get_ollama_host())
    if check_service and not is_ollama_available(target_host, timeout=0.8):
        raise OllamaConnectionError(f"本機 Ollama 服務未啟動或無法連線 ({target_host})")
    target_model = model or (get_default_vision_model() if images else get_default_text_model())
    target_num_ctx = num_ctx if num_ctx is not None else get_default_num_ctx()
    target_keep_alive = keep_alive or get_default_keep_alive()

    # 組合訊息列表
    chat_messages: List[Dict[str, Any]] = []
    if system:
        chat_messages.append({"role": "system", "content": system})

    if messages:
        chat_messages.extend(messages)
    elif prompt is not None:
        user_msg: Dict[str, Any] = {"role": "user", "content": prompt}
        if images:
            formatted_images: List[str] = []
            for img in images:
                if isinstance(img, bytes):
                    formatted_images.append(base64.b64encode(img).decode("utf-8"))
                elif isinstance(img, str):
                    # 若已是 base64 或路徑
                    if img.startswith("data:image"):
                        img = img.split(",", 1)[-1]
                    formatted_images.append(img)
            user_msg["images"] = formatted_images
        chat_messages.append(user_msg)
    else:
        raise ValueError("必須提供 prompt 或 messages 參數。")

    payload: Dict[str, Any] = {
        "model": target_model,
        "messages": chat_messages,
        "stream": False,
        "options": {
            "num_ctx": target_num_ctx,
            "temperature": temperature,
        },
        "keep_alive": target_keep_alive,
    }

    # 思考標籤控制
    if not think:
        payload["think"] = False
        payload["options"]["thinking"] = False

    # 結構化輸出格式限制
    if format:
        payload["format"] = format

    req_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{target_host}/api/chat",
        data=req_bytes,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_body = resp.read().decode("utf-8")
            res_data = json.loads(raw_body)
    except urllib.error.HTTPError as e:
        err_msg = ""
        try:
            err_msg = e.read().decode("utf-8")
        except Exception:
            pass
        raise OllamaResponseError(f"Ollama HTTP 錯誤 ({e.code}): {err_msg or e.reason}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise OllamaConnectionError(f"連線至本地 Ollama 失敗: {e}")
    except json.JSONDecodeError as e:
        raise OllamaResponseError(f"無法解析 Ollama 回應 JSON: {e}")

    content = res_data.get("message", {}).get("content", "")
    return clean_llm_output(content, strip_markdown_fence=strip_fence)


async def async_ollama_chat(*args: Any, **kwargs: Any) -> str:
    """
    非同步包裝器，透過 asyncio.to_thread 執行同步阻塞請求，避免阻礙事件迴圈。
    """
    return await asyncio.to_thread(ollama_chat, *args, **kwargs)


def ollama_structured_chat(
    prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, Any]]] = None,
    schema: Optional[Union[Dict[str, Any], str]] = None,
    model: Optional[str] = None,
    images: Optional[List[Union[bytes, str]]] = None,
    system: Optional[str] = None,
    timeout: float = 60.0,
    **kwargs: Any,
) -> Optional[Union[Dict[str, Any], List[Any]]]:
    """
    執行結構化輸出請求，利用 Ollama JSON Schema 格式，並保證回傳 Python 結構化資料 (dict / list)。
    """
    fmt: Any = schema if schema else "json"
    raw_output = ollama_chat(
        prompt=prompt,
        messages=messages,
        model=model,
        images=images,
        system=system,
        format=fmt,
        timeout=timeout,
        strip_fence=True,
        **kwargs,
    )
    if not raw_output:
        return None

    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        # 備援容錯：尋找字串中的第一個 JSON 陣列或物件
        match = re.search(r"(\[.*\]|\{.*\})", raw_output, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        return None
