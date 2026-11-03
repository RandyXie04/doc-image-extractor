# -*- coding: utf-8 -*-
"""
layout_classifier.py: P1 Layout Classifier Engine (Phase 2)
============================================================
Pure-computation, deterministic layout classification engine for PDF paragraphs.
Ingests reconstructed ParagraphRecord, LineRecord, and PageGeometry objects from Phase 1,
and returns decoupled, immutable ParagraphClassification records.

Key Architecture Principles:
- Pure computation: 0 disk I/O, no network calls, strictly deterministic.
- Immutability: Frozen dataclass output wrapped in MappingProxyType; Phase 1 records unmutated.
- Tier decoupling: ParagraphRecord.text is the semantic truth; LineRecord is read-only for geometry/meter.
- Closed Two-Tier Evidence Registry: Validates primary and secondary diagnostic evidence tokens.
- Strict Type Defense: Rejects Python `bool` masquerading as integer or float.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from types import MappingProxyType
from typing import (
    Dict,
    FrozenSet,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from src.scripts.paragraph_reconstruction import (
    LineRecord,
    PageGeometry,
    ParagraphRecord,
)

SemanticRole = Literal[
    "body",
    "heading_candidate",
    "caption",
    "header",
    "footer",
    "poetry",
    "uncertain",
]
HeadingLevel = Literal[1, 2, 3]
ActiveGroup = Literal["A", "B", "C"]
LineStructureStatus = Literal["verified_single_line", "verified_multiline", "unavailable"]

VALID_ROLES: FrozenSet[str] = frozenset({
    "body",
    "heading_candidate",
    "caption",
    "header",
    "footer",
    "poetry",
    "uncertain",
})

VALID_EVIDENCE_TOKENS: FrozenSet[str] = frozenset({
    # Primary Tokens
    "caption: table_or_figure_prefix",
    "footer: page_number_sequence_valid",
    "footer: page_number_valid_baseline_invalid",
    "footer: recurring_bottom_pattern",
    "header: recurring_top_pattern",
    "poetry: metric_couplet_rhythm_kaiti",
    "heading: level_1_candidate",
    "heading: level_2_candidate",
    "heading: level_3_candidate",
    "body: multiline_prose_flow",
    "body: heading_vetoed_by_period",
    "body: unstyled_single_line",
    "body: unverified_lines_single_line_fallback",
    "uncertain: heading_single_group_quarantine",
    "uncertain: heading_insufficient_score",
    "uncertain: invalid_baseline_quarantine",
    "uncertain: single_page_occurrence",
    "uncertain: isolated_page_number",
    "uncertain: page_level_vertical_conflict",
    "uncertain: broken_page_number_sequence",
    "uncertain: poetry_unresolved_lines",
    "uncertain: poetry_rhythm_without_kaiti_font",
    "uncertain: standalone_question_without_prefix",
    # Secondary Diagnostic Tokens
    "geo: missing_page_geometry",
    "geo: pitch_unverified_missing_lines",
    "geo: spacing_above_dominant",
    "geo: centered_alignment",
    "typo: major_size_delta(+35%)",
    "typo: minor_size_delta(+20%)",
    "typo: bold_weight",
    "typo: title_font_family",
    "lex: chapter_prefix",
    "lex: section_prefix",
    "lex: subsection_prefix",
})

ROLE_PRIMARY_EVIDENCE_MAP: Mapping[str, FrozenSet[str]] = MappingProxyType({
    "caption": frozenset({"caption: table_or_figure_prefix"}),
    "footer": frozenset({
        "footer: page_number_sequence_valid",
        "footer: page_number_valid_baseline_invalid",
        "footer: recurring_bottom_pattern",
    }),
    "header": frozenset({"header: recurring_top_pattern"}),
    "poetry": frozenset({"poetry: metric_couplet_rhythm_kaiti"}),
    "heading_candidate": frozenset({
        "heading: level_1_candidate",
        "heading: level_2_candidate",
        "heading: level_3_candidate",
    }),
    "body": frozenset({
        "body: multiline_prose_flow",
        "body: heading_vetoed_by_period",
        "body: unstyled_single_line",
        "body: unverified_lines_single_line_fallback",
    }),
    "uncertain": frozenset({
        "uncertain: heading_single_group_quarantine",
        "uncertain: heading_insufficient_score",
        "uncertain: invalid_baseline_quarantine",
        "uncertain: single_page_occurrence",
        "uncertain: isolated_page_number",
        "uncertain: page_level_vertical_conflict",
        "uncertain: broken_page_number_sequence",
        "uncertain: poetry_unresolved_lines",
        "uncertain: poetry_rhythm_without_kaiti_font",
        "uncertain: standalone_question_without_prefix",
    }),
})

PRIMARY_CONFIDENCE_MAP: Mapping[str, float] = MappingProxyType({
    "caption: table_or_figure_prefix": 0.95,
    "footer: page_number_sequence_valid": 0.95,
    "footer: page_number_valid_baseline_invalid": 0.85,
    "footer: recurring_bottom_pattern": 0.90,
    "header: recurring_top_pattern": 0.90,
    "poetry: metric_couplet_rhythm_kaiti": 0.85,
    "heading: level_1_candidate": 0.90,
    "heading: level_2_candidate": 0.80,
    "heading: level_3_candidate": 0.80,
    "body: multiline_prose_flow": 0.85,
    "body: heading_vetoed_by_period": 0.85,
    "body: unstyled_single_line": 0.60,
    "body: unverified_lines_single_line_fallback": 0.60,
    "uncertain: heading_single_group_quarantine": 0.40,
    "uncertain: heading_insufficient_score": 0.40,
    "uncertain: invalid_baseline_quarantine": 0.35,
    "uncertain: single_page_occurrence": 0.35,
    "uncertain: isolated_page_number": 0.35,
    "uncertain: page_level_vertical_conflict": 0.35,
    "uncertain: broken_page_number_sequence": 0.35,
    "uncertain: poetry_unresolved_lines": 0.35,
    "uncertain: poetry_rhythm_without_kaiti_font": 0.35,
    "uncertain: standalone_question_without_prefix": 0.35,
})

TITLE_FONT_KEYWORDS = (
    "hei", "黑", "fzht", "fzhei", "simhei", "yahei", "stheiti",
    "fzlt", "fzdbs", "fzxbs", "fzcs", "fzqk", "fzbw", "fzl2", "fzzys",
    "sourcehanserifcn-bold", "title",
)

TITLE_FONT_PATTERNS: FrozenSet[str] = frozenset({
    "heiti", "simhei", "yahei", "fzht", "fzhei", "stheiti", "fzlt", "fzdbs", "fzxbs",
})


@dataclass(frozen=True)
class ParagraphClassification:
    paragraph_id: str
    page_num: int
    semantic_role: SemanticRole
    suggested_heading_level: Optional[HeadingLevel]
    confidence: float
    is_provisional: bool
    evidence: Tuple[str, ...]
    active_groups: Tuple[ActiveGroup, ...]
    score: float

    def __post_init__(self):
        # 1. Identity & Page (excludes bool)
        if type(self.paragraph_id) is not str or not self.paragraph_id.strip():
            raise ValueError(f"Invalid paragraph_id: {self.paragraph_id}")
        if type(self.page_num) is not int or isinstance(self.page_num, bool) or self.page_num < 1:
            raise ValueError(f"page_num must be positive int (non-bool), got {self.page_num}")

        # 2. Roles & Levels
        if type(self.semantic_role) is not str or self.semantic_role not in VALID_ROLES:
            raise ValueError(f"Invalid semantic_role: {self.semantic_role}")
        if self.suggested_heading_level is not None:
            if (
                type(self.suggested_heading_level) is not int
                or isinstance(self.suggested_heading_level, bool)
                or self.suggested_heading_level not in (1, 2, 3)
            ):
                raise ValueError(f"Invalid suggested_heading_level: {self.suggested_heading_level}")

        # Cross-field consistency
        if self.semantic_role == "heading_candidate" and self.suggested_heading_level not in (1, 2, 3):
            raise ValueError(
                f"heading_candidate requires suggested_heading_level in (1, 2, 3), got {self.suggested_heading_level}"
            )
        if self.semantic_role != "heading_candidate" and self.suggested_heading_level is not None:
            raise ValueError(f"Non-heading role {self.semantic_role} must have suggested_heading_level=None")

        # 3. Numeric bounds (strict non-bool finite)
        if (
            type(self.confidence) not in (float, int)
            or isinstance(self.confidence, bool)
            or not math.isfinite(self.confidence)
            or not (0.0 <= self.confidence <= 1.0)
        ):
            raise ValueError(f"confidence must be finite in [0.0, 1.0], got {self.confidence}")
        if (
            type(self.score) not in (float, int)
            or isinstance(self.score, bool)
            or not math.isfinite(self.score)
            or not (0.0 <= self.score <= 1.0)
        ):
            raise ValueError(f"score must be finite in [0.0, 1.0], got {self.score}")
        if type(self.is_provisional) is not bool:
            raise ValueError(f"is_provisional must be bool, got {self.is_provisional}")
        if self.semantic_role == "uncertain" and not self.is_provisional:
            raise ValueError("uncertain role must have is_provisional=True")
        if self.semantic_role != "uncertain" and self.is_provisional:
            raise ValueError(f"Non-uncertain role {self.semantic_role} must have is_provisional=False")

        # 4. Evidence & Groups
        if type(self.evidence) is not tuple or len(self.evidence) == 0:
            raise ValueError(f"evidence must be non-empty Tuple[str, ...], got {self.evidence}")
        for e in self.evidence:
            if type(e) is not str or e not in VALID_EVIDENCE_TOKENS:
                raise ValueError(f"Invalid evidence token: '{e}'")

        primary_token = self.evidence[0]
        valid_primaries = ROLE_PRIMARY_EVIDENCE_MAP[self.semantic_role]
        if primary_token not in valid_primaries:
            raise ValueError(
                f"Primary evidence token '{primary_token}' is not valid for semantic_role '{self.semantic_role}'. "
                f"Allowed: {valid_primaries}"
            )
        if len(set(self.evidence)) != len(self.evidence):
            raise ValueError(f"evidence contains duplicate tokens: {self.evidence}")

        expected_conf = PRIMARY_CONFIDENCE_MAP.get(primary_token)
        if expected_conf is not None and abs(self.confidence - expected_conf) > 1e-4:
            raise ValueError(
                f"confidence {self.confidence} does not match expected {expected_conf} for primary token '{primary_token}'"
            )

        if type(self.active_groups) is not tuple or not all(g in ("A", "B", "C") for g in self.active_groups):
            raise ValueError(f"active_groups must be Tuple[ActiveGroup, ...], got {self.active_groups}")
        if len(set(self.active_groups)) != len(self.active_groups):
            raise ValueError(f"active_groups cannot contain duplicates: {self.active_groups}")
        if list(self.active_groups) != sorted(self.active_groups):
            raise ValueError(f"active_groups must be canonically sorted, got {self.active_groups}")


@dataclass(frozen=True)
class DocumentTypographyBaseline:
    body_font: str
    body_size: float
    standard_line_pitch: float
    is_valid: bool
    rejection_reasons: Tuple[str, ...]


@dataclass(frozen=True)
class DocumentRepetitionContext:
    recurring_top_patterns: Tuple[Tuple[str, float], ...]      # ((normalized_pattern, median_y1), ...)
    recurring_bottom_patterns: Tuple[Tuple[str, float], ...]   # ((normalized_pattern, median_y0), ...)
    page_number_entries: Tuple[Tuple[int, int, str], ...]      # ((page_num, parsed_int, raw_text), ...)
    total_pages_observed: int
    is_multi_page: bool


@dataclass(frozen=True)
class HeadingEvaluation:
    qualified: bool
    suggested_level: Optional[HeadingLevel]
    confidence: float
    primary_evidence: str
    role: SemanticRole

    def __post_init__(self):
        if self.qualified:
            if self.role != "heading_candidate" or self.suggested_level not in (1, 2, 3):
                raise ValueError(f"Qualified heading must have role='heading_candidate' and level in (1, 2, 3), got {self}")
        else:
            if self.suggested_level is not None or self.role not in ("body", "uncertain"):
                raise ValueError(f"Disqualified heading must have level=None and role in ('body', 'uncertain'), got {self}")
        if (
            type(self.confidence) not in (float, int)
            or isinstance(self.confidence, bool)
            or not math.isfinite(self.confidence)
            or not (0.0 <= self.confidence <= 1.0)
        ):
            raise ValueError(f"Invalid confidence: {self.confidence}")


def quantize_font_size(size: float, step: float = 0.25) -> float:
    """Quantize font size into discrete intervals using Decimal step formula."""
    if type(size) not in (float, int) or isinstance(size, bool) or not math.isfinite(size) or size <= 0.0:
        raise ValueError(f"Invalid font size: {size}")
    if type(step) not in (float, int) or isinstance(step, bool) or not math.isfinite(step) or step <= 0.0:
        raise ValueError(f"Invalid quantization step: {step}")
    d = Decimal(str(size))
    s = Decimal(str(step))
    return float((d / s).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * s)


CJK_DIGIT_MAP = {
    '零': 0, '〇': 0,
    '一': 1, '二': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
}


def parse_cjk_or_arabic_numeral(raw: str) -> Optional[int]:
    """
    Parses Arabic digits and CJK numeral representations deterministically.
    Returns Optional[int]. Rejects non-positive integers (val < 1) with None.
    """
    if not raw or not raw.strip():
        return None

    # 1. Strip decorative symbols, whitespace, and leading/trailing markers
    text = re.sub(r'^[·*•\-\—~第\s]+|[·*•\-\—~页頁\s]+$', '', raw.strip())
    if not text:
        return None

    # 2. ASCII digits (strictly [0-9]+; str.isdigit() is banned to reject superscripts)
    if re.fullmatch(r'[0-9]+', text):
        val = int(text)
        return val if val >= 1 else None

    # 3. Positional CJK digits (1 to 4 characters)
    if re.fullmatch(r'[〇零一二三四五六七八九]{1,4}', text):
        val = 0
        for ch in text:
            val = val * 10 + CJK_DIGIT_MAP[ch]
        return val if val >= 1 else None

    # 4. Formal CJK numbers with units (十, 百)
    m = re.fullmatch(r'^(?:([一二三四五六七八九])百)?(?:([一二三四五六七八九]?)十)?(?:[零〇]?([一二三四五六七八九]))?$', text)
    if m:
        hundred_digit, ten_digit, unit_digit = m.group(1), m.group(2), m.group(3)
        has_ten = ('十' in text)
        if not hundred_digit and not has_ten and not unit_digit:
            return None

        val = 0
        if hundred_digit:
            val += CJK_DIGIT_MAP[hundred_digit] * 100
        if has_ten:
            val += (CJK_DIGIT_MAP[ten_digit] if ten_digit else 1) * 10
        if unit_digit:
            val += CJK_DIGIT_MAP[unit_digit]
        return val if val >= 1 else None

    return None


def is_kaiti_font(font_name: str) -> bool:
    """Checks whether a font name indicates KaiTi."""
    fn = font_name.lower().strip()
    return any(k in fn for k in ["kaiti", "kai_ti", "fzkt", "fzkai", "stkaiti", "kai", "楷"])


def is_title_font(font_name: str) -> bool:
    """Checks whether a font name indicates a title/heading font family."""
    fn = font_name.lower().strip()
    return fn in TITLE_FONT_PATTERNS or any(k in fn for k in TITLE_FONT_KEYWORDS)


def clean_line_meter_text(text: str) -> int:
    """Measures physical line length for poetry meter by stripping punctuation and whitespace."""
    cleaned = re.sub(r'[\s\u3000\u2000-\u200b，。？！、；：“”‘’（）《》〈〉【】—…·\-\.,;:!?\'"()\[\]{}]+', '', text)
    return len(cleaned)


def is_valid_poetry_rhythm(line_lengths: Sequence[int]) -> bool:
    """Checks strict 5/7 couplet rhythm for poetry."""
    if not line_lengths or len(line_lengths) < 3:
        return False
    # All 5-character
    if all(l == 5 for l in line_lengths):
        return True
    # All 7-character
    if all(l == 7 for l in line_lengths):
        return True
    # Alternating 5/7 or 7/5 strictly requires >= 4 lines and even count
    if len(line_lengths) >= 4 and len(line_lengths) % 2 == 0:
        if all(line_lengths[i] == (5 if i % 2 == 0 else 7) for i in range(len(line_lengths))):
            return True
        if all(line_lengths[i] == (7 if i % 2 == 0 else 5) for i in range(len(line_lengths))):
            return True
    return False


def get_footer_vertical_tolerance(baseline: DocumentTypographyBaseline) -> float:
    """Calculates decoupled footer vertical clustering tolerance."""
    if baseline.is_valid:
        return max(3.0, baseline.body_size * 0.35)
    return 3.0


def cluster_vertical_candidates(
    candidates: Sequence[ParagraphRecord],
    tolerance: float,
) -> List[List[ParagraphRecord]]:
    """Anchor-based vertical clustering of candidates on a single page."""
    if (
        type(tolerance) not in (float, int)
        or isinstance(tolerance, bool)
        or not math.isfinite(tolerance)
        or tolerance < 0.0
    ):
        raise ValueError(f"tolerance must be finite >= 0.0, got {tolerance}")
    if not candidates:
        return []
    page_nums = {c.page_num for c in candidates}
    if len(page_nums) > 1:
        raise ValueError(f"cluster_vertical_candidates must only receive candidates from single page, got {page_nums}")

    for c in candidates:
        if (
            not math.isfinite(c.bbox[0])
            or not math.isfinite(c.bbox[1])
            or not math.isfinite(c.bbox[2])
            or not math.isfinite(c.bbox[3])
            or c.bbox[2] < c.bbox[0]
            or c.bbox[3] < c.bbox[1]
        ):
            raise ValueError(f"Invalid bounding box coordinates (inverted boundary): {c.bbox}")

    sorted_c = sorted(candidates, key=lambda c: (c.bbox[1], c.bbox[0], c.paragraph_id))
    clusters: List[List[ParagraphRecord]] = [[sorted_c[0]]]
    anchor_y0 = sorted_c[0].bbox[1]
    for c in sorted_c[1:]:
        if c.bbox[1] - anchor_y0 <= tolerance:
            clusters[-1].append(c)
        else:
            clusters.append([c])
            anchor_y0 = c.bbox[1]
    return clusters


def resolve_heading_level(
    lexical_match: Optional[str],
    total_score: float,
) -> Tuple[HeadingLevel, float, str]:
    """Stage B of Heading decision: determines heading level after gate passes."""
    if lexical_match not in (None, "chapter", "section", "subsection"):
        raise ValueError(f"Unknown lexical_match: {lexical_match}")
    if (
        type(total_score) not in (float, int)
        or isinstance(total_score, bool)
        or not math.isfinite(total_score)
        or not (0.65 <= total_score <= 1.0)
    ):
        raise ValueError(f"total_score must be in [0.65, 1.0] for qualified heading, got {total_score}")

    # Priority 1: Lexical Override
    if lexical_match == "chapter":
        return 1, 0.90, "heading: level_1_candidate"
    if lexical_match == "section":
        return 2, 0.80, "heading: level_2_candidate"
    if lexical_match == "subsection":
        return 3, 0.80, "heading: level_3_candidate"

    # Priority 2: Typography Score Fallback
    if total_score >= 0.85:
        return 1, 0.90, "heading: level_1_candidate"
    if total_score >= 0.70:
        return 2, 0.80, "heading: level_2_candidate"
    return 3, 0.80, "heading: level_3_candidate"


def evaluate_heading_candidate(
    para: ParagraphRecord,
    active_groups: Tuple[ActiveGroup, ...],
    total_score: float,
    lexical_match: Optional[str],
    line_status: LineStructureStatus,
) -> HeadingEvaluation:
    """Two-stage pipeline: Gate qualification followed by Level resolution."""
    if (
        type(total_score) not in (float, int)
        or isinstance(total_score, bool)
        or not math.isfinite(total_score)
        or not (0.0 <= total_score <= 1.0)
    ):
        raise ValueError(f"total_score must be finite [0.0, 1.0], got {total_score}")
    if lexical_match not in (None, "chapter", "section", "subsection"):
        raise ValueError(f"Unknown lexical_match: {lexical_match}")
    if line_status not in ("verified_single_line", "verified_multiline", "unavailable"):
        raise ValueError(f"Unknown line_status: {line_status}")

    text = para.text.rstrip()

    # 1. Period veto handling (respects line_status)
    if re.search(r'[。]\s*$', text):
        if line_status == "unavailable":
            return HeadingEvaluation(
                qualified=False,
                suggested_level=None,
                confidence=0.60,
                primary_evidence="body: unverified_lines_single_line_fallback",
                role="body",
            )
        if line_status == "verified_multiline" and len(active_groups) == 0:
            return HeadingEvaluation(
                qualified=False,
                suggested_level=None,
                confidence=0.85,
                primary_evidence="body: multiline_prose_flow",
                role="body",
            )
        return HeadingEvaluation(
            qualified=False,
            suggested_level=None,
            confidence=0.85,
            primary_evidence="body: heading_vetoed_by_period",
            role="body",
        )

    # 2. Question mark check (supports fullwidth ？ and halfwidth ?)
    if re.search(r'[?？]\s*$', text):
        if lexical_match == "chapter":
            pass  # Chapter questions proceed to Gate
        elif line_status == "verified_multiline":
            return HeadingEvaluation(
                qualified=False,
                suggested_level=None,
                confidence=0.85,
                primary_evidence="body: multiline_prose_flow",
                role="body",
            )
        else:
            return HeadingEvaluation(
                qualified=False,
                suggested_level=None,
                confidence=0.35,
                primary_evidence="uncertain: standalone_question_without_prefix",
                role="uncertain",
            )

    # 3. Qualification Gate: requires >= 2 active groups AND total_score >= 0.65
    if len(active_groups) >= 2 and total_score >= 0.65:
        level, conf, ev = resolve_heading_level(lexical_match, total_score)
        return HeadingEvaluation(
            qualified=True,
            suggested_level=level,
            confidence=conf,
            primary_evidence=ev,
            role="heading_candidate",
        )

    # Gate Failed: Differentiate quarantine vs body fallback
    if len(active_groups) >= 2 and total_score < 0.65:
        return HeadingEvaluation(
            qualified=False,
            suggested_level=None,
            confidence=0.40,
            primary_evidence="uncertain: heading_insufficient_score",
            role="uncertain",
        )
    if len(active_groups) == 1 and total_score >= 0.35:
        return HeadingEvaluation(
            qualified=False,
            suggested_level=None,
            confidence=0.40,
            primary_evidence="uncertain: heading_single_group_quarantine",
            role="uncertain",
        )

    # Fall through to body evaluation
    if line_status == "unavailable":
        return HeadingEvaluation(
            qualified=False,
            suggested_level=None,
            confidence=0.60,
            primary_evidence="body: unverified_lines_single_line_fallback",
            role="body",
        )
    is_multi = (line_status == "verified_multiline")
    return HeadingEvaluation(
        qualified=False,
        suggested_level=None,
        confidence=0.85 if is_multi else 0.60,
        primary_evidence="body: multiline_prose_flow" if is_multi else "body: unstyled_single_line",
        role="body",
    )


def build_typography_baseline(
    paragraphs_by_page: Mapping[int, Sequence[ParagraphRecord]],
    lines_by_page: Mapping[int, Sequence[LineRecord]],
    page_geometries: Mapping[int, PageGeometry],
) -> DocumentTypographyBaseline:
    """Computes DocumentTypographyBaseline using 4-stage clean pool."""
    all_paras: List[ParagraphRecord] = []
    for paras in paragraphs_by_page.values():
        all_paras.extend(paras)

    # Stage 1: Geometry Exclusion
    pool_1: List[ParagraphRecord] = []
    for p in all_paras:
        if p.page_num in page_geometries:
            geo = page_geometries[p.page_num]
            if geo.content_top > 0.0 and p.bbox[3] <= geo.content_top:
                continue
            if geo.content_bottom < geo.height and p.bbox[1] >= geo.content_bottom:
                continue
        pool_1.append(p)

    # Stage 2: Semantic Exclusion
    caption_pattern = re.compile(r'^(?i:(?:表|图|圖|Table|Figure))\s*\d+(?:[\-\.]\d+)*(?=[.、:：\s]|$)', re.IGNORECASE)
    chapter_pattern = re.compile(r'^第[一二三四五六七八九十百\d]+[章卷篇]')

    pool_2: List[ParagraphRecord] = []
    for p in pool_1:
        text_clean = p.text.strip()
        if len(text_clean) <= 10:
            continue
        if caption_pattern.match(text_clean):
            continue
        if chapter_pattern.match(text_clean):
            continue
        pool_2.append(p)

    # Stage 3: Font Size Outlier Exclusion
    if not pool_2:
        return DocumentTypographyBaseline(
            body_font="",
            body_size=0.0,
            standard_line_pitch=0.0,
            is_valid=False,
            rejection_reasons=("insufficient_clean_characters",),
        )

    quantized_sizes_map: Dict[str, float] = {
        p.paragraph_id: quantize_font_size(p.dominant_size, 0.25)
        for p in pool_2
    }
    distinct_sizes = sorted(list(set(quantized_sizes_map.values())), reverse=True)
    k = len(distinct_sizes)
    if k >= 4:
        n_excluded = max(1, math.ceil(0.10 * k))
        excluded_sizes = set(distinct_sizes[:n_excluded])
        pool_3 = [p for p in pool_2 if quantized_sizes_map[p.paragraph_id] not in excluded_sizes]
    else:
        pool_3 = pool_2

    # Stage 4: Threshold & Mode Calculation
    total_clean_chars = sum(len(p.text.strip()) for p in pool_3)
    if total_clean_chars < 50:
        return DocumentTypographyBaseline(
            body_font="",
            body_size=0.0,
            standard_line_pitch=0.0,
            is_valid=False,
            rejection_reasons=("insufficient_clean_characters",),
        )

    # Aggregate characters by font
    font_char_counts: Dict[str, int] = {}
    for p in pool_3:
        font_char_counts[p.dominant_font] = font_char_counts.get(p.dominant_font, 0) + len(p.text.strip())
    # Tie-break: alphabetical min
    sorted_fonts = sorted(font_char_counts.keys(), key=lambda f: (-font_char_counts[f], f))
    body_font = sorted_fonts[0]

    # Aggregate characters by size within body_font
    size_char_counts: Dict[float, int] = {}
    for p in pool_3:
        if p.dominant_font == body_font:
            qs = quantized_sizes_map[p.paragraph_id]
            size_char_counts[qs] = size_char_counts.get(qs, 0) + len(p.text.strip())
    # Tie-break: numerical max
    sorted_sizes = sorted(size_char_counts.keys(), key=lambda s: (-size_char_counts[s], -s))
    body_size = sorted_sizes[0]

    # Standard line pitch
    pitches: List[float] = []
    for p in pool_3:
        if p.page_num in lines_by_page:
            page_line_map = {l.line_id: l for l in lines_by_page[p.page_num]}
            if all(lid in page_line_map for lid in p.source_line_ids) and len(p.source_line_ids) >= 2:
                p_lines = [page_line_map[lid] for lid in p.source_line_ids]
                sorted_lines = sorted(p_lines, key=lambda l: (l.bbox[1], l.bbox[0]))
                for i in range(len(sorted_lines) - 1):
                    dy = sorted_lines[i + 1].bbox[1] - sorted_lines[i].bbox[1]
                    if dy > 0.0:
                        pitches.append(dy)

    if pitches:
        standard_line_pitch = round(float(statistics.median(pitches)), 2)
    else:
        standard_line_pitch = round(body_size * 1.4, 2)

    return DocumentTypographyBaseline(
        body_font=body_font,
        body_size=body_size,
        standard_line_pitch=standard_line_pitch,
        is_valid=True,
        rejection_reasons=(),
    )


def build_repetition_context(
    paragraphs_by_page: Mapping[int, Sequence[ParagraphRecord]],
    page_geometries: Mapping[int, PageGeometry],
    baseline: DocumentTypographyBaseline,
) -> DocumentRepetitionContext:
    """Builds DocumentRepetitionContext across observed pages."""
    total_pages_observed = len(paragraphs_by_page)
    is_multi_page = (total_pages_observed >= 2)

    top_candidates_by_page: Dict[str, Dict[int, ParagraphRecord]] = {}
    bottom_candidates_by_page: Dict[str, Dict[int, ParagraphRecord]] = {}

    pitch = baseline.standard_line_pitch if baseline.is_valid else 0.0

    for page_num, paras in paragraphs_by_page.items():
        if page_num not in page_geometries:
            continue
        geo = page_geometries[page_num]
        if geo.content_top < 0.0 or geo.content_bottom <= geo.content_top:
            continue

        # Top boundary threshold
        top_thresh = geo.content_top + 0.5 * pitch if geo.content_top > 0.0 else 0.12 * geo.height
        bottom_thresh = geo.content_bottom - 0.5 * pitch if geo.content_bottom < geo.height else 0.88 * geo.height

        for p in paras:
            # Text normalization
            s = re.sub(r'[\s\u3000]+', '', p.text.lower())
            s = re.sub(r'[\d\-_·*•—\s]+$', '', s)
            if len(s) < 2:
                continue

            # Check Top slot
            if p.bbox[3] <= top_thresh:
                if s not in top_candidates_by_page:
                    top_candidates_by_page[s] = {}
                if page_num not in top_candidates_by_page[s] or p.bbox[1] < top_candidates_by_page[s][page_num].bbox[1]:
                    top_candidates_by_page[s][page_num] = p

            # Check Bottom slot
            if p.bbox[1] >= bottom_thresh:
                if s not in bottom_candidates_by_page:
                    bottom_candidates_by_page[s] = {}
                if page_num not in bottom_candidates_by_page[s] or p.bbox[1] > bottom_candidates_by_page[s][page_num].bbox[1]:
                    bottom_candidates_by_page[s][page_num] = p

    k_repeat = max(2, min(3, math.ceil(0.05 * total_pages_observed)))

    recurring_top: List[Tuple[str, float]] = []
    for pat, pages_dict in top_candidates_by_page.items():
        if len(pages_dict) >= k_repeat:
            med_y1 = float(statistics.median([cand.bbox[3] for cand in pages_dict.values()]))
            recurring_top.append((pat, med_y1))

    recurring_bottom: List[Tuple[str, float]] = []
    for pat, pages_dict in bottom_candidates_by_page.items():
        if len(pages_dict) >= k_repeat:
            med_y0 = float(statistics.median([cand.bbox[1] for cand in pages_dict.values()]))
            recurring_bottom.append((pat, med_y0))

    return DocumentRepetitionContext(
        recurring_top_patterns=tuple(recurring_top),
        recurring_bottom_patterns=tuple(recurring_bottom),
        page_number_entries=(),
        total_pages_observed=total_pages_observed,
        is_multi_page=is_multi_page,
    )


def classify_layout(
    paragraphs_by_page: Mapping[int, Sequence[ParagraphRecord]],
    lines_by_page: Mapping[int, Sequence[LineRecord]],
    page_geometries: Mapping[int, PageGeometry],
) -> Mapping[str, ParagraphClassification]:
    """
    Main entry point for Phase 2 layout classification:
    1. Validates input integrity (rejects duplicates and key mismatches with ValueError).
    2. Internally computes DocumentTypographyBaseline via 4-stage clean pool.
    3. Internally computes DocumentRepetitionContext across observed pages.
    4. Evaluates paragraph roles strictly according to Section 3.1 Precedence Pipeline.
    5. Returns an immutable MappingProxyType mapping paragraph_id -> ParagraphClassification.
    Zero disk I/O; zero mutation on input Phase 1 objects.
    """
    # -------------------------------------------------------------
    # Step 1: Input Integrity & Structural Validation
    # -------------------------------------------------------------
    all_paragraphs: List[ParagraphRecord] = []
    seen_para_ids: Set[str] = set()

    for page_num, paras in paragraphs_by_page.items():
        if type(page_num) is not int or isinstance(page_num, bool) or page_num < 1:
            raise ValueError(f"Mapping key page_num must be positive int (non-bool), got {page_num}")
        for p in paras:
            if p.page_num != page_num:
                raise ValueError(f"Mapping key page_num {page_num} mismatches para.page_num {p.page_num}")
            if p.paragraph_id in seen_para_ids:
                raise ValueError(f"Duplicate paragraph_id detected: {p.paragraph_id}")
            seen_para_ids.add(p.paragraph_id)
            if (
                not math.isfinite(p.bbox[0])
                or not math.isfinite(p.bbox[1])
                or not math.isfinite(p.bbox[2])
                or not math.isfinite(p.bbox[3])
                or p.bbox[2] < p.bbox[0]
                or p.bbox[3] < p.bbox[1]
            ):
                raise ValueError(f"Invalid bounding box coordinates (inverted boundary): {p.bbox}")
            all_paragraphs.append(p)

    for page_num, lines in lines_by_page.items():
        if type(page_num) is not int or isinstance(page_num, bool) or page_num < 1:
            raise ValueError(f"Mapping key page_num must be positive int (non-bool), got {page_num}")
        seen_line_ids: Set[str] = set()
        for l in lines:
            if l.page_num != page_num:
                raise ValueError(f"Mapping key page_num {page_num} mismatches line.page_num {l.page_num}")
            if l.line_id in seen_line_ids:
                raise ValueError(f"Duplicate line_id detected on page {page_num}: {l.line_id}")
            seen_line_ids.add(l.line_id)
            if (
                not math.isfinite(l.bbox[0])
                or not math.isfinite(l.bbox[1])
                or not math.isfinite(l.bbox[2])
                or not math.isfinite(l.bbox[3])
                or l.bbox[2] < l.bbox[0]
                or l.bbox[3] < l.bbox[1]
            ):
                raise ValueError(f"Invalid bounding box coordinates (inverted boundary): {l.bbox}")

    for page_num, geo in page_geometries.items():
        if type(page_num) is not int or isinstance(page_num, bool) or page_num < 1:
            raise ValueError(f"Mapping key page_num must be positive int (non-bool), got {page_num}")
        if (
            not math.isfinite(geo.width)
            or not math.isfinite(geo.height)
            or not math.isfinite(geo.base_x0)
            or not math.isfinite(geo.max_x1)
            or not math.isfinite(geo.content_top)
            or not math.isfinite(geo.content_bottom)
            or geo.max_x1 < geo.base_x0
            or geo.content_bottom < geo.content_top
        ):
            raise ValueError(f"Invalid page geometry coordinates: {geo}")

    # -------------------------------------------------------------
    # Step 2: Build Typography Baseline & Repetition Context
    # -------------------------------------------------------------
    baseline = build_typography_baseline(paragraphs_by_page, lines_by_page, page_geometries)
    drc = build_repetition_context(paragraphs_by_page, page_geometries, baseline)

    # -------------------------------------------------------------
    # Step 3: Pre-Evaluate Footer Page-Number Sequence Pipeline
    # -------------------------------------------------------------
    footer_tolerance = get_footer_vertical_tolerance(baseline)
    footer_candidates_by_page: Dict[int, List[ParagraphRecord]] = {}

    for p in all_paragraphs:
        if p.page_num not in page_geometries:
            continue
        geo = page_geometries[p.page_num]
        pitch = baseline.standard_line_pitch if baseline.is_valid else 0.0
        bottom_thresh = geo.content_bottom - 0.5 * pitch if geo.content_bottom < geo.height else 0.88 * geo.height
        if p.bbox[1] >= bottom_thresh:
            num = parse_cjk_or_arabic_numeral(p.text)
            if num is not None:
                if p.page_num not in footer_candidates_by_page:
                    footer_candidates_by_page[p.page_num] = []
                footer_candidates_by_page[p.page_num].append(p)

    # Evaluate clusters on each page
    page_resolved_numbers: Dict[int, Tuple[int, ParagraphRecord]] = {}
    quarantined_footer_paras: Dict[str, Tuple[str, float]] = {}

    for page_num, cands in footer_candidates_by_page.items():
        clusters = cluster_vertical_candidates(cands, footer_tolerance)
        page_has_vertical_conflict = False
        for cl in clusters:
            distinct_vals = {parse_cjk_or_arabic_numeral(c.text) for c in cl}
            if len(distinct_vals) > 1:
                page_has_vertical_conflict = True
                break

        if page_has_vertical_conflict:
            for c in cands:
                quarantined_footer_paras[c.paragraph_id] = ("uncertain: page_level_vertical_conflict", 0.35)
        else:
            # Check if candidates across clusters have multiple distinct values
            all_page_distinct = {parse_cjk_or_arabic_numeral(c.text) for c in cands}
            if len(all_page_distinct) > 1:
                for c in cands:
                    quarantined_footer_paras[c.paragraph_id] = ("uncertain: page_level_vertical_conflict", 0.35)
            elif len(all_page_distinct) == 1:
                # Exactly 1 resolved numeral value for this page
                val = list(all_page_distinct)[0]
                assert val is not None
                # Choose the bottommost / most prominent candidate
                chosen_cand = sorted(cands, key=lambda c: (-c.bbox[1], c.bbox[0]))[0]
                page_resolved_numbers[page_num] = (val, chosen_cand)

    # Monotonic Sequence Validation
    sorted_pages = sorted(page_resolved_numbers.keys())
    m = len(sorted_pages)
    valid_footer_para_ids: Set[str] = set()

    if m < 2:
        if drc.is_multi_page:
            for p_num in sorted_pages:
                _, cand = page_resolved_numbers[p_num]
                quarantined_footer_paras[cand.paragraph_id] = ("uncertain: isolated_page_number", 0.35)
        else:
            for p_num in sorted_pages:
                _, cand = page_resolved_numbers[p_num]
                quarantined_footer_paras[cand.paragraph_id] = ("uncertain: single_page_occurrence", 0.35)
    else:
        # Check monotonicity across all adjacent pairs
        sequence_broken = False
        for i in range(m - 1):
            p_curr = sorted_pages[i]
            p_next = sorted_pages[i + 1]
            v_curr = page_resolved_numbers[p_curr][0]
            v_next = page_resolved_numbers[p_next][0]
            delta_val = v_next - v_curr
            delta_page = p_next - p_curr
            if not (1 <= delta_val <= delta_page):
                sequence_broken = True
                break

        if sequence_broken:
            for p_num in sorted_pages:
                _, cand = page_resolved_numbers[p_num]
                quarantined_footer_paras[cand.paragraph_id] = ("uncertain: broken_page_number_sequence", 0.35)
        else:
            for p_num in sorted_pages:
                _, cand = page_resolved_numbers[p_num]
                valid_footer_para_ids.add(cand.paragraph_id)

    # -------------------------------------------------------------
    # Step 4: Classify Every Paragraph (Section 3.1 Precedence Pipeline)
    # -------------------------------------------------------------
    caption_regex = re.compile(r'^(?i:(?:表|图|圖|Table|Figure))\s*\d+(?:[\-\.]\d+)*(?=[.、:：\s]|$)', re.IGNORECASE)
    results: Dict[str, ParagraphClassification] = {}

    for page_num, paras in paragraphs_by_page.items():
        geo = page_geometries.get(page_num)
        page_lines = lines_by_page.get(page_num, ())
        line_map = {l.line_id: l for l in page_lines}

        # Pre-sort paragraphs on page by (y0, x0)
        sorted_paras = sorted(paras, key=lambda p: (p.bbox[1], p.bbox[0]))
        para_index_map = {p.paragraph_id: idx for idx, p in enumerate(sorted_paras)}

        for para in paras:
            idx = para_index_map[para.paragraph_id]
            prev_para = sorted_paras[idx - 1] if idx > 0 else None
            next_para = sorted_paras[idx + 1] if idx < len(sorted_paras) - 1 else None

            # Spacings (rejects -1.0 sentinels at page boundaries)
            spacing_above = (para.bbox[1] - prev_para.bbox[3]) if prev_para is not None else -1.0
            spacing_below = (next_para.bbox[1] - para.bbox[3]) if next_para is not None else -1.0

            # Line structure status
            if page_num not in lines_by_page:
                line_status: LineStructureStatus = "unavailable"
                lines_fully_resolved = False
                resolved_lines: List[LineRecord] = []
            else:
                if all(lid in line_map for lid in para.source_line_ids):
                    lines_fully_resolved = True
                    resolved_lines = [line_map[lid] for lid in para.source_line_ids]
                    line_status = "verified_multiline" if len(resolved_lines) >= 2 else "verified_single_line"
                else:
                    lines_fully_resolved = False
                    resolved_lines = []
                    line_status = "unavailable"

            # Precedence 1: Caption Regex
            clean_text = para.text.strip()
            if caption_regex.match(clean_text) and len(clean_text) <= 60:
                results[para.paragraph_id] = ParagraphClassification(
                    paragraph_id=para.paragraph_id,
                    page_num=page_num,
                    semantic_role="caption",
                    suggested_heading_level=None,
                    confidence=0.95,
                    is_provisional=False,
                    evidence=("caption: table_or_figure_prefix",),
                    active_groups=(),
                    score=0.0,
                )
                continue

            # Precedence 2: Bottom Region + Page-Num Pipeline
            if para.paragraph_id in valid_footer_para_ids:
                if baseline.is_valid:
                    ev_token = "footer: page_number_sequence_valid"
                    conf = 0.95
                else:
                    ev_token = "footer: page_number_valid_baseline_invalid"
                    conf = 0.85
                results[para.paragraph_id] = ParagraphClassification(
                    paragraph_id=para.paragraph_id,
                    page_num=page_num,
                    semantic_role="footer",
                    suggested_heading_level=None,
                    confidence=conf,
                    is_provisional=False,
                    evidence=(ev_token,),
                    active_groups=(),
                    score=0.0,
                )
                continue

            # Quarantined footer candidates
            if para.paragraph_id in quarantined_footer_paras:
                ev_token, conf = quarantined_footer_paras[para.paragraph_id]
                results[para.paragraph_id] = ParagraphClassification(
                    paragraph_id=para.paragraph_id,
                    page_num=page_num,
                    semantic_role="uncertain",
                    suggested_heading_level=None,
                    confidence=conf,
                    is_provisional=True,
                    evidence=(ev_token,),
                    active_groups=(),
                    score=0.0,
                )
                continue

            # Check single-page header/footer restriction (LC-10)
            if not drc.is_multi_page and geo is not None:
                pitch = baseline.standard_line_pitch if baseline.is_valid else 0.0
                top_thresh = geo.content_top + 0.5 * pitch if geo.content_top > 0.0 else 0.12 * geo.height
                bottom_thresh = geo.content_bottom - 0.5 * pitch if geo.content_bottom < geo.height else 0.88 * geo.height
                if para.bbox[3] <= top_thresh or para.bbox[1] >= bottom_thresh:
                    results[para.paragraph_id] = ParagraphClassification(
                        paragraph_id=para.paragraph_id,
                        page_num=page_num,
                        semantic_role="uncertain",
                        suggested_heading_level=None,
                        confidence=0.35,
                        is_provisional=True,
                        evidence=("uncertain: single_page_occurrence",),
                        active_groups=(),
                        score=0.0,
                    )
                    continue

            # Precedence 3 & 4: Recurring Header / Footer from DRC (baseline valid)
            if baseline.is_valid and geo is not None:
                s_norm = re.sub(r'[\s\u3000]+', '', para.text.lower())
                s_norm = re.sub(r'[\d\-_·*•—\s]+$', '', s_norm)
                matched_header = False
                matched_footer = False

                for pat, med_y1 in drc.recurring_top_patterns:
                    tol = max(12.0, 0.02 * geo.height)
                    if s_norm == pat and abs(para.bbox[3] - med_y1) <= tol:
                        matched_header = True
                        break

                if matched_header:
                    results[para.paragraph_id] = ParagraphClassification(
                        paragraph_id=para.paragraph_id,
                        page_num=page_num,
                        semantic_role="header",
                        suggested_heading_level=None,
                        confidence=0.90,
                        is_provisional=False,
                        evidence=("header: recurring_top_pattern",),
                        active_groups=(),
                        score=0.0,
                    )
                    continue

                for pat, med_y0 in drc.recurring_bottom_patterns:
                    tol = max(12.0, 0.02 * geo.height)
                    if s_norm == pat and abs(para.bbox[1] - med_y0) <= tol:
                        matched_footer = True
                        break

                if matched_footer:
                    results[para.paragraph_id] = ParagraphClassification(
                        paragraph_id=para.paragraph_id,
                        page_num=page_num,
                        semantic_role="footer",
                        suggested_heading_level=None,
                        confidence=0.90,
                        is_provisional=False,
                        evidence=("footer: recurring_bottom_pattern",),
                        active_groups=(),
                        score=0.0,
                    )
                    continue

            # Precedence 5: Strict Poetry Pattern
            is_kaiti = is_kaiti_font(para.dominant_font)
            if is_kaiti and len(para.source_line_ids) >= 3:
                if not lines_fully_resolved:
                    results[para.paragraph_id] = ParagraphClassification(
                        paragraph_id=para.paragraph_id,
                        page_num=page_num,
                        semantic_role="uncertain",
                        suggested_heading_level=None,
                        confidence=0.35,
                        is_provisional=True,
                        evidence=("uncertain: poetry_unresolved_lines",),
                        active_groups=(),
                        score=0.0,
                    )
                    continue

                meter_lengths = tuple(clean_line_meter_text(l.text) for l in resolved_lines)
                if is_valid_poetry_rhythm(meter_lengths):
                    results[para.paragraph_id] = ParagraphClassification(
                        paragraph_id=para.paragraph_id,
                        page_num=page_num,
                        semantic_role="poetry",
                        suggested_heading_level=None,
                        confidence=0.85,
                        is_provisional=False,
                        evidence=("poetry: metric_couplet_rhythm_kaiti",),
                        active_groups=(),
                        score=0.0,
                    )
                    continue
                else:
                    # KaiTi block with >= 3 lines failing poetry meter is deferred to P3
                    results[para.paragraph_id] = ParagraphClassification(
                        paragraph_id=para.paragraph_id,
                        page_num=page_num,
                        semantic_role="uncertain",
                        suggested_heading_level=None,
                        confidence=0.35,
                        is_provisional=True,
                        evidence=("uncertain: poetry_unresolved_lines",),
                        active_groups=(),
                        score=0.0,
                    )
                    continue

            if not is_kaiti and lines_fully_resolved and len(resolved_lines) >= 3:
                meter_lengths = tuple(clean_line_meter_text(l.text) for l in resolved_lines)
                if is_valid_poetry_rhythm(meter_lengths):
                    # Rhythm present, but non-KaiTi font
                    results[para.paragraph_id] = ParagraphClassification(
                        paragraph_id=para.paragraph_id,
                        page_num=page_num,
                        semantic_role="uncertain",
                        suggested_heading_level=None,
                        confidence=0.35,
                        is_provisional=True,
                        evidence=("uncertain: poetry_rhythm_without_kaiti_font",),
                        active_groups=(),
                        score=0.0,
                    )
                    continue

            # Precedence 6: Baseline Validity Gate
            if not baseline.is_valid:
                # Under invalid baseline: check multiline prose ending in period
                if line_status == "verified_multiline" and re.search(r'[。]\s*$', para.text.rstrip()):
                    results[para.paragraph_id] = ParagraphClassification(
                        paragraph_id=para.paragraph_id,
                        page_num=page_num,
                        semantic_role="body",
                        suggested_heading_level=None,
                        confidence=0.85,
                        is_provisional=False,
                        evidence=("body: multiline_prose_flow",),
                        active_groups=(),
                        score=0.0,
                    )
                else:
                    results[para.paragraph_id] = ParagraphClassification(
                        paragraph_id=para.paragraph_id,
                        page_num=page_num,
                        semantic_role="uncertain",
                        suggested_heading_level=None,
                        confidence=0.35,
                        is_provisional=True,
                        evidence=("uncertain: invalid_baseline_quarantine",),
                        active_groups=(),
                        score=0.0,
                    )
                continue

            # -------------------------------------------------------------
            # Heading & Body Decision (Baseline Valid)
            # -------------------------------------------------------------
            score_A = 0.0
            score_B = 0.0
            score_C = 0.0
            secondary_tokens: List[str] = []

            # Group A: Typography
            quantized_size = quantize_font_size(para.dominant_size, 0.25)
            if quantized_size >= baseline.body_size * 1.25:
                score_A += 0.35
                secondary_tokens.append("typo: major_size_delta(+35%)")
            elif quantized_size >= baseline.body_size * 1.12:
                score_A += 0.20
                secondary_tokens.append("typo: minor_size_delta(+20%)")

            if para.bold_ratio >= 0.70:
                score_A += 0.20
                secondary_tokens.append("typo: bold_weight")

            if is_title_font(para.dominant_font) and para.dominant_font.lower() != baseline.body_font.lower():
                score_A += 0.20
                secondary_tokens.append("typo: title_font_family")
            score_A = min(score_A, 0.45)

            # Group B: Geometry
            if (
                spacing_above >= 0.0
                and spacing_below >= 0.0
                and spacing_above >= spacing_below * 1.30
                and baseline.is_valid
                and lines_fully_resolved
                and spacing_above >= baseline.standard_line_pitch * 1.25
            ):
                score_B += 0.25
                secondary_tokens.append("geo: spacing_above_dominant")

            page_width = geo.width if geo is not None else 0.0
            center_x = (para.bbox[0] + para.bbox[2]) / 2.0
            if page_width > 0.0 and abs(center_x - (page_width / 2.0)) <= page_width * 0.08:
                score_B += 0.20
                secondary_tokens.append("geo: centered_alignment")
            score_B = min(score_B, 0.35)

            # Diagnostic tokens for missing data
            if geo is None:
                secondary_tokens.append("geo: missing_page_geometry")
            elif not lines_fully_resolved:
                secondary_tokens.append("geo: pitch_unverified_missing_lines")

            # Group C: Lexical Prefixes
            lexical_match: Optional[str] = None
            if re.match(r'^(?:第[一二三四五六七八九十百\d]+[章卷篇]|Chapter\s*\d+)', clean_text):
                score_C = 0.35
                lexical_match = "chapter"
                secondary_tokens.append("lex: chapter_prefix")
            elif re.match(r'^(?:第[一二三四五六七八九十百\d]+[节節講讲]|\d+\.\d+(?!\.))', clean_text):
                score_C = 0.30
                lexical_match = "section"
                secondary_tokens.append("lex: section_prefix")
            elif re.match(r'^(?:[一二三四五六七八九十]+[、\s]|\d+\.\d+\.\d+)', clean_text):
                score_C = 0.25
                lexical_match = "subsection"
                secondary_tokens.append("lex: subsection_prefix")
            score_C = min(score_C, 0.35)

            total_score = min(1.0, score_A + score_B + score_C)
            active_groups_list: List[ActiveGroup] = []
            if score_A > 0.0:
                active_groups_list.append("A")
            if score_B > 0.0:
                active_groups_list.append("B")
            if score_C > 0.0:
                active_groups_list.append("C")
            active_groups: Tuple[ActiveGroup, ...] = tuple(active_groups_list)

            heading_eval = evaluate_heading_candidate(
                para=para,
                active_groups=active_groups,
                total_score=total_score,
                lexical_match=lexical_match,
                line_status=line_status,
            )

            # Assemble canonical evidence: primary token first, then sorted secondary diagnostic tokens
            primary_ev = heading_eval.primary_evidence
            sec_ev = [tok for tok in secondary_tokens if tok != primary_ev and tok in VALID_EVIDENCE_TOKENS]
            full_evidence = (primary_ev, *sec_ev)

            # Deduplicate while preserving primary token first
            dedup_ev: List[str] = [full_evidence[0]]
            for tok in full_evidence[1:]:
                if tok not in dedup_ev:
                    dedup_ev.append(tok)

            results[para.paragraph_id] = ParagraphClassification(
                paragraph_id=para.paragraph_id,
                page_num=page_num,
                semantic_role=heading_eval.role,
                suggested_heading_level=heading_eval.suggested_level,
                confidence=heading_eval.confidence,
                is_provisional=(heading_eval.role == "uncertain"),
                evidence=tuple(dedup_ev),
                active_groups=active_groups,
                score=total_score,
            )

    return MappingProxyType(results)
