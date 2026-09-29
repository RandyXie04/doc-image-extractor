import re
from typing import Optional


class HeadingDetector:
    """
    書籍 PDF 標題層級偵測器。
    支援三層判定：正則規則 → TOC 索引校正 → AI 語義兜底。
    """

    # 句末標點（出現任何一個即排除標題候選資格）
    _SENTENCE_PUNCTUATION = set('。，.！？；：、')

    # 中文常見正文功能詞（出現 ≥ 2 次則排除標題候選資格）
    _BODY_FUNCTION_WORDS = list('的了在是有與和於為以從到對從但又及')

    # 表格/圖片標題正則
    _CAPTION_PATTERN = re.compile(
        r'^(?:表|圖|图|Table|Figure)\s*[\d\-\.]+[.、:：\s]',
        re.IGNORECASE
    )

    @staticmethod
    def detect_caption_type(text: str) -> Optional[str]:
        """
        偵測文字是否為表格或圖片標題。
        回傳 "table" / "figure" / None。
        """
        if not text or not text.strip():
            return None
        text = text.strip()
        if re.match(r'^(?:表|Table)\s*[\d\-\.]+', text, re.IGNORECASE):
            return "table"
        if re.match(r'^(?:圖|图|Figure)\s*[\d\-\.]+', text, re.IGNORECASE):
            return "figure"
        return None

    @staticmethod
    def detect_block_level(
        block: dict,
        page_width: float = 0.0,
        toc_index: dict = None,
        page_num: int = 0
    ) -> int:
        """
        根據 layout block 的文字與幾何特徵偵測標題層級。
        回傳 1, 2, 3 表示 H1, H2, H3，若為普通內文則回傳 0。

        Parameters:
            block: layout block dict (含 lines > spans > content/bold/size)
            page_width: 頁面寬度（用於居中判定）
            toc_index: 目錄索引表 {fuzzy_title: (level, expected_page)}（可選）
            page_num: 當前頁碼（配合 toc_index 使用）
        """
        # ── 1. 提取文字與特徵 ──
        text_parts = []
        bboxes = []
        is_bold = False
        font_sizes = []
        total_lines = 0

        for line in block.get("lines", []):
            total_lines += 1
            if "bbox" in line:
                bboxes.append(line["bbox"])
            for span in line.get("spans", []):
                content = span.get("content", "")
                if content:
                    text_parts.append(content)
                    if span.get("bold"):
                        is_bold = True
                    if "size" in span:
                        font_sizes.append(span["size"])

        text = "".join(text_parts).strip()
        if not text:
            return 0

        # ── 2. 長度門檻（收緊至 25 字） ──
        if len(text) > 25:
            return 0

        # ── 3. 句末標點排除（擴充完整集） ──
        if text[-1] in HeadingDetector._SENTENCE_PUNCTUATION:
            return 0

        # 文字中間包含句末標點也排除（如 "xxx。yyy" 是正文斷句）
        clean_text = text.rstrip()
        if any(p in clean_text[:-1] for p in '。！？'):
            return 0

        # ── 4. 表格/圖片標題排除 ──
        if HeadingDetector._CAPTION_PATTERN.match(text):
            return 0

        # ── 5. 正則規則偵測（最高優先級） ──
        level_by_regex = 0
        if (re.match(r'^第[一二三四五六七八九十百零]+[章卷編篇]', text) or
                re.match(r'^(Chapter|Part)\s*\d+', text) or
                re.match(r'^(?:附錄|附录|參考文獻|参考文献|前言|序言|楔子|跋|後記|后记|目錄|目录|序|结语|主要参考文献)$', text)):
            level_by_regex = 1
        elif (re.match(r'^第[一二三四五六七八九十百零]+[節条條]', text) or
              re.match(r'^\d+\.\d+(?!\.)', text)):
            level_by_regex = 2
        elif (re.match(r'^\d+\.\d+\.\d+', text) or
              re.match(r'^[(（][一二三四五六七八九十\d]+[)）]', text) or
              re.match(r'^[①-⑩]', text)):
            level_by_regex = 3

        if level_by_regex > 0:
            # 若有 TOC 索引，用 TOC 層級覆蓋正則結果
            if toc_index and page_num > 0:
                toc_level = _match_toc_entry(text, page_num, toc_index)
                if toc_level > 0:
                    return toc_level
            return level_by_regex

        # ── 6. TOC 索引校正（對非正則匹配的候選標題） ──
        if toc_index and page_num > 0:
            toc_level = _match_toc_entry(text, page_num, toc_index)
            if toc_level > 0:
                return toc_level

        # ── 7. 幾何與樣式啟發式（收緊條件） ──

        # 7a. 居中判定
        is_centered = False
        if bboxes and page_width > 0:
            x0, y0, x1, y1 = bboxes[0]
            center_x = (x0 + x1) / 2
            page_center = page_width / 2
            if abs(center_x - page_center) < page_width * 0.1:
                is_centered = True

        # 7b. 居中 + 短文 → H2（保留原有邏輯，但排除含正文功能詞的文字）
        if is_centered and len(text) < 20:
            if not _has_body_word_pattern(text):
                return 2

        # 7c. 粗體 → H3（大幅收緊條件）
        if is_bold and len(text) < 20:
            # 必須是單行 block（多行 block 中的粗體大概率是正文強調）
            if total_lines > 1:
                return 0
            # 排除含正文功能詞的文字
            if _has_body_word_pattern(text):
                return 0
            # 排除含常見正文句式的短語
            if re.search(r'[的了]$', text):
                return 0
            return 3

        return 0


def _has_body_word_pattern(text: str) -> bool:
    """檢查文字是否包含 ≥ 2 個常見正文功能詞，以排除正文加粗短句。"""
    count = 0
    for w in HeadingDetector._BODY_FUNCTION_WORDS:
        count += text.count(w)
        if count >= 2:
            return True
    return False


def _match_toc_entry(text: str, page_num: int, toc_index: dict, threshold: float = 0.8) -> int:
    """
    將候選標題文字與 TOC 索引表做 fuzzy match。
    回傳匹配到的層級 (1/2/3)，未匹配回傳 0。

    toc_index 格式: {normalized_title: {"level": int, "page": int}}
    """
    if not toc_index:
        return 0

    normalized = _normalize_title(text)

    # 精確匹配
    if normalized in toc_index:
        entry = toc_index[normalized]
        if abs(entry["page"] - page_num) <= 2:
            return entry["level"]

    # Fuzzy 匹配（簡易版：包含關係）
    for toc_title, entry in toc_index.items():
        if abs(entry["page"] - page_num) > 3:
            continue
        sim = _simple_similarity(normalized, toc_title)
        if sim >= threshold:
            return entry["level"]

    return 0


def _normalize_title(text: str) -> str:
    """正規化標題文字：去除空白、統一全半形。"""
    text = text.strip()
    text = re.sub(r'\s+', '', text)
    # 全形數字 → 半形
    text = text.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    return text


def _simple_similarity(a: str, b: str) -> float:
    """簡易字元級相似度（Jaccard-like）。"""
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    intersection = set_a & set_b
    union = set_a | set_b
    if not union:
        return 0.0
    return len(intersection) / len(union)
