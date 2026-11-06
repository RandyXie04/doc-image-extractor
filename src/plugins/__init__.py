# -*- coding: utf-8 -*-
"""
Doc-Image-Extractor Specialized Task Plugin Architecture
========================================================
Supports pluggable, domain-specific publishing sub-tasks without modifying
the core typesetting or proofreading pipelines.
"""

from src.plugins.base import BaseTaskPlugin, TaskPluginSpec
from src.plugins.registry import TaskPluginRegistry, get_plugin_registry

__all__ = ["BaseTaskPlugin", "TaskPluginSpec", "TaskPluginRegistry", "get_plugin_registry"]
