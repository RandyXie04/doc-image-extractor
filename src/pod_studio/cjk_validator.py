# -*- coding: utf-8 -*-
"""
CJK Skeleton Invariant & Defensive Gatekeeper
=============================================
Enforces strict character-level conservation across transformation pipelines:
1. Zero-Deletion guarantee on CJK and alphanumeric characters (excluding explicit whitelist).
2. Closed-Set Word style validation against template.docx / styles.xml.
3. Traffic light audit classification: GREEN (clean), YELLOW (injected/repaired), RED (dropped/invalid).
"""

from __future__ import annotations
import re
import difflib
from dataclasses import dataclass, field, asdict
from typing import List, Set, Dict, Any, Optional, Iterable, Sequence

# Regex matching core CJK unified ideographs, extensions, and standard alphanumeric characters
_CJK_SKELETON_RE = re.compile(
    r'[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002ceafA-Za-z0-9]'
)
_CUSTOM_STYLE_RE = re.compile(r'\{custom-style="([^"]+)"\}')
_PANDOC_FENCE_RE = re.compile(r':::\s*\{custom-style="([^"]+)"\}|:::')
_IMAGE_MD_RE = re.compile(r'!\[.*?\]\(.*?\)(?:\{.*?\})?')


@dataclass
class CJKValidationResult:
    section_id: str
    section_title: str
    status: str                         # "GREEN" | "YELLOW" | "RED"
    raw_char_count: int
    processed_char_count: int
    dropped_fragments: List[str] = field(default_factory=list)
    added_fragments: List[str] = field(default_factory=list)
    replaced_fragments: List[str] = field(default_factory=list)
    invalid_styles: List[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PODIntegrityValidator:
    """
    Production POD Defensive Boundary Gatekeeper:
    - Protects against LLM silent text dropping and hallucinated modifications.
    - Validates that all custom-style tags map to a known closed-set whitelist.
    """

    def __init__(
        self,
        valid_docx_styles: Optional[Iterable[str]] = None,
        allowed_injected_badges: Optional[Iterable[str]] = None,
    ):
        self.valid_docx_styles: Set[str] = set(valid_docx_styles or [])
        self.allowed_badges: Set[str] = set(allowed_injected_badges or [])

    def extract_skeleton(self, text: str) -> str:
        """
        Strips markdown formatting, styles, images, and allowed injected badges,
        leaving pure CJK characters and alphanumeric text.
        """
        # 1. Remove Markdown custom-style fences and attributes
        cleaned = _PANDOC_FENCE_RE.sub('', text)
        cleaned = _CUSTOM_STYLE_RE.sub('', cleaned)
        cleaned = _IMAGE_MD_RE.sub('', cleaned)

        # 2. Remove known legitimately injected badges (e.g. 【導讀】, 【重點】)
        for badge in self.allowed_badges:
            cleaned = cleaned.replace(badge, '')

        # 3. Extract pure CJK and alphanumeric sequence
        return "".join(_CJK_SKELETON_RE.findall(cleaned))

    def validate_section(
        self,
        section_id: str,
        section_title: str,
        raw_text: str,
        processed_text: str,
        intentionally_deleted_texts: Optional[Sequence[str]] = None,
    ) -> CJKValidationResult:
        """
        Validates character conservation and style conformance for an individual section.
        """
        baseline_raw = raw_text
        if intentionally_deleted_texts:
            for del_txt in intentionally_deleted_texts:
                baseline_raw = baseline_raw.replace(del_txt, '')

        raw_skel = self.extract_skeleton(baseline_raw)
        proc_skel = self.extract_skeleton(processed_text)

        # 1. Closed-set style validation
        used_styles = set(_CUSTOM_STYLE_RE.findall(processed_text))
        invalid_styles = set()
        if self.valid_docx_styles:
            # Allow standard built-in structural styles by default
            invalid_styles = used_styles - self.valid_docx_styles - {"Normal", "Table Caption", "Caption"}

        # 2. Sequence diff
        matcher = difflib.SequenceMatcher(None, raw_skel, proc_skel)
        dropped_fragments: List[str] = []
        added_fragments: List[str] = []
        replaced_fragments: List[str] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'delete':
                dropped_fragments.append(raw_skel[i1:i2])
            elif tag == 'insert':
                added_fragments.append(proc_skel[j1:j2])
            elif tag == 'replace':
                replaced_fragments.append(f"{raw_skel[i1:i2]} -> {proc_skel[j1:j2]}")

        dropped_count = sum(len(x) for x in dropped_fragments)
        added_count = sum(len(x) for x in added_fragments)

        # 3. Traffic light classification
        # RED: Any character dropped OR invalid style used
        # YELLOW: Characters added (e.g. visual repair) but zero dropped
        # GREEN: 100% skeleton conservation
        status = "GREEN"
        messages = []

        if dropped_count > 0:
            status = "RED"
            messages.append(f"檢測到靜默掉字 {dropped_count} 字: {dropped_fragments[:3]}")
        if invalid_styles:
            status = "RED"
            messages.append(f"使用未定義樣式: {list(invalid_styles)}")

        if status != "RED":
            if added_count > 0:
                status = "YELLOW"
                messages.append(f"包含增補文字 {added_count} 字（需人工快速瀏覽）")
            elif replaced_fragments:
                status = "YELLOW"
                messages.append(f"包含替換文字片段: {replaced_fragments[:3]}")

        if not messages:
            messages.append("漢字骨架 100% 守恆，樣式合規")

        return CJKValidationResult(
            section_id=section_id,
            section_title=section_title,
            status=status,
            raw_char_count=len(raw_skel),
            processed_char_count=len(proc_skel),
            dropped_fragments=dropped_fragments,
            added_fragments=added_fragments,
            replaced_fragments=replaced_fragments,
            invalid_styles=sorted(list(invalid_styles)),
            message="; ".join(messages),
        )
