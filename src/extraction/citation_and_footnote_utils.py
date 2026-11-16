# -*- coding: utf-8 -*-
"""
Shared Citation Detection & Footnote Marker Utilities
=====================================================
Centralizes literature citation regexes, footnote marker parsing, and
3-stage footnote anchor matching/replacement shared across the Vector PDF
pipeline (`book_layout_extractor.py`) and the OCR pipeline (`process_ocr.py`).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

CIRCLED_MAP: Dict[str, int] = {
    '①': 1, '②': 2, '③': 3, '④': 4, '⑤': 5,
    '⑥': 6, '⑦': 7, '⑧': 8, '⑨': 9, '⑩': 10,
    '⑪': 11, '⑫': 12, '⑬': 13, '⑭': 14, '⑮': 15,
    '⑯': 16, '⑰': 17, '⑱': 18, '⑲': 19, '⑳': 20,
}

_SUPERSCRIPT_CHAR_MAP: Dict[str, int] = {
    '⁰': 0, '¹': 1, '²': 2, '³': 3, '⁴': 4,
    '⁵': 5, '⁶': 6, '⁷': 7, '⁸': 8, '⁹': 9,
}

FN_MARKER_PATTERN = (
    r'('
    r'[\u2460-\u24ff\u2780-\u2793\u3251-\u325f]|'
    r'(?![\[［〔【][MJDCGRPAKNSZ][\]］〕】](?:[.、/，,\s]|$))[\[［〔【]\s*(?:\d+|[a-jA-J])\s*[\]］〕】]|'
    r'(?<!\d)(?<!\d\s)(?<!第)(?<![卷页頁册冊部篇期])(?<![卷页頁册冊部篇期]\s)[\(（]\s*(?:\d+|[a-jA-J])\s*[\)）](?![:：;；])(?!\s*[:：;；])(?!\s*[页頁期卷条條])|'
    r'[\u2070\u00b9\u00b2\u00b3\u2074-\u2079]+|'
    r'(?<![a-zA-Z\d:：,，;；\-–—~～/\\第卷页頁册冊部篇期年版.])(?<![:：] )(?<![:：]  )(?<![:：]   )(?<![:：]    )(?<![:：]\u3000)(?<![:：]\t)(?<![,，] )(?<![,，]  )(?<![,，]   )(?<![,，]    )(?<![;；] )(?<![;；]  )(?<![;；]   )(?<![;；]    )(?<![\-–—~～] )(?<![\-–—~～]  )(?<![\-–—~～]   )(?<!第 )(?<!第  )(?<!第   )(?<!第    )(?<!\d )(?<!\d  )(?<![卷页頁册冊部篇期年版] )(?<![卷页頁册冊部篇期年版]  )(?<![卷页頁册冊部篇期年版]   )(?<![卷页頁册冊部篇期年版]    )(?<![Pp]\. )(?<![Pp]\.  )(?<![Pp]\.   )(?<![Pp]\.    )(?<![Pp][Pp]\. )(?<![Pp][Pp]\.  )(?<![Pp][Pp]\.   )(?<![Pp][Pp]\.    )(?<![Vv]ol\. )(?<![Vv]ol\.  )(?<![Nn]o\. )(?<![Nn]o\.  )(?<!\d\. )(?<!\d\.  )(?<!\d\.   )(?<!\d\.    )(?<!\]\. )(?<!\]\.  )(?<!\] )(?<!\]  )(?!(?:18|19|20)\d{2}[.、])\d{1,3}[.、](?!\s*[页頁期卷条條])(?![a-zA-Z0-9/])|'
    r'(?<![a-zA-Z0-9.])[a-jA-J][.、)）](?!\s*(?:e|g)\.)|(?:^|(?<=[\r\n]))\s*[a-jA-J]\s'
    r')'
)

_WEAK_MARKER_RE = re.compile(r'^[\d.、\s()（）]+$')
_WEAK_MARKER_CHECK_RE = re.compile(r'^(?:\d+[.、\s]?|[（(]\s*(?:\d+|[a-jA-J])\s*[)）][.、]?)$')
_WEAK_CANDIDATE_FULL_RE = re.compile(r'[\d.、\s]+|[\(（]\s*(?:\d+|[a-jA-J])\s*[\)）]')
_ALPHA_MARKER_RE = re.compile(r'^[a-zA-Z][.、\s)）]?$')
_DIGITS_RE = re.compile(r'\d+')
_FN_MARKER_SPLIT_RE = re.compile(FN_MARKER_PATTERN)
_STARTS_WITH_FN_MARKER_RE = re.compile(r'^\s*(' + FN_MARKER_PATTERN + r')\s*')
_FN_MARKER_PARSE_RE = re.compile(r'^\s*' + FN_MARKER_PATTERN + r'\s*')
_URL_OR_ASCII_TAIL_RE = re.compile(r'https?://[^\s]*$|www\.[^\s]*$|[a-zA-Z]$')

_CITATION_PRECEDING_RE = re.compile(
    r'(?:'
    r'[:：;；]|'
    r'[Pp]\.?|[Pp][Pp]\.?|[Vv]ol\.?|[Nn]o\.?|[Pp]ages?\.?|'
    r'第|[卷页頁册冊部篇期年版]|'
    r'[\-–—~～/\\]|\d+\s*[,，]|'
    r'\b(?:18|19|20)\d{2}[.、,，]?|'
    r'\[[A-Z]+(?:/[A-Z]+)?\]\.?'
    r')\s*$'
)

_CITATION_PATTERNS = (
    r'\[[A-Z]+(?:/[A-Z]+)?\]',
    r'(?:出版社|出版|Press)',
    r'(?:\d{4}\s*年\s*版|\d{4}\s*年|\d{4}\s*[:：]\s*\d+)',
    r'(?:第\s*\d+\s*页|[Pp]\.?\s*\d+)',
    r'(?:参阅|参见|转引自|主编)',
)


def is_strong_citation_text(text: str) -> bool:
    """Check if text exhibits characteristics of a formal literature citation."""
    if not text:
        return False
    for pat in _CITATION_PATTERNS:
        if re.search(pat, text):
            return True
    if re.search(r'《[^》]+》', text) and re.search(
        r'(?:\[[MJZD]\]|著|主编|编著|等编|译|\d{4}|第\s*\d+\s*页|[Pp]\.?\s*\d+|出版)', text
    ):
        return True
    return False


def _circled_to_int(marker_str: str) -> int:
    """Convert any footnote marker string to its integer index."""
    if not marker_str:
        return 1
    if marker_str in CIRCLED_MAP:
        return CIRCLED_MAP[marker_str]
    if any(c in _SUPERSCRIPT_CHAR_MAP for c in marker_str):
        digits = "".join(str(_SUPERSCRIPT_CHAR_MAP[c]) for c in marker_str if c in _SUPERSCRIPT_CHAR_MAP)
        if digits:
            return int(digits)
    alpha_m = re.search(r'[a-zA-Z]', marker_str)
    if alpha_m:
        return ord(alpha_m.group(0).lower()) - ord('a') + 1
    digs = _DIGITS_RE.findall(marker_str)
    return int(digs[0]) if digs else 1


def build_alpha_callout_pattern(alpha_char: str) -> re.Pattern:
    """Build regex matching standalone single-letter footnote callouts attached to CJK text."""
    return re.compile(
        r'(?<=[。，；！？、”’」』）)\]】\u4e00-\u9fff])(?<![a-zA-Z0-9])'
        + re.escape(alpha_char)
        + r'(?![a-zA-Z0-9])(?=[。，；！？、”’」』）)\]】\s\n]|$)'
    )


def build_weak_marker_pattern(marker_str: str) -> re.Pattern:
    """Build guarded regex for weak numeric/paren footnote markers."""
    return re.compile(
        r'(?<![a-zA-Z\d])'
        + re.escape(marker_str)
        + r'(?!\d)(?![:：;；])(?!\s*[:：;；])(?!\s*[页頁期卷条條])(?![a-zA-Z0-9/])'
    )


def is_preceded_by_citation_or_url(text: str, pos: int, preceding_context: str = "") -> bool:
    """Check whether position `pos` in `text` is preceded by citation page delimiters or URLs."""
    prefix = text[:pos]
    preceding = (preceding_context + " " + prefix).rstrip() if (preceding_context and not prefix.strip()) else prefix.rstrip()
    return bool(_CITATION_PRECEDING_RE.search(preceding) or _URL_OR_ASCII_TAIL_RE.search(preceding))


def is_valid_footnote_split_match(fb_text: str, match: re.Match) -> bool:
    """Return True if a candidate footnote marker match is not a citation page number or URL segment."""
    m_txt = match.group(1).strip() if match.lastindex else match.group(0).strip()
    if not _WEAK_CANDIDATE_FULL_RE.fullmatch(m_txt):
        return True
    preceding = fb_text[:match.start()].rstrip()
    if _CITATION_PRECEDING_RE.search(preceding):
        return False
    if _URL_OR_ASCII_TAIL_RE.search(fb_text[:match.start()]):
        return False
    if re.match(r'^[a-zA-Z0-9/]', fb_text[match.end():]):
        return False
    return True


def is_citation_continuation_marker(marker_str: str, num_val: int, prev_content: str) -> bool:
    """Return True if `marker_str` is a 4-digit year or a page/URL continuation of `prev_content`."""
    if 1800 <= num_val <= 2100 and re.match(r'^\d{4}[.、]', marker_str):
        return True
    if prev_content and re.fullmatch(r'[\d.、\s]+', marker_str):
        if _CITATION_PRECEDING_RE.search(prev_content) or re.search(r'https?://[^\s]*$|www\.[^\s]*$', prev_content):
            return True
    return False


def _replace_weak_marker_occurrence(
    text: str, marker_str: str, fn_tag: str, preceding_context: str = ""
) -> Tuple[str, bool]:
    """Attempt guarded replacement of a weak marker (e.g. '1.' or '(1)') in `text`."""
    safe_pat = build_weak_marker_pattern(marker_str)
    for m in safe_pat.finditer(text):
        if is_preceded_by_citation_or_url(text, m.start(), preceding_context):
            continue
        return text[:m.start()] + fn_tag + text[m.end():], True
    return text, False


def _replace_exact_substring_marker(
    text: str,
    marker_str: str,
    fn_tag: str,
    preceding_context: str = "",
    require_citation_at_start: bool = False,
) -> Tuple[str, bool]:
    """Attempt guarded exact substring replacement for non-weak markers in `text`."""
    idx = 0
    is_weak_cand = bool(_WEAK_CANDIDATE_FULL_RE.fullmatch(marker_str))
    while True:
        idx = text.find(marker_str, idx)
        if idx == -1:
            return text, False
        if not is_weak_cand or not is_preceded_by_citation_or_url(text, idx, preceding_context):
            if require_citation_at_start and idx == 0 and not is_strong_citation_text(text):
                idx += len(marker_str)
                continue
            return text[:idx] + fn_tag + text[idx + len(marker_str):], True
        idx += len(marker_str)


def try_replace_primary_marker(
    text: str,
    marker_str: str,
    fn_tag: str,
    preceding_context: str = "",
    use_ocr_weak_check: bool = False,
    require_citation_at_start: bool = False,
) -> Tuple[str, bool]:
    """Stage 1: Replace primary footnote marker (alpha, weak numeric/paren, or exact bracket/circled)."""
    if not marker_str:
        return text, False
    if _ALPHA_MARKER_RE.search(marker_str.strip()):
        alpha_m = re.search(r'[a-zA-Z]', marker_str)
        if alpha_m:
            new_text, n_subs = build_alpha_callout_pattern(alpha_m.group(0)).subn(fn_tag, text, count=1)
            if n_subs > 0:
                return new_text, True
        return text, False
    is_weak = bool(_WEAK_MARKER_CHECK_RE.fullmatch(marker_str)) if use_ocr_weak_check else bool(_WEAK_MARKER_RE.match(marker_str))
    if is_weak:
        return _replace_weak_marker_occurrence(text, marker_str, fn_tag, preceding_context)
    if marker_str in text:
        return _replace_exact_substring_marker(text, marker_str, fn_tag, preceding_context, require_citation_at_start)
    return text, False


def try_replace_variant_marker(text: str, fn_id: int, fn_tag: str) -> Tuple[str, bool]:
    """Stage 2: Replace strong bracketed or circled variants matching `fn_id`."""
    variants = [
        f"[{fn_id}]",
        f"［{fn_id}］",
        f"〔{fn_id}〕",
        f"【{fn_id}】",
        f"[ {fn_id} ]",
        f"［ {fn_id} ］",
    ]
    rev_circled = [k for k, v in CIRCLED_MAP.items() if v == fn_id]
    if rev_circled:
        variants.append(rev_circled[0])
    for var in variants:
        if var in text:
            return text.replace(var, fn_tag, 1), True
    return text, False


def try_replace_alpha_fallback(text: str, fn_id: int, fn_tag: str) -> Tuple[str, bool]:
    """Stage 3: Replace letter superscript callouts ('a'..'z' / 'A'..'Z') for 1 <= fn_id <= 26."""
    if not (1 <= fn_id <= 26):
        return text, False
    for alpha_char in (chr(ord('a') + fn_id - 1), chr(ord('A') + fn_id - 1)):
        new_text, n_subs = build_alpha_callout_pattern(alpha_char).subn(fn_tag, text, count=1)
        if n_subs > 0:
            return new_text, True
    return text, False


def _replace_fn_markers_in_text(
    text: str, page_footnotes: list, page_num: int, preceding_context: str = ""
) -> str:
    """Replace all recognised footnote marker occurrences in `text` with Pandoc ref-tags."""
    for fn in page_footnotes:
        m_str = fn.get('marker', '')
        fn_id = fn.get('id', 1)
        if not m_str and not fn_id:
            continue
        fn_tag = f"[^p{page_num}_{fn_id}]"
        text, matched = try_replace_primary_marker(text, m_str, fn_tag, preceding_context=preceding_context)
        if not matched and fn_id is not None:
            text, matched = try_replace_variant_marker(text, fn_id, fn_tag)
        if not matched and fn_id is not None:
            text, matched = try_replace_alpha_fallback(text, fn_id, fn_tag)
        if matched:
            fn['matched'] = True
    return text


def has_ocr_marker_match_in_block(
    b_txt: str, marker_str: str, fn_id: int, prev_context: str = "", marker_detector: Any = None
) -> bool:
    """Check whether a single OCR body block contains a valid anchor for `marker_str` or `fn_id`."""
    _, matched = try_replace_primary_marker(
        b_txt,
        marker_str,
        "__Probe__",
        preceding_context=prev_context,
        use_ocr_weak_check=True,
        require_citation_at_start=True,
    )
    if matched:
        return True
    if marker_detector is not None:
        return any(d.number == fn_id for d in marker_detector.detect(b_txt, "auto"))
    return False

