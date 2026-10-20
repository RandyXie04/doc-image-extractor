# -*- coding: utf-8 -*-
"""
Propagation Engine
==================
Executes deterministic AST-level batch propagation across section units
based on BookBlueprint rules, without touching fragile Word XML DOM nodes.
Supports both deterministic regex rule execution and zero-regeneration Index Tagging.
"""

from __future__ import annotations
import re
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

from .blueprint_schema import BookBlueprint, StyleTriggerRule, IndexTaggingInstruction
from .section_ast import SectionUnit, SectionAST, ParagraphUnit


class PropagationEngine:
    """High-speed deterministic rule engine and Index Tagging coordinator."""

    def __init__(self, blueprint: BookBlueprint):
        self.blueprint = blueprint
        # Sort rules by priority (ascending)
        self.rules = sorted(blueprint.style_rules, key=lambda r: r.priority)

    def process_all(self, sections: List[SectionUnit]) -> List[SectionUnit]:
        """Runs batch rule propagation across all sections in the document."""
        processed = []
        for sec in sections:
            processed.append(self.process_section(sec))
        return processed

    def process_section(self, section: SectionUnit) -> SectionUnit:
        """Processes an individual SectionUnit using rule transformations."""
        if section.title == "__PREAMBLE__" or section.level == 0:
            section.processed_content = section.raw_content
            return section

        # Track badges already present
        existing_badges = set(re.findall(r'【([^】]+)】|\[([^\]]+)\]', section.raw_content))
        flattened_badges = {b[0] or b[1] for b in existing_badges}

        # If paragraphs are explicitly populated in the SectionUnit, transform them directly
        if section.paragraphs:
            for p in section.paragraphs:
                p_strip = p.raw_text.strip()
                if not p_strip or re.match(r'^#+\s+', p_strip):
                    continue

                transformed = p_strip
                should_delete = False

                for rule in self.rules:
                    if rule.action == "delete_line" and rule.trigger_regex:
                        if re.search(rule.trigger_regex, transformed):
                            should_delete = True
                            break

                    elif rule.action == "split_circled_num":
                        if re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]', transformed):
                            transformed = self._split_circled_numbers(transformed)

                    elif rule.action == "inject_badge" and rule.inject_prefix_badge:
                        badge_clean = rule.inject_prefix_badge.strip("【】[] ")
                        if badge_clean not in flattened_badges and rule.trigger_regex:
                            if re.search(rule.trigger_regex, transformed):
                                if not transformed.startswith(rule.inject_prefix_badge):
                                    p.injected_badge = rule.inject_prefix_badge
                                    flattened_badges.add(badge_clean)

                    elif rule.action == "apply_style" and rule.target_docx_style:
                        if "custom-style=" not in transformed and rule.trigger_regex:
                            if re.search(rule.trigger_regex, transformed):
                                p.custom_style = rule.target_docx_style

                p.is_deleted = should_delete
                p.processed_text = transformed

            section.processed_content = section.effective_content
            return section

        # Fallback for plain text paragraphs
        paragraphs = section.raw_content.split("\n\n")
        new_paragraphs: List[str] = []

        for p in paragraphs:
            p_strip = p.strip()
            if not p_strip:
                continue

            if re.match(r'^#+\s+', p_strip):
                new_paragraphs.append(p_strip)
                continue

            transformed = p_strip
            should_delete = False

            for rule in self.rules:
                if rule.action == "delete_line" and rule.trigger_regex:
                    if re.search(rule.trigger_regex, transformed):
                        should_delete = True
                        break

                elif rule.action == "split_circled_num":
                    if re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]', transformed):
                        transformed = self._split_circled_numbers(transformed)

                elif rule.action == "inject_badge" and rule.inject_prefix_badge:
                    badge_clean = rule.inject_prefix_badge.strip("【】[] ")
                    if badge_clean not in flattened_badges and rule.trigger_regex:
                        if re.search(rule.trigger_regex, transformed):
                            if not transformed.startswith(rule.inject_prefix_badge):
                                transformed = f"{rule.inject_prefix_badge}{transformed}"
                                flattened_badges.add(badge_clean)

                elif rule.action == "apply_style" and rule.target_docx_style:
                    if "custom-style=" not in transformed and rule.trigger_regex:
                        if re.search(rule.trigger_regex, transformed):
                            transformed = f'::: {{custom-style="{rule.target_docx_style}"}}\n{transformed}\n:::'

            if not should_delete:
                new_paragraphs.append(transformed)

        section.processed_content = "\n\n".join(new_paragraphs)
        return section

    def _split_circled_numbers(self, text: str) -> str:
        """Splits running circled numbers into cleanly indented separate lines."""
        pattern = r'(?<=[^\n])\s*([①②③④⑤⑥⑦⑧⑨⑩])'
        return re.sub(pattern, r'\n\1', text)

    @staticmethod
    def generate_index_tagging_payload(section: SectionUnit, preview_len: int = 25) -> List[Dict[str, Any]]:
        """
        Generates a token-minimal paragraph index summary for LLM classification.
        Does not transmit the entire text body.
        """
        payload = []
        # Ensure paragraphs exist
        paras = section.paragraphs
        if not paras:
            paras = SectionAST._text_to_paragraphs(section.raw_content, section.section_id)

        for p in paras:
            if p.is_deleted:
                continue
            prev = p.raw_text[:preview_len] + ("..." if len(p.raw_text) > preview_len else "")
            payload.append({
                "id": p.para_id,
                "font": p.font_name,
                "size": p.font_size,
                "len": len(p.raw_text),
                "preview": prev,
            })
        return payload

    @staticmethod
    def apply_index_tagging(
        section: SectionUnit,
        instructions: Sequence[Union[IndexTaggingInstruction, Dict[str, Any]]],
    ) -> SectionUnit:
        """
        Applies patch instructions onto paragraphs by para_id deterministically.
        Guarantees zero text mutation or hallucinated character alterations.
        """
        if not section.paragraphs:
            section.paragraphs = SectionAST._text_to_paragraphs(section.raw_content, section.section_id)

        inst_map: Dict[str, IndexTaggingInstruction] = {}
        for inst in instructions:
            if isinstance(inst, dict):
                obj = IndexTaggingInstruction.from_dict(inst)
            else:
                obj = inst
            inst_map[obj.para_id] = obj

        for p in section.paragraphs:
            if p.para_id in inst_map:
                op = inst_map[p.para_id]
                if op.delete:
                    p.is_deleted = True
                    continue
                if op.style:
                    p.custom_style = op.style
                if op.prepend_badge:
                    p.injected_badge = op.prepend_badge
                if op.split_numbering:
                    p.raw_text = re.sub(r'(?<=[^\n])\s*([①②③④⑤⑥⑦⑧⑨⑩])', r'\n\1', p.raw_text)

        section.processed_content = section.effective_content
        return section

    def format_agent_prompt(self, section: SectionUnit) -> str:
        """
        Formats a zero-drift prompt for Claude Code, Antigravity, or Codex
        containing the blueprint rules, few-shot examples, and the target section.
        """
        prompt_parts = [
            f"# POD 排版單元修復任務: {section.title} ({section.section_id})",
            "",
            "## 1. 任務說明",
            "請將以下【生稿文字 (Raw)】轉換為完全符合出版社 POD 標準的 Extended Markdown 格式。",
            "必須嚴格遵守以下排版規範：",
            "- 樣式宣告使用 Pandoc 語法: `::: {custom-style=\"樣式名\"}`",
            f"- 該單元必備結構標籤: {', '.join([f'【{b}】' for b in self.blueprint.mandatory_section_badges])}",
            "- 圓圈數字（①②③）必須連續獨立成行，不可在內文中混排斷號。",
            "- 嚴禁刪減原文句子或實質內文，確保漢字骨架 100% 守恆。",
            "",
            "## 2. 人工標準範本 (Few-Shot Golden Examples)",
        ]

        for i, ex in enumerate(self.blueprint.few_shot_examples[:2], 1):
            prompt_parts.extend([
                f"### 範本 {i}: {ex.get('unit_title', '範例')}",
                "**生稿輸入:**",
                "```markdown",
                ex.get("raw_input", "").strip(),
                "```",
                "**標準輸出 (Golden):**",
                "```markdown",
                ex.get("golden_output", "").strip(),
                "```",
                "",
            ])

        prompt_parts.extend([
            "## 3. 本次需處理的生稿",
            "```markdown",
            section.raw_content.strip(),
            "```",
            "",
            "請直接輸出修復完成的 Markdown 內容（包含該單元標題），不要包含多餘的打招呼或解釋文字：",
        ])

        return "\n".join(prompt_parts)


def main():
    parser = argparse.ArgumentParser(description="Propagation Engine for POD Studio")
    parser.add_argument("--workspace", required=True, help="Path to section AST workspace")
    parser.add_argument("--blueprint", required=True, help="Path to BookBlueprint JSON")
    parser.add_argument("--out-md", help="Optional path to output reassembled Markdown")
    args = parser.parse_args()

    bp = BookBlueprint.load(args.blueprint)
    sections = SectionAST.load_from_workspace(args.workspace)

    engine = PropagationEngine(bp)
    processed_secs = engine.process_all(sections)

    SectionAST.dump_to_workspace(args.workspace, processed_secs)
    print(f"Batch propagation complete across {len(processed_secs)} sections in {args.workspace}")

    if args.out_md:
        out_text = SectionAST.to_markdown(processed_secs)
        Path(args.out_md).write_text(out_text, encoding="utf-8")
        print(f"Reassembled Markdown saved to: {args.out_md}")


if __name__ == "__main__":
    main()
