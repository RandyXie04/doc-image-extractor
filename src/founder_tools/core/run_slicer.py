import xml.etree.ElementTree as ET
from typing import List, Tuple

class RunSlicer:
    """
    OpenXML Virtual Run Slicer
    解決 Word 中標記 (如 `〔12〕`) 跨越多個 `<w:r>` 標籤的問題。
    """
    W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    
    @classmethod
    def get_paragraph_text(cls, p_elem: ET.Element) -> str:
        """取得段落的純文字內容"""
        text = ""
        for t in p_elem.findall(f".//{cls.W_NS}t"):
            if t.text:
                text += t.text
        return text

    @classmethod
    def inject_footnote(cls, p_elem: ET.Element, start_char: int, end_char: int, footnote_id: str, ref_style_id: str):
        """
        在段落 p_elem 的 [start_char, end_char) 位置替換為腳註參照，
        不會破壞周圍的樣式 (w:rPr)。
        """
        current_idx = 0
        
        # 收集所有 t 節點及其所屬的 r 節點與文字長度
        t_nodes = []
        for r_elem in p_elem.findall(f"{cls.W_NS}r"):
            for t_elem in r_elem.findall(f"{cls.W_NS}t"):
                if t_elem.text:
                    t_nodes.append({
                        'r': r_elem,
                        't': t_elem,
                        'text': t_elem.text,
                        'start': current_idx,
                        'end': current_idx + len(t_elem.text)
                    })
                    current_idx += len(t_elem.text)
                    
        injection_point_r = None
        injection_index = -1
        
        for node in t_nodes:
            t_start = node['start']
            t_end = node['end']
            t_elem = node['t']
            
            # 不在替換範圍內
            if t_end <= start_char or t_start >= end_char:
                continue
                
            # 發生重疊，需要切削文字
            text = node['text']
            new_text = ""
            
            if t_start < start_char:
                # 保留左側
                new_text += text[:start_char - t_start]
                # 記錄注入點，應插在此 r 節點之後
                if injection_point_r is None:
                    injection_point_r = node['r']
            
            if t_end > end_char:
                # 保留右側
                new_text += text[end_char - t_start:]
                # 如果注入點還沒找到，表示標記起始就在此節點開頭
                if injection_point_r is None:
                    # 我們將新節點插在此 r 節點之前
                    injection_point_r = node['r']
                    
            t_elem.text = new_text
            
            # 如果尚未設定注入點 (例如整個 t 被吞噬)，預設為該 r 節點
            if injection_point_r is None:
                injection_point_r = node['r']
                
        # 建立新的腳註參照 r 節點
        new_r = ET.Element(f"{cls.W_NS}r")
        rpr = ET.SubElement(new_r, f"{cls.W_NS}rPr")
        rstyle = ET.SubElement(rpr, f"{cls.W_NS}rStyle")
        rstyle.set(f"{cls.W_NS}val", ref_style_id)
        
        ref = ET.SubElement(new_r, f"{cls.W_NS}footnoteReference")
        ref.set(f"{cls.W_NS}id", footnote_id)
        
        # 找到 injection_point_r 在 p_elem 中的位置並插入
        if injection_point_r is not None:
            # 轉換為 list 找到 index
            children = list(p_elem)
            try:
                idx = children.index(injection_point_r)
                # 插在該節點之後
                p_elem.insert(idx + 1, new_r)
            except ValueError:
                p_elem.append(new_r)
        else:
            # 極端情況
            p_elem.append(new_r)
            
        # 清除空白的 t 節點與其 r 節點以保持乾淨
        cls._cleanup_empty_runs(p_elem)

    @classmethod
    def _cleanup_empty_runs(cls, p_elem: ET.Element):
        for r in p_elem.findall(f"{cls.W_NS}r"):
            t_elems = r.findall(f"{cls.W_NS}t")
            # 若有 t 標籤，但所有 t 都是空的，且沒有其他有意義的內容 (如 drawing, footnoteReference)
            if t_elems and all(not t.text for t in t_elems):
                has_other = False
                for child in r:
                    if child.tag not in (f"{cls.W_NS}t", f"{cls.W_NS}rPr"):
                        has_other = True
                        break
                if not has_other:
                    p_elem.remove(r)
