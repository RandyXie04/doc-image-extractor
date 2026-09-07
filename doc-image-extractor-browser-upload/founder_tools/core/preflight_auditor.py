from typing import Dict, Any, List
import logging
from .document_model import UnifiedDocument
from .annotation_profile import AnnotationProfile

logger = logging.getLogger(__name__)

class PreflightAuditor:
    """
    轉換前體檢審計模組 (PRE-FLIGHT Audit)
    根據 FootnoteMatcher 的結果，執行強制性的轉換前風險攔截。
    符合 Zero-Unexplained Error 標準。
    """
    
    @classmethod
    def audit(cls, match_results: Dict[str, Any], doc: UnifiedDocument, profile: AnnotationProfile) -> str:
        """
        執行審計。回傳狀態字串: "PASS", "WARNING", "FAIL"
        - PASS: 零孤立、零衝突，高信心。
        - WARNING: 低信心純數字、跳號，需進入 Human Review Gate。
        - FAIL: 存在無可挽回的孤立標記或孤立註釋。
        """
        errors: List[Dict[str, Any]] = match_results.get("errors", [])
        warnings: List[Dict[str, Any]] = match_results.get("warnings", [])
        
        # 1. 檢查不可原諒的錯誤 (孤立項目)
        if errors:
            logger.error(f"[PREFLIGHT FAIL] 發現 {len(errors)} 個孤立錯誤。")
            for err in errors:
                logger.error(f"  - {err['reason']}")
            return "FAIL"
            
        # 2. 檢查警告事項 (低信心或跳號)
        # 在 v2.0 中，若設定了純數字，除非四重證據完全命中，否則容易產生 warning
        if warnings:
            logger.warning(f"[PREFLIGHT WARNING] 發現 {len(warnings)} 個需要人工覆核的項目。")
            for warn in warnings:
                logger.warning(f"  - {warn['reason']}")
            return "WARNING"
            
        # 3. 未確認 Profile (系統合法狀態準則)
        if not profile.is_locked:
            logger.warning("[PREFLIGHT WARNING] AnnotationProfile 尚未經人工確認，禁止放行。")
            return "WARNING"
            
        # 4. 檢查 UNRESOLVED
        # 若文件中存在未解析字元 (例如 PDF 中無法復原的字)
        # 雖然容許，但也可能發出 Warning 讓人工確認
        if doc.unresolved_chars_count > 0:
            logger.warning(f"[PREFLIGHT WARNING] 發現 {doc.unresolved_chars_count} 個 UNRESOLVED 字元。")
            return "WARNING"
            
        return "PASS"
