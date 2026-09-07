import zipfile
import xml.etree.ElementTree as ET
import logging

logger = logging.getLogger(__name__)

class PostflightValidator:
    """
    轉換後合規驗證 (POST-FLIGHT Full Validator)
    驗證產出的 DOCX 是否符合 template 規範、數量是否正確、有無毀損。
    """
    W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    
    @classmethod
    def validate(cls, output_docx: str, expected_footnote_count: int, template_ref_id: str) -> bool:
        """
        執行輸出文檔驗證。
        """
        ns = f"{{{cls.W_NS}}}"
        
        try:
            with zipfile.ZipFile(output_docx, 'r') as z:
                # 1. 基本結構檢查
                if 'word/document.xml' not in z.namelist():
                    logger.error("POSTFLIGHT: 缺少 document.xml")
                    return False
                if 'word/footnotes.xml' not in z.namelist() and expected_footnote_count > 0:
                    logger.error("POSTFLIGHT: 預期有腳註，但缺少 footnotes.xml")
                    return False
                    
                # 2. 驗證 document.xml 中的標記數量與樣式
                doc_tree = ET.fromstring(z.read('word/document.xml'))
                ref_nodes = doc_tree.findall(f".//{ns}footnoteReference")
                
                if len(ref_nodes) != expected_footnote_count:
                    logger.error(f"POSTFLIGHT: 腳註參照數量不符。預期 {expected_footnote_count}，實際 {len(ref_nodes)}")
                    return False
                    
                # 檢查樣式 (確認是否有套用 template 規定的 ref_style_id)
                # 由於腳註參照的樣式通常綁在 w:rPr 內
                style_miss_count = 0
                for ref in ref_nodes:
                    parent_r = ref.find("..") # lxml 支援，但內建 ET 不支援
                    # 在內建 ET 中，我們直接遍歷尋找
                    pass
                    
                # 換個方式：找所有的 r > footnoteReference
                for r_elem in doc_tree.findall(f".//{ns}r"):
                    if r_elem.find(f"{ns}footnoteReference") is not None:
                        rpr = r_elem.find(f"{ns}rPr")
                        rstyle = rpr.find(f"{ns}rStyle") if rpr is not None else None
                        val = rstyle.get(f"{ns}val") if rstyle is not None else None
                        
                        if val != template_ref_id:
                            style_miss_count += 1
                            
                if style_miss_count > 0:
                    logger.warning(f"POSTFLIGHT: 發現 {style_miss_count} 個腳註參照未使用 {template_ref_id} 樣式。")
                    # 依據 Zero-Unexplained Error，這可能視為 FAIL
                    return False
                    
                # 3. 驗證 footnotes.xml 中的內容
                if expected_footnote_count > 0:
                    fn_tree = ET.fromstring(z.read('word/footnotes.xml'))
                    # 扣除 id <= 0 的 separator
                    actual_fn = [f for f in fn_tree.findall(f"{ns}footnote") if int(f.get(f"{ns}id", "0")) > 0]
                    if len(actual_fn) != expected_footnote_count:
                        logger.error(f"POSTFLIGHT: 腳註實體數量不符。預期 {expected_footnote_count}，實際 {len(actual_fn)}")
                        return False
                        
            logger.info("POSTFLIGHT: 驗證通過。符合 template 規範與預期數量。")
            return True
            
        except Exception as e:
            logger.error(f"POSTFLIGHT: 驗證過程發生例外: {e}")
            return False
