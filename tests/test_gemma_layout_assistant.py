from unittest.mock import patch

from src.scripts.gemma_layout_assistant import (
    review_uncertain_boundaries,
    review_uncertain_layout,
    suggest_docx_style_mapping,
    validate_boundary_reviews,
    validate_layout_reviews,
)


def test_layout_reviews_keep_source_text_and_reject_low_confidence_decisions():
    """A model must not rewrite extracted prose or force a low-confidence role."""
    source = [
        {"paragraph_id": "p1", "text": "第一章 緒論", "role": "uncertain"},
        {"paragraph_id": "p2", "text": "原始文字", "role": "uncertain"},
    ]
    response = [
        {"paragraph_id": "p1", "role": "heading", "level": 1, "confidence": 0.92, "reason": "章節起點"},
        {"paragraph_id": "p2", "text": "改寫文字", "role": "heading", "level": 2, "confidence": 0.2, "reason": ""},
    ]

    result = validate_layout_reviews(source, response, confidence_threshold=0.75)

    assert result[0]["text"] == "第一章 緒論"
    assert result[0]["role"] == "heading"
    assert result[0]["level"] == 1
    assert result[1]["text"] == "原始文字"
    assert result[1]["role"] == "uncertain"


def test_style_suggestion_uses_gemma_and_returns_a_complete_role_map():
    """The template mapping proposal must be model-backed and cover required roles."""
    model_result = {
        "mapping": {
            "h1": "章標題",
            "h2": "節標題",
            "h3": "小標題",
            "body": "內文",
            "caption": "圖表說明",
            "quote": "引文",
        }
    }
    with patch("src.scripts.gemma_layout_assistant.gemma_available", return_value=True), patch(
        "src.scripts.gemma_layout_assistant.ollama_structured_chat", return_value=model_result
    ) as call:
        result = suggest_docx_style_mapping(
            [
                {"name": "章標題", "outline_level": 0, "font_size_pt": 20, "bold": True},
                {"name": "節標題", "outline_level": 1, "font_size_pt": 16, "bold": True},
                {"name": "小標題", "outline_level": 2, "font_size_pt": 14, "bold": True},
                {"name": "內文", "outline_level": None, "font_size_pt": 12, "bold": False},
                {"name": "圖表說明", "outline_level": None, "font_size_pt": 10, "bold": False},
                {"name": "引文", "outline_level": None, "font_size_pt": 11, "bold": False},
            ],
            model="gemma4:e4b",
        )

    assert result == model_result["mapping"]
    assert call.call_args.kwargs["model"] == "gemma4:e4b"


def test_style_suggestion_discards_names_not_present_in_the_template():
    with patch("src.scripts.gemma_layout_assistant.gemma_available", return_value=True), patch(
        "src.scripts.gemma_layout_assistant.ollama_structured_chat",
        return_value={"mapping": {"h1": "不存在的樣式", "body": "內文"}},
    ):
        result = suggest_docx_style_mapping(
            [{"name": "內文", "outline_level": None, "font_size_pt": 12, "bold": False}],
            model="gemma4:e4b",
        )

    assert result["h1"] is None
    assert result["body"] == "內文"


def test_missing_local_model_keeps_deterministic_layout_result():
    source = [{"paragraph_id": "p1", "text": "原文", "role": "body", "level": None}]
    with patch("src.scripts.gemma_layout_assistant.gemma_available", return_value=False):
        result = review_uncertain_layout(source, model="gemma4:e4b")

    assert result[0]["text"] == "原文"
    assert result[0]["role"] == "body"
    assert result[0]["ai_status"] == "model_unavailable"


def test_boundary_review_accepts_only_known_high_confidence_boolean_decisions():
    pairs = [{"next_line_id": "line-2", "previous_text": "原句", "next_text": "接續"}]
    response = {"items": [
        {"next_line_id": "line-2", "should_break": True, "confidence": 0.91},
        {"next_line_id": "line-2", "should_break": False, "confidence": 0.2},
        {"next_line_id": "other", "should_break": True, "confidence": 1.0},
        {"next_line_id": "line-2", "should_break": 1, "confidence": 1.0},
    ]}

    assert validate_boundary_reviews(pairs, response) == {
        "line-2": {"should_break": True, "confidence": 0.91, "source": "gemma"}
    }


def test_missing_model_marks_boundary_review_as_not_participating():
    with patch("src.scripts.gemma_layout_assistant.gemma_available", return_value=False):
        result = review_uncertain_boundaries(
            [{"next_line_id": "line-2", "previous_text": "原句", "next_text": "接續"}],
            model="gemma4:e4b",
        )

    assert result == {"_status": {"status": "model_unavailable", "model": "gemma4:e4b"}}
