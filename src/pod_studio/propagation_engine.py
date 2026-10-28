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
from typing import List, Dict, Any, Optional, Union, Sequence, Tuple

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
        is_preamble = (section.title == "__PREAMBLE__" or section.level == 0)

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
                        if is_preamble:
                            continue
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

                # Sanitize alien custom_style not defined in blueprint template
                if self.blueprint and self.blueprint.template_styles_used:
                    valid_styles = set(self.blueprint.template_styles_used)
                    if p.custom_style and p.custom_style not in valid_styles and p.custom_style != "Normal":
                        p.custom_style = ""

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
                    if is_preamble:
                        continue
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

    def classify_paragraphs_hybrid(
        self,
        paragraphs: Sequence[Tuple[int, str]],
        ai_client: Optional[Any] = None,
        model: Optional[str] = None,
        batch_size: int = 70,
    ) -> Dict[int, str]:
        """
        Classifies paragraphs into target docx styles using:
        1. High-speed deterministic rules learned from exemplar.
        2. Gemini API / LLM intelligence for unclassified or ambiguous paragraphs.

        paragraphs: sequence of (paragraph_index, paragraph_text)
        Returns: mapping of {paragraph_index: target_style}
        """
        import os
        import json
        import time

        results: Dict[int, str] = {}
        unclassified: List[Tuple[int, str]] = []

        # ── Step 1: High-Speed Deterministic Regex Evaluation ──
        for idx, text in paragraphs:
            t = text.strip()
            if not t:
                continue
            matched_style = None
            for rule in self.rules:
                if rule.action == "apply_style" and rule.target_docx_style and rule.trigger_regex:
                    if re.search(rule.trigger_regex, t):
                        matched_style = rule.target_docx_style
                        break
            if matched_style:
                results[idx] = matched_style
            else:
                unclassified.append((idx, t))

        # ── Step 2: Intelligent Gemini API Classification for Remaining Paragraphs ──
        if unclassified:
            if ai_client is None:
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    try:
                        from config.settings import AI
                        api_key = AI.gemini_key
                    except Exception:
                        pass
                if not api_key:
                    try:
                        from pathlib import Path
                        from dotenv import load_dotenv
                        for parent in Path(__file__).resolve().parents:
                            cand_env = parent / ".env"
                            if cand_env.exists():
                                load_dotenv(dotenv_path=cand_env)
                                break
                        api_key = os.getenv("GEMINI_API_KEY")
                    except Exception:
                        pass
                if api_key:
                    try:
                        from google import genai
                        ai_client = genai.Client(api_key=api_key)
                    except Exception:
                        pass

            if ai_client is not None:
                target_model = model or os.getenv("DEFAULT_AI_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite"
                valid_styles = list(self.blueprint.template_styles_used)
                if "Normal" not in valid_styles:
                    valid_styles.append("Normal")

                # Prepare style definitions / few-shot cues
                style_cues = []
                meta = self.blueprint.metadata or {}
                style_defs = meta.get("style_definitions", {})
                for s, samples in style_defs.items():
                    sample_str = "、".join([f'"{samp[:40]}"' for samp in samples[:3]])
                    style_cues.append(f"- 【{s}】範例: {sample_str}")

                boundary_idx = meta.get("seed_last_modified_idx", 0)
                manual_anchor = meta.get("manual_boundary_anchor", "")
                boundary_ctx = meta.get("boundary_context_text", "")
                boundary_note = f"人工精修截止邊界：第 {boundary_idx} 段"
                if manual_anchor:
                    boundary_note += f"（人工定位錨點：「{manual_anchor}」）"
                if boundary_ctx:
                    boundary_note += f"\n截止處最後人工確認內文：「{boundary_ctx}」"

                total_batches = (len(unclassified) + batch_size - 1) // batch_size
                for b_idx, i in enumerate(range(0, len(unclassified), batch_size), 1):
                    batch = unclassified[i : i + batch_size]
                    batch_payload = [{"id": p_idx, "text": p_txt[:90]} for p_idx, p_txt in batch]
                    print(f"[POD Studio AI] Batch {b_idx}/{total_batches}: Classifying {len(batch)} ambiguous paragraphs via {target_model}...", flush=True)

                    prompt = (
                        "你是一位專精於中文圖書出版與 POD 數位整稿的專家。\n"
                        "請根據以下人工精修範本歸納出的自訂樣式定義與範例，為人工截止點之後的後續生稿段落標記最適用的樣式名稱：\n\n"
                        f"【人工定位確認】\n{boundary_note}\n\n"
                        f"可用樣式清單：{json.dumps(valid_styles, ensure_ascii=False)}\n"
                        "樣式特徵與範例：\n"
                        + "\n".join(style_cues[:8])
                        + "\n\n"
                        "待標記後續生稿段落列表：\n"
                        + json.dumps(batch_payload, ensure_ascii=False, indent=2)
                        + "\n\n"
                        "要求：\n"
                        "1. 若為普通正文敘述或段落，請標記為 'Normal'。\n"
                        "2. 請僅輸出 JSON 陣列，不要包含任何開場白或解釋：\n"
                        '[{"id": 188, "style": "Heading 3"}, ...]'
                    )

                    for attempt in range(4):
                        try:
                            resp_text = ""
                            if hasattr(ai_client, "models") and hasattr(ai_client.models, "generate_content"):
                                resp = ai_client.models.generate_content(
                                    model=target_model,
                                    contents=prompt,
                                )
                                resp_text = resp.text.strip()
                            elif hasattr(ai_client, "generate_content"):
                                resp = ai_client.generate_content(prompt)
                                resp_text = resp.text.strip()
                            elif callable(ai_client):
                                resp_text = str(ai_client(prompt)).strip()

                            if resp_text:
                                clean_json = re.sub(r'^```(?:json)?\s*', '', resp_text)
                                clean_json = re.sub(r'\s*```$', '', clean_json).strip()
                                parsed = json.loads(clean_json)
                                if isinstance(parsed, list):
                                    for item in parsed:
                                        if isinstance(item, dict) and "id" in item and "style" in item:
                                            p_id = int(item["id"])
                                            s_name = str(item["style"]).strip()
                                            if s_name in valid_styles or s_name == "Normal":
                                                results[p_id] = s_name
                                    print(f"[POD Studio AI] Batch {b_idx}/{total_batches} done: processed {len(parsed)} paragraphs.", flush=True)
                            break
                        except Exception as e:
                            err_str = str(e)
                            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                                wait_sec = 16.0
                                match = re.search(r'retry in ([0-9.]+)', err_str)
                                if match:
                                    try:
                                        wait_sec = float(match.group(1)) + 1.0
                                    except Exception:
                                        pass
                                print(f"[POD Studio AI] Batch {b_idx}/{total_batches}: 429 rate limit hit. Waiting {wait_sec:.1f}s before retry...", flush=True)
                                time.sleep(wait_sec)
                            else:
                                print(f"[POD Studio AI] Batch {b_idx}/{total_batches} warning: {e}", flush=True)
                                break

        return results


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
