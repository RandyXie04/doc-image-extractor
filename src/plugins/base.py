# -*- coding: utf-8 -*-
"""
src/plugins/base.py: Abstract Base Class for Pluggable Specialized Tasks
=======================================================================
Defines the standard specification and lifecycle hooks for specialized publishing
work tasks (e.g., Founder Repair, Image Extraction, Formula Extraction, and
future pluggable proofreading/verification sub-tasks).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter

TaskCategory = Literal["core_typesetting", "core_proofreading", "auxiliary_task"]


@dataclass(frozen=True)
class TaskPluginSpec:
    """Immutable specification declaring a task plugin's capabilities and entry points."""
    id: str
    name: str
    category: TaskCategory
    description: str
    entry_url: str
    api_prefix: str
    icon: str = "doc"
    allowed_input_exts: List[str] = field(default_factory=lambda: [".pdf"])
    output_types: List[str] = field(default_factory=lambda: ["docx"])
    requires_gpu: bool = False
    is_enabled: bool = True
    order: int = 100

    def __post_init__(self):
        valid_cats = ("core_typesetting", "core_proofreading", "auxiliary_task")
        if self.category not in valid_cats:
            raise ValueError(f"Invalid plugin category: '{self.category}'. Must be one of {valid_cats}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "icon": self.icon,
            "entry_url": self.entry_url,
            "api_prefix": self.api_prefix,
            "allowed_input_exts": list(self.allowed_input_exts),
            "output_types": list(self.output_types),
            "requires_gpu": self.requires_gpu,
            "is_enabled": self.is_enabled,
            "order": self.order,
        }


class BaseTaskPlugin(ABC):
    """
    Abstract Base Class for Task Plugins.
    New publishing tasks inherit from this class and register with TaskPluginRegistry.
    """

    @property
    @abstractmethod
    def spec(self) -> TaskPluginSpec:
        """Returns the static specification of the plugin."""
        raise NotImplementedError

    def get_router(self) -> Optional[APIRouter]:
        """
        Optional FastAPI APIRouter exposing endpoints for this plugin.
        If returned, will be automatically mounted into the web application.
        """
        return None

    def validate_input(self, file_path: Path | str) -> Tuple[bool, str]:
        """Validates uploaded file against allowed extensions and basic format."""
        path_obj = Path(file_path)
        ext = path_obj.suffix.lower()
        if ext not in self.spec.allowed_input_exts:
            allowed = ", ".join(self.spec.allowed_input_exts)
            return False, f"不支援的檔案格式：僅支援 {allowed}，目前檔案為 {ext}"
        return True, ""

    def cleanup_task(self, task_id: str) -> None:
        """Optional hook called when a task is purged or cancelled."""
        pass
