"""Local Gemma assistance for uncertain PDF layout decisions and font group suggestions.

The model may classify supplied text, font groups, and boundary choices, but it never returns
replacement prose. All accepted results retain the original extracted text.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.utils.ollama_client import (
    OllamaConnectionError,
    OllamaTimeoutError,
    is_model_installed,
    is_ollama_available,
    ollama_structured_chat,
)


DEFAULT_GEMMA_MODEL = os.getenv("AI_LAYOUT_MODEL", "gemma4:e4b")
GEMMA_FONT_NUM_CTX = 8192
GEMMA_FONT_BATCH_SIZE = 8
GEMMA_FONT_MAX_SAMPLES = 3
GEMMA_FONT_MAX_SAMPLE_LEN = 60

_WIN_PATH_RE = re.compile(r"[A-Za-z]:[\\\/][^\s\"'<>|]+")
_UNC_PATH_RE = re.compile(r"\\\\[^\s\"'<>|]+")
_UNIX_PATH_RE = re.compile(r"(?:/Users/|/home/|/tmp/|/var/|/etc/|/opt/|/private/|/mnt/)[^\s\"'<>|]+")
_REL_FILE_PATH_RE = re.compile(r"[^\s\"'<>|]+[\\\/][^\s\"'<>|]+\.(?:pdf|docx|json|md|py|txt|log)", re.I)


def sanitize_diagnostic_text(text: Any, max_len: int = 120) -> str:
    """Sanitize diagnostic or error text by stripping file paths, quotes, and multiline noise."""
    if text is None:
        return ""
    raw = str(text)
    raw = _WIN_PATH_RE.sub("<path>", raw)
    raw = _UNC_PATH_RE.sub("<path>", raw)
    raw = _UNIX_PATH_RE.sub("<path>", raw)
    raw = _REL_FILE_PATH_RE.sub("<path>", raw)
    raw = re.sub(r"[\r\n\t]+", " ", raw)
    raw = re.sub(r"\s{2,}", " ", raw).strip()
    raw = raw.replace('"', "'")
    return raw[:max_len]


def resolve_font_suggestion_outcome(status: str) -> str:
    """Classify overall suggestion status into 'success', 'fallback', or 'failed'."""
    if status == "ready":
        return "success"
    if status in ("ollama_unavailable", "model_unavailable", "low_confidence", "no_suggestions"):
        return "fallback"
    return "failed"


def format_font_suggestion_diag_log(
    event: str,
    req_id: str,
    model: str,
    total_groups: int,
    *,
    template_styles: Optional[int] = None,
    status: Optional[str] = None,
    valid_suggestions: Optional[int] = None,
    low_confidence: Optional[int] = None,
    elapsed_ms: Optional[int] = None,
    error_type: Optional[str] = None,
    error_msg: Optional[str] = None,
    module: str = "ocr_router",
    endpoint: str = "/api/suggest_font_mappings",
) -> str:
    """Format a single-line, privacy-preserving diagnostic log entry for CMD and server logs."""
    safe_model = sanitize_diagnostic_text(model or DEFAULT_GEMMA_MODEL, max_len=48)
    parts = [
        "[GemmaFontSuggest]",
        f"event={event}",
        f"module={module}",
        f"endpoint={endpoint}",
        f"req_id={req_id}",
        f"model={safe_model}",
    ]
    if event == "start":
        parts.append(f"total_groups={int(total_groups)}")
        if template_styles is not None:
            parts.append(f"template_styles={int(template_styles)}")
        return " ".join(parts)

    resolved_status = status or "inference_failed"
    outcome = resolve_font_suggestion_outcome(resolved_status)
    parts.extend([
        f"status={resolved_status}",
        f"outcome={outcome}",
        f"total_groups={int(total_groups)}",
        f"valid_suggestions={int(valid_suggestions or 0)}",
        f"low_confidence={int(low_confidence or 0)}",
        f"elapsed_ms={int(elapsed_ms or 0)}",
    ])
    if error_type:
        safe_err_type = sanitize_diagnostic_text(error_type, max_len=48)
        parts.append(f"error_type={safe_err_type}")
    if error_msg:
        safe_err = sanitize_diagnostic_text(error_msg, max_len=100)
        parts.append(f'error="{safe_err}"')
    return " ".join(parts)

STYLE_ROLES = ("h1", "h2", "h3", "body", "caption", "quote")
LAYOUT_ROLES = ("heading", "body", "caption", "quote", "uncertain")
FONT_GROUP_ROLES = ("H1", "H2", "H3", "圖說", "楷體", "正文", "忽略")

_ROLE_NORMALIZATION_MAP: Dict[str, str] = {
    "h1": "H1",
    "heading1": "H1",
    "標題1": "H1",
    "标题1": "H1",
    "一級標題": "H1",
    "一级标题": "H1",
    "h2": "H2",
    "heading2": "H2",
    "標題2": "H2",
    "标题2": "H2",
    "二級標題": "H2",
    "二级标题": "H2",
    "h3": "H3",
    "heading3": "H3",
    "標題3": "H3",
    "标题3": "H3",
    "三級標題": "H3",
    "三级标题": "H3",
    "caption": "圖說",
    "圖說": "圖說",
    "图说": "圖說",
    "圖片標籤": "圖說",
    "圖表說明": "圖說",
    "quote": "楷體",
    "kaiti": "楷體",
    "楷體": "楷體",
    "楷体": "楷體",
    "引言": "楷體",
    "引文": "楷體",
    "body": "正文",
    "正文": "正文",
    "內文": "正文",
    "内文": "正文",
    "paragraph": "正文",
    "ignore": "忽略",
    "ignored": "忽略",
    "忽略": "忽略",
}


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


def normalize_font_role(role: Any) -> Optional[str]:
    """Normalize role string to canonical FONT_GROUP_ROLES."""
    if not isinstance(role, str):
        return None
    cleaned = role.strip()
    if cleaned in FONT_GROUP_ROLES:
        return cleaned
    return _ROLE_NORMALIZATION_MAP.get(cleaned.lower())


def _sanitize_font_group_for_prompt(group: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract only bounded summary and sample fields for prompt construction."""
    raw_samples = group.get("sample_texts") or []
    samples: List[str] = []
    if isinstance(raw_samples, Sequence) and not isinstance(raw_samples, (str, bytes)):
        for s in list(raw_samples)[:GEMMA_FONT_MAX_SAMPLES]:
            if s is not None:
                txt = str(s).strip()[:GEMMA_FONT_MAX_SAMPLE_LEN]
                if txt:
                    samples.append(txt)
    pos = group.get("position_summary")
    pos_summary = dict(pos) if isinstance(pos, Mapping) else {}
    return {
        "font_name": str(group.get("name", "")).strip(),
        "full_name": str(group.get("full_name", "")).strip(),
        "size_pt": float(group.get("size_pt", 0.0) or 0.0),
        "occurrence_count": int(group.get("occurrence_count", 0) or 0),
        "page_count": int(group.get("page_count", 0) or 0),
        "position_summary": pos_summary,
        "sample_texts": samples,
        "rule_suggested_role": group.get("suggested_role"),
    }


def validate_font_group_suggestions(
    font_groups: Sequence[Mapping[str, Any]],
    docx_styles: Sequence[Mapping[str, Any]],
    raw_response: Any,
    confidence_threshold: float = 0.6,
) -> Dict[str, Dict[str, Any]]:
    """Validate Gemma font group suggestions against template styles and confidence bounds."""
    valid_style_names = {
        str(s.get("name", "")).strip()
        for s in docx_styles
        if isinstance(s, Mapping) and str(s.get("name", "")).strip()
    }
    group_names = {
        str(g.get("name", "")).strip()
        for g in font_groups
        if isinstance(g, Mapping) and str(g.get("name", "")).strip()
    }

    items = raw_response.get("items", []) if isinstance(raw_response, Mapping) else raw_response
    if not isinstance(items, list):
        items = []

    raw_by_name: Dict[str, Mapping[str, Any]] = {}
    for item in items:
        if isinstance(item, Mapping) and item.get("font_name"):
            fname = str(item.get("font_name")).strip()
            if fname in group_names:
                raw_by_name[fname] = item

    validated: Dict[str, Dict[str, Any]] = {}
    for fname in group_names:
        item = raw_by_name.get(fname)
        if not item:
            validated[fname] = {
                "font_name": fname,
                "role": None,
                "docx_style": None,
                "confidence": None,
                "reason": "Gemma 未回傳此字體群組建議",
                "status": "no_suggestion",
                "source": "deterministic",
            }
            continue

        norm_role = normalize_font_role(item.get("role"))
        raw_style = item.get("docx_style")
        valid_style = (
            str(raw_style).strip()
            if isinstance(raw_style, str) and str(raw_style).strip() in valid_style_names
            else None
        )
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, round(confidence, 2)))
        reason = str(item.get("reason") or "").strip()[:200]

        if not norm_role and not valid_style:
            validated[fname] = {
                "font_name": fname,
                "role": None,
                "docx_style": None,
                "confidence": confidence,
                "reason": reason or "無符合範本的樣式或角色建議",
                "status": "no_suggestion",
                "source": "deterministic",
            }
        elif confidence < confidence_threshold:
            validated[fname] = {
                "font_name": fname,
                "role": norm_role,
                "docx_style": valid_style,
                "confidence": confidence,
                "reason": reason or "信心度偏低，建議人工確認",
                "status": "low_confidence",
                "source": "gemma",
            }
        else:
            validated[fname] = {
                "font_name": fname,
                "role": norm_role,
                "docx_style": valid_style,
                "confidence": confidence,
                "reason": reason or "依字體、字級、頻率與樣本判定",
                "status": "suggested",
                "source": "gemma",
            }

    return validated


def suggest_pdf_font_group_mappings(
    font_groups: Sequence[Mapping[str, Any]],
    docx_styles: Sequence[Mapping[str, Any]],
    model: Optional[str] = None,
    confidence_threshold: float = 0.6,
    batch_size: int = GEMMA_FONT_BATCH_SIZE,
    num_ctx: int = GEMMA_FONT_NUM_CTX,
    timeout: float = 45.0,
) -> Dict[str, Any]:
    """Suggest role and DOCX style per PDF font group sequentially in 8K-context batches."""
    target_model = model or DEFAULT_GEMMA_MODEL
    groups_list = [dict(g) for g in font_groups if isinstance(g, Mapping) and g.get("name")]
    styles_list = [
        {
            "name": str(s.get("name", "")).strip(),
            "outline_level": s.get("outline_level"),
            "font_size_pt": s.get("font_size_pt"),
            "bold": bool(s.get("bold", False)),
        }
        for s in docx_styles
        if isinstance(s, Mapping) and str(s.get("name", "")).strip()
    ]

    total_groups = len(groups_list)
    if not groups_list:
        return {
            "status": "no_suggestions",
            "outcome": "fallback",
            "model": target_model,
            "num_ctx": num_ctx,
            "message": "PDF 中沒有可分析的字體群組。",
            "stats": {
                "total_groups": 0,
                "valid_suggestions": 0,
                "low_confidence": 0,
            },
            "error_type": None,
            "sanitized_error": None,
            "suggestions": {},
        }

    # Check Ollama connection and model installation without auto-downloading
    if not is_ollama_available(timeout=0.8):
        return {
            "status": "ollama_unavailable",
            "outcome": "fallback",
            "model": target_model,
            "num_ctx": num_ctx,
            "message": "無法連線至本機 Ollama 服務；Gemma 未參與，已保留既有規則與人工覆核。",
            "stats": {
                "total_groups": total_groups,
                "valid_suggestions": 0,
                "low_confidence": 0,
            },
            "error_type": "OllamaConnectionError",
            "sanitized_error": "Ollama service unreachable",
            "suggestions": {
                str(g["name"]): {
                    "font_name": str(g["name"]),
                    "role": None,
                    "docx_style": None,
                    "confidence": None,
                    "reason": "Ollama 無法連線（Gemma 未參與）",
                    "status": "not_participated",
                    "source": "deterministic",
                }
                for g in groups_list
            },
        }

    if not gemma_available(target_model):
        return {
            "status": "model_unavailable",
            "outcome": "fallback",
            "model": target_model,
            "num_ctx": num_ctx,
            "message": f"本機尚未安裝 {target_model}；Gemma 未參與，已保留既有規則與人工覆核。",
            "stats": {
                "total_groups": total_groups,
                "valid_suggestions": 0,
                "low_confidence": 0,
            },
            "error_type": "ModelNotInstalledError",
            "sanitized_error": f"Model {sanitize_diagnostic_text(target_model, 48)} not installed",
            "suggestions": {
                str(g["name"]): {
                    "font_name": str(g["name"]),
                    "role": None,
                    "docx_style": None,
                    "confidence": None,
                    "reason": f"未安裝 {target_model}（Gemma 未參與）",
                    "status": "not_participated",
                    "source": "deterministic",
                }
                for g in groups_list
            },
        }

    all_suggestions: Dict[str, Dict[str, Any]] = {}
    batch_errors: List[str] = []
    error_types: List[str] = []
    timed_out = False
    connection_failed = False

    effective_batch_size = max(1, min(int(batch_size or GEMMA_FONT_BATCH_SIZE), 12))
    effective_num_ctx = min(int(num_ctx or GEMMA_FONT_NUM_CTX), GEMMA_FONT_NUM_CTX)

    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "font_name": {"type": "string"},
                        "role": {"type": ["string", "null"], "enum": [*FONT_GROUP_ROLES, None]},
                        "docx_style": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": ["font_name", "role", "docx_style", "confidence", "reason"],
                },
            }
        },
        "required": ["items"],
    }

    for start_idx in range(0, len(groups_list), effective_batch_size):
        batch = groups_list[start_idx : start_idx + effective_batch_size]
        sanitized_batch = [_sanitize_font_group_for_prompt(g) for g in batch]
        prompt = (
            "你是繁體/簡體中文圖書排版專家。請根據以下 PDF 字體群組摘要（字型、字級、出現頻率、涵蓋頁數、"
            "頁面位置分布與限長樣本文字）以及目前 DOCX 範本段落樣式屬性，為每個 PDF 字體群組建議最適合的"
            "「內容角色 (role)」與「DOCX 範本樣式 (docx_style)」。\n"
            "規則：\n"
            "1. role 只能是 H1、H2、H3、圖說、楷體、正文、忽略 或 null。\n"
            "2. docx_style 只能從提供的 DOCX 範本樣式名稱中選擇；若範本無合適樣式或清單為空，填 null。\n"
            "3. 頁眉、頁碼或重複版權裝飾字體（如極高頻出現在 top/bottom 的短數字或書名頁眉）可建議為「忽略」。\n"
            "4. 僅做分類與樣式配對，嚴禁改寫樣本文字。請提供 0 到 1 的信心度 (confidence) 與簡短中文理由 (reason)。\n"
            f"DOCX 範本樣式：{styles_list}\n"
            f"PDF 字體群組：{sanitized_batch}"
        )

        try:
            response = ollama_structured_chat(
                prompt=prompt,
                model=target_model,
                schema=schema,
                num_ctx=effective_num_ctx,
                timeout=timeout,
                temperature=0.0,
                think=False,
                check_service=False,
            )
        except OllamaTimeoutError as exc:
            timed_out = True
            error_types.append("OllamaTimeoutError")
            batch_errors.append(sanitize_diagnostic_text(exc))
            response = None
        except OllamaConnectionError as exc:
            err_str = str(exc).lower()
            if "timed out" in err_str or "timeout" in err_str:
                timed_out = True
                error_types.append("OllamaTimeoutError")
            else:
                connection_failed = True
                error_types.append("OllamaConnectionError")
            batch_errors.append(sanitize_diagnostic_text(exc))
            response = None
        except Exception as exc:
            err_str = str(exc).lower()
            if "timed out" in err_str or "timeout" in err_str:
                timed_out = True
                error_types.append("OllamaTimeoutError")
            else:
                error_types.append(type(exc).__name__)
            batch_errors.append(sanitize_diagnostic_text(exc))
            response = None

        if response is None or not isinstance(response, Mapping) or not isinstance(response.get("items"), list):
            if response is not None and not error_types:
                error_types.append("InvalidResponseSchema")
                batch_errors.append("Invalid model response schema")
            fail_reason = "Gemma 推論逾時，保留規則與人工設定" if timed_out else "Gemma 推論失敗或回傳無效格式，保留規則與人工設定"
            for g in batch:
                fname = str(g["name"])
                all_suggestions[fname] = {
                    "font_name": fname,
                    "role": None,
                    "docx_style": None,
                    "confidence": None,
                    "reason": fail_reason,
                    "status": "failed",
                    "source": "deterministic",
                }
        else:
            batch_validated = validate_font_group_suggestions(
                batch,
                styles_list,
                response,
                confidence_threshold=confidence_threshold,
            )
            all_suggestions.update(batch_validated)

    suggested_count = sum(1 for v in all_suggestions.values() if v.get("status") == "suggested")
    low_conf_count = sum(1 for v in all_suggestions.values() if v.get("status") == "low_confidence")
    all_failed = all(v.get("status") == "failed" for v in all_suggestions.values())

    if all_failed:
        if timed_out:
            overall_status = "timeout"
            msg = "Gemma 推論逾時；已保留既有規則建議與人工選擇。"
        elif connection_failed:
            overall_status = "ollama_unavailable"
            msg = "無法連線至本機 Ollama 服務；已保留既有規則建議與人工選擇。"
        else:
            overall_status = "inference_failed"
            msg = "Gemma 推論失敗或回傳格式無效；已保留既有規則建議與人工選擇。"
    elif suggested_count == 0 and low_conf_count > 0:
        overall_status = "low_confidence"
        msg = f"Gemma 建議信心度偏低（低信心 {low_conf_count} 筆）；已保留既有規則預選，請人工覆核確認。"
    elif suggested_count == 0 and low_conf_count == 0:
        overall_status = "no_suggestions"
        msg = "Gemma 未能針對目前的字體群組提出明確建議；請使用規則預選或人工指定。"
    else:
        overall_status = "ready"
        msg = f"Gemma 已完成字體群組建議（高信心 {suggested_count} 筆" + (f"、低信心 {low_conf_count} 筆" if low_conf_count else "") + "），請覆核後點擊「確認套用」。"

    primary_error_type = error_types[0] if error_types else None
    primary_sanitized_err = batch_errors[0] if batch_errors else None

    return {
        "status": overall_status,
        "outcome": resolve_font_suggestion_outcome(overall_status),
        "model": target_model,
        "num_ctx": effective_num_ctx,
        "message": msg,
        "stats": {
            "total_groups": total_groups,
            "valid_suggestions": suggested_count,
            "low_confidence": low_conf_count,
        },
        "error_type": primary_error_type,
        "sanitized_error": primary_sanitized_err,
        "suggestions": all_suggestions,
    }


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
            num_ctx=GEMMA_FONT_NUM_CTX,
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
            num_ctx=GEMMA_FONT_NUM_CTX,
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
            num_ctx=GEMMA_FONT_NUM_CTX,
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
