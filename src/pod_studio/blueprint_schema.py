# -*- coding: utf-8 -*-
"""
Blueprint Schema
================
Defines data structures for book styling blueprints, semantic triggers,
mandatory section badges, few-shot pairs, and book-specific validation configurations.
Supports arbitrary book archetypes (novels, Q&A, recipes, academic, legal, technical).
"""

from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional


@dataclass
class ValidationConfig:
    """
    Book-specific quality gate settings.
    Allows turning on/off or adjusting checks depending on book structure.
    """
    enable_flowcheck: bool = True
    max_shrink_ratio: float = 0.40
    enable_badge_check: bool = True       # Only active when mandatory_section_badges is non-empty
    enable_numbering_check: bool = False   # Enabled only when the exemplar indicates structured numbering
    enable_style_check: bool = True
    strict_mode: bool = False              # If True, treat warnings as errors
    custom_rules: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ValidationConfig:
        return cls(
            enable_flowcheck=data.get("enable_flowcheck", True),
            max_shrink_ratio=data.get("max_shrink_ratio", 0.40),
            enable_badge_check=data.get("enable_badge_check", True),
            enable_numbering_check=data.get("enable_numbering_check", False),
            enable_style_check=data.get("enable_style_check", True),
            strict_mode=data.get("strict_mode", False),
            custom_rules=dict(data.get("custom_rules", {})),
        )


@dataclass
class StyleTriggerRule:
    """
    Describes text-based or structural features that trigger Word custom styles,
    badge injections (e.g., 【導讀】, 【重點】), or text transformations.
    """
    rule_id: str
    target_docx_style: str = ""
    inject_prefix_badge: str = ""      # e.g., "【導讀】" when missing from outlined text
    trigger_regex: str = ""            # Regex trigger
    action: str = "apply_style"        # "apply_style" | "inject_badge" | "delete_line" | "split_circled_num"
    priority: int = 10                 # Lower number = higher priority

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StyleTriggerRule:
        return cls(
            rule_id=data.get("rule_id", ""),
            target_docx_style=data.get("target_docx_style", ""),
            inject_prefix_badge=data.get("inject_prefix_badge", ""),
            trigger_regex=data.get("trigger_regex", ""),
            action=data.get("action", "apply_style"),
            priority=data.get("priority", 10),
        )


@dataclass
class IndexTaggingInstruction:
    """
    Fine-grained operation instruction addressing an isolated paragraph by its ID.
    Enforces the zero-regeneration rule: text is kept in deterministic memory,
    only operation tags are transmitted.
    """
    para_id: str
    style: Optional[str] = None
    prepend_badge: Optional[str] = None
    delete: bool = False
    split_numbering: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> IndexTaggingInstruction:
        return cls(
            para_id=data.get("para_id", ""),
            style=data.get("style"),
            prepend_badge=data.get("prepend_badge"),
            delete=data.get("delete", False),
            split_numbering=data.get("split_numbering", False),
        )


@dataclass
class BookBlueprint:
    """
    Standard POD layout blueprint shared between automation scripts,
    Antigravity, Claude Code, and Codex.
    """
    book_name: str
    book_type: str = "general"         # "general" | "qa_dialogue" | "narrative" | "academic" | "technical_manual"
    template_styles_used: List[str] = field(default_factory=list)
    heading_hierarchy: Dict[str, str] = field(default_factory=dict)
    mandatory_section_badges: List[str] = field(default_factory=list)
    intentionally_deleted_patterns: List[str] = field(default_factory=list)
    style_rules: List[StyleTriggerRule] = field(default_factory=list)
    few_shot_examples: List[Dict[str, str]] = field(default_factory=list)
    validation_config: ValidationConfig = field(default_factory=ValidationConfig)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["style_rules"] = [r.to_dict() if isinstance(r, StyleTriggerRule) else r for r in self.style_rules]
        d["validation_config"] = self.validation_config.to_dict() if isinstance(self.validation_config, ValidationConfig) else self.validation_config
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def save(self, file_path: str | Path) -> None:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BookBlueprint:
        rules_data = data.get("style_rules", [])
        rules = [StyleTriggerRule.from_dict(r) if isinstance(r, dict) else r for r in rules_data]
        val_cfg_data = data.get("validation_config", {})
        val_cfg = ValidationConfig.from_dict(val_cfg_data) if isinstance(val_cfg_data, dict) else ValidationConfig()

        return cls(
            book_name=data.get("book_name", ""),
            book_type=data.get("book_type", "general"),
            template_styles_used=list(data.get("template_styles_used", [])),
            heading_hierarchy=dict(data.get("heading_hierarchy", {})),
            mandatory_section_badges=list(data.get("mandatory_section_badges", [])),
            intentionally_deleted_patterns=list(data.get("intentionally_deleted_patterns", [])),
            style_rules=rules,
            few_shot_examples=list(data.get("few_shot_examples", [])),
            validation_config=val_cfg,
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_json(cls, json_str: str) -> BookBlueprint:
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def load(cls, file_path: str | Path) -> BookBlueprint:
        p = Path(file_path)
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
