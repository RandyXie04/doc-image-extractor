import os
import json
import logging
from functools import partial
from pathlib import Path
from typing import Tuple, Dict

from .runner import run_pipeline

logger = logging.getLogger(__name__)

def run_unified_postprocessing(
    markdown_text: str, 
    pdf_name: str, 
    output_dir: str, 
    style_mapping: dict = None, 
    progress_callback=None,
    enable_dictionary_postprocess: bool = False
) -> Tuple[str, Dict]:
    """
    統一的後處理管線門面。
    四個通道統一呼叫此函式進行後處理。
    """
    nodes = []
    
    # 1. 辭典專用語意修正節點
    if enable_dictionary_postprocess:
        try:
            from src.scripts.dictionary_post_processor import postprocess_dictionary_markdown
            # 確保包裝成標準 Node 介面 (str -> str)
            def dict_node(text: str) -> str:
                return postprocess_dictionary_markdown(text, style_mapping)
            dict_node.__name__ = "postprocess_dictionary_markdown"
            nodes.append(dict_node)
        except ImportError as e:
            logger.warning(f"無法載入 dictionary_post_processor: {e}")

    # 執行字串轉換 Pipeline
    try:
        markdown_text = run_pipeline(markdown_text, nodes)
        if enable_dictionary_postprocess and progress_callback:
            progress_callback(81, "[INFO] 已套用辭典專用語意修正器 (自動降級詞條標題與楷體區隔)")
    except Exception as e:
        if progress_callback:
            progress_callback(81, f"[WARN] 後處理 Pipeline 失敗: {e}")
        logger.error(f"Pipeline error: {e}")

    # 2. 生僻字處理（回傳值含 stats，故在此獨立呼叫）
    rare_char_stats = {}
    try:
        from src.scripts.ocr_rare_char_corrector import postprocess_ocr_markdown
        try:
            from config import PATHS
            data_dir = str(PATHS.data_dir)
        except ImportError:
            data_dir = str(Path(__file__).parent.parent.parent.parent / "data")
            
        markdown_text, rare_char_stats = postprocess_ocr_markdown(
            markdown_text=markdown_text,
            data_dir=data_dir,
            pdf_name=pdf_name,
            output_dir=output_dir,
        )
        corrected = rare_char_stats.get("corrections_applied", 0)
        suspicious = rare_char_stats.get("suspicious_chars_found", 0)
        
        if progress_callback:
            if corrected > 0:
                progress_callback(88, f"[INFO] 靜態字典自動修正了 {corrected} 處已知錯字。")
            if suspicious > 0:
                report_path = rare_char_stats.get("report_path", "")
                progress_callback(89, f"[REVIEW] ⚠️ 偵測到 {suspicious} 處可疑字元（疑似生僻字/亂碼），覆核報告已生成。")
    except ImportError as e:
        logger.warning(f"無法載入 ocr_rare_char_corrector: {e}")

    return markdown_text, rare_char_stats
