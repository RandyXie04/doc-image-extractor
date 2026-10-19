# -*- coding: utf-8 -*-
"""
Exemplar Learner
================
Compares raw extraction files with human pre-processed golden exemplars (Golden Seed),
dynamically inferring book archetype (novels, Q&A, recipes, academic, legal, technical),
learning used Word styles, recurring structural badges, and Few-Shot pairs without
imposing rigid assumptions across different book genres.
"""

from __future__ import annotations
import re
import json
import argparse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
import docx

from .blueprint_schema import BookBlueprint, StyleTriggerRule, ValidationConfig
from .section_ast import SectionAST, SectionUnit


class ExemplarLearner:
    """Extracts typography and semantic transformation blueprints from human golden seeds."""

    # Archetype-specific trigger packs
    RECIPE_TRIGGERS = [
        {
            "badge": "用法",
            "regex": r"(?:水煎服|日服|每日\s*[一二三123]\s*劑|空腹[溫温]服|分\s*[一二三123]\s*次服|水煎[，,]\s*去渣|煎湯代茶|代茶飲|早晚各一次|日一劑)",
            "style": "Normal",
        },
        {
            "badge": "組成",
            "regex": r"(?:(?:[\u4e00-\u9fa5]{1,6}\s*\d+[\s\u3000]*[克g克千克兩钱錢]|各等分|適量).*){2,}",
            "style": "Normal",
        },
        {
            "badge": "功效",
            "regex": r"(?:清熱|健脾|補腎|活血|祛風|化痰|散寒|疏肝|養心|理氣|利水|溫陽|益氣|止痛|潤肺|安神)[\u4e00-\u9fa5]{2,6}",
            "style": "Normal",
        },
        {
            "badge": "按語",
            "regex": r"(?:本方出自|按[：:]|臨床體會|臨證應用|本方主要|配伍特點|筆者體會)",
            "style": "備注楷體",
        },
        {
            "badge": "備注",
            "regex": r"(?:孕婦忌服|忌生冷|服藥期間|注意[：:]|禁忌[：:])",
            "style": "備注楷體",
        },
    ]

    QA_TRIGGERS = [
        {
            "badge": "問",
            "regex": r"^(?:問[：:]|Q[：:]|問題[：:])\s*",
            "style": "問答題幹",
        },
        {
            "badge": "答",
            "regex": r"^(?:答[：:]|A[：:]|解答[：:])\s*",
            "style": "問答解析",
        },
    ]

    COOKBOOK_TRIGGERS = [
        {
            "badge": "材料",
            "regex": r"^(?:材料|食材|主料|配料|調料)[：:]\s*",
            "style": "Normal",
        },
        {
            "badge": "步驟",
            "regex": r"^(?:步驟|做法|製作方法|烹調步驟)[：:]\s*",
            "style": "Normal",
        },
    ]

    @classmethod
    def _extract_badges_from_text(cls, text: str) -> List[str]:
        """Extracts candidate structural badges or prefixes from text."""
        badges = []
        # Pattern 1: Bracketed badges 【...】, [...], 〔...〕
        bracket_matches = re.findall(r'(?:^|[\n\r])\s*(?:【([^】]{2,10})】|\[([^\]]{2,10})\]|〔([^〕]{2,10})〕)', text)
        for m in bracket_matches:
            b = m[0] or m[1] or m[2]
            if b and len(b.strip()) <= 8:
                badges.append(b.strip())

        # Pattern 2: Prefix labels like 問：, 答：, 材料：, 步驟：
        prefix_matches = re.findall(r'(?:^|[\n\r])\s*([問答QA材料步驟作法解析案情評析提示注意要點病案分析]{1,6})[：:]', text)
        for p in prefix_matches:
            badges.append(p.strip())

        return badges

    @classmethod
    def _detect_book_type(cls, learned_badges: List[str]) -> str:
        """Infers the book archetype based on recurring badges."""
        badge_set = set(learned_badges)
        if any(b in badge_set for b in ("組成", "用法", "方解", "方歌", "加減")):
            return "recipe_formula"
        elif any(b in badge_set for b in ("問", "答", "Q", "A", "問題", "解答")):
            return "qa_dialogue"
        elif any(b in badge_set for b in ("材料", "步驟", "作法", "主料", "調料")):
            return "cookbook"
        elif any(b in badge_set for b in ("條文", "判例", "要件", "釋義")):
            return "legal_statute"
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

        # Determine section count (excluding preamble)
        sec_count = max(len([t for t in gold_sections if t != "__PREAMBLE__"]), 1)

        # Mandatory badges must appear in >= 60% of sampled sections (or >= 1 if <= 2 sections)
        threshold = 1 if sec_count <= 2 else max(2, int(sec_count * 0.6))
        mandatory_badges = [
            b for b, count in badge_counts.items()
            if count >= threshold
        ]

        book_type = cls._detect_book_type(distinct_badges)

        # Few-shots
        few_shots: List[Dict[str, str]] = []
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
                if len(few_shots) >= sample_chapters:
                    break

        # Numbering check enabled only if circled numbers are regularly used
        enable_numbering = circled_number_count >= max(2, int(sec_count * 0.4))

        # Dynamic validation config
        val_config = ValidationConfig(
            enable_flowcheck=True,
            max_shrink_ratio=0.40,
            enable_badge_check=bool(mandatory_badges),
            enable_numbering_check=enable_numbering,
            enable_style_check=True,
        )

        rules = cls._build_style_rules(distinct_badges, used_styles, book_type, enable_numbering)

        return BookBlueprint(
            book_name=Path(golden_docx_path).stem.replace("_前處理", "").replace("_golden", ""),
            book_type=book_type,
            template_styles_used=sorted(list(used_styles)),
            heading_hierarchy=heading_hierarchy,
            mandatory_section_badges=mandatory_badges,
            style_rules=rules,
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
        gold_sections = h2_gold_sections if h2_gold_sections else {s.title: s.raw_content for s in gold_units if s.title != "__PREAMBLE__"}

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
        for title, gold_content in gold_sections.items():
            if title == "__PREAMBLE__":
                continue
            if title in raw_sections:
                few_shots.append({
                    "unit_title": title,
                    "raw_input": raw_sections[title],
                    "golden_output": gold_content,
                })
                if len(few_shots) >= sample_chapters:
                    break

        val_config = ValidationConfig(
            enable_flowcheck=True,
            max_shrink_ratio=0.40,
            enable_badge_check=bool(mandatory_badges),
            enable_numbering_check=enable_numbering,
            enable_style_check=True,
        )

        rules = cls._build_style_rules(distinct_badges, used_styles, book_type, enable_numbering)

        return BookBlueprint(
            book_name=Path(golden_md_path).stem.replace("_前處理", "").replace("_golden", ""),
            book_type=book_type,
            template_styles_used=sorted(list(used_styles)),
            heading_hierarchy={"H1": "Heading 1", "H2": "Heading 2"},
            mandatory_section_badges=mandatory_badges,
            style_rules=rules,
            few_shot_examples=few_shots,
            validation_config=val_config,
        )

    @classmethod
    def _build_style_rules(
        cls,
        learned_badges: List[str],
        used_styles: Set[str],
        book_type: str,
        enable_numbering: bool,
    ) -> List[StyleTriggerRule]:
        """Maps known semantic patterns to trigger rules according to book archetype."""
        rules: List[StyleTriggerRule] = []

        # 1. Circle number separation rule (only if book actually uses them)
        if enable_numbering:
            rules.append(StyleTriggerRule(
                rule_id="split_circled_num_rule",
                action="split_circled_num",
                trigger_regex=r"[①②③④⑤⑥⑦⑧⑨⑩]",
                priority=5,
            ))

        # 2. Add badge injection rules based on inferred archetype
        trigger_pool = []
        if book_type == "recipe_formula":
            trigger_pool = cls.RECIPE_TRIGGERS
        elif book_type == "qa_dialogue":
            trigger_pool = cls.QA_TRIGGERS
        elif book_type == "cookbook":
            trigger_pool = cls.COOKBOOK_TRIGGERS

        for item in trigger_pool:
            badge = item["badge"]
            if badge in learned_badges:
                target_style = item["style"] if item["style"] in used_styles else "Normal"
                rules.append(StyleTriggerRule(
                    rule_id=f"inject_badge_{badge}",
                    action="inject_badge",
                    inject_prefix_badge=f"【{badge}】",
                    trigger_regex=item["regex"],
                    target_docx_style=target_style,
                    priority=10,
                ))

        # 3. Apply custom style rules if custom styles are observed
        for st in used_styles:
            if "詩詞" in st or "框" in st:
                rules.append(StyleTriggerRule(
                    rule_id=f"apply_{st}",
                    action="apply_style",
                    target_docx_style=st,
                    trigger_regex=r"^[\u4e00-\u9fa5]{5,7}[，,。]\s*[\u4e00-\u9fa5]{5,7}",
                    priority=20,
                ))

        return rules

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
