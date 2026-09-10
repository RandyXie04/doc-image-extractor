import re

class HeadingDetector:
    @staticmethod
    def detect_block_level(block: dict, page_width: float = 0.0) -> int:
        """
        根據 layout block 的文字與幾何特徵（如可用）偵測標題層級。
        回傳 1, 2, 3 表示 H1, H2, H3，若為普通內文則回傳 0。
        """
        # Extract full text
        text_parts = []
        bboxes = []
        is_bold = False
        font_sizes = []

        for line in block.get("lines", []):
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
        if not text or len(text) > 40:
            return 0
            
        if text.endswith('。') or text.endswith('，') or text.endswith('.') or text.endswith(','):
            return 0

        # 基本文字正則偵測
        level_by_regex = 0
        if re.match(r'^第[一二三四五六七八九十百零]+[章卷編篇]', text) or re.match(r'^(Chapter|Part)\s*\d+', text) or re.match(r'^(?:附錄|附录|參考文獻|参考文献|前言|序言|楔子|跋|後記|后记)$', text):
            level_by_regex = 1
        elif re.match(r'^第[一二三四五六七八九十百零]+[節条條]', text) or re.match(r'^\d+\.\d+(?!\.)', text):
            level_by_regex = 2
        elif re.match(r'^\d+\.\d+\.\d+', text) or re.match(r'^[(（][一二三四五六七八九十\d]+[)）]', text) or re.match(r'^[①-⑩]', text):
            level_by_regex = 3

        if level_by_regex > 0:
            return level_by_regex

        # 如果正則未能匹配，則檢查幾何與樣式特徵
        # 若為粗體、置中（透過 bbox 判定）或字數極少的單行文字，可判定為標題
        is_centered = False
        if bboxes and page_width > 0:
            # 假設 bbox 格式為 [x0, y0, x1, y1]
            x0, y0, x1, y1 = bboxes[0]
            center_x = (x0 + x1) / 2
            page_center = page_width / 2
            # 若中心點誤差小於 10% page width 則視為置中
            if abs(center_x - page_center) < page_width * 0.1:
                is_centered = True
                
        # 啟發式規則：若置中且短（<20字），視為 H2
        if is_centered and len(text) < 20:
            return 2
            
        # 啟發式規則：若全粗體且短，視為 H3
        if is_bold and len(text) < 20:
            return 3

        return 0
