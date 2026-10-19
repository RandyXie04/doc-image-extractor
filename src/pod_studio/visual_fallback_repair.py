# -*- coding: utf-8 -*-
"""
Visual Fallback Repair
======================
Reuses the 150 DPI block screenshot rendering pattern from AIKaitiClassifier
to provide visual context for sections with vector-outlined missing badges or OCR corruption.
"""

from __future__ import annotations
import fitz
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Sequence

from .blueprint_schema import BookBlueprint


def render_page_crop(
    pdf_path: str | Path,
    page_num: int,
    bbox: Optional[Sequence[float]] = None,
    dpi: int = 150,
) -> bytes:
    """
    Renders a page or a padded bounding box to PNG bytes.
    1-indexed page_num.
    Reuses the robust logic from AIKaitiClassifier._render_block_screenshot.
    """
    with fitz.open(str(pdf_path)) as doc:
        if page_num < 1 or page_num > len(doc):
            raise IndexError(f"Page {page_num} out of bounds (1..{len(doc)})")
        page = doc[page_num - 1]
        page_rect = page.rect

        if bbox:
            x0, y0, x1, y1 = bbox
            pad = 10.0
            clip = fitz.Rect(
                max(x0 - pad, page_rect.x0),
                max(y0 - pad, page_rect.y0),
                min(x1 + pad, page_rect.x1),
                min(y1 + pad, page_rect.y1),
            )
        else:
            clip = page_rect

        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        pix = page.get_pixmap(matrix=mat, clip=clip)
        return pix.tobytes("png")


def build_vlm_repair_prompt(
    corrupted_raw_md: str,
    golden_few_shots: List[Dict[str, str]],
    missing_badges: Optional[List[str]] = None,
) -> str:
    """Constructs prompt for multimodal LLM visual repair."""
    prompt_lines = [
        "你是一位專精於繁體/簡體中文圖書 POD 排版的專家。",
        "附圖為書籍原版 PDF 頁面截圖。原書中部分特殊標題、印章（如【組成】、【用法】）可能因美編轉曲而在生稿中遺失，或者存在版面欄位錯位。",
        "",
        "### 【標準排版範本 (Golden Reference)】",
    ]

    for ex in golden_few_shots[:2]:
        prompt_lines.extend([
            f"**範本單元：{ex.get('unit_title', '參考單元')}**",
            "```markdown",
            ex.get("golden_output", "").strip(),
            "```",
            "",
        ])

    missing_notice = ""
    if missing_badges:
        missing_notice = f"\n自動化檢測發現此區塊可能缺少以下必備標籤：{', '.join([f'【{b}】' for b in missing_badges])}，請在原圖中核對並補回。\n"

    prompt_lines.extend([
        f"### 【待修復生稿】{missing_notice}",
        "```markdown",
        corrupted_raw_md.strip(),
        "```",
        "",
        "### 任務要求：",
        "1. 對照 PDF 原圖，將生稿中遺失的標題、印章標籤（如【組成】、【用法】、【按語】）與文字準確補回。",
        "2. 嚴格套用 Pandoc `::: {custom-style=\"樣式名\"}` 標記。",
        "3. 直接回傳修復完成的 Markdown 內文，不需附加說明。",
    ])

    return "\n".join(prompt_lines)


def repair_corrupted_section_with_vlm(
    pdf_path: str | Path,
    page_num: int,
    corrupted_raw_md: str,
    blueprint: BookBlueprint,
    ai_client: Optional[Any] = None,
    bbox: Optional[Sequence[float]] = None,
    missing_badges: Optional[List[str]] = None,
) -> str:
    """
    Executes visual fallback repair.
    If ai_client is provided, calls multimodal model. Otherwise returns generated prompt.
    """
    image_bytes = render_page_crop(pdf_path, page_num, bbox=bbox, dpi=150)
    prompt = build_vlm_repair_prompt(
        corrupted_raw_md=corrupted_raw_md,
        golden_few_shots=blueprint.few_shot_examples,
        missing_badges=missing_badges,
    )

    if ai_client is not None:
        # Client invocation dispatch (e.g., google.genai, anthropic, or openai)
        if hasattr(ai_client, "models") and hasattr(ai_client.models, "generate_content"):
            # Google GenAI SDK
            resp = ai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[image_bytes, prompt],
            )
            return resp.text.strip()
        elif hasattr(ai_client, "generate_content"):
            resp = ai_client.generate_content([prompt, {"mime_type": "image/png", "data": image_bytes}])
            return resp.text.strip()
        elif callable(ai_client):
            return ai_client(prompt, image_bytes)

    # If no active client, return the prompt representation
    return f"<!-- VLM Repair Prompt Prepared ({len(image_bytes)} bytes image rendered) -->\n{prompt}"
