import zipfile
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List
from .document_model import UnifiedDocument
from .template_resolver import TemplateResolver

class OpenXMLBuilder:
    """
    OpenXML Builder
    負責接收 UnifiedDocument，並將其內容注入到 template.docx 中。
    """
    W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    
    def __init__(self, template_path: str):
        self.template_path = template_path
        self.resolver = TemplateResolver(template_path)
        
    def build(self, doc_model: UnifiedDocument, output_path: str):
        """建構最終的 DOCX 檔案"""
        styles = self.resolver.resolve()
        
        # 1. 將 template.docx 複製並解壓縮到暫存記憶體 (這裡我們直接用 zipfile 修改)
        # ZipFile 不支援直接修改，所以我們讀取所有的檔案到記憶體，修改 document.xml 與 footnotes.xml，然後寫入新的 ZipFile
        
        files_dict = {}
        with zipfile.ZipFile(self.template_path, 'r') as z_in:
            for item in z_in.infolist():
                files_dict[item.filename] = z_in.read(item.filename)
                
        # 2. 準備 document.xml
        if 'word/document.xml' not in files_dict:
            raise ValueError("template.docx 無效: 找不到 word/document.xml")
            
        doc_tree = ET.fromstring(files_dict['word/document.xml'])
        body = doc_tree.find(f"{self.W_NS}body")
        
        # 清除 template 原本的內容 (保留 sectPr)
        sect_pr = body.find(f"{self.W_NS}sectPr")
        for child in list(body):
            if child.tag != f"{self.W_NS}sectPr":
                body.remove(child)
                
        # 3. 準備 footnotes.xml
        footnotes_tree = None
        if 'word/footnotes.xml' in files_dict:
            footnotes_tree = ET.fromstring(files_dict['word/footnotes.xml'])
        else:
            # 建立基本的 footnotes.xml
            footnotes_tree = ET.Element(f"{self.W_NS}footnotes")
            # 補上預設的 separator (-1) 與 continuation (0)
            # 這裡簡化處理，標準流程應該由 template 提供
            pass
            
        next_footnote_id = 1
        # 找出目前最大的 footnote id
        if footnotes_tree is not None:
            for fn in footnotes_tree.findall(f"{self.W_NS}footnote"):
                f_id = int(fn.get(f"{self.W_NS}id", "0"))
                if f_id >= next_footnote_id:
                    next_footnote_id = f_id + 1
                    
        # 4. 寫入內容
        # 這個階段，我們需要遍歷 UnifiedDocument，將每個段落轉換為 w:p
        # 並同時替換為 w:footnoteReference，然後把內容加入 footnotes.xml
        
        for section in doc_model.sections:
            for para in section.paragraphs:
                p_elem = ET.Element(f"{self.W_NS}p")
                
                # 簡單模式：直接組合純文字並插入腳註
                # 若要支援 DOCX 樣式保留，需要從 para.runs 中的 original_xml 還原
                text_content = ""
                has_original_xml = False
                
                for run in para.runs:
                    if run.original_xml:
                        has_original_xml = True
                        r_elem = ET.fromstring(run.original_xml)
                        p_elem.append(r_elem)
                    else:
                        r_elem = ET.SubElement(p_elem, f"{self.W_NS}r")
                        t_elem = ET.SubElement(r_elem, f"{self.W_NS}t")
                        t_elem.text = run.text
                        
                # 這裡需要整合 RunSlicer，如果 UnifiedDocument 已經包含腳註標記的資訊
                # 但目前為了確保不破壞架構，標記替換邏輯會留給具體的注入階段 (可由上層傳入)
                
                # ... (後續將整合 RunSlicer 與腳註生成) ...
                
                if sect_pr is not None:
                    # 必須確保 p_elem 插入在 sectPr 之前
                    body.insert(len(body) - 1, p_elem)
                else:
                    body.append(p_elem)
                    
        # 5. 封裝回新的 DOCX
        files_dict['word/document.xml'] = ET.tostring(doc_tree, encoding='utf-8')
        if footnotes_tree is not None:
            files_dict['word/footnotes.xml'] = ET.tostring(footnotes_tree, encoding='utf-8')
            
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z_out:
            for filename, content in files_dict.items():
                z_out.writestr(filename, content)
