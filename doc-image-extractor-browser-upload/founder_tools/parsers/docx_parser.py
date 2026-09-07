import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from core.document_model import UnifiedDocument, SectionNode, ParagraphNode, RunNode, FootnoteRecord

class DocxParser:
    """
    DOCX 來源文件解析器
    從原始 DOCX 中抽取段落與文字，並盡可能保留原始的 w:r XML 以供後續樣式還原。
    """
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    
    @classmethod
    def parse(cls, filepath: str) -> UnifiedDocument:
        # 註冊 namespace，避免 ET.tostring 產生 ns0 前綴
        ET.register_namespace('w', cls.W_NS)
        ns = f"{{{cls.W_NS}}}"
        
        doc = UnifiedDocument()
        section = SectionNode(title="Default Section")
        
        with zipfile.ZipFile(filepath, 'r') as z:
            if 'word/document.xml' not in z.namelist():
                raise ValueError(f"{filepath} 並非標準 DOCX (缺少 word/document.xml)")
                
            document_tree = ET.fromstring(z.read('word/document.xml'))
            body = document_tree.find(f"{ns}body")
            
            if body is None:
                raise ValueError("找不到 w:body")
                
            for p_elem in body.findall(f"{ns}p"):
                para_node = ParagraphNode()
                has_content = False
                
                for r_elem in p_elem.findall(f"{ns}r"):
                    # 抽取文字
                    t_elems = r_elem.findall(f"{ns}t")
                    text = "".join([t.text for t in t_elems if t.text])
                    
                    if text or r_elem.find(f"{ns}drawing") is not None:
                        has_content = True
                        
                    # 序列化這個 w:r 以便後續無損還原樣式
                    # 使用 encoding='unicode' 會回傳字串
                    raw_xml = ET.tostring(r_elem, encoding='unicode')
                    
                    run_node = RunNode(
                        text=text,
                        original_xml=raw_xml
                    )
                    para_node.runs.append(run_node)
                    
                # 即使是空段落 (只有排版)，也先保留
                section.paragraphs.append(para_node)
                
            # 若輸入文檔已經包含腳註 (非純手寫標記)，可在此處提取
            if 'word/footnotes.xml' in z.namelist():
                footnotes_tree = ET.fromstring(z.read('word/footnotes.xml'))
                for fn_elem in footnotes_tree.findall(f"{ns}footnote"):
                    fn_id = fn_elem.get(f"{ns}id")
                    if int(fn_id) <= 0:
                        continue # 略過 separator
                        
                    # 萃取註釋純文字
                    fn_text = ""
                    for p in fn_elem.findall(f"{ns}p"):
                        for r in p.findall(f"{ns}r"):
                            for t in r.findall(f"{ns}t"):
                                if t.text:
                                    fn_text += t.text
                                    
                    # 建立 FootnoteRecord (暫且將 ID 與 marker_text 設為相同)
                    doc.footnotes[fn_id] = FootnoteRecord(
                        footnote_id=fn_id,
                        marker_text=fn_id,
                        content=fn_text.strip()
                    )
                    
        doc.sections.append(section)
        return doc
