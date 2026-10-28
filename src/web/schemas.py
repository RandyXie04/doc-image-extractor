# -*- coding: utf-8 -*-
"""
Strict FastAPI Request & Response Schemas (P2 Guardrail: Schema-Driven Development)
===================================================================================
Single Source of Truth for FastAPI OpenAPI generation and TypeScript contract codegen.
All models use `ConfigDict(extra="forbid")` to reject hallucinated keys at runtime.
"""

from __future__ import annotations
from typing import Annotated, Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class StrictApiSchema(BaseModel):
    """Base API schema forbidding undeclared fields."""
    model_config = ConfigDict(extra="forbid")


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

