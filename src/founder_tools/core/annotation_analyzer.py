import re
from collections import Counter
from typing import Optional
from .document_model import UnifiedDocument
from .annotation_profile import AnnotationProfile
from .marker_detector import MarkerDetector

class AnnotationAnalyzer:
    """
    註釋結構探勘 (AI 偵察兵)
    自動分析來源文件前幾個段落，推斷最可能的註釋標籤與標記型態，
    產出建議供人工確認 (模式 A)。
    """
    
    @classmethod
    def analyze(cls, doc: UnifiedDocument) -> AnnotationProfile:
        # 1. 探勘標籤
        label_candidates = Counter()
        marker_candidates = Counter()
        
        # 只取前 200 個段落作樣本
        sample_paras = []
        for section in doc.sections:
            sample_paras.extend([p.text for p in section.paragraphs])
            if len(sample_paras) > 200:
                break
                
        for text in sample_paras:
            text_strip = text.strip()
            # 尋找獨立成段，或被括號包圍的標籤
            m = re.match(r'^【?(校注|注釋|注解|注|考證)】?$', text_strip)
            if m:
                label_candidates[m.group(1)] += 1
                
            # 統計標記頻率
            if MarkerDetector.detect(text, "circled_number"):
                marker_candidates["circled_number"] += 1
            if MarkerDetector.detect(text, "square_bracket"):
                marker_candidates["square_bracket"] += 1
            if MarkerDetector.detect(text, "chinese_bracket"):
                marker_candidates["chinese_bracket"] += 1
                
        # 2. 推斷標籤
        best_label = None
        if label_candidates:
            best_label = label_candidates.most_common(1)[0][0]
            
        # 3. 推斷標記型態
        # 若都沒有，則預設可能是純數字 (風險較高)
        best_marker = "plain_number"
        if marker_candidates:
            best_marker = marker_candidates.most_common(1)[0][0]
            
        # 4. 推斷編號範圍與位置 (預設提供合理猜測)
        confidence = 0.9 if (best_label and best_marker != "plain_number") else 0.5
        
        return AnnotationProfile(
            annotation_label=best_label,
            marker_type=best_marker,
            marker_scope="chapter",   # 預設每章重置 (古籍常見)
            numbering_scope="continuous", # Word 輸出預設全書連續
            footnote_location="section_end",
            extraction_strategy="explicit_label" if best_label else "marker_based",
            confidence=confidence,
            is_locked=False # 強制未鎖定，等待人工確認
        )
