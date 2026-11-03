# -*- coding: utf-8 -*-
"""
paragraph_reconstruction.py: PDF Paragraph Reconstruction Module (Phase 1.2)
=============================================================================
Pure-computation, deterministic module for reconstructing semantic paragraphs
from raw PDF physical lines and text spans.

Key Principles & Contracts:
- Multi-feature BoundaryEvidence (reasons recorded for both split and merge decisions)
- Structural isolation: Identifies standalone_block_candidate; NO heading semantics assigned
- Invariants: Font change alone, terminal punct alone, or short length alone NEVER forces a break
- Non-destructive text reconstruction:
  - CJK character/punctuation boundaries join without inserting ASCII space
  - Hyphenated words (e.g. well-known, HLA-B27) retain original hyphens without dehyphenation
- Character-weighted typography statistics (dominant font, dominant size, bold ratio)
- Single-Column Contract:
  - Assumes input lines belong to a single-column reading stream per page.
  - Sorted deterministically by (bbox[1], bbox[0]).
  - Multi-column de-interleaving is explicitly out of scope and deferred to Phase 6.
- Cross-Page Continuation:
  - continuation_confidence is a heuristic score, NOT a calibrated statistical probability.
  - Page-local scope: does NOT merge across pages; records explainable positive/negative evidence.
"""

from __future__ import annotations
import re
import statistics
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Sequence, Dict, Any


# ── Data Contracts ────────────────────────────────────────────────────────────

@dataclass
class SpanRecord:
    """Represents an atomic styled text snippet from PDF."""
    text: str
    bbox: Tuple[float, float, float, float]
    font_family: str
    font_size: float
    font_flags: int = 0  # 16 = bold, 2 = italic


@dataclass
class LineRecord:
    """Represents a physical line of text in PDF."""
    line_id: str
    page_num: int
    text: str
    bbox: Tuple[float, float, float, float]
    spans: List[SpanRecord] = field(default_factory=list)
    block_id: str = ""
    line_order: int = 0


@dataclass
class PageGeometry:
    """Page layout dimensions and effective content boundaries."""
    width: float
    height: float
    base_x0: float
    max_x1: float
    content_top: float = 0.0
    content_bottom: float = 0.0

    def __post_init__(self):
        if self.content_bottom == 0.0:
            self.content_bottom = self.height


@dataclass
class BoundaryEvidence:
    """Diagnostic evidence for an adjacent-line boundary decision."""
    should_break: bool
    confidence: float
    vertical_gap_ratio: float
    indentation_delta: float
    terminal_punctuation: bool
    unclosed_delimiter: bool
    font_variation_only: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class ParagraphRecord:
    """Represents a reconstructed semantic paragraph."""
    paragraph_id: str
    page_num: int
    text: str
    source_line_ids: List[str]
    bbox: Tuple[float, float, float, float]
    dominant_font: str
    dominant_size: float
    bold_ratio: float
    paragraph_boundary_before: bool = False
    continuation_from_previous: bool = False
    continuation_to_next: bool = False
    # Note: continuation_confidence is a heuristic score, NOT a calibrated statistical probability.
    continuation_confidence: float = 0.0
    continuation_evidence: List[str] = field(default_factory=list)
    # Structural role (purely structural, never semantic heading in Phase 1)
    is_standalone_block: bool = False
    semantic_role: str = "uncertain"
    heading_level: Optional[int] = None
    confidence: float = 0.0
    evidence: List[BoundaryEvidence] = field(default_factory=list)
    target_docx_style: Optional[str] = None


# ── Delimiter & Punctuation Tracking ──────────────────────────────────────────

_OPEN_CLOSE_PAIRS: Dict[str, str] = {
    '《': '》',
    '〈': '〉',
    '（': '）',
    '(': ')',
    '“': '”',
    '‘': '’',
    '【': '】',
    '[': ']',
    '「': '」',
    '『': '』',
    '{': '}',
}
_OPEN_DELIMS = set(_OPEN_CLOSE_PAIRS.keys())
_CLOSE_DELIMS = set(_OPEN_CLOSE_PAIRS.values())
_REVERSE_PAIRS = {v: k for k, v in _OPEN_CLOSE_PAIRS.items()}

# Exact CJK ideographs and fullwidth/halfwidth punctuation regex
_CJK_CHAR_RE = re.compile(
    r"[\u3400-\u4DBF"
    r"\u4E00-\u9FFF"
    r"\uF900-\uFAFF"
    r"\u3000-\u303F"
    r"\uFF01-\uFF60"
    r"\uFFE0-\uFFEE"
    r"\u2018-\u201F]"
)

_TERMINAL_PUNCT_RE = re.compile(r'[。！？；!?;][”’"\'）\)\]】」』]*$')
_CLAUSE_CONTINUING_PUNCT_RE = re.compile(r'[，、：:,]$')


def update_delimiter_stack(text: str, current_stack: Optional[List[str]] = None) -> List[str]:
    """Updates and returns a stack of unclosed paired delimiters."""
    stack = list(current_stack or [])
    for ch in text:
        if ch in _OPEN_DELIMS:
            stack.append(ch)
        elif ch in _CLOSE_DELIMS:
            expected_open = _REVERSE_PAIRS.get(ch)
            if stack and stack[-1] == expected_open:
                stack.pop()
            elif expected_open in stack:
                idx = len(stack) - 1 - stack[::-1].index(expected_open)
                stack = stack[:idx]
    return stack


def has_terminal_punctuation(text: str) -> bool:
    """Checks if text ends with a sentence-terminal punctuation mark."""
    stripped = text.strip()
    return bool(_TERMINAL_PUNCT_RE.search(stripped))


def has_clause_continuing_punctuation(text: str) -> bool:
    """Checks if text ends with a comma, enumeration pause, or colon."""
    stripped = text.strip()
    return bool(_CLAUSE_CONTINUING_PUNCT_RE.search(stripped))


def is_cjk_boundary_character(ch: str) -> bool:
    """Returns True if character is within defined CJK ideograph or punctuation ranges."""
    if not ch:
        return False
    return bool(_CJK_CHAR_RE.search(ch))


# ── Typography & Geometry Computations ────────────────────────────────────────

def compute_character_weighted_typography(
    lines: Sequence[LineRecord],
    fallback_font: str = "SimSun",
    fallback_size: float = 10.5,
) -> Tuple[str, float, float]:
    """
    Computes character-weighted typography statistics across all spans in lines:
    - dominant_font: font covering the highest number of characters
    - dominant_size: size covering the highest number of characters (rounded to 0.5pt)
    - bold_ratio: (bold characters) / (total characters)
    """
    font_char_counts: Dict[str, int] = {}
    size_char_counts: Dict[float, int] = {}
    total_chars = 0
    bold_chars = 0

    for line in lines:
        for span in line.spans:
            txt_len = len(span.text.strip())
            if txt_len == 0:
                continue
            total_chars += txt_len

            fn = span.font_family.strip() or fallback_font
            font_char_counts[fn] = font_char_counts.get(fn, 0) + txt_len

            sz = round(span.font_size * 2) / 2
            size_char_counts[sz] = size_char_counts.get(sz, 0) + txt_len

            fn_lower = fn.lower()
            is_bold = (
                (span.font_flags & 16 != 0)
                or any(k in fn_lower for k in ["bold", "heavy", "hei", "黑"])
            )
            if is_bold:
                bold_chars += txt_len

    if total_chars == 0:
        return fallback_font, fallback_size, 0.0

    dominant_font = max(font_char_counts.items(), key=lambda item: item[1])[0]
    dominant_size = max(size_char_counts.items(), key=lambda item: item[1])[0]
    bold_ratio = round(bold_chars / total_chars, 4)

    return dominant_font, dominant_size, bold_ratio


def union_line_bboxes(lines: Sequence[LineRecord]) -> Tuple[float, float, float, float]:
    """Computes bounding box union for a group of lines."""
    valid_boxes = [ln.bbox for ln in lines if ln.bbox and len(ln.bbox) == 4]
    if not valid_boxes:
        return (0.0, 0.0, 0.0, 0.0)
    x0 = min(b[0] for b in valid_boxes)
    y0 = min(b[1] for b in valid_boxes)
    x1 = max(b[2] for b in valid_boxes)
    y1 = max(b[3] for b in valid_boxes)
    return (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))


def join_line_texts(lines: Sequence[LineRecord]) -> str:
    """
    Joins line texts smoothly without destructive modifications:
    - Never inserts space when either boundary character is CJK (character or punctuation)
    - Preserves trailing hyphen without stripping (e.g. 'well-' + 'known' -> 'well-known')
    - Inserts single space between distinct Latin/numeric words
    """
    out = ""
    for ln in lines:
        t = ln.text.strip()
        if not t:
            continue
        if not out:
            out = t
            continue

        prev_char = out[-1]
        next_char = t[0]

        # 1. Trailing hyphen: preserve hyphen and join directly without inserting extra space
        if out.endswith("-"):
            out += t
            continue

        # 2. CJK boundary: If either preceding end or current start is CJK, do NOT insert space
        if is_cjk_boundary_character(prev_char) or is_cjk_boundary_character(next_char):
            out += t
        else:
            # 3. Pure Latin/Numeric boundary: insert single space
            out += " " + t
    return out


def compute_standard_pitch(
    lines: Sequence[LineRecord],
    fallback_pitch: float = 18.0,
) -> float:
    """
    Derives standard line pitch using median of positive vertical shifts
    between consecutive lines in identical or adjacent blocks.
    """
    shifts: List[float] = []
    for i in range(len(lines) - 1):
        curr_y0 = lines[i].bbox[1]
        next_y0 = lines[i + 1].bbox[1]
        diff = next_y0 - curr_y0
        if 8.0 <= diff <= 45.0:
            shifts.append(diff)
    if not shifts:
        return fallback_pitch
    return float(statistics.median(shifts))


# ── Boundary Decision Algorithm ───────────────────────────────────────────────

def calculate_boundary_evidence(
    prev_line: LineRecord,
    curr_line: LineRecord,
    page_geo: PageGeometry,
    standard_pitch: float,
    unclosed_stack: Sequence[str],
) -> BoundaryEvidence:
    """
    Evaluates composite boundary evidence between prev_line and curr_line.
    Records reasons for both split and merge decisions.

    Invariants Enforced:
    1. Font variation alone NEVER creates a paragraph break.
    2. Terminal punctuation alone NEVER creates a paragraph break.
    3. Short text length alone NEVER creates a paragraph break.
    4. Unclosed delimiters provide strong continuation evidence.
    5. Pure structural evidence: Does NOT assign heading semantics.
    """
    reasons: List[str] = []

    # 1. Geometric measurements
    y_gap = curr_line.bbox[1] - prev_line.bbox[3]
    pitch = curr_line.bbox[1] - prev_line.bbox[1]
    gap_ratio = round(pitch / max(standard_pitch, 1.0), 3)

    indent_delta = round(curr_line.bbox[0] - prev_line.bbox[0], 2)
    curr_indent = round(curr_line.bbox[0] - page_geo.base_x0, 2)

    # Check if lines are horizontally adjacent on the same line (|y diff| < 4pt)
    is_same_horizontal_line = abs(pitch) < 4.0 and curr_line.bbox[0] >= prev_line.bbox[0]

    # 2. Linguistic features
    has_term_punct = has_terminal_punctuation(prev_line.text)
    has_clause_punct = has_clause_continuing_punctuation(prev_line.text)
    has_unclosed = len(unclosed_stack) > 0

    # 3. Typography variations
    prev_font, prev_size, _ = compute_character_weighted_typography([prev_line])
    curr_font, curr_size, _ = compute_character_weighted_typography([curr_line])
    font_diff = (prev_font != curr_font)
    size_diff = abs(prev_size - curr_size) >= 1.5

    # 4. Line length & Margin features
    prev_is_short = (prev_line.bbox[2] < page_geo.max_x1 - max(20.0, prev_size * 2.0))
    curr_has_first_line_indent = (curr_indent >= max(10.0, curr_size * 1.4))
    large_vertical_gap = (gap_ratio >= 1.45 or y_gap >= prev_size * 0.9)

    # ── Evidence Collection ───────────────────────────────────────────────────

    if is_same_horizontal_line:
        reasons.append("MERGE: horizontally adjacent fragments on identical line")

    if has_unclosed:
        reasons.append(f"CONTINUE: unclosed_delimiter({','.join(unclosed_stack)})")

    if font_diff or size_diff:
        reasons.append(f"TYPO_CHANGE: font({prev_font}->{curr_font}), size({prev_size}->{curr_size})")

    # Standalone block candidate check on prev_line (structural boundary, NOT heading semantics):
    # Must NOT end with clause continuing punct (，、：), must be short, and have vertical gap or explicit prefix/size
    prev_clean = prev_line.text.strip()
    is_standalone_block_candidate = (
        not is_same_horizontal_line
        and len(prev_clean) <= 30
        and not has_term_punct
        and not has_clause_punct
        and prev_is_short
        and not re.search(r'[的了在和与]$', prev_clean)
        and (size_diff or large_vertical_gap or prev_clean.startswith(('第', '一', '二', '三', '四', '1', '2', '3', '附录')))
    )

    # Decision Matrix
    should_break = False
    confidence = 0.5
    font_variation_only = False

    # Scenario 0: Same physical line horizontally
    if is_same_horizontal_line:
        should_break = False
        confidence = 0.99
        font_variation_only = font_diff or size_diff

    # Scenario A: Unclosed delimiter strongly favors merge unless explicit standalone block
    elif has_unclosed and not is_standalone_block_candidate:
        should_break = False
        confidence = 0.95
        reasons.append("MERGE: unclosed delimiter overrides regular breaks")

    # Scenario B: Standalone short block preceding content
    elif is_standalone_block_candidate and not has_unclosed:
        should_break = True
        confidence = 0.92
        reasons.append("BREAK: standalone_block_preceding_content")

    # Scenario C: Indented start of new paragraph
    elif curr_has_first_line_indent and (has_term_punct or prev_is_short or large_vertical_gap):
        should_break = True
        confidence = 0.94
        reasons.append(f"BREAK: first_line_indent({curr_indent}pt) with prior terminal/gap")

    # Scenario D: Flush-left layout separated by vertical gap (空行/段前距)
    elif large_vertical_gap and not has_unclosed:
        should_break = True
        confidence = 0.88
        reasons.append(f"BREAK: vertical_gap_ratio({gap_ratio} >= 1.45) in unindented flow")

    # Scenario E: Prior line was short line + terminal punctuation
    elif prev_is_short and has_term_punct:
        should_break = True
        confidence = 0.85
        reasons.append("BREAK: short line terminating sentence before next line")

    # Scenario F: Font variation occurred mid-stream without structural break
    elif (font_diff or size_diff) and not (large_vertical_gap or curr_has_first_line_indent):
        should_break = False
        font_variation_only = True
        confidence = 0.90
        reasons.append("MERGE: font/style variation alone invariant enforced")

    # Scenario G: Standard mid-paragraph flow
    else:
        should_break = False
        confidence = 0.80
        reasons.append("MERGE: regular intra-paragraph line progression")

    return BoundaryEvidence(
        should_break=should_break,
        confidence=confidence,
        vertical_gap_ratio=gap_ratio,
        indentation_delta=indent_delta,
        terminal_punctuation=has_term_punct,
        unclosed_delimiter=has_unclosed,
        font_variation_only=font_variation_only,
        reasons=reasons,
    )


# ── Page-Local Paragraph Reconstruction Engine ────────────────────────────────

def reconstruct_page_paragraphs(
    lines: List[LineRecord],
    page_geo: PageGeometry,
    standard_pitch: Optional[float] = None,
) -> List[ParagraphRecord]:
    """
    Reconstructs semantic paragraphs for a single PDF page in deterministic order.

    Pure computation function:
    - Zero file I/O, zero network, zero LLM calls.
    - Preserves span and line lineage.
    - Single-Column Contract: Sorts lines by (bbox[1], bbox[0]).
    - Sets continuation flags and explainable evidence for page boundaries.
    """
    if not lines:
        return []

    # 1. Deterministic sorting (single-column reading flow by Y0, then X0)
    sorted_lines = sorted(lines, key=lambda ln: (ln.bbox[1], ln.bbox[0]))

    # 2. Derive robust standard pitch if not explicitly provided
    resolved_pitch = standard_pitch or compute_standard_pitch(sorted_lines)

    paragraphs: List[ParagraphRecord] = []
    current_lines: List[LineRecord] = []
    current_evidences: List[BoundaryEvidence] = []
    delimiter_stack: List[str] = []
    para_idx = 0

    def flush_current_paragraph(boundary_before: bool = False, boundary_after: Optional[BoundaryEvidence] = None):
        nonlocal current_lines, current_evidences, para_idx
        if not current_lines:
            return

        full_text = join_line_texts(current_lines)
        union_bbox = union_line_bboxes(current_lines)
        dom_font, dom_size, bold_rat = compute_character_weighted_typography(current_lines)
        source_ids = [ln.line_id for ln in current_lines]

        # Check if single line was marked as standalone block
        is_standalone = (
            len(current_lines) == 1
            and (
                any("BREAK: standalone_block" in r for ev in current_evidences for r in ev.reasons)
                or (boundary_after is not None and any("BREAK: standalone_block" in r for r in boundary_after.reasons))
            )
        )

        para_rec = ParagraphRecord(
            paragraph_id=f"p{current_lines[0].page_num}_para_{para_idx + 1:03d}",
            page_num=current_lines[0].page_num,
            text=full_text,
            source_line_ids=source_ids,
            bbox=union_bbox,
            dominant_font=dom_font,
            dominant_size=dom_size,
            bold_ratio=bold_rat,
            paragraph_boundary_before=boundary_before,
            is_standalone_block=is_standalone,
            semantic_role="uncertain",  # Never assign heading semantic role in Phase 1
            heading_level=None,         # Strict decoupling: heading level is None
            evidence=list(current_evidences),
        )
        paragraphs.append(para_rec)
        para_idx += 1
        current_lines = []
        current_evidences = []

    # 3. Sequential Line-by-Line Boundary Assessment
    for i, line in enumerate(sorted_lines):
        if not line.text.strip():
            continue

        if not current_lines:
            current_lines.append(line)
            delimiter_stack = update_delimiter_stack(line.text, delimiter_stack)
            continue

        prev_line = current_lines[-1]
        evidence = calculate_boundary_evidence(
            prev_line=prev_line,
            curr_line=line,
            page_geo=page_geo,
            standard_pitch=resolved_pitch,
            unclosed_stack=delimiter_stack,
        )

        if evidence.should_break:
            flush_current_paragraph(boundary_before=True, boundary_after=evidence)
            current_evidences.append(evidence)
            delimiter_stack = []
        else:
            current_evidences.append(evidence)

        current_lines.append(line)
        delimiter_stack = update_delimiter_stack(line.text, delimiter_stack)

    # 4. Flush trailing paragraph
    if current_lines:
        flush_current_paragraph(boundary_before=(len(paragraphs) > 0))

    # 5. Page-level Cross-Page Continuation Assessment (Heuristic Score & Evidence)
    if paragraphs:
        last_para = paragraphs[-1]
        last_line_y1 = last_para.bbox[3]
        has_term = has_terminal_punctuation(last_para.text)
        has_unclosed = (len(delimiter_stack) > 0)
        is_near_bottom = (last_line_y1 >= page_geo.content_bottom - (resolved_pitch * 1.5))

        cont_evidence: List[str] = []
        cont_confidence: float = 0.0
        cont_to_next: bool = False

        if not is_near_bottom:
            cont_to_next = False
            cont_confidence = 0.0
            cont_evidence.append("suppressed: not near page bottom content boundary")
        else:
            cont_evidence.append("near_page_bottom")

            # Check unclosed delimiter first (unclosed delimiter takes precedence)
            if has_unclosed:
                cont_to_next = True
                cont_confidence = 0.90
                cont_evidence.append(f"active: unclosed_delimiter({','.join(delimiter_stack)})")
                if has_term:
                    cont_evidence.append("note: unclosed delimiter overrides inner terminal punctuation")
            elif has_term:
                # Terminal punctuation present at bottom suppresses continuation
                cont_to_next = False
                cont_confidence = 0.05
                cont_evidence.append("suppressed: terminal_punctuation_present")
            elif last_para.is_standalone_block or len(last_para.text.strip()) <= 15:
                # Short standalone line or caption at bottom: lower heuristic score
                cont_to_next = False
                cont_confidence = 0.35
                cont_evidence.append("suppressed: standalone_or_short_block_at_bottom")
            else:
                # Normal mid-sentence line wrap across page
                cont_to_next = True
                cont_confidence = 0.80
                cont_evidence.append("active: unpunctuated_wrap_at_bottom")

        last_para.continuation_to_next = cont_to_next
        last_para.continuation_confidence = round(min(max(cont_confidence, 0.0), 1.0), 2)
        last_para.continuation_evidence = cont_evidence

    return paragraphs
