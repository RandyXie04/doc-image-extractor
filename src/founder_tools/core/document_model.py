from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class FootnoteRecord:
    """代表一條獨立的註釋紀錄"""
    footnote_id: str            # 內部唯一識別碼，通常為流水號或標記內容
    marker_text: str            # 來源標記，例如 "①"、"1"、"〔1〕"
    content: str                # 註釋完整內容
    is_unresolved: bool = False # 註釋內容是否包含無法解析之字元

@dataclass
class RunNode:
    """代表一個最小文字片段（對應 OpenXML w:r 或 PDF 文本片段）"""
    text: str
    is_footnote_marker: bool = False
    marker_ref_id: Optional[str] = None # 若此 Run 為註腳標記，對應的 footnote_id
    original_xml: Optional[str] = None  # 若為 DOCX 來源，可暫存原本的 w:r XML 以保留樣式

@dataclass
class ParagraphNode:
    """代表一個段落"""
    runs: List[RunNode] = field(default_factory=list)
    is_heading: bool = False
    
    @property
    def text(self) -> str:
        """獲取段落純文字"""
        return "".join(run.text for run in self.runs)

@dataclass
class SectionNode:
    """代表一個章節結構"""
    title: str = ""
    paragraphs: List[ParagraphNode] = field(default_factory=list)

@dataclass
class UnifiedDocument:
    """統一語義文件模型，隔離來源格式與輸出產生的差異"""
    sections: List[SectionNode] = field(default_factory=list)
    footnotes: Dict[str, FootnoteRecord] = field(default_factory=dict)
    unresolved_chars_count: int = 0
