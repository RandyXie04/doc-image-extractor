# -*- coding: utf-8 -*-
"""
POD VLM Continuation & Infilling Engine
=======================================
安全合規：NIST CSF (Protect/Detect) / ISO 27001
職責：
1. 結合階段一之原版 PDF 頁面截圖 (150 DPI) 與粗糙 OCR 文字骨架。
2. 結合階段二之前 5%~10% 人工後處理 DOCX (Golden Seed)。
3. 調度 Gemini 或本機 Ollama 視覺模型，以 Few-Shot 視覺學習自動完成剩餘段落接續整稿。
4. 強制執行 UUID 工作區隔離、背景線程防阻塞、非機率型 CJK 骨架守恆檢驗。
"""

from __future__ import annotations

import os
import re
import io
import json
import uuid
import base64
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Sequence
from dataclasses import dataclass, asdict, field

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Inches
import fitz
from src.pod_studio.section_ast import SectionAST, SectionUnit, ParagraphUnit
from src.pod_studio.blueprint_schema import BookBlueprint
from src.pod_studio.cjk_validator import PODIntegrityValidator, CJKValidationResult
from src.pod_studio.docx_writer import DocxSerializer


@dataclass
class VisualExemplarPair:
    """前 5%~10% 範本之多模態對齊結構"""
    section_title: str
    page_num: int
    raw_ocr_skeleton: str
    golden_markdown: str
    page_image_bytes: bytes


@dataclass
class ContinuationResult:
    """接續處理結果"""
    session_id: str
    total_sections: int
    seed_sections_count: int
    continued_sections_count: int
    completed_docx_path: str
    completed_md_path: str
    validation_passed: bool
    character_retention_rate: float
    violations: List[str]
    section_summaries: List[Dict[str, Any]] = field(default_factory=list)
    processed_sections: List[SectionUnit] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("processed_sections", None)
        return d


class SecureVLMContinuationEngine:
    """
    結合 Surya/PyMuPDF OCR 骨架與前 5%~10% 人工 DOCX 之視覺整稿接續引擎
    """

    def __init__(
        self,
        workspace_base: Path,
        max_concurrency: int = 2,
        dpi: int = 150,
    ) -> None:
        self.workspace_base = Path(workspace_base).resolve()
        self.workspace_base.mkdir(parents=True, exist_ok=True)
        self.max_concurrency = max(1, max_concurrency)
        self.dpi = dpi
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    def _render_page_image_sync(self, pdf_path: Path, page_num: int) -> bytes:
        """
        [防禦性設計] 同步渲染 PDF 頁面截圖，並確保 Document 資源及時釋放
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF 檔案不存在: {pdf_path.name}")

        with fitz.open(str(pdf_path)) as doc:
            if page_num < 1 or page_num > len(doc):
                raise IndexError(f"頁碼 {page_num} 超出文件範圍 (1..{len(doc)})")
            page = doc[page_num - 1]
            mat = fitz.Matrix(self.dpi / 72.0, self.dpi / 72.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            return pix.tobytes("png")

    async def render_page_image(self, pdf_path: Path, page_num: int) -> bytes:
        """非阻塞非同步渲染 PDF 頁面"""
        return await asyncio.to_thread(self._render_page_image_sync, pdf_path, page_num)

    def extract_seed_exemplars_sync(
        self,
        pdf_path: Path,
        raw_sections: List[SectionUnit],
        seed_docx_path: Path,
        max_exemplars: int = 2,
    ) -> Tuple[List[VisualExemplarPair], int]:
        """
        比對人工精修 DOCX 與生稿 AST，識別出已人工精修的章節數 (seed_count)，
        並提取 Few-Shot 視覺示範對 (PDF 截圖 + 精修 Markdown)
        """
        if not seed_docx_path.exists() or not raw_sections:
            return [], 0

        seed_doc = docx.Document(str(seed_docx_path))
        seed_paras = [p.text.strip() for p in seed_doc.paragraphs if p.text.strip()]
        full_seed_text = "\n\n".join(seed_paras)

        exemplars: List[VisualExemplarPair] = []
        seed_count = 0

        for sec in raw_sections:
            if sec.title == "__PREAMBLE__":
                seed_count += 1
                continue

            sec_clean_title = re.sub(r'^[#\s]+', '', sec.title).strip()
            # 檢查此章節是否出現在人工精修檔案中
            first_p_snip = sec.paragraphs[0].raw_text[:20].strip() if sec.paragraphs else ""

            matched = (sec_clean_title and sec_clean_title in full_seed_text) or (first_p_snip and first_p_snip in full_seed_text)

            if matched:
                seed_count += 1
                if len(exemplars) < max_exemplars and sec.paragraphs:
                    sec_page = sec.paragraphs[0].page_num if sec.paragraphs[0].page_num > 0 else 1
                    try:
                        page_img = self._render_page_image_sync(pdf_path, sec_page)
                    except Exception:
                        page_img = b""

                    sec_raw_text = "\n\n".join(p.raw_text for p in sec.paragraphs)
                    # 擷取對應 golden 段落
                    golden_snip = ""
                    idx = full_seed_text.find(sec_clean_title)
                    if idx != -1:
                        golden_snip = full_seed_text[idx:idx + 1200]
                    else:
                        golden_snip = full_seed_text[:1200]

                    exemplars.append(
                        VisualExemplarPair(
                            section_title=sec.title,
                            page_num=sec_page,
                            raw_ocr_skeleton=sec_raw_text[:600],
                            golden_markdown=golden_snip,
                            page_image_bytes=page_img,
                        )
                    )
            else:
                # 一旦遇到未在 seed 出現的章節，認定為接續起點
                break

        return exemplars, max(1, seed_count)

    def _build_continuation_prompt(
        self,
        exemplars: List[VisualExemplarPair],
        current_section_title: str,
        current_ocr_draft: str,
    ) -> str:
        """建立引導 VLM 進行視覺比對與樣式接續的 Prompt"""
        prompt_parts: List[str] = [
            "你是一位專精於中文圖書出版與數位 POD 整稿的排版專家。",
            "任務：請比對附帶的 PDF 原版頁面截圖，並參照前 5%~10% 的【人工排版示範 (Golden Reference)】，",
            "將本單元的【粗糙 OCR 生稿】重構成符合出版規範的結構化 Markdown 內文。",
            "",
            "### 【規範約束 (Mandatory Constraints)】",
            "1. 【版面修復】：原版 PDF 中的特殊印章（如【導讀】、【案例分析】、【重點提醒】）、欄位與多欄圖文，若在生稿中遺失或錯位，請依原圖精確補齊。",
            "2. 【樣式標記】：套用 Pandoc 語法標記自訂樣式，例如 `::: {custom-style=\"樣式名\"}`，並保留標準標題階層 (#, ##, ###)。",
            "3. 【文字嚴謹度】：絕不可憑空捏造、杜撰或刪減書本正文文字，必須忠實反映 PDF 原始文字。",
            "4. 【輸出格式】：直接輸出修復後的 Markdown，嚴禁加入「好的」、「以下是為您整理」等交談贅詞。",
            "",
            "### 【人工精修範本參照】",
        ]

        for idx, ex in enumerate(exemplars, 1):
            prompt_parts.extend([
                f"--- 範例 {idx} ({ex.section_title}) ---",
                "[範本輸出樣式]:",
                ex.golden_markdown[:400] + "...",
                "",
            ])

        prompt_parts.extend([
            f"### 【待接續單元：{current_section_title}】",
            "[粗糙 OCR 草稿 (供文字對照避免漏字)]:",
            "```text",
            current_ocr_draft.strip(),
            "```",
            "",
            "請立即輸出接續完成的 Markdown 內容：",
        ])

        return "\n".join(prompt_parts)

    async def _call_vlm_infer(
        self,
        prompt: str,
        image_bytes: bytes,
        model_name: str = "gemini-2.5-flash",
    ) -> str:
        """
        支援 Gemini API 與本機 Ollama 多模態呼叫，包含安全防護與例外脫敏
        """
        async with self._semaphore:
            api_key = os.getenv("GEMINI_API_KEY", "")

            # 1. 優先嘗試使用 Gemini API
            if api_key and ("gemini" in model_name.lower()):
                try:
                    from google import genai
                    from google.genai import types

                    client = genai.Client(api_key=api_key)
                    image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")

                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model=model_name,
                        contents=[
                            types.Content(
                                role="user",
                                parts=[image_part, types.Part.from_text(text=prompt)],
                            )
                        ],
                    )
                    out_text = response.text or ""
                    # 清理 markdown 代碼塊包裹
                    out_text = re.sub(r'^```(?:markdown)?\n?', '', out_text.strip())
                    out_text = re.sub(r'\n?```$', '', out_text.strip())
                    return out_text
                except Exception as err:
                    return f"<!-- VLM_FAIL: Gemini 推論異常 ({type(err).__name__}) -->"

            # 2. 本機 Ollama 視覺模型 (如 qwen2.5-vl:7b, llama3.2-vision)
            ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
            target_ollama_model = model_name if ("gemini" not in model_name.lower()) else "qwen2.5-vl:7b"
            try:
                import urllib.request

                b64_img = base64.b64encode(image_bytes).decode("utf-8")
                payload = json.dumps({
                    "model": target_ollama_model,
                    "prompt": prompt,
                    "images": [b64_img],
                    "stream": False,
                }).encode("utf-8")

                def _sync_ollama():
                    req = urllib.request.Request(
                        f"{ollama_host}/api/generate",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=180) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        return res_data.get("response", "")

                raw_resp = await asyncio.to_thread(_sync_ollama)
                raw_resp = re.sub(r'^```(?:markdown)?\n?', '', raw_resp.strip())
                raw_resp = re.sub(r'\n?```$', '', raw_resp.strip())
                return raw_resp
            except Exception as err:
                return f"<!-- VLM_FAIL: Ollama 推論異常 ({type(err).__name__}) -->"

    def _save_sections_to_docx(
        self,
        sections: List[SectionUnit],
        output_docx_path: Path,
        template_docx_path: Optional[Path] = None,
    ) -> None:
        """
        將完成接續之 Section 列表寫入正式 DOCX，委派至 DocxSerializer 統一處理。
        """
        DocxSerializer.render_sections_to_docx(
            sections=sections,
            output_docx_path=output_docx_path,
            template_docx_path=template_docx_path,
        )

    async def execute_continuation(
        self,
        pdf_path: Path,
        raw_ast_path: Path,
        seed_docx_path: Path,
        template_docx_path: Optional[Path] = None,
        model_name: str = "gemini-2.5-flash",
        max_continuation_sections: Optional[int] = None,
        target_session_dir: Optional[Path] = None,
    ) -> ContinuationResult:
        """
        執行前 5%~10% 後續段落的完整視覺接續流程
        """
        if target_session_dir:
            session_dir = Path(target_session_dir).resolve()
            session_id = session_dir.name
        else:
            session_id = f"pod_vlm_{uuid.uuid4().hex[:12]}"
            session_dir = self.workspace_base / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        violations: List[str] = []

        # 1. 讀取 AST
        raw_sections = SectionAST.load_book_ast_json(raw_ast_path)
        if not raw_sections:
            raise ValueError(f"AST 檔案未包含任何有效單元: {raw_ast_path.name}")

        # 2. 比對精修 DOCX，定位接續切分點 (Seed Index) 與提取 Few-Shot 示範
        exemplars, seed_count = await asyncio.to_thread(
            self.extract_seed_exemplars_sync,
            pdf_path,
            raw_sections,
            seed_docx_path,
        )

        processed_sections: List[SectionUnit] = []
        section_summaries: List[Dict[str, Any]] = []

        total_raw_chars = 0
        total_final_chars = 0
        continued_count = 0

        # 3. 遍歷章節進行接續推論
        for idx, sec in enumerate(raw_sections):
            is_seed_section = (idx < seed_count)

            if is_seed_section:
                processed_sections.append(sec)
                section_summaries.append({
                    "id": sec.section_id,
                    "title": sec.title,
                    "source": "human_seed",
                    "status": "PASS",
                })
                continue

            if max_continuation_sections and continued_count >= max_continuation_sections:
                # 測試模式下可限制接續章節數
                processed_sections.append(sec)
                section_summaries.append({
                    "id": sec.section_id,
                    "title": sec.title,
                    "source": "raw_unprocessed",
                    "status": "SKIPPED",
                })
                continue

            sec_page = sec.paragraphs[0].page_num if (sec.paragraphs and sec.paragraphs[0].page_num > 0) else 1
            raw_text = "\n\n".join(p.raw_text for p in sec.paragraphs)
            raw_chars = len(re.sub(r'\s+', '', raw_text))
            total_raw_chars += raw_chars

            # 渲染該頁面影像
            try:
                page_img = await self.render_page_image(pdf_path, sec_page)
            except Exception:
                page_img = b""

            prompt = self._build_continuation_prompt(
                exemplars=exemplars,
                current_section_title=sec.title,
                current_ocr_draft=raw_text,
            )

            # 呼叫 VLM 進行視覺整稿接續
            if page_img:
                repaired_md = await self._call_vlm_infer(prompt, page_img, model_name=model_name)
            else:
                repaired_md = raw_text

            if repaired_md.startswith("<!-- VLM_FAIL"):
                violations.append(f"單元 [{sec.title}] VLM 推論異常，回退為原始草稿。")
                sec.processed_content = raw_text
                sec_status = "FALLBACK"
            else:
                sec.processed_content = repaired_md
                sec_status = "VLM_CONTINUED"

            final_chars = len(re.sub(r'[\s#:\-\{\}\[\]\(\)\=]+', '', sec.effective_content))
            total_final_chars += final_chars
            continued_count += 1

            processed_sections.append(sec)
            section_summaries.append({
                "id": sec.section_id,
                "title": sec.title,
                "source": "vlm_continuation",
                "status": sec_status,
                "raw_chars": raw_chars,
                "final_chars": final_chars,
            })

        # 4. 輸出接續後的 DOCX 與 Markdown
        output_docx_path = session_dir / "Book_VLM_Continued.docx"
        output_md_path = session_dir / "Book_VLM_Continued.md"

        full_md_content = "\n\n".join(s.effective_content for s in processed_sections)
        output_md_path.write_text(full_md_content, encoding="utf-8")

        await asyncio.to_thread(
            self._save_sections_to_docx,
            processed_sections,
            output_docx_path,
            template_docx_path,
        )

        # 5. 骨架字元守恆率驗證
        retention_rate = (total_final_chars / total_raw_chars) if total_raw_chars > 0 else 1.0
        validation_passed = retention_rate >= 0.90

        if not validation_passed:
            violations.append(f"字元留存率未達標: {retention_rate:.2%} (< 90.0%)")

        result = ContinuationResult(
            session_id=session_id,
            total_sections=len(raw_sections),
            seed_sections_count=seed_count,
            continued_sections_count=continued_count,
            completed_docx_path=str(output_docx_path),
            completed_md_path=str(output_md_path),
            validation_passed=validation_passed,
            character_retention_rate=round(retention_rate, 4),
            violations=violations,
            section_summaries=section_summaries,
            processed_sections=processed_sections,
        )

        # 保存審計報表
        report_path = session_dir / "vlm_audit_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

        return result
