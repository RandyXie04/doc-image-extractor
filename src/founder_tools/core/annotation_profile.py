from dataclasses import dataclass
from typing import Optional

@dataclass
class AnnotationProfile:
    """定義一本書籍的註釋組織規則與提取策略 (v2.0)"""
    annotation_label: Optional[str]   # 註釋區塊標籤，如 "校注"、"注釋"、"注解"、"注"；若無標籤則為 None
    marker_type: str                  # 標記型態: "circled_number", "square_bracket", "chinese_bracket", "plain_number"
    marker_scope: str                 # 標記編號重置範圍: "chapter" (每章重編), "page" (每頁重編), "global" (全書唯一)
    numbering_scope: str              # 腳註輸出編號模式: "continuous" (全書連續), "each_page" (每頁重新編號)
    footnote_location: str            # 註釋在來源的位置: "page_bottom" (頁底), "section_end" (段/章節末), "inline"
    extraction_strategy: str          # 萃取策略: "explicit_label" (標籤區塊), "marker_based" (標記引導), "contextual" (上下文純數字)
    confidence: float = 1.0           # 分析信心度 (0.0 ~ 1.0)
    is_locked: bool = False           # 是否已經由人工確認鎖定
