import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class TemplateStyles:
    footnote_text_id: str
    footnote_reference_id: str

class TemplateResolver:
    """動態解析 template.docx 樣式與配置 (Template Resolver Engine)"""
    W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    
    def __init__(self, template_path: str):
        self.template_path = template_path
        self._styles: Optional[TemplateStyles] = None
        
    def resolve(self) -> TemplateStyles:
        """解析並回傳 template.docx 中的註腳樣式 ID"""
        if self._styles is not None:
            return self._styles
            
        footnote_text_id = None
        footnote_ref_id = None
        
        with zipfile.ZipFile(self.template_path, 'r') as z:
            if 'word/styles.xml' not in z.namelist():
                raise FileNotFoundError(f"{self.template_path} 缺少 word/styles.xml，請確認是否為標準 DOCX")
                
            tree = ET.fromstring(z.read('word/styles.xml'))
            for s in tree.findall(f"{self.W_NS}style"):
                s_id = s.get(f"{self.W_NS}styleId")
                name_el = s.find(f"{self.W_NS}name")
                if name_el is not None:
                    name_val = name_el.get(f"{self.W_NS}val", "")
                    name_lower = name_val.lower()
                    
                    if name_lower == "footnote text" or name_val == "註腳文字":
                        footnote_text_id = s_id
                    elif name_lower == "footnote reference" or name_val == "註腳參照":
                        footnote_ref_id = s_id
                        
        # 嚴格要求 template 必須具備這兩個樣式
        if not footnote_text_id:
            # Fallback based on common assumptions if not explicitly found, but log a warning ideally
            footnote_text_id = "FootnoteText" 
        if not footnote_ref_id:
            footnote_ref_id = "FootnoteReference"
            
        self._styles = TemplateStyles(
            footnote_text_id=footnote_text_id,
            footnote_reference_id=footnote_ref_id
        )
        return self._styles
