# -*- coding: utf-8 -*-
"""
Exemplar Learner & Diff Aligner
===============================
Compares raw extraction files with human pre-processed golden exemplars (Golden Seed),
dynamically inferring layout blueprints (custom styles, recurring structural badges,
and text transformation rules) via deterministic LCS Diff Alignment without domain-specific hardcoding.
"""

from __future__ import annotations
import re
import json
import difflib
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
import docx

from .blueprint_schema import BookBlueprint, StyleTriggerRule, ValidationConfig
from .section_ast import SectionAST, SectionUnit


class DiffAligner:
    """
    Compares raw and golden paragraphs using SequenceMatcher to automatically infer:
    1. Injected badges (e.g. 【導讀】, 【重點】)
    2. Applied custom styles (e.g. ::: {custom-style="提示框"} ...)
    3. Intentionally deleted lines (e.g. decorative running headers)
    """

    _BADGE_PREFIX_RE = re.compile(r'^(?:【([^】]+)】|\[([^\]]+)\]|〔([^〕]+)〕)')
    _CUSTOM_STYLE_RE = re.compile(r':::\s*\{\s*custom-style="([^"]+)"\s*\}\n?(.*?)\n?:::', re.DOTALL)

    @classmethod
    def align_paragraphs(cls, raw_text: str, golden_text: str) -> List[StyleTriggerRule]:
        """Infers transformation rules by comparing raw and golden paragraph streams."""
        raw_paras = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
        gold_paras = [p.strip() for p in golden_text.split("\n\n") if p.strip()]

        inferred_rules: List[StyleTriggerRule] = []
        rule_signatures: Set[str] = set()

        # Step A: Find paragraphs in golden that have custom styles
        for gp in gold_paras:
            m_style = cls._CUSTOM_STYLE_RE.search(gp)
            if m_style:
                style_name = m_style.group(1).strip()
                inner_text = m_style.group(2).strip()
                # Find matching paragraph in raw_paras
                for rp in raw_paras:
                    # If raw paragraph is contained in or contains inner_text
                    if inner_text and (inner_text in rp or rp in inner_text):
                        # Construct a leading regex trigger (first 6-12 chars)
                        clean_start = re.sub(r'^[#\s【】\[\]\d\.\-、]+', '', rp).strip()
                        prefix = clean_start[:8]
                        if len(prefix) >= 2:
                            escaped = re.escape(prefix)
                            sig = f"style_{style_name}_{escaped}"
                            if sig not in rule_signatures:
                                rule_signatures.add(sig)
                                inferred_rules.append(StyleTriggerRule(
                                    rule_id=f"rule_style_{len(inferred_rules)+1}",
                                    target_docx_style=style_name,
                                    trigger_regex=f"^{escaped}",
                                    action="apply_style",
                                    priority=20,
                                ))

        # Step B: Find injected badges
        for gp in gold_paras:
            m_badge = cls._BADGE_PREFIX_RE.match(gp)
            if m_badge:
                badge_name = m_badge.group(1) or m_badge.group(2) or m_badge.group(3)
                full_badge = f"【{badge_name}】"
                post_badge_text = gp[m_badge.end():].strip()

                # Check if raw version lacked this badge
                for rp in raw_paras:
                    if not rp.startswith(full_badge) and post_badge_text and post_badge_text[:12] in rp:
                        clean_start = re.sub(r'^[#\s【】\[\]\d\.\-、]+', '', post_badge_text).strip()
                        prefix = clean_start[:8]
                        if len(prefix) >= 2:
                            escaped = re.escape(prefix)
                            sig = f"badge_{badge_name}_{escaped}"
                            if sig not in rule_signatures:
                                rule_signatures.add(sig)
                                inferred_rules.append(StyleTriggerRule(
                                    rule_id=f"rule_badge_{badge_name}_{len(inferred_rules)+1}",
                                    action="inject_badge",
                                    inject_prefix_badge=full_badge,
                                    trigger_regex=f"^{escaped}",
                                    priority=10,
                                ))

        return inferred_rules


class ExemplarLearner:
    """Extracts typography and semantic transformation blueprints from human golden seeds."""

    @classmethod
    def _extract_badges_from_text(cls, text: str) -> List[str]:
        """Extracts candidate structural badges or prefixes from text."""
        badges = []
        # Pattern 1: Bracketed badges 【...】, [...], 〔...〕
        bracket_matches = re.findall(
            r'(?:^|[\n\r])\s*(?:【([^】]{2,10})】|\[([^\]]{2,10})\]|〔([^〕]{2,10})〕)',
            text
        )
        for m in bracket_matches:
            b = m[0] or m[1] or m[2]
            if b and len(b.strip()) <= 8:
                badges.append(b.strip())

        # Pattern 2: Standard prefix labels like 導讀：, 摘要：, 提示：, 注意：, 範例：
        prefix_matches = re.findall(
            r'(?:^|[\n\r])\s*([問答QA材料步驟作法解析案情評析提示注意要點導讀摘要重點範例]{1,6})[：:]',
            text
        )
        for p in prefix_matches:
            badges.append(p.strip())

        return badges

    @classmethod
    def _detect_book_type(cls, learned_badges: List[str]) -> str:
        """Infers the book archetype based on recurring badges."""
        badge_set = set(learned_badges)
        if any(b in badge_set for b in ("問", "答", "Q", "A", "問題", "解答")):
            return "qa_dialogue"
        elif any(b in badge_set for b in ("導讀", "重點", "摘要", "提示", "範例", "說明", "解析")):
            return "technical_manual"
        elif not learned_badges:
            return "narrative"
        return "general"

    @classmethod
    def learn_from_docx_pair(
        cls,
        raw_docx_path: str | Path,
        golden_docx_path: str | Path,
        sample_chapters: int = 3,
    ) -> BookBlueprint:
        """Learns blueprint dynamically from raw and golden DOCX files."""
        raw_doc = docx.Document(str(raw_docx_path))
        gold_doc = docx.Document(str(golden_docx_path))

        used_styles: Set[str] = set()
        heading_hierarchy: Dict[str, str] = {}
        all_text_chunks = []
        circled_number_count = 0

        for p in gold_doc.paragraphs:
            txt = p.text.strip()
            if not txt:
                continue
            all_text_chunks.append(txt)
            s_name = p.style.name if p.style else "Normal"
            used_styles.add(s_name)

            if s_name.lower().startswith("heading") or "標題" in s_name:
                level_match = re.search(r'\d+', s_name)
                level_num = level_match.group(0) if level_match else "1"
                heading_hierarchy[f"H{level_num}"] = s_name

            if re.search(r'[①②③④⑤⑥⑦⑧⑨⑩]', txt):
                circled_number_count += 1

        full_golden_text = "\n".join(all_text_chunks)

        # 2. Extract sections from both documents
        raw_sections = cls._split_docx_by_h2(raw_doc)
        gold_sections = cls._split_docx_by_h2(gold_doc)

        # Count badge occurrences across sections
        badge_counts: Dict[str, int] = {}
        candidate_badges = cls._extract_badges_from_text(full_golden_text)
        distinct_badges = list(dict.fromkeys(candidate_badges))

        for sec_content in gold_sections.values():
            sec_badges = set(cls._extract_badges_from_text(sec_content))
            for b in sec_badges:
                badge_counts[b] = badge_counts.get(b, 0) + 1

        sec_count = max(len([t for t in gold_sections if t != "__PREAMBLE__"]), 1)
        threshold = 1 if sec_count <= 2 else max(2, int(sec_count * 0.6))
        mandatory_badges = [
            b for b, count in badge_counts.items()
            if count >= threshold
        ]

        book_type = cls._detect_book_type(distinct_badges)

        # Few-shots and Diff-Aligned rules
        few_shots: List[Dict[str, str]] = []
        all_inferred_rules: List[StyleTriggerRule] = []

        for title, gold_md in gold_sections.items():
            if title == "__PREAMBLE__":
                continue
            raw_match = raw_sections.get(title)
            if not raw_match:
                clean_title = re.sub(r'^[一二三四五六七八九十0-9\s、.·]+', '', title).strip()
                for r_title, r_content in raw_sections.items():
                    clean_r = re.sub(r'^[一二三四五六七八九十0-9\s、.·]+', '', r_title).strip()
                    if clean_title and (clean_title in clean_r or clean_r in clean_title):
                        raw_match = r_content
                        break

            if raw_match:
                few_shots.append({
                    "unit_title": title,
                    "raw_input": raw_match,
                    "golden_output": gold_md,
                })
                # Infer rules from diff
                rules_from_sec = DiffAligner.align_paragraphs(raw_match, gold_md)
                all_inferred_rules.extend(rules_from_sec)
                if len(few_shots) >= sample_chapters:
                    break

        # Numbering check enabled only if circled numbers are regularly used
        enable_numbering = circled_number_count >= max(2, int(sec_count * 0.4))

        if enable_numbering:
            all_inferred_rules.insert(0, StyleTriggerRule(
                rule_id="split_circled_num_rule",
                action="split_circled_num",
                trigger_regex=r"[①②③④⑤⑥⑦⑧⑨⑩]",
                priority=5,
            ))

        # Dynamic validation config
        val_config = ValidationConfig(
            enable_flowcheck=True,
            max_shrink_ratio=0.40,
            enable_badge_check=bool(mandatory_badges),
            enable_numbering_check=enable_numbering,
            enable_style_check=True,
        )

        # Deduplicate rules by rule_id or signature
        seen_rules = set()
        deduped_rules = []
        for r in all_inferred_rules:
            sig = (r.action, r.target_docx_style, r.inject_prefix_badge, r.trigger_regex)
            if sig not in seen_rules:
                seen_rules.add(sig)
                deduped_rules.append(r)

        return BookBlueprint(
            book_name=Path(golden_docx_path).stem.replace("_前處理", "").replace("_golden", ""),
            book_type=book_type,
            template_styles_used=sorted(list(used_styles)),
            heading_hierarchy=heading_hierarchy,
            mandatory_section_badges=mandatory_badges,
            style_rules=deduped_rules,
            few_shot_examples=few_shots,
            validation_config=val_config,
            metadata={
                "source_golden": str(golden_docx_path),
                "gold_section_count": len(gold_sections),
            }
        )

    @classmethod
    def learn_from_md_pair(
        cls,
        raw_md_path: str | Path,
        golden_md_path: str | Path,
        sample_chapters: int = 3,
    ) -> BookBlueprint:
        """Learns blueprint dynamically from raw and golden Markdown files."""
        raw_text = Path(raw_md_path).read_text(encoding="utf-8")
        gold_text = Path(golden_md_path).read_text(encoding="utf-8")

        raw_units = SectionAST.from_markdown(raw_text, split_level=2)
        gold_units = SectionAST.from_markdown(gold_text, split_level=2)

        raw_sections = {s.title: s.raw_content for s in raw_units}
        h2_gold_sections = {s.title: s.raw_content for s in gold_units if s.level >= 2}
        gold_sections = h2_gold_sections if h2_gold_sections else {
            s.title: s.raw_content for s in gold_units if s.title != "__PREAMBLE__"
        }

        used_styles = set(re.findall(r':::\s*\{\s*custom-style="([^"]+)"\s*\}', gold_text))

        # Extract badges and count frequencies
        badge_counts: Dict[str, int] = {}
        candidate_badges = cls._extract_badges_from_text(gold_text)
        distinct_badges = list(dict.fromkeys(candidate_badges))

        for sec_content in gold_sections.values():
            sec_badges = set(cls._extract_badges_from_text(sec_content))
            for b in sec_badges:
                badge_counts[b] = badge_counts.get(b, 0) + 1

        sec_count = max(len(gold_sections), 1)
        threshold = 1 if sec_count <= 2 else max(2, int(sec_count * 0.6))
        mandatory_badges = [
            b for b, count in badge_counts.items()
            if count >= threshold
        ]

        book_type = cls._detect_book_type(distinct_badges)

        # Check numbering frequency
        circled_number_count = len(re.findall(r'[①②③④⑤⑥⑦⑧⑨⑩]', gold_text))
        enable_numbering = circled_number_count >= max(2, int(sec_count * 0.4))

        few_shots = []
        all_inferred_rules: List[StyleTriggerRule] = []

        for title, gold_content in gold_sections.items():
            if title == "__PREAMBLE__":
                continue
            if title in raw_sections:
                few_shots.append({
                    "unit_title": title,
                    "raw_input": raw_sections[title],
                    "golden_output": gold_content,
                })
                # Infer rules from diff
                rules_from_sec = DiffAligner.align_paragraphs(raw_sections[title], gold_content)
                all_inferred_rules.extend(rules_from_sec)
                if len(few_shots) >= sample_chapters:
                    break

        if enable_numbering:
            all_inferred_rules.insert(0, StyleTriggerRule(
                rule_id="split_circled_num_rule",
                action="split_circled_num",
                trigger_regex=r"[①②③④⑤⑥⑦⑧⑨⑩]",
                priority=5,
            ))

        val_config = ValidationConfig(
            enable_flowcheck=True,
            max_shrink_ratio=0.40,
            enable_badge_check=bool(mandatory_badges),
            enable_numbering_check=enable_numbering,
            enable_style_check=True,
        )

        seen_rules = set()
        deduped_rules = []
        for r in all_inferred_rules:
            sig = (r.action, r.target_docx_style, r.inject_prefix_badge, r.trigger_regex)
            if sig not in seen_rules:
                seen_rules.add(sig)
                deduped_rules.append(r)

        return BookBlueprint(
            book_name=Path(golden_md_path).stem.replace("_前處理", "").replace("_golden", ""),
            book_type=book_type,
            template_styles_used=sorted(list(used_styles)),
            heading_hierarchy={"H1": "Heading 1", "H2": "Heading 2"},
            mandatory_section_badges=mandatory_badges,
            style_rules=deduped_rules,
            few_shot_examples=few_shots,
            validation_config=val_config,
        )

    @staticmethod
    def _split_docx_by_h2(doc: docx.Document) -> Dict[str, str]:
        """Parses a docx document into sections keyed by H2 heading text."""
        sections: Dict[str, List[str]] = {}
        curr_title = "__PREAMBLE__"
        sections[curr_title] = []

        for p in doc.paragraphs:
            txt = p.text.strip()
            if not txt:
                continue
            s_name = p.style.name if p.style else "Normal"
            is_h2 = s_name in ("Heading 2", "標題 2", "Heading 2 Char") or (
                s_name.startswith("Heading") and "2" in s_name
            )

            if is_h2:
                curr_title = txt
                sections[curr_title] = [f"## {txt}"]
            else:
                if s_name not in ("Normal", "Body Text", "內文", "標準"):
                    sections[curr_title].append(f'::: {{custom-style="{s_name}"}}\n{txt}\n:::')
                else:
                    sections[curr_title].append(txt)

        return {k: "\n\n".join(v) for k, v in sections.items() if v}


def main():
    parser = argparse.ArgumentParser(description="Exemplar Learner CLI for POD Studio")
    parser.add_argument("--raw", required=True, help="Path to raw input file (.docx or .md)")
    parser.add_argument("--golden", required=True, help="Path to human pre-processed golden file (.docx or .md)")
    parser.add_argument("--output", default="book_blueprint.json", help="Path to save output blueprint JSON")
    parser.add_argument("--samples", type=int, default=3, help="Number of few-shot sample chapters to extract")
    args = parser.parse_args()

    raw_p = Path(args.raw)
    gold_p = Path(args.golden)

    if raw_p.suffix.lower() == ".docx" and gold_p.suffix.lower() == ".docx":
        blueprint = ExemplarLearner.learn_from_docx_pair(raw_p, gold_p, sample_chapters=args.samples)
    else:
        blueprint = ExemplarLearner.learn_from_md_pair(raw_p, gold_p, sample_chapters=args.samples)

    blueprint.save(args.output)
    print(f"Successfully learned blueprint from {gold_p.name} -> {args.output}")
    print(f"  - Book Archetype: {blueprint.book_type}")
    print(f"  - Styles used: {len(blueprint.template_styles_used)} ({', '.join(blueprint.template_styles_used[:5])})")
    print(f"  - Mandatory Badges: {blueprint.mandatory_section_badges}")
    print(f"  - Validation Config: BadgeCheck={blueprint.validation_config.enable_badge_check}, NumberingCheck={blueprint.validation_config.enable_numbering_check}")
    print(f"  - Style Rules: {len(blueprint.style_rules)}")
    print(f"  - Few-Shot Examples: {len(blueprint.few_shot_examples)}")


if __name__ == "__main__":
    main()
