# -*- coding: utf-8 -*-
from unittest.mock import patch

from src.scripts.gemma_layout_assistant import review_uncertain_boundaries


def test_gemma_can_split_a_deterministic_ocr_wrap_when_review_confirms_boundary():
    line_pairs = [
        {"prev_text": "前一段文字未結束", "next_text": "這是新段落。", "next_line_id": "ocr-line-1"},
    ]
    mock_llm_response = {
        "items": [
            {"next_line_id": "ocr-line-1", "should_break": True, "confidence": 0.95}
        ]
    }
    with patch("src.scripts.gemma_layout_assistant.gemma_available", return_value=True), \
         patch("src.scripts.gemma_layout_assistant.ollama_structured_chat", return_value=mock_llm_response):
        decisions = review_uncertain_boundaries(line_pairs, confidence_threshold=0.8)

    assert "ocr-line-1" in decisions
    assert decisions["ocr-line-1"]["should_break"] is True
    assert decisions["ocr-line-1"]["confidence"] == 0.95
    assert decisions["_status"]["status"] == "ready"
