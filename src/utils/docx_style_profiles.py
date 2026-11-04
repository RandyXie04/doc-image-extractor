"""Read paragraph style names and lightweight formatting metadata from DOCX."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Dict, List, Union
from xml.etree import ElementTree as ET


W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _word_value(element: Any, attribute: str = "val") -> Any:
    return element.get(f"{W_NS}{attribute}") if element is not None else None


def read_docx_style_profiles(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Return paragraph style names and outline, size, and bold properties."""
    profiles: List[Dict[str, Any]] = []
    with zipfile.ZipFile(path, "r") as archive:
        if "word/styles.xml" not in archive.namelist():
            return profiles
        root = ET.fromstring(archive.read("word/styles.xml"))
    for style in root.findall(f"{W_NS}style"):
        if _word_value(style, "type") != "paragraph":
            continue
        name = _word_value(style.find(f"{W_NS}name"))
        if not name:
            continue
        ppr = style.find(f"{W_NS}pPr")
        rpr = style.find(f"{W_NS}rPr")
        outline = _word_value(ppr.find(f"{W_NS}outlineLvl")) if ppr is not None else None
        # Word permits outline level in paragraph properties; tolerate older
        # templates that put it directly below style.
        if outline is None:
            outline = _word_value(style.find(f"{W_NS}outlineLvl"))
        size = _word_value(rpr.find(f"{W_NS}sz")) if rpr is not None else None
        bold_element = rpr.find(f"{W_NS}b") if rpr is not None else None
        bold_value = _word_value(bold_element)
        profiles.append({
            "name": name,
            "outline_level": int(outline) if outline is not None and outline.isdigit() else None,
            "font_size_pt": float(size) / 2.0 if size is not None and size.isdigit() else None,
            "bold": bold_element is not None and bold_value not in ("0", "false", "off"),
        })
    return profiles
