"""Local Gemma assistance for uncertain PDF layout decisions.

The model may classify supplied text and boundary choices, but it never returns
replacement prose. All accepted results retain the original extracted text.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.utils.ollama_client import is_model_installed, ollama_structured_chat


DEFAULT_GEMMA_MODEL = os.getenv("AI_LAYOUT_MODEL", "gemma4:e4b")
STYLE_ROLES = ("h1", "h2", "h3", "body", "caption", "quote")
LAYOUT_ROLES = ("heading", "body", "caption", "quote", "uncertain")


_GEMMA_AVAILABILITY_CACHE: Dict[str, tuple[float, bool]] = {}


def gemma_available(model: Optional[str] = None) -> bool:
    """Return whether the configured local model is installed and Ollama responds."""
    target_model = model or DEFAULT_GEMMA_MODEL
    cached = _GEMMA_AVAILABILITY_CACHE.get(target_model)
    if cached and time.monotonic() - cached[0] < 15.0:
        return cached[1]
    try:
        available = is_model_installed(target_model)
    except Exception:
        available = False
    _GEMMA_AVAILABILITY_CACHE[target_model] = (time.monotonic(), available)
    return available


def validate_layout_reviews(
    source_blocks: Sequence[Mapping[str, Any]],
    reviews: Any,
    confidence_threshold: float = 0.75,
) -> List[Dict[str, Any]]:
    """Apply schema-valid, high-confidence labels without accepting model text."""
    source_by_id = {str(item.get("paragraph_id")): item for item in source_blocks}
    review_items = reviews.get("items", []) if isinstance(reviews, Mapping) else reviews
    if not isinstance(review_items, list):
        review_items = []
    review_by_id = {
        str(item.get("paragraph_id")): item
        for item in review_items
        if isinstance(item, Mapping) and item.get("paragraph_id") is not None
    }

    results: List[Dict[str, Any]] = []
    for paragraph_id, source in source_by_id.items():
        result = dict(source)
        review = review_by_id.get(paragraph_id)
        try:
            confidence = float(review.get("confidence", 0.0)) if review else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        role = review.get("role") if review else None
        level = review.get("level") if review else None
        valid_level = level in (1, 2, 3) and not isinstance(level, bool)
        valid_role = role in LAYOUT_ROLES
        valid_pair = (role == "heading" and valid_level) or (role != "heading" and level is None)
        if review and valid_role and valid_pair and 0.0 <= confidence <= 1.0 and confidence >= confidence_threshold:
            result.update({
                "role": role,
                "level": level,
                "confidence": confidence,
                "source": "gemma",
                "reason": str(review.get("reason", ""))[:240],
            })
        else:
            result.setdefault("source", "deterministic")
            if review:
                result["ai_status"] = "invalid_or_low_confidence_review"
        results.append(result)
    return results


def review_uncertain_layout(
    blocks: Sequence[Mapping[str, Any]],
    model: Optional[str] = None,
    confidence_threshold: float = 0.75,
) -> List[Dict[str, Any]]:
    """Classify a small set of ambiguous text blocks with local Gemma."""
    source = [dict(item) for item in blocks]
    if not source:
        return []
    target_model = model or DEFAULT_GEMMA_MODEL
    if not gemma_available(target_model):
        return [{**item, "source": "deterministic", "ai_status": "model_unavailable"} for item in source]

    prompt = (
        "判斷以下繁體/簡體中文書稿段落的角色。只依輸入文字與幾何/字體特徵判斷；"
        "不要改寫或補充文字。role 只能是 heading、body、caption、quote、uncertain；"
        "heading 必須提供 1/2/3 層級，其餘 level 為 null。每筆提供 0 到 1 信心度與簡短依據。\n"
        f"候選：{source}"
    )
    try:
        response = ollama_structured_chat(
            prompt=prompt,
            model=target_model,
            schema={
                "type": "object",
                "properties": {"items": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "paragraph_id": {"type": "string"},
                        "role": {"type": "string", "enum": list(LAYOUT_ROLES)},
                        "level": {"type": ["integer", "null"]},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["paragraph_id", "role", "level", "confidence", "reason"],
                }}},
                "required": ["items"],
            },
            timeout=45.0,
            temperature=0.0,
            think=False,
        )
    except Exception:
        response = None
    results = validate_layout_reviews(source, response, confidence_threshold)
    if not isinstance(response, Mapping) or not isinstance(response.get("items"), list):
        for result in results:
            result["ai_status"] = "invalid_or_unavailable_response"
    else:
        valid_ids = {str(item.get("paragraph_id")) for item in response["items"] if isinstance(item, Mapping)}
        for result in results:
            if result.get("source") != "gemma" and result["paragraph_id"] not in valid_ids:
                result["ai_status"] = "missing_review"
    return results


def validate_boundary_reviews(
    line_pairs: Sequence[Mapping[str, Any]],
    reviews: Any,
    confidence_threshold: float = 0.8,
) -> Dict[str, Dict[str, Any]]:
    """Return trusted paragraph boundary choices keyed by the following line id."""
    review_items = reviews.get("items", []) if isinstance(reviews, Mapping) else reviews
    pair_ids = {str(item.get("next_line_id")) for item in line_pairs}
    decisions: Dict[str, Dict[str, Any]] = {}
    if not isinstance(review_items, list):
        return decisions
    for item in review_items:
        if not isinstance(item, Mapping):
            continue
        line_id = str(item.get("next_line_id", ""))
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            continue
        if line_id in pair_ids and type(item.get("should_break")) is bool and 0.0 <= confidence <= 1.0 and confidence >= confidence_threshold:
            decisions[line_id] = {
                "should_break": item["should_break"],
                "confidence": confidence,
                "source": "gemma",
            }
    return decisions


def review_uncertain_boundaries(
    line_pairs: Sequence[Mapping[str, Any]],
    model: Optional[str] = None,
    confidence_threshold: float = 0.8,
) -> Dict[str, Any]:
    """Review ambiguous adjacent PDF lines; failures leave deterministic output intact."""
    if not line_pairs:
        return {}
    target_model = model or DEFAULT_GEMMA_MODEL
    if not gemma_available(target_model):
        return {"_status": {"status": "model_unavailable", "model": target_model}}
    prompt = (
        "判斷每組相鄰 PDF 文字行應屬同一段落 (should_break=false) 或新段落 "
        "(should_break=true)。保留原文，不可改寫。只依文字、行距、縮排與既有證據判斷。\n"
        f"候選：{list(line_pairs)}"
    )
    try:
        response = ollama_structured_chat(
            prompt=prompt,
            model=target_model,
            schema={
                "type": "object",
                "properties": {"items": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "next_line_id": {"type": "string"},
                        "should_break": {"type": "boolean"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["next_line_id", "should_break", "confidence"],
                }}},
                "required": ["items"],
            },
            timeout=45.0,
            temperature=0.0,
            think=False,
        )
    except Exception:
        response = None
    decisions = validate_boundary_reviews(line_pairs, response, confidence_threshold)
    if not isinstance(response, Mapping) or not isinstance(response.get("items"), list):
        status = "invalid_or_unavailable_response"
    elif not decisions:
        status = "no_valid_decisions"
    else:
        status = "ready"
    decisions["_status"] = {"status": status, "model": target_model}
    return decisions


def suggest_docx_style_mapping(
    styles: Sequence[Mapping[str, Any]],
    model: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Suggest role-to-template-style mappings and reject nonexistent style names."""
    style_names = [str(style.get("name", "")).strip() for style in styles]
    style_names = [name for name in style_names if name]
    result: Dict[str, Optional[str]] = {role: None for role in STYLE_ROLES}
    if not style_names or not gemma_available(model):
        return result
    prompt = (
        "將文件角色對應到最適合的段落樣式。只能使用提供的樣式名稱，沒有合適樣式回傳 null。"
        "使用 h1/h2/h3/body/caption/quote 六種角色。\n"
        f"樣式：{list(styles)}"
    )
    try:
        response = ollama_structured_chat(
            prompt=prompt,
            model=model or DEFAULT_GEMMA_MODEL,
            schema={
                "type": "object",
                "properties": {"mapping": {
                    "type": "object",
                    "properties": {role: {"type": ["string", "null"]} for role in STYLE_ROLES},
                    "required": list(STYLE_ROLES),
                }},
                "required": ["mapping"],
            },
            timeout=45.0,
            temperature=0.0,
            think=False,
        )
    except Exception:
        response = None
    mapping = response.get("mapping", {}) if isinstance(response, Mapping) else {}
    for role in STYLE_ROLES:
        value = mapping.get(role)
        if isinstance(value, str) and value in style_names:
            result[role] = value
    return result
