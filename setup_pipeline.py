import os
from pathlib import Path

src_dir = Path("src")
pipeline_dir = src_dir / "extraction" / "pipeline"
pipeline_dir.mkdir(parents=True, exist_ok=True)
nodes_dir = src_dir / "extraction" / "nodes"
nodes_dir.mkdir(parents=True, exist_ok=True)

# 1. exceptions.py
with open(pipeline_dir / "exceptions.py", "w", encoding="utf-8") as f:
    f.write('''class OutputAnomalyError(Exception):
    """輸出與輸入差異超過安全閾值時拋出。"""
    def __init__(self, input_len: int, output_len: int, threshold: float, sample: str):
        self.input_len = input_len
        self.output_len = output_len
        self.threshold = threshold
        super().__init__(
            f"Flowcheck 失敗｜輸入長度={input_len}, 輸出長度={output_len}, "
            f"縮減比={1 - output_len/input_len:.1%} > 閾值={threshold:.0%}｜"
            f"輸出前 100 字: {sample!r}"
        )
''')

# 2. runner.py
with open(pipeline_dir / "runner.py", "w", encoding="utf-8") as f:
    f.write('''import logging
from typing import Callable, List
from .exceptions import OutputAnomalyError

logger = logging.getLogger(__name__)

def run_pipeline(text: str, nodes: List[Callable]) -> str:
    """
    依序執行傳入的文字處理節點（Nodes），並負責捕捉異常與日誌紀錄。
    
    Args:
        text: 待處理的原始字串。
        nodes: 遵循 Node 契約的 Callable 列表（輸入 str，回傳 str）。
    
    Returns:
        處理完成的字串。
    """
    if not text or not isinstance(text, str):
        logger.warning("run_pipeline: 收到空字串或非字串，直接回傳。")
        return text

    current_text = text
    for node in nodes:
        node_name = node.func.__name__ if hasattr(node, 'func') else getattr(node, '__name__', 'UnknownNode')
        try:
            current_text = node(current_text)
        except OutputAnomalyError as e:
            logger.error(f"節點 {node_name} 觸發長度異常防護: {e}")
            raise
        except Exception as e:
            logger.error(f"節點 {node_name} 發生未預期錯誤: {e}")
            raise
            
    return current_text
''')

# 3. facade (unified postprocessor for the 4 channels)
with open(pipeline_dir / "facade.py", "w", encoding="utf-8") as f:
    f.write('''import os
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
''')

# empty __init__.py files
(pipeline_dir / "__init__.py").touch()
(nodes_dir / "__init__.py").touch()
