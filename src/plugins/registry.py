# -*- coding: utf-8 -*-
"""
src/plugins/registry.py: Task Plugin Registry & Lifecycle Manager
==================================================================
Central registry for pluggable publishing tasks.
Allows new specialized sub-tasks to be added without modifying the core app
routing or sidebar layout.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter

from src.plugins.base import BaseTaskPlugin, TaskPluginSpec

logger = logging.getLogger(__name__)


class BuiltinTaskPlugin(BaseTaskPlugin):
    """Wrapper plugin for existing routers and static tools."""

    def __init__(self, spec: TaskPluginSpec, router: Optional[APIRouter] = None):
        self._spec = spec
        self._router = router

    @property
    def spec(self) -> TaskPluginSpec:
        return self._spec

    def get_router(self) -> Optional[APIRouter]:
        return self._router


class TaskPluginRegistry:
    """Singleton registry managing active and pluggable task modules."""

    _instance: Optional[TaskPluginRegistry] = None

    def __init__(self):
        self._plugins: Dict[str, BaseTaskPlugin] = {}
        self._initialize_builtins()

    @classmethod
    def get_instance(cls) -> TaskPluginRegistry:
        if cls._instance is None:
            cls._instance = TaskPluginRegistry()
        return cls._instance

    def _initialize_builtins(self):
        """Initializes default core and auxiliary publishing sub-tasks."""
        # ── Core Typesetting ────────────────────────────────────────────────
        self.register(BuiltinTaskPlugin(TaskPluginSpec(
            id="ocr_pipeline",
            name="全自動整稿",
            category="core_typesetting",
            description="視覺裁切去頁眉頁尾，自動重建標題、表格與圖片流，產出出版級初稿。",
            icon="doc",
            entry_url="/static/ocr_pipeline.html",
            api_prefix="/api/upload_and_run_ocr",
            allowed_input_exts=[".pdf"],
            output_types=["docx", "md"],
            requires_gpu=True,
            order=10,
        )))

        self.register(BuiltinTaskPlugin(TaskPluginSpec(
            id="pod_studio",
            name="POD 整稿",
            category="core_typesetting",
            description="依人工精修前 1~2 章之 Word 範本學習排版藍圖，批量擴散全書並驗收 CJK 骨架。",
            icon="pod",
            entry_url="/static/pod_studio.html",
            api_prefix="/api/pod",
            allowed_input_exts=[".docx", ".pdf"],
            output_types=["docx", "md", "json"],
            requires_gpu=False,
            order=20,
        )))

        # ── Core Proofreading (Second Core Architectural Extension Anchor) ─
        self.register(BuiltinTaskPlugin(TaskPluginSpec(
            id="proofreading",
            name="輔助校對",
            category="core_proofreading",
            description="原文 PDF 幾何對照、版面標註、生僻字比對與字庫缺字校驗 (即將推出)。",
            icon="check",
            entry_url="/static/proofreading.html",
            api_prefix="/api/proofreading",
            allowed_input_exts=[".pdf", ".docx"],
            output_types=["json", "docx"],
            requires_gpu=False,
            is_enabled=False,
            order=30,
        )))

        # ── Auxiliary Specialized Tasks ─────────────────────────────────────
        self.register(BuiltinTaskPlugin(TaskPluginSpec(
            id="founder_repair",
            name="方正修復",
            category="auxiliary_task",
            description="還原方正排版系統 PDF / DOCX 的 CMap 編碼缺陷與缺字亂碼，直接輸出乾淨 Word。",
            icon="wrench",
            entry_url="/static/founder_repair.html",
            api_prefix="/api/founder",
            allowed_input_exts=[".pdf", ".docx"],
            output_types=["docx"],
            requires_gpu=False,
            order=100,
        )))

        self.register(BuiltinTaskPlugin(TaskPluginSpec(
            id="extract_images",
            name="圖片提取",
            category="auxiliary_task",
            description="從 PDF 或 DOCX 中按物理幾何無損提取內嵌的原始高解析度圖片圖檔包。",
            icon="image",
            entry_url="/static/extract_images.html",
            api_prefix="/api/extract_images",
            allowed_input_exts=[".pdf", ".docx"],
            output_types=["zip"],
            requires_gpu=False,
            order=110,
        )))

        self.register(BuiltinTaskPlugin(TaskPluginSpec(
            id="formula_extraction",
            name="公式提取",
            category="auxiliary_task",
            description="調度 YOLO 視覺定位與 Mathpix/Surya 獨立數學公式偵測並打包圖檔。",
            icon="formula",
            entry_url="/static/formula.html",
            api_prefix="/api/process_pdf",
            allowed_input_exts=[".pdf"],
            output_types=["zip"],
            requires_gpu=True,
            order=120,
        )))

    def register(self, plugin: BaseTaskPlugin) -> None:
        """Registers a new task plugin."""
        self._plugins[plugin.spec.id] = plugin
        logger.info(f"[PluginRegistry] Registered task plugin: {plugin.spec.id} ({plugin.spec.name})")

    def unregister(self, plugin_id: str) -> Optional[BaseTaskPlugin]:
        """Unregisters an existing task plugin."""
        return self._plugins.pop(plugin_id, None)

    def get(self, plugin_id: str) -> Optional[BaseTaskPlugin]:
        """Returns plugin by its ID."""
        return self._plugins.get(plugin_id)

    def list_specs(
        self, category: Optional[str] = None, only_enabled: bool = True
    ) -> List[TaskPluginSpec]:
        """Returns sorted list of plugin specs matching filters."""
        specs = [p.spec for p in self._plugins.values()]
        if only_enabled:
            specs = [s for s in specs if s.is_enabled]
        if category:
            specs = [s for s in specs if s.category == category]
        return sorted(specs, key=lambda s: s.order)

    def get_routers(self) -> List[APIRouter]:
        """Collects all APIRouters from registered plugins."""
        routers = []
        for p in self._plugins.values():
            r = p.get_router()
            if r is not None:
                routers.append(r)
        return routers


def get_plugin_registry() -> TaskPluginRegistry:
    """Helper to access global TaskPluginRegistry."""
    return TaskPluginRegistry.get_instance()
