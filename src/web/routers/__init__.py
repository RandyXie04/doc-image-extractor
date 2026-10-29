# -*- coding: utf-8 -*-
"""
Modular FastAPI Routers Package (P3-4 Architecture Remediation)
"""

from src.web.routers.pod_router import router as pod_router
from src.web.routers.system_router import router as system_router

__all__ = ["pod_router", "system_router"]

