# -*- coding: utf-8 -*-
"""
Strict FastAPI Request & Response Schemas (P2/P3 Guardrail: Schema-Driven Development)
======================================================================================
Single Source of Truth for FastAPI OpenAPI generation and TypeScript contract codegen.
All models use `ConfigDict(extra="forbid")` to reject hallucinated keys at runtime.
"""

from __future__ import annotations
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class StrictApiSchema(BaseModel):
    """Base API schema forbidding undeclared fields."""
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# P2 / P2-B: POD Studio Contracts
# ---------------------------------------------------------------------------

class PodSectionPreview(StrictApiSchema):
    id: str
    title: str
    paragraphs: int = Field(..., ge=0)


class PodExtractRawResponse(StrictApiSchema):
    status: Literal["success"] = "success"
    session_id: str
    raw_docx_name: str
    ast_json_name: str
    total_sections: int = Field(..., ge=0)
    sections_preview: List[PodSectionPreview]


class PodCompileBlueprintResponse(StrictApiSchema):
    status: Literal["success"] = "success"
    session_id: str
    blueprint: Dict[str, Any]
    inferred_rules_count: int = Field(..., ge=0)
    mandatory_badges: List[str]
    detected_styles: List[str]
    boundary_idx: int = Field(..., ge=0)
    boundary_source: str
    manual_boundary_anchor: str
    boundary_context_text: str
    total_paragraphs: int = Field(..., ge=0)
    has_source_pdf: bool = False
    detected_tables_count: int = Field(default=0, ge=0)


class PodAuditSummary(StrictApiSchema):
    total_sections: int = Field(..., ge=0)
    passed_sections: int = Field(..., ge=0)
    failed_sections: int = Field(..., ge=0)
    green_count: int = Field(..., ge=0)
    yellow_count: int = Field(..., ge=0)
    red_count: int = Field(..., ge=0)
    violations_count: int = Field(..., ge=0)


class PodPropagateResponse(StrictApiSchema):
    status: Literal["success"] = "success"
    session_id: str
    engine_mode: Literal["rule_first", "vlm_continuation"]
    is_valid: bool
    final_docx_name: str
    audit_summary: PodAuditSummary
    audit_report: Dict[str, Any]


class PodVlmContinuationResponse(StrictApiSchema):
    status: Literal["success"] = "success"
    session_id: str
    result: Dict[str, Any]
    download_docx_url: str
    download_md_url: str
    audit_report_url: str


class RuleFirstPropagationPayload(StrictApiSchema):
    """Discriminated union branch for Rule-First deterministic propagation."""
    engine_mode: Literal["rule_first"] = "rule_first"
    session_id: str
    blueprint_json: Optional[str] = None
    manual_boundary_anchor: Optional[str] = None
    manual_boundary_idx: Optional[int] = Field(default=None, ge=0)


class VlmContinuationPropagationPayload(StrictApiSchema):
    """Discriminated union branch for VLM visual continuation."""
    engine_mode: Literal["vlm_continuation"] = "vlm_continuation"
    session_id: str
    model: str = "gemini-3.8-flash"
    max_continuation_sections: Optional[int] = Field(default=None, ge=1)
    blueprint_json: Optional[str] = None
    manual_boundary_anchor: Optional[str] = None
    manual_boundary_idx: Optional[int] = Field(default=None, ge=0)


PropagationPayload = Annotated[
    Union[RuleFirstPropagationPayload, VlmContinuationPropagationPayload],
    Field(discriminator="engine_mode"),
]


# ---------------------------------------------------------------------------
# P2-A: Automated Draft & Font Mapping Workbench (`ocr_pipeline.html`)
# ---------------------------------------------------------------------------

class OcrFileUploadResponse(StrictApiSchema):
    file_id: str
    filename_orig: str
    filename_stem: str


class OcrRunStartResponse(StrictApiSchema):
    message: str
    filename_stem: str
    task_id: str


class OcrProgressResponse(StrictApiSchema):
    task_id: Optional[str] = None
    progress: int = Field(..., ge=0, le=100)
    message: str
    status: Literal["processing", "completed", "failed", "queued", "running"]
    error: Optional[str] = None
    created_at: Optional[float] = None


class FontInfoItem(StrictApiSchema):
    name: str
    full_name: str
    size_pt: float
    sample_texts: List[str] = Field(default_factory=list)
    current_role: Optional[str] = "auto"
    current_docx_style: Optional[str] = None


class FontScanResponse(StrictApiSchema):
    fonts: List[FontInfoItem]
    docx_styles: List[str] = Field(default_factory=list)
    default_roles: List[str] = Field(default_factory=list)


class FontMappingEntry(StrictApiSchema):
    role: Optional[str] = None
    docx_style: Optional[str] = None
    mapped_by: Optional[str] = "user"


class FontMappingSaveRequest(StrictApiSchema):
    mapping: Dict[str, FontMappingEntry] = Field(default_factory=dict)
    remove_keys: List[str] = Field(default_factory=list)


class FontMappingSaveResponse(StrictApiSchema):
    status: Literal["success"] = "success"
    saved: int = Field(..., ge=0)
    removed: int = Field(default=0, ge=0)
    message: str


class QueueTaskItem(StrictApiSchema):
    task_id: str
    stem: str
    status: str
    progress: int = Field(..., ge=0, le=100)
    message: str
    engine: str = "auto"
    error: Optional[str] = None
    created_at: float
    updated_at: float


class QueueTasksResponse(StrictApiSchema):
    tasks: List[QueueTaskItem]


class MarkdownRebuildRequest(StrictApiSchema):
    content: str


class MarkdownRebuildResponse(StrictApiSchema):
    status: Literal["success"] = "success"
    message: str


# ---------------------------------------------------------------------------
# P2-C: AI Formula & Dual-Mode Workbench (`formula.html`)
# ---------------------------------------------------------------------------

class FormulaTaskSubmitResponse(StrictApiSchema):
    task_id: str


class FormulaTaskStatusResponse(StrictApiSchema):
    status: Literal["processing", "completed", "failed"]
    progress: int = Field(..., ge=0, le=100)
    message: str
    mode: str
    total_pages: int = Field(default=0, ge=0)
    current_page: int = Field(default=0, ge=0)
    results: List[Dict[str, Any]] = Field(default_factory=list)
    final_files: Dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# P2-D: Utility Subpages & Global Sidebar (`extract_images`, `founder_repair`, `sidebar`)
# ---------------------------------------------------------------------------

class ExtractImagesResponse(StrictApiSchema):
    success: bool
    count: int = Field(..., ge=0)
    message: str = ""
    download_url: str = ""
    filename: str = ""
    source_path: str = ""


class FounderRepairResponse(StrictApiSchema):
    success: bool = True
    source_path: str
    filename: str


class HardwareStatusResponse(StrictApiSchema):
    gpu_name: str = "Unknown"
    target_accelerator: str = "CPU"
    active_provider: str = "CPUExecutionProvider"
    vram_gb: float = 0.0
    is_accelerated: bool = False


class UpdateCheckResponse(StrictApiSchema):
    current_version: str
    latest_version: str
    has_update: bool
    download_url: str = ""
    release_notes: str = ""
    published_at: str = ""
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# P1 / P2 / P3 Upgrades: Handoff, SSE & Observability Contracts
# ---------------------------------------------------------------------------

class PodHandoffResponse(StrictApiSchema):
    status: Literal["success"] = "success"
    session_id: str
    docx_name: str
    pdf_name: str
    total_paragraphs: int = Field(default=0, ge=0)
    message: str = "已成功由 OCR 產出初稿建立 POD 整稿工作區"


class HardwareTelemetryResponse(StrictApiSchema):
    gpu_name: str = "Unknown"
    target_accelerator: str = "CPU"
    active_provider: str = "CPUExecutionProvider"
    total_vram_gb: float = 0.0
    allocated_vram_mb: float = 0.0
    reserved_vram_mb: float = 0.0
    vram_usage_percent: float = 0.0
    is_accelerated: bool = False
    gpu_locked: bool = False
    app_mode: str = "editor"
