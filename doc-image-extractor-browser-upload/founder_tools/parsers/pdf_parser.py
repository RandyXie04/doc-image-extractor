import sys
import os
from pathlib import Path

# 將上層目錄加入 sys.path 以便 import 既有的修復腳本
sys.path.insert(0, str(Path(__file__).parent.parent))

from fix_founder_fonts import clean_founder_text
from core.document_model import UnifiedDocument, SectionNode, ParagraphNode, RunNode

class PdfParser:
    """
    PDF 來源文件解析器
    從 PDF 抽取文字，並自動呼叫方正字庫 (Founder Fonts) CMap 修復模組。
    無法解析的生僻字，保留其未解析狀態 (若修復模組無法辨識)。
    """
    
    @classmethod
    def parse(cls, filepath: str) -> UnifiedDocument:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError("請安裝 PyMuPDF: pip install pymupdf")
            
        doc = UnifiedDocument()
        
        # 由於 PDF 沒有原始的 OpenXML，我們只建立純文字的 RunNode
        pdf_doc = fitz.open(filepath)
        
        for page_idx, page in enumerate(pdf_doc):
            # 以每頁為一個 Section 來管理 (可以根據需求調整)
            section = SectionNode(title=f"Page {page_idx + 1}")
            
            raw_text = page.get_text()
            
            # 使用使用者的方正字庫修復模組
            cleaned_text = clean_founder_text(raw_text)
            
            # 建立段落
            for line in cleaned_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                    
                para_node = ParagraphNode()
                # 建立單一的 RunNode
                run_node = RunNode(
                    text=line,
                    original_xml=None # PDF 來源無原始 XML
                )
                para_node.runs.append(run_node)
                section.paragraphs.append(para_node)
                
            doc.sections.append(section)
            
        pdf_doc.close()
        return doc
