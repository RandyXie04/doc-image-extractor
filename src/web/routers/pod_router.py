# -*- coding: utf-8 -*-
"""
POD Studio FastAPI Router (`src/web/routers/pod_router.py`)
===========================================================
Modularized from `src/web/app.py` (P3-4 Risk 4 Remediation).
All endpoints enforce strict Pydantic v2 `response_model` contracts from `src/web/schemas.py`.
"""

from __future__ import annotations
import uuid
from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.pod_studio.blueprint_schema import BookBlueprint
from src.pod_studio.pod_service import (
    compile_blueprint_from_seed,
    extract_raw_from_markdown,
    extract_raw_from_pdf,
    propagate_and_validate_session,
)
from src.pod_studio.vlm_continuation_engine import SecureVLMContinuationEngine
from src.web.schemas import (
    PodAuditSummary,
    PodCompileBlueprintResponse,
    PodExtractRawResponse,
    PodPropagateResponse,
    PodSectionPreview,
    PodVlmContinuationResponse,
)

router = APIRouter(tags=["pod_studio"])


def _get_web_deps():
    import src.web.app as _web_app
    return _web_app.PATHS, _web_app.CFG, _web_app.save_upload_file_safely


@router.post("/api/pod/1_extract_raw", response_model=PodExtractRawResponse)
async def pod_1_extract_raw(
    file: UploadFile = File(...),
    split_level: int = Form(2),
) -> PodExtractRawResponse:
    """
    階段一：初稿生成 API
    上傳 PDF 或 MD 原稿，輸出 Book_raw.docx 與包含幾何座標的 Book_raw_ast.json。
    """
    PATHS, CFG, save_upload_file_safely = _get_web_deps()
    session_id = f"pod_{uuid.uuid4().hex[:12]}"
    session_dir = PATHS.output_dir / "pod_workspaces" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    input_path = session_dir / (file.filename or "input_book.pdf")
    await save_upload_file_safely(file, input_path, max_mb=CFG.max_upload_size_mb)

    ext = input_path.suffix.lower()
    if ext == ".pdf":
        sections, ast_path, raw_docx_path = extract_raw_from_pdf(input_path, session_dir, split_level=split_level)
    elif ext in (".md", ".txt"):
        md_text = input_path.read_text(encoding="utf-8")
        sections, ast_path, raw_docx_path = extract_raw_from_markdown(md_text, session_dir, split_level=split_level)
    else:
        raise HTTPException(status_code=400, detail="生稿僅支援 .pdf 或 .md 檔案")

    return PodExtractRawResponse(
        status="success",
        session_id=session_id,
        raw_docx_name=raw_docx_path.name,
        ast_json_name=ast_path.name,
        total_sections=len(sections),
        sections_preview=[
            PodSectionPreview(id=s.section_id, title=s.title, paragraphs=len(s.paragraphs))
            for s in sections[:10]
        ],
    )


@router.post("/api/pod/2_compile_blueprint", response_model=PodCompileBlueprintResponse)
async def pod_2_compile_blueprint(
    seed_file: UploadFile = File(...),
    pdf_file: Optional[UploadFile] = File(None),
    session_id: Optional[str] = Form(None),
    manual_boundary_anchor: Optional[str] = Form(None),
    manual_boundary_idx: Optional[int] = Form(None),
) -> PodCompileBlueprintResponse:
    """
    範本學習與藍圖合成 API
    比對人工精修範本推導樣式定義與狀態機轉換規則。
    若提供原始 PDF (pdf_file)，則直接解析完整幾何結構與三線表，建立 Book_raw_ast.json。
    """
    PATHS, CFG, save_upload_file_safely = _get_web_deps()
    if not session_id:
        session_id = f"pod_{uuid.uuid4().hex[:12]}"
    session_dir = PATHS.output_dir / "pod_workspaces" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    seed_path = session_dir / (seed_file.filename or "Book_seed.docx")
    await save_upload_file_safely(seed_file, seed_path, max_mb=CFG.max_template_size_mb)

    ast_path = session_dir / "Book_raw_ast.json"
    has_source_pdf = False
    detected_tables_count = 0

    if pdf_file and pdf_file.filename:
        source_pdf_path = session_dir / "source_book.pdf"
        await save_upload_file_safely(pdf_file, source_pdf_path, max_mb=CFG.max_upload_size_mb)
        has_source_pdf = True
        try:
            from src.scripts.book_layout_extractor import extract_book_vector_ast
            from src.pod_studio.section_ast import SectionAST
            book_ast = extract_book_vector_ast(source_pdf_path, enable_footnotes=False)
            SectionAST.dump_book_ast_json(book_ast.sections, ast_path)
            detected_tables_count = sum(
                1 for sec in book_ast.sections for p in sec.paragraphs if p.font_name == "table"
            )
        except Exception as e:
            print(f"[POD Warning] Failed to extract vector AST from uploaded source PDF: {e}")

    if not ast_path.exists() and seed_path.suffix.lower() == ".docx":
        import docx
        from src.pod_studio.section_ast import SectionAST, SectionUnit, ParagraphUnit
        seed_doc = docx.Document(str(seed_path))
        sections = [
            SectionUnit(
                section_id=f"sec_{i:03d}",
                title=p.text[:30],
                level=1,
                paragraphs=[ParagraphUnit(para_id=f"p_{i}", raw_text=p.text)],
                raw_content=p.text,
            )
            for i, p in enumerate(seed_doc.paragraphs)
        ]
        SectionAST.dump_book_ast_json(sections, ast_path)

    blueprint = compile_blueprint_from_seed(
        session_dir,
        seed_path,
        manual_boundary_anchor=manual_boundary_anchor,
        manual_boundary_idx=manual_boundary_idx,
    )
    if has_source_pdf:
        blueprint.metadata["has_source_pdf"] = True
        blueprint.metadata["detected_tables_count"] = detected_tables_count
        blueprint.save(session_dir / "book_blueprint.json")

    return PodCompileBlueprintResponse(
        status="success",
        session_id=session_id,
        blueprint=blueprint.to_dict(),
        inferred_rules_count=len(blueprint.style_rules),
        mandatory_badges=blueprint.mandatory_section_badges,
        detected_styles=blueprint.template_styles_used,
        boundary_idx=blueprint.metadata.get("seed_last_modified_idx", 0),
        boundary_source=blueprint.metadata.get("boundary_source", "auto_heuristic"),
        manual_boundary_anchor=blueprint.metadata.get("manual_boundary_anchor", ""),
        boundary_context_text=blueprint.metadata.get("boundary_context_text", ""),
        total_paragraphs=blueprint.metadata.get("seed_total_paragraphs", 0),
        has_source_pdf=has_source_pdf,
        detected_tables_count=detected_tables_count,
    )


@router.post("/api/pod/3_propagate_and_validate", response_model=PodPropagateResponse)
async def pod_3_propagate_and_validate(
    session_id: str = Form(...),
    engine_mode: str = Form("rule_first"),
    template_file: Optional[UploadFile] = File(None),
    blueprint_json: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    max_continuation_sections: Optional[int] = Form(None),
    manual_boundary_anchor: Optional[str] = Form(None),
    manual_boundary_idx: Optional[int] = Form(None),
) -> PodPropagateResponse:
    """
    階段三：批量擴散與硬性驗收 API (支援 Dual-Engine: rule_first 與 vlm_continuation)
    """
    PATHS, CFG, save_upload_file_safely = _get_web_deps()
    session_dir = PATHS.output_dir / "pod_workspaces" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Session 不存在或已過期")

    template_path = None
    if template_file and template_file.filename:
        template_path = session_dir / "template.docx"
        await save_upload_file_safely(template_file, template_path, max_mb=CFG.max_template_size_mb)

    custom_bp = None
    if blueprint_json:
        try:
            custom_bp = BookBlueprint.from_json(blueprint_json)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"自訂 Blueprint JSON 格式錯誤: {e}")

    pdf_files = list(session_dir.glob("*.pdf"))
    pdf_path = pdf_files[0] if pdf_files else None

    final_docx_path, report, _ = propagate_and_validate_session(
        session_dir=session_dir,
        engine_mode=engine_mode,
        template_docx_path=template_path,
        custom_blueprint=custom_bp,
        pdf_path=pdf_path,
        model=model,
        max_sections=max_continuation_sections,
        manual_boundary_anchor=manual_boundary_anchor,
        manual_boundary_idx=manual_boundary_idx,
    )

    resolved_mode = "vlm_continuation" if engine_mode == "vlm_continuation" else "rule_first"
    return PodPropagateResponse(
        status="success",
        session_id=session_id,
        engine_mode=resolved_mode,
        is_valid=report.is_valid,
        final_docx_name=final_docx_path.name,
        audit_summary=PodAuditSummary(
            total_sections=report.total_sections,
            passed_sections=report.passed_sections,
            failed_sections=report.failed_sections,
            green_count=report.green_count,
            yellow_count=report.yellow_count,
            red_count=report.red_count,
            violations_count=len(report.violations),
        ),
        audit_report=report.to_dict(),
    )


@router.get("/api/pod/download/{session_id}/{filename}")
async def pod_download_file(session_id: str, filename: str):
    """下載 POD 工作區之產出物 (Book_raw.docx, Book_POD_Final.docx, audit_report.json 等)"""
    PATHS, _, _ = _get_web_deps()
    session_dir = (PATHS.output_dir / "pod_workspaces" / session_id).resolve()
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="Session 不存在")

    target_file = (session_dir / filename).resolve()
    if not target_file.is_relative_to(session_dir) or not target_file.exists():
        raise HTTPException(status_code=404, detail="檔案不存在或存取受限")

    media_type = "application/octet-stream"
    if filename.endswith(".docx"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif filename.endswith(".json"):
        media_type = "application/json"
    elif filename.endswith(".md"):
        media_type = "text/markdown"

    return FileResponse(path=str(target_file), media_type=media_type, filename=filename)


@router.post("/api/pod/vlm_continuation", response_model=PodVlmContinuationResponse)
async def pod_vlm_continuation(
    session_id: Optional[str] = Form(None),
    pdf_file: Optional[UploadFile] = File(None),
    seed_file: UploadFile = File(...),
    template_file: Optional[UploadFile] = File(None),
    model_name: str = Form("gemini-2.5-flash"),
    max_continuation_sections: Optional[int] = Form(None),
    split_level: int = Form(2),
    manual_boundary_anchor: Optional[str] = Form(None),
    manual_boundary_idx: Optional[int] = Form(None),
) -> PodVlmContinuationResponse:
    """
    POD 視覺整稿接續 API (VLM Continuation & Infilling)
    結合階段一 PDF 與前 5%~10% 人工精修 DOCX (Golden Seed)，
    利用 Gemini 或 Ollama 視覺多模態模型接續完成全書排版。
    """
    PATHS, CFG, save_upload_file_safely = _get_web_deps()
    if session_id:
        session_dir = (PATHS.output_dir / "pod_workspaces" / session_id).resolve()
        if not session_dir.exists():
            raise HTTPException(status_code=404, detail="指定 Session 不存在或已過期")
    else:
        session_id = f"pod_vlm_{uuid.uuid4().hex[:12]}"
        session_dir = PATHS.output_dir / "pod_workspaces" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = None
    if pdf_file and pdf_file.filename:
        pdf_path = session_dir / pdf_file.filename
        await save_upload_file_safely(pdf_file, pdf_path, max_mb=CFG.max_upload_size_mb)
    else:
        existing_pdfs = list(session_dir.glob("*.pdf"))
        if existing_pdfs:
            pdf_path = existing_pdfs[0]

    if not pdf_path or not pdf_path.exists():
        raise HTTPException(status_code=400, detail="請提供原始 PDF 檔案")

    ast_path = session_dir / "Book_raw_ast.json"
    if not ast_path.exists():
        try:
            _, ast_path, _ = extract_raw_from_pdf(
                pdf_path, session_dir, split_level=split_level
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF 生稿剖析失敗: {e}")

    seed_path = session_dir / (seed_file.filename or "Book_seed.docx")
    await save_upload_file_safely(seed_file, seed_path, max_mb=CFG.max_template_size_mb)

    template_path = None
    if template_file and template_file.filename:
        template_path = session_dir / "template.docx"
        await save_upload_file_safely(template_file, template_path, max_mb=CFG.max_template_size_mb)

    engine = SecureVLMContinuationEngine(
        workspace_base=PATHS.output_dir / "pod_workspaces"
    )

    try:
        result = await engine.execute_continuation(
            pdf_path=pdf_path,
            raw_ast_path=ast_path,
            seed_docx_path=seed_path,
            template_docx_path=template_path,
            model_name=model_name,
            max_continuation_sections=max_continuation_sections,
            target_session_dir=session_dir,
            manual_boundary_anchor=manual_boundary_anchor,
            manual_boundary_idx=manual_boundary_idx,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"視覺接續流程執行異常: {str(e)}")

    return PodVlmContinuationResponse(
        status="success",
        session_id=session_id,
        result=result.to_dict(),
        download_docx_url=f"/api/pod/download/{session_id}/Book_VLM_Continued.docx",
        download_md_url=f"/api/pod/download/{session_id}/Book_VLM_Continued.md",
        audit_report_url=f"/api/pod/download/{session_id}/vlm_audit_report.json",
    )

