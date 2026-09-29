# // ==============================================================================
# // ai_heading_classifier.py: AI 語義輔助標題判定模組
# // - 使用 LLM (DeepSeek-V4 首選) 對「不確定」的文本 block 進行語義判定
# // - 批次打包、超時防護、失敗降級、結果快取
# // ==============================================================================

import os
import re
import json
import hashlib
import time
from pathlib import Path
from typing import Optional


class AIHeadingClassifier:
    """
    AI 語義輔助標題分類器。
    在啟發式規則和 TOC 索引都無法確定的情況下，呼叫 LLM API 做最終判定。
    """

    # 支援的 API 提供者
    PROVIDERS = {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-4o-mini",
        },
        "custom": {
            "base_url": None,  # from env CUSTOM_LLM_BASE_URL
            "default_model": None,
        },
    }

    # 給 LLM 的判定 Prompt
    SYSTEM_PROMPT = """你是一位中文書籍排版專家。你將收到一本書 PDF 中連續的幾個文本片段。
每個片段附有其字型大小、是否粗體、是否居中的資訊。
請判斷每個片段是「標題」還是「正文」，如果是標題請給出層級。

判斷規則：
- H1（章標題）：如「第一章 xxx」「上篇 xxx」「序」「後記」等主要結構劃分
- H2（節標題）：段落小標題，通常居中或加粗，不含句號，語意上是一個主題的概括
- H3（子節標題）：如「（一）xxx」「1.1 xxx」格式
- body（正文）：含完整句子結構（有主謂賓、句號）的文字，即使加粗也是正文
- caption（表格/圖片標題）：「表X-X xxx」「圖X-X xxx」格式，不是章節標題
- quote（引用/楷體引文）：引用他人論述、法規條文、案例等，語氣與正文不同

請以 JSON 陣列回覆，每個元素格式為：
{"index": 0, "type": "H1|H2|H3|body|caption|quote", "confidence": 0.0-1.0}

只回覆 JSON，不要其他文字。"""

    def __init__(
        self,
        provider: str = "deepseek",
        api_key: str = None,
        base_url: str = None,
        model: str = None,
        cache_dir: str = None,
        timeout: float = 10.0,
    ):
        self.provider = provider.lower()
        self.timeout = timeout

        # Resolve API key
        if api_key:
            self.api_key = api_key
        elif self.provider == "deepseek":
            self.api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("CUSTOM_LLM_API_KEY")
        elif self.provider == "openai":
            self.api_key = os.getenv("OPENAI_API_KEY")
        elif self.provider == "custom":
            self.api_key = os.getenv("CUSTOM_LLM_API_KEY")
        else:
            self.api_key = None

        # Resolve base URL
        provider_config = self.PROVIDERS.get(self.provider, {})
        if base_url:
            self.base_url = base_url
        elif self.provider == "custom":
            self.base_url = os.getenv("CUSTOM_LLM_BASE_URL", "")
        else:
            self.base_url = provider_config.get("base_url", "")

        # Resolve model
        self.model = model or provider_config.get("default_model", "deepseek-chat")

        # Cache directory
        if cache_dir:
            self._cache_dir = Path(cache_dir)
        else:
            self._cache_dir = Path(os.getenv("TEMP", "/tmp")) / "doc-image-extractor-temp" / "ai_heading_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        self._available = bool(self.api_key and self.base_url)

    @property
    def is_available(self) -> bool:
        return self._available

    def classify_blocks(self, blocks_batch: list) -> list:
        """
        批次判定一組 block 的類型。

        Parameters:
            blocks_batch: list of dicts, each with:
                - "text": str
                - "font_size": float (optional)
                - "is_bold": bool (optional)
                - "is_centered": bool (optional)

        Returns:
            list of dicts: {"type": "H1|H2|H3|body|caption|quote", "confidence": float}
            與輸入同序。若 AI 呼叫失敗，回傳所有 type="uncertain" 的降級結果。
        """
        if not blocks_batch:
            return []

        # 檢查快取
        batch_hash = self._compute_batch_hash(blocks_batch)
        cached = self._load_cache(batch_hash)
        if cached is not None:
            return cached

        # 若 AI 不可用，直接降級
        if not self._available:
            return [{"type": "uncertain", "confidence": 0.0}] * len(blocks_batch)

        # 構建 user prompt
        user_prompt = self._build_user_prompt(blocks_batch)

        # 呼叫 API
        try:
            result = self._call_api(user_prompt)
            if result:
                self._save_cache(batch_hash, result)
                return result
        except Exception:
            pass

        # 降級
        return [{"type": "uncertain", "confidence": 0.0}] * len(blocks_batch)

    def _build_user_prompt(self, blocks_batch: list) -> str:
        """構建送給 LLM 的 user prompt。"""
        items = []
        for i, block in enumerate(blocks_batch):
            item = {
                "index": i,
                "text": block.get("text", ""),
                "font_size": block.get("font_size", None),
                "is_bold": block.get("is_bold", False),
                "is_centered": block.get("is_centered", False),
            }
            items.append(item)
        return json.dumps(items, ensure_ascii=False, indent=2)

    def _call_api(self, user_prompt: str) -> Optional[list]:
        """呼叫 LLM API（OpenAI-compatible chat completion）。"""
        import urllib.request
        import urllib.error

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2000,
        }

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                content = resp_data["choices"][0]["message"]["content"].strip()

                # 嘗試解析 JSON（可能被 markdown code block 包裹）
                content = re.sub(r'^```(?:json)?\s*', '', content)
                content = re.sub(r'\s*```$', '', content)

                results = json.loads(content)
                if isinstance(results, list):
                    return [
                        {
                            "type": r.get("type", "uncertain"),
                            "confidence": float(r.get("confidence", 0.5)),
                        }
                        for r in results
                    ]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError):
            pass

        return None

    def _compute_batch_hash(self, blocks_batch: list) -> str:
        """計算批次的 hash（用於快取 key）。"""
        texts = [b.get("text", "") for b in blocks_batch]
        raw = "|".join(texts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _load_cache(self, batch_hash: str) -> Optional[list]:
        """從磁碟快取讀取結果。"""
        cache_file = self._cache_dir / f"{batch_hash}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _save_cache(self, batch_hash: str, results: list):
        """將結果寫入磁碟快取。"""
        cache_file = self._cache_dir / f"{batch_hash}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False)
        except Exception:
            pass


def should_trigger_ai(
    heading_density: int = 0,
    is_ambiguous: bool = False,
    max_consecutive_headings: int = 3,
) -> bool:
    """
    判斷是否應觸發 AI 判定。

    Parameters:
        heading_density: 連續被判定為標題的 block 數量
        is_ambiguous: 當前 block 的啟發式結果是否不確定
        max_consecutive_headings: 觸發 AI 的連續標題密度閾值

    Returns:
        True if AI classification should be triggered.
    """
    if is_ambiguous:
        return True
    if heading_density >= max_consecutive_headings:
        return True
    return False
