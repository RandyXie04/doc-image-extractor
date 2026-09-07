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
    
    @classmethod
    def detect(cls, text: str, marker_type: str, para_idx: int = -1, sec_idx: int = -1) -> List[MarkerMatch]:
        matches = []
        if marker_type == "circled_number":
            for i, char in enumerate(text):
                if char in cls.CIRCLED_NUMBERS:
                    num = cls.CIRCLED_NUMBERS.index(char) + 1
                    matches.append(MarkerMatch(
                        text=char, number=num, start_char=i, end_char=i+1,
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
