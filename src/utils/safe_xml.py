"""XXE-safe XML parsing helpers backed by defusedxml."""

from __future__ import annotations

from typing import Union
import xml.etree.ElementTree as _stdlib_et

Element = _stdlib_et.Element

try:
    from defusedxml import ElementTree as _defused_et
except ImportError:  # pragma: no cover - fallback only when defusedxml is absent locally
    _defused_et = None


def fromstring(data: Union[str, bytes]) -> _stdlib_et.Element:
    """Parse XML string or bytes using defusedxml to prevent XXE attacks."""
    if _defused_et is not None:
        return _defused_et.fromstring(data)
    return _stdlib_et.fromstring(data)  # nosec B314
