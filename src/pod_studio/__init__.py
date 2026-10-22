# -*- coding: utf-8 -*-
"""
POD Studio Domain Module
========================
High-reliability Publisher POD (Print-On-Demand) workflow engine.
Combines exemplar learning from human pre-processed samples, Markdown AST sectioning,
deterministic rule propagation, visual fallback repair, and CLI validation gatekeeping.
"""

from .blueprint_schema import (
    StyleTriggerRule,
    BookBlueprint,
    ValidationConfig,
    IndexTaggingInstruction,
)
from .cjk_validator import PODIntegrityValidator, CJKValidationResult
from .exemplar_learner import ExemplarLearner, DiffAligner
from .section_ast import SectionUnit, ParagraphUnit, SectionAST, BookAST, SectionAdapter
from .propagation_engine import PropagationEngine
from .visual_fallback_repair import render_page_crop, build_vlm_repair_prompt, repair_corrupted_section_with_vlm
from .pod_validator import PodValidator, ValidationReport, ValidationViolation
from .pod_service import (
    extract_raw_from_pdf,
    extract_raw_from_pdf_ast,
    extract_raw_from_markdown,
    compile_blueprint_from_seed,
    propagate_and_validate_session,
)

__all__ = [
    "StyleTriggerRule",
    "BookBlueprint",
    "ValidationConfig",
    "IndexTaggingInstruction",
    "PODIntegrityValidator",
    "CJKValidationResult",
    "ExemplarLearner",
    "DiffAligner",
    "SectionUnit",
    "ParagraphUnit",
    "SectionAST",
    "BookAST",
    "SectionAdapter",
    "PropagationEngine",
    "render_page_crop",
    "build_vlm_repair_prompt",
    "repair_corrupted_section_with_vlm",
    "PodValidator",
    "ValidationReport",
    "ValidationViolation",
    "extract_raw_from_pdf",
    "extract_raw_from_pdf_ast",
    "extract_raw_from_markdown",
    "compile_blueprint_from_seed",
    "propagate_and_validate_session",
]
