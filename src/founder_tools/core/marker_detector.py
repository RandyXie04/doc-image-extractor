import re
from typing import List
from dataclasses import dataclass

@dataclass
class MarkerMatch:
    text: str           # 原文標記字串，例如 "①" 或 "〔12〕"
    number: int         # 萃取出的純數字，例如 1 或 12
    start_char: int     # 該標記在所屬段落內的起始索引
    end_char: int       # 該標記在所屬段落內的結束索引 (不包含)
    paragraph_idx: int  # 所屬的段落 index (可選)
    section_idx: int    # 所屬的章節 index (可選)

class MarkerDetector:
    """
    多型態標記偵測器
    支援圓圈數字、方括號、六角括號與純數字的偵測。
    """
    # Unicode 圓圈數字 ①(U+2460) 到 ㊿(U+32BF)
    CIRCLED_NUMBERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚㉛㉜㉝㉞㉟㊱㊲㊳㊴㊵㊶㊷㊸㊹㊺㊻㊼㊽㊾㊿"
    # Unicode 上標數字 ⁰¹²³⁴⁵⁶⁷⁸⁹
    SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
    
    @classmethod
    def detect(cls, text: str, marker_type: str = "auto", para_idx: int = -1, sec_idx: int = -1) -> List[MarkerMatch]:
        matches = []
        if marker_type == "auto":
            # 優先偵測高信賴標記：圓圈數字、上標數字、各類括號
            matches = cls.detect(text, "circled_number", para_idx, sec_idx)
            if not matches:
                matches = cls.detect(text, "superscript", para_idx, sec_idx)
            if not matches:
                matches = cls.detect(text, "square_bracket", para_idx, sec_idx)
            if not matches:
                matches = cls.detect(text, "chinese_bracket", para_idx, sec_idx)
            return matches

        if marker_type == "circled_number":
            for i, char in enumerate(text):
                if char in cls.CIRCLED_NUMBERS:
                    num = cls.CIRCLED_NUMBERS.index(char) + 1
                    matches.append(MarkerMatch(
                        text=char, number=num, start_char=i, end_char=i+1,
                        paragraph_idx=para_idx, section_idx=sec_idx
                    ))

        elif marker_type == "superscript":
            # 匹配連續的一個或多個上標數字，如 ¹ 或 ¹²
            super_pattern = f"[{cls.SUPERSCRIPT_DIGITS}]+"
            for m in re.finditer(super_pattern, text):
                raw_str = m.group(0)
                # 轉成常規十進位整數
                norm_digits = "".join(str(cls.SUPERSCRIPT_DIGITS.index(ch)) for ch in raw_str)
                matches.append(MarkerMatch(
                    text=raw_str, number=int(norm_digits),
                    start_char=m.start(), end_char=m.end(),
                    paragraph_idx=para_idx, section_idx=sec_idx
                ))
                    
        elif marker_type == "square_bracket":
            for m in re.finditer(r'\[(\d+)\]', text):
                matches.append(MarkerMatch(
                    text=m.group(0), number=int(m.group(1)),
                    start_char=m.start(), end_char=m.end(),
                    paragraph_idx=para_idx, section_idx=sec_idx
                ))
                
        elif marker_type == "chinese_bracket":
            # 考量可能會有全形方括號 ［］ 或六角括號 〔〕
            for m in re.finditer(r'[〔［](\d+)[〕］]', text):
                matches.append(MarkerMatch(
                    text=m.group(0), number=int(m.group(1)),
                    start_char=m.start(), end_char=m.end(),
                    paragraph_idx=para_idx, section_idx=sec_idx
                ))
                
        elif marker_type == "plain_number":
            for m in re.finditer(r'\d+', text):
                matches.append(MarkerMatch(
                    text=m.group(0), number=int(m.group(0)),
                    start_char=m.start(), end_char=m.end(),
                    paragraph_idx=para_idx, section_idx=sec_idx
                ))
                
        return matches
