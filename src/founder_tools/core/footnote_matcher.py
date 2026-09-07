import logging
from typing import List, Dict, Any
from .document_model import UnifiedDocument, FootnoteRecord
from .marker_detector import MarkerDetector, MarkerMatch
from .annotation_profile import AnnotationProfile

logger = logging.getLogger(__name__)

class FootnoteMatcher:
    """
    雙向標記與註釋關聯匹配器 (Footnote Matcher)
    負責將正文中所偵測到的標記，與提取到的註釋內容進行雙向匹配驗證。
    """
    
    @classmethod
    def match(cls, doc: UnifiedDocument, profile: AnnotationProfile) -> Dict[str, Any]:
        """
        執行匹配作業。
        回傳結果包含成功匹配清單、警告(如低信心純數字)、錯誤(找不到對應註釋等)。
        """
        all_matches: List[MarkerMatch] = []
        
        # 1. 在正文中偵測所有的標記
        for s_idx, section in enumerate(doc.sections):
            for p_idx, para in enumerate(section.paragraphs):
                # 如果該段落已經被判定為註釋區塊，則跳過 (依賴 Parser 實作)
                # 這裡假設 doc.sections 內的 paragraphs 為正文
                matches = MarkerDetector.detect(para.text, profile.marker_type, p_idx, s_idx)
                all_matches.extend(matches)
                
        # 2. 準備註釋字典 (以標記號碼為 key 建立索引)
        # 假設註釋在解析時已經將流水號記錄為 footnote_id (如 "1", "2")
        footnote_pool = {str(fn.footnote_id): fn for fn in doc.footnotes.values()}
        
        results = {
            "matched": [],
            "warnings": [],
            "errors": []
        }
        
        expected_seq = 1
        
        # 3. 執行雙向驗證與順序檢查
        for match in all_matches:
            marker_num_str = str(match.number)
            
            # 檢查註釋池中是否存在
            if marker_num_str in footnote_pool:
                # 檢查順序 (Sequence Analysis)
                if match.number != expected_seq:
                    if profile.marker_scope == "chapter" and match.number == 1:
                        # 章節重置
                        expected_seq = 1
                    elif profile.marker_scope == "page" and match.number == 1:
                        # 頁碼重置 (需有分頁資訊，暫簡化)
                        expected_seq = 1
                    else:
                        msg = f"順序警告: 預期 {expected_seq}，實際找到 {match.number}"
                        results["warnings"].append({"match": match, "reason": msg})
                        # 發生跳號時，若仍能對應到實體，我們可選擇繼續，但需要人工審查
                
                # 純數字的四重證據鏈檢驗 (Context Heuristics)
                if profile.marker_type == "plain_number":
                    # TODO: 加入進階的上下文排除，例如年份 "1994"、量詞 "1個人"
                    # 若存疑，應標記為低信心
                    pass
                    
                results["matched"].append({
                    "match": match,
                    "footnote": footnote_pool[marker_num_str]
                })
                
                # 更新預期順序
                expected_seq = match.number + 1
                
                # 從池中移除以追蹤孤立註釋
                del footnote_pool[marker_num_str]
            else:
                msg = f"孤立標記: 找不到對應的註釋內容 (標記 {match.text})"
                results["errors"].append({"match": match, "reason": msg})
                
        # 4. 檢查是否有孤立註釋 (有註釋但正文無標記)
        for fn_id, fn in footnote_pool.items():
            msg = f"孤立註釋: 找不到正文對應標記 (註釋 ID {fn_id})"
            results["errors"].append({"footnote": fn, "reason": msg})
            
        return results
