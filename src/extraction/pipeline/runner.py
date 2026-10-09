import logging
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
