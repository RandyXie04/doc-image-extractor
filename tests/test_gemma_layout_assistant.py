import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import fitz

from src.scripts.gemma_layout_assistant import (
    GEMMA_FONT_NUM_CTX,
    review_uncertain_boundaries,
    review_uncertain_layout,
    suggest_docx_style_mapping,
    suggest_pdf_font_group_mappings,
    validate_boundary_reviews,
    validate_layout_reviews,
)
from src.scripts.pdf_font_analyzer import analyze_pdf_for_ui, scan_pdf_fonts
from src.utils.ollama_client import OllamaTimeoutError


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
    assert call.call_args.kwargs["num_ctx"] == GEMMA_FONT_NUM_CTX


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


def test_scan_pdf_fonts_collects_frequency_pages_and_position_summary():
    """Verify PDF font scanner extracts occurrence count, page count, position distribution, and bounded samples."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "layout_stats.pdf")
        doc: Any = fitz.open()
        page1 = doc.new_page(width=500, height=800)
        page1.insert_text(fitz.Point(220, 60), "Running Header", fontname="helv", fontsize=9)
        page1.insert_text(fitz.Point(80, 400), "Body paragraph text on page one.", fontname="tiro", fontsize=12)
        page2 = doc.new_page(width=500, height=800)
        page2.insert_text(fitz.Point(220, 60), "Running Header", fontname="helv", fontsize=9)
        page2.insert_text(fitz.Point(80, 420), "Body paragraph text on page two.", fontname="tiro", fontsize=12)
        doc.save(pdf_path)
        doc.close()

        fonts = scan_pdf_fonts(pdf_path, max_samples=2, max_sample_len=20)
        by_size = {f["size_pt"]: f for f in fonts}

        assert 9.0 in by_size
        header_font = by_size[9.0]
        assert header_font["occurrence_count"] == 2
        assert header_font["page_count"] == 2
        assert header_font["position_summary"]["dominant_zone"] == "top"
        assert header_font["position_summary"]["top_ratio"] == 1.0

        body_font = by_size[12.0]
        assert body_font["occurrence_count"] == 2
        assert body_font["page_count"] == 2
        assert body_font["position_summary"]["dominant_zone"] == "middle"
        assert all(len(s) <= 20 for s in body_font["sample_texts"])

        # Scanning for UI does NOT invoke Gemma automatically
        with patch("src.scripts.gemma_layout_assistant.ollama_structured_chat") as mock_chat:
            ui_data = analyze_pdf_for_ui(pdf_path, None, os.path.join(tmpdir, "fonts.json"))
            mock_chat.assert_not_called()
            assert all(f["gemma_status"] == "not_run" for f in ui_data["fonts"])


def test_font_group_suggestions_use_pdf_and_docx_evidence_and_enforce_8k_batches():
    font_groups = [
        {
            "name": "FZHei-B01 (16.0pt)",
            "full_name": "ABCDEF+FZHei-B01",
            "size_pt": 16.0,
            "occurrence_count": 6,
            "page_count": 6,
            "position_summary": {"top_ratio": 0.67, "middle_ratio": 0.33, "bottom_ratio": 0.0, "centered_ratio": 0.83, "dominant_zone": "top"},
            "sample_texts": ["第一章 緒論", "第二章 方法"],
            "suggested_role": "H2",
        },
        {
            "name": "FZShuSong-Z01 (10.5pt)",
            "full_name": "ABCDEF+FZShuSong-Z01",
            "size_pt": 10.5,
            "occurrence_count": 420,
            "page_count": 30,
            "position_summary": {"top_ratio": 0.1, "middle_ratio": 0.8, "bottom_ratio": 0.1, "centered_ratio": 0.0, "dominant_zone": "middle"},
            "sample_texts": ["本研究探討文獻與實證方法。"],
            "suggested_role": "正文",
        },
    ]
    docx_styles = [
        {"name": "章標題", "outline_level": 0, "font_size_pt": 16.0, "bold": True},
        {"name": "內文", "outline_level": None, "font_size_pt": 10.5, "bold": False},
    ]
    mock_resp = {
        "items": [
            {
                "font_name": "FZHei-B01 (16.0pt)",
                "role": "H1",
                "docx_style": "章標題",
                "confidence": 0.93,
                "reason": "16pt 黑體居上置中，樣本為章名，對應 16pt 粗體章標題",
            },
            {
                "font_name": "FZShuSong-Z01 (10.5pt)",
                "role": "正文",
                "docx_style": "不存在的樣式",
                "confidence": 0.88,
                "reason": "高頻率 10.5pt 宋體分布於版心，為內文段落",
            },
        ]
    }

    with patch("src.scripts.gemma_layout_assistant.is_ollama_available", return_value=True), patch(
        "src.scripts.gemma_layout_assistant.gemma_available", return_value=True
    ), patch("src.scripts.gemma_layout_assistant.ollama_structured_chat", return_value=mock_resp) as mock_chat:
        res = suggest_pdf_font_group_mappings(font_groups, docx_styles, model="gemma4:e4b", batch_size=2)

    assert res["status"] == "ready"
    assert res["num_ctx"] == 8192
    assert mock_chat.call_args.kwargs["num_ctx"] == 8192
    sug_h1 = res["suggestions"]["FZHei-B01 (16.0pt)"]
    assert sug_h1["role"] == "H1"
    assert sug_h1["docx_style"] == "章標題"
    assert sug_h1["confidence"] == 0.93
    assert "章標題" in sug_h1["reason"]
    assert sug_h1["status"] == "suggested"

    # Nonexistent DOCX style must be discarded while keeping valid role
    sug_body = res["suggestions"]["FZShuSong-Z01 (10.5pt)"]
    assert sug_body["role"] == "正文"
    assert sug_body["docx_style"] is None
    assert sug_body["status"] == "suggested"


def test_font_group_suggestions_cover_edge_states():
    font_groups = [{"name": "TestFont (12.0pt)", "size_pt": 12.0, "sample_texts": ["機密樣本文字不應外洩"]}]
    docx_styles = [{"name": "內文", "outline_level": None, "font_size_pt": 12.0, "bold": False}]

    # 1. Ollama unreachable -> fallback
    with patch("src.scripts.gemma_layout_assistant.is_ollama_available", return_value=False):
        res_offline = suggest_pdf_font_group_mappings(font_groups, docx_styles)
        assert res_offline["status"] == "ollama_unavailable"
        assert res_offline["outcome"] == "fallback"
        assert res_offline["stats"]["total_groups"] == 1
        assert res_offline["stats"]["valid_suggestions"] == 0
        assert res_offline["suggestions"]["TestFont (12.0pt)"]["status"] == "not_participated"

    # 2. Gemma model not installed -> fallback
    with patch("src.scripts.gemma_layout_assistant.is_ollama_available", return_value=True), patch(
        "src.scripts.gemma_layout_assistant.gemma_available", return_value=False
    ):
        res_uninstalled = suggest_pdf_font_group_mappings(font_groups, docx_styles)
        assert res_uninstalled["status"] == "model_unavailable"
        assert res_uninstalled["outcome"] == "fallback"
        assert res_uninstalled["stats"]["valid_suggestions"] == 0
        assert res_uninstalled["suggestions"]["TestFont (12.0pt)"]["status"] == "not_participated"

    # 3. Low confidence -> fallback (status == "low_confidence", not treated as ready/success)
    low_and_empty_resp = {
        "items": [
            {
                "font_name": "TestFont (12.0pt)",
                "role": "H2",
                "docx_style": "內文",
                "confidence": 0.35,
                "reason": "樣本過短無法確定",
            }
        ]
    }
    with patch("src.scripts.gemma_layout_assistant.is_ollama_available", return_value=True), patch(
        "src.scripts.gemma_layout_assistant.gemma_available", return_value=True
    ), patch("src.scripts.gemma_layout_assistant.ollama_structured_chat", return_value=low_and_empty_resp):
        res_low = suggest_pdf_font_group_mappings(font_groups, docx_styles, confidence_threshold=0.6)
        assert res_low["status"] == "low_confidence"
        assert res_low["outcome"] == "fallback"
        assert res_low["stats"]["low_confidence"] == 1
        assert res_low["stats"]["valid_suggestions"] == 0
        assert res_low["suggestions"]["TestFont (12.0pt)"]["status"] == "low_confidence"

    # 4. No valid suggestions -> fallback
    no_sug_resp = {
        "items": [
            {
                "font_name": "TestFont (12.0pt)",
                "role": None,
                "docx_style": None,
                "confidence": 0.9,
                "reason": "無對應",
            }
        ]
    }
    with patch("src.scripts.gemma_layout_assistant.is_ollama_available", return_value=True), patch(
        "src.scripts.gemma_layout_assistant.gemma_available", return_value=True
    ), patch("src.scripts.gemma_layout_assistant.ollama_structured_chat", return_value=no_sug_resp):
        res_none = suggest_pdf_font_group_mappings(font_groups, docx_styles, confidence_threshold=0.6)
        assert res_none["status"] == "no_suggestions"
        assert res_none["outcome"] == "fallback"
        assert res_none["stats"]["valid_suggestions"] == 0

    # 5. Timeout -> failed
    with patch("src.scripts.gemma_layout_assistant.is_ollama_available", return_value=True), patch(
        "src.scripts.gemma_layout_assistant.gemma_available", return_value=True
    ), patch(
        "src.scripts.gemma_layout_assistant.ollama_structured_chat",
        side_effect=OllamaTimeoutError("Request timed out at C:\\Users\\secret\\book.pdf"),
    ):
        res_timeout = suggest_pdf_font_group_mappings(font_groups, docx_styles)
        assert res_timeout["status"] == "timeout"
        assert res_timeout["outcome"] == "failed"
        assert res_timeout["error_type"] == "OllamaTimeoutError"
        assert "C:\\Users\\secret" not in (res_timeout["sanitized_error"] or "")
        assert res_timeout["suggestions"]["TestFont (12.0pt)"]["status"] == "failed"


def test_cmd_diagnostic_logs_and_privacy_sanitization():
    """Verify CMD diagnostic logs record start/end, status, outcome, model, counts, elapsed_ms, and strip private data."""
    from src.scripts.gemma_layout_assistant import (
        format_font_suggestion_diag_log,
        sanitize_diagnostic_text,
    )

    secret_pdf_sample = "第一章 機密歷史文獻內文段落樣本"
    secret_win_path = r"C:\Users\sonbo\Desktop\secret_project\data\book.pdf"
    secret_unix_path = "/Users/sonbo/private_docs/template.docx"

    cleaned = sanitize_diagnostic_text(f"Failed reading {secret_win_path} and {secret_unix_path}")
    assert "C:\\Users" not in cleaned
    assert "/Users/sonbo" not in cleaned
    assert "secret_project" not in cleaned
    assert "<path>" in cleaned

    start_log = format_font_suggestion_diag_log(
        "start",
        req_id="a1b2c3d4",
        model="gemma4:e4b",
        total_groups=5,
        template_styles=8,
    )
    assert "\n" not in start_log
    assert "event=start" in start_log
    assert "endpoint=/api/suggest_font_mappings" in start_log
    assert "req_id=a1b2c3d4" in start_log
    assert "model=gemma4:e4b" in start_log
    assert "total_groups=5" in start_log
    assert secret_pdf_sample not in start_log

    scenarios = [
        ("ready", "success", 4, 1, None, None),
        ("model_unavailable", "fallback", 0, 0, "ModelNotInstalledError", "Model gemma4:e4b not installed"),
        ("ollama_unavailable", "fallback", 0, 0, "OllamaConnectionError", "Connection refused"),
        ("timeout", "failed", 0, 0, "OllamaTimeoutError", f"Timeout on {secret_win_path}"),
        ("low_confidence", "fallback", 0, 3, None, None),
        ("no_suggestions", "fallback", 0, 0, None, None),
    ]
    for status, expected_outcome, valid_cnt, low_cnt, err_type, err_msg in scenarios:
        end_log = format_font_suggestion_diag_log(
            "end",
            req_id="a1b2c3d4",
            model="gemma4:e4b",
            total_groups=5,
            status=status,
            valid_suggestions=valid_cnt,
            low_confidence=low_cnt,
            elapsed_ms=135,
            error_type=err_type,
            error_msg=err_msg,
        )
        assert "\n" not in end_log
        assert f"status={status}" in end_log
        assert f"outcome={expected_outcome}" in end_log
        assert "model=gemma4:e4b" in end_log
        assert "total_groups=5" in end_log
        assert f"valid_suggestions={valid_cnt}" in end_log
        assert f"low_confidence={low_cnt}" in end_log
        assert "elapsed_ms=135" in end_log
        assert "C:\\Users" not in end_log
        assert secret_pdf_sample not in end_log
        if status != "ready":
            assert "outcome=success" not in end_log


def test_fonts_json_compatibility_and_docx_style_output():
    """Verify fonts.json read/update/fallback derivation and Markdown/DOCX style preservation after UI convergence."""
    from src.scripts.pdf_font_analyzer import (
        derive_style_mapping_from_fonts,
        get_font_role_map,
        load_fonts_json,
        save_fonts_json,
    )
    from src.scripts.book_layout_extractor import process_book_vector_pdf

    with tempfile.TemporaryDirectory() as tmpdir:
        fonts_json = os.path.join(tmpdir, "fonts.json")
        # Seed legacy + user entry
        with open(fonts_json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "LegacyFont": "舊格式樣本文字",
                    "FZHei-B01 (16.0pt)": {"role": "H1", "docx_style": "Heading 1", "mapped_by": "user"},
                },
                f,
                ensure_ascii=False,
            )

        loaded = load_fonts_json(fonts_json)
        assert loaded["LegacyFont"]["mapped_by"] == "legacy"
        assert loaded["FZHei-B01 (16.0pt)"]["role"] == "H1"

        # Update via save_fonts_json (simulating Font Review Modal confirmation)
        save_fonts_json(
            fonts_json,
            {
                "FZShuSong-Z01 (10.5pt)": {"role": "正文", "docx_style": "Body Text", "mapped_by": "user"},
                "FZKai-Z03 (9.5pt)": {"role": "圖說", "docx_style": "Caption", "mapped_by": "user"},
            },
        )

        role_map = get_font_role_map(fonts_json)
        assert "LegacyFont" not in role_map
        assert role_map["FZHei-B01 (16.0pt)"]["docx_style"] == "Heading 1"
        assert role_map["FZShuSong-Z01 (10.5pt)"]["docx_style"] == "Body Text"
        assert role_map["FZKai-Z03 (9.5pt)"]["docx_style"] == "Caption"

        derived = derive_style_mapping_from_fonts(
            fonts_json,
            active_font_names=["FZHei-B01 (16.0pt)", "FZShuSong-Z01 (10.5pt)", "FZKai-Z03 (9.5pt)"],
        )
        assert derived == {
            "h1": "Heading 1",
            "body": "Body Text",
            "image_caption": "Caption",
        }

        # Create a test vector PDF and verify Markdown output preserves heading, body, and custom styles
        pdf_path = os.path.join(tmpdir, "sample.pdf")
        doc: Any = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 120), "第一章 緒論", fontsize=16, fontname="china-ts")
        page.insert_text((72, 180), "這是一段完整的內文測試段落，確認整稿輸出與樣式套用正常運作。", fontsize=10.5, fontname="china-ts")
        doc.save(pdf_path)
        doc.close()

        out_dir = os.path.join(tmpdir, "out")
        md_path, _audit = process_book_vector_pdf(
            pdf_path=pdf_path,
            output_dir=out_dir,
            output_stem="sample",
            style_mapping=derived,
        )
        md_text = Path(md_path).read_text(encoding="utf-8")
        assert "第一章" in md_text
        assert "這是一段完整的內文測試段落" in md_text
        assert 'custom-style="Body Text"' in md_text


def test_suggest_font_mappings_endpoint_respects_gpu_semaphore():
    """Ensure /api/suggest_font_mappings is guarded by the global GPU semaphore to prevent concurrency with OCR."""
    import inspect
    from src.web.routers.ocr_router import suggest_font_mappings
    source = inspect.getsource(suggest_font_mappings)
    assert "async with get_gpu_semaphore():" in source
    assert "suggest_pdf_font_group_mappings" in source


def test_duplicate_style_mapping_gemma_endpoint_removed():
    """Confirm /api/suggest_ocr_style_mapping is removed so duplicate Gemma suggestions cannot occur."""
    from src.web.routers.formula_router import router as formula_r
    from src.web.routers.ocr_router import router as ocr_r
    routes = [getattr(r, "path", "") for r in (*formula_r.routes, *ocr_r.routes)]
    assert "/api/suggest_ocr_style_mapping" not in routes
    assert "/api/suggest_font_mappings" in routes


def test_ai_layout_font_group_cache_and_persistence_to_fonts_json():
    """Verify ADR-013/BUG-013: user-confirmed fonts bypass Ollama, unmapped fonts cache per font group and persist as ai_layout."""
    from src.scripts.book_layout_extractor import (
        _extract_primary_font_key,
        _lookup_block_font_mapping,
        _sort_blocks_by_row_and_x,
    )
    from src.scripts.pdf_font_analyzer import (
        load_fonts_json,
        save_ai_layout_suggestions_to_fonts_json,
        save_fonts_json,
    )

    # 1. Mixed-span heading (ASCII prefix in body font + CJK title in heading font) resolves CJK heading font
    mixed_lines = [
        {
            "spans": [
                {"text": "1　", "font": "E-BZ", "size": 13.0},
                {"text": "风云突变", "font": "FZS3K--GBK1-0", "size": 13.0},
            ]
        }
    ]
    font_role_map = {
        "E-BZ (13.0pt)": {"role": "正文", "docx_style": "Normal", "mapped_by": "user"},
        "FZS3K--GBK1-0 (13.0pt)": {"role": "H2", "docx_style": "heading 2", "mapped_by": "user"},
    }
    assert _extract_primary_font_key(mixed_lines) == ("FZS3K--GBK1-0 (13.0pt)", "FZS3K--GBK1-0", 13.0)
    role, docx_style, mapped_by = _lookup_block_font_mapping(mixed_lines, font_role_map)
    assert role == "H2"
    assert docx_style == "heading 2"
    assert mapped_by == "user"

    # 2. Footnote row+X sorting pairs left marker blocks with right text blocks on the same row
    unsorted_fn_blocks = [
        {"bbox": (147.4, 495.5, 421.8, 520.9), "text": "第一个脚注内容"},
        {"bbox": (147.4, 525.5, 421.8, 535.9), "text": "第二个脚注内容"},
        {"bbox": (132.4, 495.3, 139.9, 505.7), "text": "①"},
        {"bbox": (132.4, 525.3, 139.9, 535.7), "text": "②"},
    ]
    sorted_fn = _sort_blocks_by_row_and_x(unsorted_fn_blocks)
    assert [b["text"] for b in sorted_fn] == ["①", "第一个脚注内容", "②", "第二个脚注内容"]

    # 3. AI layout suggestions persist with mapped_by="ai_layout", never overwrite mapped_by="user", and promote on UI save
    with tempfile.TemporaryDirectory() as tmpdir:
        fonts_json = os.path.join(tmpdir, "fonts.json")
        save_fonts_json(
            fonts_json,
            {
                "ConfirmedFont (13.0pt)": {
                    "role": "H2",
                    "docx_style": "heading 2",
                    "mapped_by": "user",
                    "sample_text": "1　风云突变",
                }
            },
        )

        # AI tries to suggest both the already-confirmed font and a new unmapped font
        persisted = save_ai_layout_suggestions_to_fonts_json(
            fonts_json,
            {
                "ConfirmedFont (13.0pt)": {
                    "role": "正文",
                    "docx_style": "Normal",
                    "confidence": 0.99,
                    "reason": "不應覆蓋人工確認結果",
                },
                "UnmappedHeadingFont (15.0pt)": {
                    "role": "H1",
                    "docx_style": "heading 1",
                    "confidence": 0.91,
                    "reason": "AI 版面預判為一級章標題",
                    "sample_text": "第一卷　鄂州之战",
                },
            },
        )
        assert persisted == 1

        loaded = load_fonts_json(fonts_json)
        assert loaded["ConfirmedFont (13.0pt)"]["role"] == "H2"
        assert loaded["ConfirmedFont (13.0pt)"]["mapped_by"] == "user"
        assert loaded["UnmappedHeadingFont (15.0pt)"]["role"] == "H1"
        assert loaded["UnmappedHeadingFont (15.0pt)"]["docx_style"] == "heading 1"
        assert loaded["UnmappedHeadingFont (15.0pt)"]["mapped_by"] == "ai_layout"

        # User reviews and confirms in Font Review UI -> promotes to mapped_by="user"
        save_fonts_json(
            fonts_json,
            {
                "UnmappedHeadingFont (15.0pt)": {
                    "role": "H1",
                    "docx_style": "heading 1",
                    "mapped_by": "user",
                }
            },
        )
        loaded_after_confirm = load_fonts_json(fonts_json)
        assert loaded_after_confirm["UnmappedHeadingFont (15.0pt)"]["mapped_by"] == "user"

