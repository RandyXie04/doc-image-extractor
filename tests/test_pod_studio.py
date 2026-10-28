# -*- coding: utf-8 -*-
"""
Tests for src/pod_studio
========================
Verifies domain-agnostic blueprint schema, AST sectioning, CJK skeleton invariant,
DiffAligner exemplar learning, rule propagation, Index Tagging, visual fallback,
and 3-stage Production API endpoints.
"""

import os
import json
import tempfile
from pathlib import Path
import pytest
import docx
from fastapi.testclient import TestClient

from src.pod_studio.blueprint_schema import StyleTriggerRule, BookBlueprint, IndexTaggingInstruction
from src.pod_studio.section_ast import SectionUnit, ParagraphUnit, SectionAST
from src.pod_studio.cjk_validator import PODIntegrityValidator
from src.pod_studio.exemplar_learner import ExemplarLearner, DiffAligner
from src.pod_studio.propagation_engine import PropagationEngine
from src.pod_studio.pod_validator import PodValidator, ValidationReport, ValidationViolation
from src.pod_studio.visual_fallback_repair import build_vlm_repair_prompt
from src.web.app import app

SAMPLE_RAW_MD = """# 第一章 分散式系統概述

本章探討雲原生微服務架構的核心概念與高可用性設計原則。

## 負載平衡與服務探索

在高併發場景下，客戶端請求必須由反向代理分流至多個工作節點。負載平衡器會依權重動態分配流量。
注意：生產環境務必配置健康檢查機制與降級熔斷策略。
① 避免單點故障。② 定期監控網路延遲與錯誤率。

## 快取失效與穿透防禦

快取系統可大幅減少後端資料庫查詢負擔。
① 設定合理的過期時間。③ 實作布隆過濾器防止惡意請求。
"""

SAMPLE_GOLDEN_MD = """# 第一章 分散式系統概述

本章探討雲原生微服務架構的核心概念與高可用性設計原則。

## 負載平衡與服務探索

::: {custom-style="提示框"}
在高併發場景下，客戶端請求必須由反向代理分流至多個工作節點。負載平衡器會依權重動態分配流量。
:::

【概念解析】在高併發場景下，客戶端請求必須由反向代理分流至多個工作節點。負載平衡器會依權重動態分配流量。

【注意事項】生產環境務必配置健康檢查機制與降級熔斷策略。

::: {custom-style="條列說明"}
① 避免單點故障。
② 定期監控網路延遲與錯誤率。
:::

## 快取失效與穿透防禦

【概念解析】快取系統可大幅減少後端資料庫查詢負擔。

【注意事項】設定合理的過期時間。
"""


class TestBlueprintSchema:
    def test_schema_serialization_roundtrip(self):
        rule = StyleTriggerRule(
            rule_id="r1",
            target_docx_style="提示框",
            inject_prefix_badge="【概念解析】",
            trigger_regex=r"^在高併發",
            action="inject_badge",
        )
        bp = BookBlueprint(
            book_name="分散式系統設計手冊",
            book_type="technical_manual",
            template_styles_used=["提示框", "條列說明"],
            mandatory_section_badges=["概念解析", "注意事項"],
            intentionally_deleted_patterns=["[版眉裝飾]"],
            style_rules=[rule],
            few_shot_examples=[{"unit_title": "負載平衡與服務探索", "raw_input": "raw", "golden_output": "gold"}],
        )

        json_str = bp.to_json()
        restored = BookBlueprint.from_json(json_str)

        assert restored.book_name == "分散式系統設計手冊"
        assert restored.book_type == "technical_manual"
        assert restored.template_styles_used == ["提示框", "條列說明"]
        assert restored.mandatory_section_badges == ["概念解析", "注意事項"]
        assert restored.intentionally_deleted_patterns == ["[版眉裝飾]"]
        assert len(restored.style_rules) == 1
        assert restored.style_rules[0].rule_id == "r1"
        assert restored.style_rules[0].inject_prefix_badge == "【概念解析】"


class TestSectionAST:
    def test_from_and_to_markdown_with_paragraphs(self):
        sections = SectionAST.from_markdown(SAMPLE_RAW_MD, split_level=2)
        assert len(sections) == 3
        assert sections[0].section_id == "sec_000"
        assert sections[0].title == "第一章 分散式系統概述"
        assert sections[1].title == "負載平衡與服務探索"
        assert sections[2].title == "快取失效與穿透防禦"

        # Check paragraphs population
        assert len(sections[1].paragraphs) >= 2
        assert sections[1].paragraphs[0].para_id.startswith("sec_001_p")

        reassembled = SectionAST.to_markdown(sections)
        assert "負載平衡與服務探索" in reassembled
        assert "快取失效與穿透防禦" in reassembled

    def test_dump_and_load_book_ast_json(self, tmp_path):
        sections = SectionAST.from_markdown(SAMPLE_RAW_MD, split_level=2)
        sections[1].paragraphs[0].page_num = 12
        sections[1].paragraphs[0].bbox = [50.0, 100.0, 400.0, 180.0]
        sections[1].paragraphs[0].font_name = "FZHT"
        sections[1].paragraphs[0].font_size = 12.0

        ast_path = tmp_path / "Book_raw_ast.json"
        SectionAST.dump_book_ast_json(sections, ast_path)
        assert ast_path.exists()

        loaded = SectionAST.load_book_ast_json(ast_path)
        assert len(loaded) == len(sections)
        assert loaded[1].paragraphs[0].page_num == 12
        assert loaded[1].paragraphs[0].bbox == [50.0, 100.0, 400.0, 180.0]
        assert loaded[1].paragraphs[0].font_name == "FZHT"


class TestCJKIntegrityValidator:
    def test_exact_character_conservation_passes_green(self):
        validator = PODIntegrityValidator(valid_docx_styles={"提示框", "條列說明"})
        raw = "在高併發場景下，客戶端請求必須由反向代理分流。"
        processed = '::: {custom-style="提示框"}\n在高併發場景下，客戶端請求必須由反向代理分流。\n:::'

        res = validator.validate_section("sec_001", "測試", raw, processed)
        assert res.status == "GREEN"
        assert len(res.dropped_fragments) == 0

    def test_silent_text_drop_detected_as_red(self):
        validator = PODIntegrityValidator(valid_docx_styles={"提示框"})
        raw = "在高併發場景下，客戶端請求必須由反向代理分流至多個工作節點。"
        # Silent drop of 6 chars: "至多個工作節點"
        processed = '::: {custom-style="提示框"}\n在高併發場景下，客戶端請求必須由反向代理分流。\n:::'

        res = validator.validate_section("sec_001", "測試", raw, processed)
        assert res.status == "RED"
        assert len(res.dropped_fragments) > 0
        assert "至多個工作節點" in "".join(res.dropped_fragments)

    def test_allowed_injected_badge_does_not_flag_false_positive(self):
        validator = PODIntegrityValidator(
            valid_docx_styles={"Normal"},
            allowed_injected_badges=["【概念解析】"],
        )
        raw = "負載平衡器會依權重動態分配流量。"
        processed = "【概念解析】負載平衡器會依權重動態分配流量。"

        res = validator.validate_section("sec_001", "測試", raw, processed)
        assert res.status == "GREEN"

    def test_invalid_style_triggers_red(self):
        validator = PODIntegrityValidator(valid_docx_styles={"合法樣式A"})
        raw = "內文段落"
        processed = '::: {custom-style="非法幽靈樣式"}\n內文段落\n:::'

        res = validator.validate_section("sec_001", "測試", raw, processed)
        assert res.status == "RED"
        assert "非法幽靈樣式" in res.invalid_styles


class TestExemplarLearnerAndDiffAligner:
    def test_diff_aligner_infers_badge_and_style(self):
        raw_text = "在高併發場景下，服務端需要防護。\n\n每日例行檢查伺服器。"
        golden_text = '::: {custom-style="提示框"}\n在高併發場景下，服務端需要防護。\n:::\n\n【重點提示】每日例行檢查伺服器。'

        rules = DiffAligner.align_paragraphs(raw_text, golden_text)
        assert len(rules) >= 1
        actions = [r.action for r in rules]
        assert "apply_style" in actions or "inject_badge" in actions

    def test_learn_from_md_pair(self, tmp_path):
        raw_file = tmp_path / "raw.md"
        gold_file = tmp_path / "gold.md"
        raw_file.write_text(SAMPLE_RAW_MD, encoding="utf-8")
        gold_file.write_text(SAMPLE_GOLDEN_MD, encoding="utf-8")

        bp = ExemplarLearner.learn_from_md_pair(raw_file, gold_file, sample_chapters=2)
        assert "概念解析" in bp.mandatory_section_badges or "注意事項" in bp.mandatory_section_badges
        assert len(bp.few_shot_examples) >= 1
        assert "提示框" in bp.template_styles_used or "條列說明" in bp.template_styles_used

    def test_learn_from_docx_pair(self, tmp_path):
        raw_docx = tmp_path / "raw.docx"
        gold_docx = tmp_path / "gold.docx"

        d_raw = docx.Document()
        d_raw.add_paragraph("服務探索與架構", style="Heading 2")
        d_raw.add_paragraph("核心系統包含路由引擎與健康探針。")
        d_raw.save(raw_docx)

        d_gold = docx.Document()
        d_gold.add_paragraph("服務探索與架構", style="Heading 2")
        d_gold.add_paragraph("【架構解析】核心系統包含路由引擎與健康探針。")
        d_gold.add_paragraph("【注意事項】配置逾時重試。")
        d_gold.save(gold_docx)

        bp = ExemplarLearner.learn_from_docx_pair(raw_docx, gold_docx)
        assert "Heading 2" in bp.template_styles_used
        assert "架構解析" in bp.mandatory_section_badges or "注意事項" in bp.mandatory_section_badges


class TestPropagationEngine:
    def test_batch_rule_propagation(self):
        bp = BookBlueprint(
            book_name="test",
            mandatory_section_badges=["注意事項"],
            style_rules=[
                StyleTriggerRule(
                    rule_id="r_note",
                    action="inject_badge",
                    inject_prefix_badge="【注意事項】",
                    trigger_regex=r"^注意",
                ),
                StyleTriggerRule(
                    rule_id="r_split_num",
                    action="split_circled_num",
                    trigger_regex=r"[①②③]",
                ),
            ],
        )

        sec = SectionUnit(
            section_id="sec_001",
            title="網路通訊",
            raw_content="## 網路通訊\n\n注意安全防護。\n\n① 啟用TLS加密。② 配置金鑰輪換。",
        )

        engine = PropagationEngine(bp)
        processed = engine.process_section(sec)

        assert "【注意事項】注意安全防護" in processed.processed_content
        assert "\n②" in processed.processed_content

    def test_index_tagging_deterministic_application(self):
        sec = SectionUnit(
            section_id="sec_001",
            title="單元標題",
            raw_content="## 單元標題\n\n段落一內文。\n\n段落二警告。",
        )
        sec.paragraphs = SectionAST._text_to_paragraphs(sec.raw_content, sec.section_id)

        # Generate preview payload
        payload = PropagationEngine.generate_index_tagging_payload(sec)
        assert len(payload) == 3  # Heading + 2 paragraphs
        assert payload[1]["preview"].startswith("段落一")

        # Apply instructions
        instructions = [
            IndexTaggingInstruction(para_id=payload[1]["id"], style="提示框"),
            IndexTaggingInstruction(para_id=payload[2]["id"], prepend_badge="【重要】"),
        ]

        patched = PropagationEngine.apply_index_tagging(sec, instructions)
        effective = patched.effective_content
        assert '::: {custom-style="提示框"}' in effective
        assert "段落一內文" in effective
        assert "【重要】段落二警告" in effective


class TestPodValidator:
    def test_validator_with_traffic_lights(self):
        bp = BookBlueprint(
            book_name="test",
            mandatory_section_badges=["概念解析"],
            template_styles_used=["提示框"],
        )
        validator = PodValidator(blueprint=bp)

        clean_sec = SectionUnit(
            section_id="sec_001",
            title="合規章節",
            raw_content="## 合規章節\n\n【概念解析】系統採用分散式一致性演算法。",
            processed_content="## 合規章節\n\n【概念解析】系統採用分散式一致性演算法。",
        )
        violations, cjk_res = validator.validate_section(clean_sec)
        assert len(violations) == 0
        assert cjk_res.status == "GREEN"

        # Missing mandatory badge
        bad_sec = SectionUnit(
            section_id="sec_002",
            title="缺少標籤章節",
            raw_content="## 缺少標籤章節\n\n系統直接運行。",
            processed_content="## 缺少標籤章節\n\n系統直接運行。",
        )
        violations, cjk_res = validator.validate_section(bad_sec)
        assert any(v.check_type == "badge" for v in violations)


class TestVisualFallbackRepair:
    def test_build_vlm_repair_prompt(self):
        few_shots = [{"unit_title": "負載平衡", "golden_output": "【概念解析】...【注意事項】..."}]
        prompt = build_vlm_repair_prompt(
            corrupted_raw_md="## 快取管理\n遺失標籤內文",
            golden_few_shots=few_shots,
            missing_badges=["注意事項"],
        )
        assert "負載平衡" in prompt
        assert "【注意事項】" in prompt
        assert "快取管理" in prompt


class TestPODProductionAPI:
    def _get_client(self):
        from config.settings import CFG
        client = TestClient(app)
        if CFG.auth_enabled and CFG.auth_password:
            client.headers["X-API-Key"] = CFG.auth_password
        return client

    def test_3_stage_api_pipeline(self, tmp_path):
        client = self._get_client()

        # Stage 1: Extract Raw
        sample_md = "# 第一章 雲原生架構\n\n## 服務註冊中心\n\n註冊中心維護節點清單。\n\n注意安全防護。"
        res1 = client.post(
            "/api/pod/1_extract_raw",
            files={"file": ("input_book.md", sample_md.encode("utf-8"), "text/markdown")},
            data={"split_level": 2},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["status"] == "success"
        session_id = data1["session_id"]

        # Stage 2: Compile Blueprint
        sample_seed_md = "# 第一章 雲原生架構\n\n## 服務註冊中心\n\n【架構解析】註冊中心維護節點清單。\n\n【注意事項】配置TLS。"
        res2 = client.post(
            "/api/pod/2_compile_blueprint",
            data={"session_id": session_id},
            files={"seed_file": ("Book_seed.md", sample_seed_md.encode("utf-8"), "text/markdown")},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "success"
        assert "blueprint" in data2

        # Stage 3: Propagate and Validate with custom model override
        res3 = client.post(
            "/api/pod/3_propagate_and_validate",
            data={"session_id": session_id, "model": "gemini-3.8-flash"},
        )
        assert res3.status_code == 200
        data3 = res3.json()
        assert data3["status"] == "success"
        assert data3["final_docx_name"] == "Book_POD_Final.docx"
        assert "audit_summary" in data3
        assert data3["audit_summary"]["green_count"] >= 1

        # Test download
        dl_res = client.get(f"/api/pod/download/{session_id}/Book_POD_Final.docx")
        assert dl_res.status_code == 200
        assert len(dl_res.content) > 0

    def test_pod_studio_frontend_serves_html(self):
        client = self._get_client()
        res = client.get("/static/pod_studio.html")
        assert res.status_code == 200
        text = res.text
        assert "vlmModelSelect" in text
        assert "gemini-3.8-flash" in text
        assert "customModelInput" in text
        assert "manualBoundaryAnchorInput" in text
        assert "manualBoundaryIdxInput" in text


class TestManualBoundaryAnchorAndLLMConfirmation:
    def test_docx_manual_boundary_anchor_and_builtin_tag_cleanup(self, tmp_path):
        import io
        import docx
        from src.pod_studio.exemplar_learner import ExemplarLearner
        from src.pod_studio.pod_service import compile_blueprint_from_seed, propagate_and_validate_session
        from src.pod_studio.section_ast import SectionAST, SectionUnit, ParagraphUnit

        doc = docx.Document()
        styles = doc.styles
        custom_s = styles.add_style("重點提示樣式", docx.enum.style.WD_STYLE_TYPE.PARAGRAPH)
        p0 = doc.add_paragraph("第一章 導論", style="Heading 1")
        p1 = doc.add_paragraph("重點：這是人工精修的第一段重點。", style="重點提示樣式")
        p2 = doc.add_paragraph("重點：這是人工精修的第二段重點（人工定位終點）。", style="重點提示樣式")
        p3 = doc.add_paragraph("【人工整稿截止】")
        p4 = doc.add_paragraph("重點：這是後續尚未人工修改但待AI擴散的段落。")
        p5 = doc.add_paragraph("普通內文敘述段落。")

        seed_path = tmp_path / "Book_seed.docx"
        doc.save(str(seed_path))

        sections = [
            SectionUnit(
                section_id="sec_001",
                title="第一章 導論",
                level=1,
                paragraphs=[
                    ParagraphUnit(para_id="p_0", raw_text=p.text)
                    for p in doc.paragraphs
                ],
                raw_content="\n\n".join(p.text for p in doc.paragraphs),
            )
        ]
        SectionAST.dump_book_ast_json(sections, tmp_path / "Book_raw_ast.json")

        # 1. Test built-in tag detection
        bp_tag = ExemplarLearner.learn_from_docx_pair("", seed_path)
        assert bp_tag.metadata["boundary_source"] == "builtin_tag"
        assert bp_tag.metadata["seed_last_modified_idx"] == 3
        assert "人工定位終點" in bp_tag.metadata["boundary_context_text"]

        # 2. Test explicit manual_boundary_anchor override
        bp_anchor = compile_blueprint_from_seed(
            tmp_path,
            seed_path,
            manual_boundary_anchor="人工定位終點",
        )
        assert bp_anchor.metadata["boundary_source"] == "manual_anchor"
        assert bp_anchor.metadata["seed_last_modified_idx"] == 2
        assert bp_anchor.metadata["manual_boundary_anchor"] == "人工定位終點"

        # 3. Verify propagation & LLM prompt receives the manual boundary anchor and strips builtin tag
        captured_prompts = []

        def fake_ai_client(prompt: str) -> str:
            captured_prompts.append(prompt)
            return '[{"id": 4, "style": "重點提示樣式"}, {"id": 5, "style": "Normal"}]'

        final_docx, report, _ = propagate_and_validate_session(
            session_dir=tmp_path,
            engine_mode="rule_first",
            ai_client=fake_ai_client,
        )
        assert final_docx.exists()
        assert len(captured_prompts) >= 1
        assert "【人工定位確認】" in captured_prompts[0]
        assert "人工定位終點" in captured_prompts[0]

        # Ensure built-in boundary tag paragraph was cleaned from final output docx
        out_doc = docx.Document(str(final_docx))
        out_texts = [p.text.strip() for p in out_doc.paragraphs]
        assert "【人工整稿截止】" not in out_texts

    def test_vlm_continuation_prompt_includes_manual_boundary_anchor(self, tmp_path):
        import docx
        from src.pod_studio.vlm_continuation_engine import SecureVLMContinuationEngine, VisualExemplarPair
        from src.pod_studio.section_ast import SectionUnit, ParagraphUnit

        engine = SecureVLMContinuationEngine(workspace_base=tmp_path)
        prompt = engine._build_continuation_prompt(
            exemplars=[
                VisualExemplarPair(
                    section_title="第一節 基礎概念",
                    page_num=1,
                    raw_ocr_skeleton="基礎概念草稿",
                    golden_markdown="## 第一節 基礎概念\n\n::: {custom-style=\"導讀\"}\n精修內容\n:::",
                    page_image_bytes=b"",
                )
            ],
            current_section_title="第二節 進階實務",
            current_ocr_draft="進階實務粗糙生稿內容",
            manual_boundary_anchor="第一節末尾人工截止錨點",
            boundary_context_text="這是人工最後確認的段落句子。",
        )
        assert "【人工精修截止定位錨點 (Human-Edited Boundary Anchor)】" in prompt
        assert "第一節末尾人工截止錨點" in prompt
        assert "這是人工最後確認的段落句子。" in prompt


