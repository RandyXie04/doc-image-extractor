# -*- coding: utf-8 -*-
"""
Tests for src/pod_studio
========================
Verifies blueprint schema, AST sectioning, exemplar learning,
rule propagation, visual fallback repair, and validator gatekeeping.
"""

import os
import json
import tempfile
from pathlib import Path
import pytest
import docx

from src.pod_studio.blueprint_schema import StyleTriggerRule, BookBlueprint
from src.pod_studio.section_ast import SectionUnit, SectionAST
from src.pod_studio.exemplar_learner import ExemplarLearner
from src.pod_studio.propagation_engine import PropagationEngine
from src.pod_studio.pod_validator import PodValidator, ValidationReport, ValidationViolation
from src.pod_studio.visual_fallback_repair import build_vlm_repair_prompt, render_page_crop


SAMPLE_RAW_MD = """# 第一章 概述

本書介紹經典經方與民間小妙招。

## 雙參靈百湯

西洋參10克，北沙參15克，百合20克。水煎服，每日一劑，早晚溫服。
功效：益氣養陰，潤肺止咳。
① 忌辛辣煙酒。② 孕婦慎用。

## 茵陳蒿湯

茵陳30克，梔子10克，大黃10克。水煎服。
① 每日服三次。③ 連服五天。
"""

SAMPLE_GOLDEN_MD = """# 第一章 概述

本書介紹經典經方與民間小妙招。

## 雙參靈百湯

::: {custom-style="說明框詩詞"}
雙參同氣潤肺家，百合甘涼散浮邪。
:::

【組成】西洋參10克，北沙參15克，百合20克。

【用法】水煎服，每日一劑，早晚溫服。

【功效】益氣養陰，潤肺止咳。

::: {custom-style="備注楷體"}
① 忌辛辣煙酒。
② 孕婦慎用。
:::

## 茵陳蒿湯

【組成】茵陳30克，梔子10克，大黃10克。

【用法】水煎服。

【功效】清熱利濕退黃。
"""


class TestBlueprintSchema:
    def test_schema_serialization_roundtrip(self):
        rule = StyleTriggerRule(
            rule_id="r1",
            target_docx_style="備注楷體",
            inject_prefix_badge="【用法】",
            trigger_regex=r"水煎服",
            action="inject_badge",
        )
        bp = BookBlueprint(
            book_name="測試手冊",
            template_styles_used=["備注楷體", "說明框詩詞"],
            mandatory_section_badges=["組成", "用法"],
            style_rules=[rule],
            few_shot_examples=[{"unit_title": "雙參靈百湯", "raw_input": "raw", "golden_output": "gold"}],
        )

        json_str = bp.to_json()
        restored = BookBlueprint.from_json(json_str)

        assert restored.book_name == "測試手冊"
        assert restored.template_styles_used == ["備注楷體", "說明框詩詞"]
        assert restored.mandatory_section_badges == ["組成", "用法"]
        assert len(restored.style_rules) == 1
        assert restored.style_rules[0].rule_id == "r1"
        assert restored.style_rules[0].inject_prefix_badge == "【用法】"
        assert len(restored.few_shot_examples) == 1


class TestSectionAST:
    def test_from_and_to_markdown(self):
        sections = SectionAST.from_markdown(SAMPLE_RAW_MD, split_level=2)
        assert len(sections) == 3
        assert sections[0].section_id == "sec_000"
        assert sections[0].title == "第一章 概述"  # level 1
        assert sections[1].title == "雙參靈百湯"
        assert sections[2].title == "茵陳蒿湯"

        reassembled = SectionAST.to_markdown(sections)
        assert "雙參靈百湯" in reassembled
        assert "茵陳蒿湯" in reassembled

    def test_dump_and_load_workspace(self, tmp_path):
        sections = SectionAST.from_markdown(SAMPLE_RAW_MD, split_level=2)
        ws = SectionAST.dump_to_workspace(tmp_path / "ws", sections)

        assert (ws / "catalog.json").exists()
        assert (ws / "sec_001.md").exists()

        loaded = SectionAST.load_from_workspace(ws)
        assert len(loaded) == len(sections)
        assert loaded[1].title == "雙參靈百湯"


class TestExemplarLearner:
    def test_learn_from_md_pair(self, tmp_path):
        raw_file = tmp_path / "raw.md"
        gold_file = tmp_path / "gold.md"
        raw_file.write_text(SAMPLE_RAW_MD, encoding="utf-8")
        gold_file.write_text(SAMPLE_GOLDEN_MD, encoding="utf-8")

        bp = ExemplarLearner.learn_from_md_pair(raw_file, gold_file, sample_chapters=2)

        assert "組成" in bp.mandatory_section_badges or "用法" in bp.mandatory_section_badges
        assert len(bp.few_shot_examples) >= 1
        assert bp.few_shot_examples[0]["unit_title"] == "雙參靈百湯"
        assert "說明框詩詞" in bp.template_styles_used or "備注楷體" in bp.template_styles_used

    def test_learn_from_docx_pair(self, tmp_path):
        # Create minimal raw and gold docx files
        raw_docx = tmp_path / "raw.docx"
        gold_docx = tmp_path / "gold.docx"

        d_raw = docx.Document()
        p1 = d_raw.add_paragraph("雙參靈百湯", style="Heading 2")
        d_raw.add_paragraph("西洋參10克，北沙參15克。水煎服。")
        d_raw.save(raw_docx)

        d_gold = docx.Document()
        p2 = d_gold.add_paragraph("雙參靈百湯", style="Heading 2")
        d_gold.add_paragraph("【組成】西洋參10克，北沙參15克。")
        d_gold.add_paragraph("【用法】水煎服。")
        d_gold.save(gold_docx)

        bp = ExemplarLearner.learn_from_docx_pair(raw_docx, gold_docx)
        assert "Heading 2" in bp.template_styles_used
        assert "組成" in bp.mandatory_section_badges or "用法" in bp.mandatory_section_badges
        assert len(bp.few_shot_examples) == 1


class TestPropagationEngine:
    def test_batch_rule_propagation(self):
        bp = BookBlueprint(
            book_name="test",
            mandatory_section_badges=["用法"],
            style_rules=[
                StyleTriggerRule(
                    rule_id="r_usage",
                    action="inject_badge",
                    inject_prefix_badge="【用法】",
                    trigger_regex=r"水煎服",
                ),
                StyleTriggerRule(
                    rule_id="r_split_num",
                    action="split_circled_num",
                    trigger_regex=r"[①②③]",
                ),
            ],
            few_shot_examples=[],
        )

        sec = SectionUnit(
            section_id="sec_001",
            title="小柴胡湯",
            raw_content="## 小柴胡湯\n\n柴胡12克，黃芩9克。\n\n水煎服，每日一劑。\n\n① 溫服。② 覆被取微汗。",
        )

        engine = PropagationEngine(bp)
        processed = engine.process_section(sec)

        # Should inject 【用法】
        assert "【用法】水煎服" in processed.processed_content
        # Should split ① and ②
        assert "\n②" in processed.processed_content

    def test_format_agent_prompt(self):
        bp = BookBlueprint(
            book_name="test",
            mandatory_section_badges=["組成", "用法"],
            few_shot_examples=[{"unit_title": "Ex1", "raw_input": "raw1", "golden_output": "gold1"}],
        )
        sec = SectionUnit(section_id="sec_002", title="生脈散", raw_content="## 生脈散\n人參、麥冬、五味子。")
        engine = PropagationEngine(bp)
        prompt = engine.format_agent_prompt(sec)

        assert "生脈散" in prompt
        assert "【組成】" in prompt
        assert "gold1" in prompt


class TestPodValidator:
    def test_validator_detects_violations(self):
        bp = BookBlueprint(
            book_name="test",
            mandatory_section_badges=["組成", "用法"],
            template_styles_used=["備注楷體"],
        )
        bp.validation_config.enable_numbering_check = True

        validator = PodValidator(blueprint=bp, max_shrink_ratio=0.30)

        # Section missing mandatory 【用法】, with broken circled numbers (① then ③ missing ②), and unknown style
        bad_sec = SectionUnit(
            section_id="sec_005",
            title="問題方劑",
            raw_content="## 問題方劑\n\n【組成】大黃10克。\n\n::: {custom-style=\"未知樣式\"}\n① 隨水送服。③ 每日兩次。\n:::",
        )

        violations = validator.validate_section(bad_sec)
        check_types = {v.check_type for v in violations}

        assert "badge" in check_types       # Missing 【用法】
        assert "numbering" in check_types   # ① and ③ missing ②
        assert "style" in check_types       # 未知樣式 not in template_styles_used

    def test_novel_narrative_without_badges_passes_validation(self):
        """A novel or essay book has no mandatory badges and no numbered lists."""
        bp = BookBlueprint(
            book_name="紅樓夢選段",
            book_type="narrative",
            mandatory_section_badges=[],  # No mandatory badges!
            template_styles_used=["Normal"],
        )
        # By default for narrative, enable_badge_check is True but mandatory_section_badges is empty
        # and enable_numbering_check is False
        validator = PodValidator(blueprint=bp)

        novel_sec = SectionUnit(
            section_id="sec_001",
            title="第一回 甄士隱夢幻識通靈",
            raw_content="## 第一回 甄士隱夢幻識通靈\n\n列位看官：你道此書從何而來？說起根由，雖近荒唐，細按則深有趣味。",
        )
        violations = validator.validate_section(novel_sec)
        assert len(violations) == 0  # Zero violations, completely clean!

    def test_qa_book_archetype(self):
        """A Q&A dialogue book has 問 and 答 badges."""
        bp = BookBlueprint(
            book_name="法律問答錄",
            book_type="qa_dialogue",
            mandatory_section_badges=["問", "答"],
            template_styles_used=["Normal"],
        )
        validator = PodValidator(blueprint=bp)

        valid_qa = SectionUnit(
            section_id="sec_001",
            title="房屋買賣糾紛",
            raw_content="## 房屋買賣糾紛\n\n問：買方延遲交款，賣方能否解除契約？\n\n答：依民法第254條規定，應先定期催告。",
        )
        violations = validator.validate_section(valid_qa)
        assert len(violations) == 0

    def test_validator_detects_flowcheck_anomaly(self):
        bp = BookBlueprint(book_name="test")
        validator = PodValidator(blueprint=bp, max_shrink_ratio=0.40)

        long_raw = "## 某病方劑\n\n" + "詳細病例與藥材辯證說明的長篇文本 " * 20
        # Heavily truncated processed content (> 40% shrink)
        truncated_proc = "## 某病方劑\n\n只有一句話。"

        sec = SectionUnit(
            section_id="sec_006",
            title="某病方劑",
            raw_content=long_raw,
            processed_content=truncated_proc,
        )

        violations = validator.validate_section(sec)
        flow_viols = [v for v in violations if v.check_type == "flowcheck"]
        assert len(flow_viols) == 1
        assert flow_viols[0].severity == "ERROR"


class TestVisualFallbackRepair:
    def test_build_vlm_repair_prompt(self):
        few_shots = [{"unit_title": "雙參靈百湯", "golden_output": "【組成】...【用法】..."}]
        prompt = build_vlm_repair_prompt(
            corrupted_raw_md="## 茵陳蒿湯\n茵陳30克",
            golden_few_shots=few_shots,
            missing_badges=["用法"],
        )
        assert "雙參靈百湯" in prompt
        assert "【用法】" in prompt
        assert "茵陳蒿湯" in prompt
