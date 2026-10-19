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
)
from .exemplar_learner import ExemplarLearner
from .section_ast import SectionUnit, SectionAST
from .propagation_engine import PropagationEngine
from .visual_fallback_repair import render_page_crop, build_vlm_repair_prompt, repair_corrupted_section_with_vlm
from .pod_validator import PodValidator, ValidationReport, ValidationViolation

__all__ = [
    "StyleTriggerRule",
    "BookBlueprint",
    "ExemplarLearner",
    "SectionUnit",
    "SectionAST",
    "PropagationEngine",
    "render_page_crop",
    "build_vlm_repair_prompt",
    "repair_corrupted_section_with_vlm",
    "PodValidator",
    "ValidationReport",
    "ValidationViolation",
]
