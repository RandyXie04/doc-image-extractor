# // ==============================================================================
# // ai_kaiti_classifier.py: AI 楷體段落輔助辨識模組 (Gemini Vision + LLM)
# // - Phase 1: Vision 截圖辨識字型（楷體 vs 宋體/黑體），適用任何 PDF 排版系統
# // - Phase 2: LLM 段落結構修正（縮排與段落邊界語義判定）
# // - Font Name Learning Cache：自動學習 PDF 內部字型名稱→視覺字型的對映
# // - 磁碟快取、超時防護、失敗降級
# // ==============================================================================

import os
import re
import json
import hashlib
import base64
import time
from pathlib import Path
from typing import Optional

# pyrefly: ignore [missing-import]
import fitz


class AIKaitiClassifier:
    """
    AI 楷體段落分類器。
    使用 Gemini Vision API 從 PDF 截圖中辨識字型樣式，
    並使用 LLM 進行段落結構語義修正。
    """

    # Vision 字型辨識 Prompt
    VISION_SYSTEM_PROMPT = """你是一位中文排版字型辨識專家。你將看到一段 PDF 頁面的截圖，其中包含中文文字。
請判斷截圖中的主要文字使用什麼字型。

判斷要點：
- **楷體 (kaiti)**：筆畫有粗細變化，起筆收筆有頓挫，結構疏朗，類似手寫書法風格。常用於引文、注釋、法條引用。
- **宋體 (songti)**：橫細豎粗，筆畫末端有三角形裝飾（襯線），是正文最常見的字型。
- **黑體 (heiti)**：筆畫粗細均勻，無襯線，常用於標題或強調。
- **仿宋 (fangsong)**：介於宋體與楷體之間，筆畫較均勻但有楷書風格的傾斜。

請以 JSON 格式回覆：
{"font": "kaiti|songti|heiti|fangsong|other", "confidence": 0.0-1.0, "reasoning": "簡述判斷依據"}

只回覆 JSON，不要其他文字。"""

    # 段落結構判定 Prompt
    PARAGRAPH_SYSTEM_PROMPT = """你是一位中文書籍排版專家。你將收到一組連續的文字塊資料，每個塊附有：
- text: 文字內容
- font_tag: 字型標籤 (kaiti/songti/heiti 等)
- x0: 左邊界座標 (pt)
- y0: 上邊界座標 (pt)
- base_x0: 頁面正文基準左邊界

請判斷：
1. 哪些塊應合併為同一段落
2. 每個段落的縮排類型（首行縮排 / 整段縮排 / 無縮排）
3. 每個段落是否為楷體引文

回覆 JSON 陣列，每個元素格式：
{"paragraph_id": 0, "block_indices": [0,1,2], "indent_type": "first_line|block|none", "is_kaiti_quote": true|false}

只回覆 JSON，不要其他文字。"""

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        cache_dir: str = None,
        timeout: float = 15.0,
        screenshot_dpi: int = 150,
    ):
        # Resolve API key
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("AI_KAITI_MODEL", "gemini-3.1-pro-preview")
        self.timeout = timeout
        self.screenshot_dpi = screenshot_dpi

        # Cache directory
        if cache_dir:
            self._cache_dir = Path(cache_dir)
        else:
            self._cache_dir = (
                Path(os.getenv("TEMP", "/tmp"))
                / "doc-image-extractor-temp"
                / "ai_kaiti_cache"
            )
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        # Lazy-init the Gemini client
        self._client = None
        self._available = bool(self.api_key)

        # ── Font Name Learning Cache ──
        # 將 PDF 內部字型名稱對映到視覺字型標籤，適用於任何排版系統：
        # - 方正: 'FZKTK--GBK1-0', 'FZKai-Z03S'
        # - Adobe InDesign: 'STKaitiSC-Regular', 'AdobeKaitiStd-Regular'
        # - CID-keyed: 'Identity-H', 'CIDFont+F3'
        # - 嵌入子集: 'BCDEFG+KaiTi', 'ABCDEF+楷体'
        # - WPS/金山/其他: 'Font-12', 'T3_0', 任意私有名稱
        # 一旦 Vision API 辨識過某 font name，後續同名字型的 block 全部免呼叫 API。
        self._font_name_cache: dict[str, str] = {}

        # Statistics
        self.stats = {
            "vision_calls": 0,
            "vision_cache_hits": 0,
            "font_name_learned": 0,
            "font_name_cache_hits": 0,
            "paragraph_calls": 0,
            "paragraph_cache_hits": 0,
            "failures": 0,
        }

    def _get_client(self):
        """Lazy-initialize the google-genai client."""
        if self._client is None:
            try:
                from google import genai  # pyrefly: ignore [missing-import]

                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                print(
                    "[AIKaitiClassifier] google-genai SDK 未安裝，"
                    "請執行: pip install -U google-genai"
                )
                self._available = False
            except Exception as e:
                print(f"[AIKaitiClassifier] Gemini client 初始化失敗: {e}")
                self._available = False
        return self._client

    @property
    def is_available(self) -> bool:
        return self._available

    # =========================================================================
    # Phase 1: Vision — 字型辨識（含 Font Name Learning Cache）
    # =========================================================================

    def lookup_font_name(self, font_name: str) -> str | None:
        """
        查詢 font name 學習快取。
        
        Returns:
            已知的字型標籤，或 None（尚未學習過此 font name）。
        """
        return self._font_name_cache.get(font_name.lower())

    def _learn_font_name(self, font_name: str, font_tag: str):
        """將 font_name → font_tag 的對映寫入學習快取。"""
        key = font_name.lower()
        if key and key not in self._font_name_cache:
            self._font_name_cache[key] = font_tag
            self.stats["font_name_learned"] += 1
            print(
                f"[AI-Kaiti] 🧠 學習到字型對映: "
                f"'{font_name}' → {font_tag} "
                f"(後續相同 font name 的 block 將免呼叫 API)"
            )

    def classify_block_font(
        self,
        page: fitz.Page,
        block_bbox: list | tuple,
        block_text: str = "",
        font_names: list[str] | None = None,
    ) -> str:
        """
        使用 Gemini Vision 判斷指定 block 區域的字型。
        
        如果提供了 font_names，會先檢查學習快取：
        - 快取命中 → 直接回傳，不呼叫 API
        - 快取未命中 → 呼叫 Vision API，並將結果寫入學習快取

        Parameters:
            page: PyMuPDF Page 物件
            block_bbox: [x0, y0, x1, y1] 區域座標
            block_text: 該 block 的文字內容（用於快取 key）
            font_names: 該 block 中出現的 PDF 內部字型名稱列表

        Returns:
            字型標籤: "kaiti" / "songti" / "heiti" / "fangsong" / "other" / "unknown"
        """
        if not self._available:
            return "unknown"

        # ── Step 1: Font Name Learning Cache 檢查 ──
        # 若此 block 的任一 font_name 已被學習過，直接回傳
        if font_names:
            for fn in font_names:
                cached_tag = self.lookup_font_name(fn)
                if cached_tag is not None:
                    self.stats["font_name_cache_hits"] += 1
                    return cached_tag

        # ── Step 2: 磁碟快取檢查 ──
        cache_key = self._compute_hash(f"vision:{block_text}:{list(block_bbox)}")
        cached = self._load_cache(cache_key)
        if cached is not None:
            self.stats["vision_cache_hits"] += 1
            font_tag = cached.get("font", "unknown")
            # 回填學習快取
            if font_names:
                for fn in font_names:
                    self._learn_font_name(fn, font_tag)
            return font_tag

        # ── Step 3: 渲染截圖 ──
        try:
            image_bytes = self._render_block_screenshot(page, block_bbox)
        except Exception as e:
            print(f"[AIKaitiClassifier] 截圖渲染失敗: {e}")
            self.stats["failures"] += 1
            return "unknown"

        # ── Step 4: 呼叫 Gemini Vision ──
        try:
            result = self._call_gemini_vision(image_bytes, block_text)
            if result:
                self._save_cache(cache_key, result)
                self.stats["vision_calls"] += 1
                font_tag = result.get("font", "unknown")
                # 寫入學習快取
                if font_names:
                    for fn in font_names:
                        self._learn_font_name(fn, font_tag)
                return font_tag
        except Exception as e:
            print(f"[AIKaitiClassifier] Vision API 呼叫失敗: {e}")
            self.stats["failures"] += 1

        return "unknown"

    def is_block_kaiti(
        self,
        page: fitz.Page,
        block_bbox: list | tuple,
        block_text: str = "",
        font_names: list[str] | None = None,
    ) -> bool:
        """
        便利方法：判斷指定 block 是否為楷體。

        Returns:
            True if the block is identified as KaiTi font.
        """
        font = self.classify_block_font(
            page, block_bbox, block_text, font_names=font_names
        )
        return font == "kaiti"

    def _render_block_screenshot(
        self, page: fitz.Page, bbox: list | tuple
    ) -> bytes:
        """
        渲染指定 block 區域的截圖（PNG bytes）。
        在 block bbox 外擴 10pt 以提供上下文。
        """
        x0, y0, x1, y1 = bbox
        page_rect = page.rect

        # 擴展邊界（提供視覺上下文）
        pad = 10.0
        clip = fitz.Rect(
            max(x0 - pad, page_rect.x0),
            max(y0 - pad, page_rect.y0),
            min(x1 + pad, page_rect.x1),
            min(y1 + pad, page_rect.y1),
        )

        # 渲染為 pixmap
        mat = fitz.Matrix(self.screenshot_dpi / 72.0, self.screenshot_dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, clip=clip)
        return pix.tobytes("png")

    def _call_gemini_vision(
        self, image_bytes: bytes, text_hint: str = ""
    ) -> Optional[dict]:
        """
        呼叫 Gemini Vision API 進行字型辨識。
        """
        client = self._get_client()
        if client is None:
            return None

        from google import genai  # pyrefly: ignore [missing-import]
        from google.genai import types  # pyrefly: ignore [missing-import]

        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        user_prompt = "請辨識這段 PDF 截圖中文字的字型。"
        if text_hint:
            user_prompt += f"\n截圖中的文字內容為：「{text_hint[:200]}」"

        try:
            interaction = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(text=self.VISION_SYSTEM_PROMPT),
                            types.Part.from_bytes(
                                data=image_bytes,
                                mime_type="image/png",
                            ),
                            types.Part.from_text(text=user_prompt),
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=500,
                ),
            )

            content = interaction.text.strip()

            # 解析 JSON（可能被 markdown code block 包裹）
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            result = json.loads(content)
            if isinstance(result, dict) and "font" in result:
                return result
        except json.JSONDecodeError as e:
            print(f"[AIKaitiClassifier] Vision 回應 JSON 解析失敗: {e}")
        except Exception as e:
            print(f"[AIKaitiClassifier] Vision API 例外: {e}")

        return None

    # =========================================================================
    # Phase 2: LLM — 段落結構修正
    # =========================================================================

    def classify_paragraph_structure(
        self, blocks_data: list
    ) -> Optional[list]:
        """
        使用 LLM 判斷一組連續 block 的段落結構。

        Parameters:
            blocks_data: list of dicts, each with:
                - "text": str
                - "font_tag": str (kaiti/songti/heiti/...)
                - "x0": float (左邊界座標)
                - "y0": float (上邊界座標)
                - "base_x0": float (頁面正文基準左邊界)

        Returns:
            list of dicts: {"paragraph_id", "block_indices", "indent_type", "is_kaiti_quote"}
            若呼叫失敗，回傳 None（呼叫方應 fallback 到規則型邏輯）。
        """
        if not self._available or not blocks_data:
            return None

        # 快取檢查
        texts = [b.get("text", "")[:100] for b in blocks_data]
        cache_key = self._compute_hash(f"para:{json.dumps(texts, ensure_ascii=False)}")
        cached = self._load_cache(cache_key)
        if cached is not None:
            self.stats["paragraph_cache_hits"] += 1
            return cached

        # 構建 prompt
        prompt_data = []
        for i, block in enumerate(blocks_data):
            prompt_data.append(
                {
                    "index": i,
                    "text": block.get("text", "")[:300],  # 截斷過長文字
                    "font_tag": block.get("font_tag", "unknown"),
                    "x0": round(block.get("x0", 0), 1),
                    "y0": round(block.get("y0", 0), 1),
                    "base_x0": round(block.get("base_x0", 65.0), 1),
                }
            )

        user_prompt = json.dumps(prompt_data, ensure_ascii=False, indent=2)

        try:
            result = self._call_gemini_text(
                system=self.PARAGRAPH_SYSTEM_PROMPT,
                user=user_prompt,
            )
            if result:
                self._save_cache(cache_key, result)
                self.stats["paragraph_calls"] += 1
                return result
        except Exception as e:
            print(f"[AIKaitiClassifier] 段落結構 API 呼叫失敗: {e}")
            self.stats["failures"] += 1

        return None

    def _call_gemini_text(
        self, system: str, user: str
    ) -> Optional[list]:
        """
        呼叫 Gemini LLM API 進行文字分析。
        """
        client = self._get_client()
        if client is None:
            return None

        from google.genai import types  # pyrefly: ignore [missing-import]

        try:
            interaction = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(text=system),
                            types.Part.from_text(text=user),
                        ],
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=2000,
                ),
            )

            content = interaction.text.strip()

            # 解析 JSON
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            result = json.loads(content)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError as e:
            print(f"[AIKaitiClassifier] LLM 回應 JSON 解析失敗: {e}")
        except Exception as e:
            print(f"[AIKaitiClassifier] LLM API 例外: {e}")

        return None

    # =========================================================================
    # 批次處理入口
    # =========================================================================

    def classify_page_blocks(
        self,
        page: fitz.Page,
        body_blocks: list,
        base_x0: float = 65.0,
    ) -> list:
        """
        整合 Phase 1 + Phase 2 的完整頁面處理入口。
        
        Phase 1: 對字型名稱不明確的 block 執行 Vision 辨識
        Phase 2: 基於字型標籤進行段落結構語義判定

        Parameters:
            page: PyMuPDF Page 物件
            body_blocks: 該頁的 body_blocks 列表（PyMuPDF dict block）
            base_x0: 頁面正文基準左邊界

        Returns:
            list of dicts, 每個 block 附加:
                - "font_tag": str
                - "ai_kaiti": bool
        """
        results = []

        for bb in body_blocks:
            bbox = bb.get("bbox", [0, 0, 0, 0])
            lines = bb.get("lines", [])
            bb_text = "".join(
                s.get("text", "") for l in lines for s in l.get("spans", [])
            ).strip()

            if not bb_text:
                results.append({"font_tag": "unknown", "ai_kaiti": False})
                continue

            # Step 1: 規則型字型判定（現有邏輯）
            total_chars = 0
            kaiti_chars = 0
            for line in lines:
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if not span_text:
                        continue
                    total_chars += len(span_text)
                    font_name = span.get("font", "").lower()
                    if "kai" in font_name or "楷" in font_name or "kaiti" in font_name:
                        kaiti_chars += len(span_text)

            rule_kaiti = total_chars > 0 and (kaiti_chars / total_chars) > 0.5

            if rule_kaiti:
                # 規則型已判定為楷體，不需要 AI 輔助
                results.append({"font_tag": "kaiti", "ai_kaiti": True})
            else:
                # Step 2: 規則型失敗，觸發 Vision AI
                font_tag = self.classify_block_font(page, bbox, bb_text)
                results.append({
                    "font_tag": font_tag,
                    "ai_kaiti": font_tag == "kaiti",
                })

        return results

    # =========================================================================
    # 快取工具
    # =========================================================================

    def _compute_hash(self, raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _load_cache(self, key: str) -> Optional[dict | list]:
        cache_file = self._cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    def _save_cache(self, key: str, data):
        cache_file = self._cache_dir / f"{key}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def get_stats_summary(self) -> str:
        """回傳統計摘要字串。"""
        s = self.stats
        total_api = s["vision_calls"] + s["paragraph_calls"]
        total_saved = s["font_name_cache_hits"] + s["vision_cache_hits"] + s["paragraph_cache_hits"]
        return (
            f"AI 楷體辨識統計: "
            f"Vision API={s['vision_calls']}次, "
            f"字型學習={s['font_name_learned']}種 "
            f"(免呼叫命中={s['font_name_cache_hits']}次), "
            f"磁碟快取={s['vision_cache_hits']}次, "
            f"失敗={s['failures']}次 | "
            f"總計 API={total_api}次, 節省={total_saved}次"
        )
