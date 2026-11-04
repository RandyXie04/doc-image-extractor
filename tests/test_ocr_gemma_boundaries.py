from unittest.mock import patch

from src.scripts.process_ocr import _merge_wrapping_paragraphs


def test_gemma_can_split_a_deterministic_ocr_wrap_when_review_confirms_boundary():
    blocks = [
        {"original_label": "text", "surya_text": "前一段文字未結束", "bbox": [10, 10, 90, 20]},
        {"original_label": "text", "surya_text": "這是新段落。", "bbox": [25, 28, 90, 38]},
    ]
    with patch("src.scripts.process_ocr.review_uncertain_boundaries", return_value={"ocr-line-1": True}):
        result = _merge_wrapping_paragraphs(blocks, page_w=100.0, line_height_thresh=35.0)

    assert len(result) == 2
    assert result[0]["surya_text"] == "前一段文字未結束"

