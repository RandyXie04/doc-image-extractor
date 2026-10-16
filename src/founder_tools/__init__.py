# -*- coding: utf-8 -*-
"""
Founder Tools Package - Special font, CMap, and layout analysis tools.
"""
from __future__ import annotations

from src.founder_tools.fix_founder_fonts import clean_founder_text
from src.founder_tools.core.heading_detector import HeadingDetector
from src.founder_tools.core.marker_detector import MarkerDetector
from src.founder_tools.core.ai_kaiti_classifier import AIKaitiClassifier

__all__ = [
    "clean_founder_text",
    "HeadingDetector",
    "MarkerDetector",
    "AIKaitiClassifier",
]
