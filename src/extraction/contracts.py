# -*- coding: utf-8 -*-
"""
Strict Layout & Extraction Data Contracts (P2 Guardrail: Zero Raw-Dict Policy)
==============================================================================
Enforces compile-time (pyright) and runtime (Pydantic v2 `extra="forbid"`)
validation across Channel 1 (Automated Vector / Pure OCR) and Channel 2 (POD Studio).
Any hallucinated field name immediately raises `pydantic.ValidationError`.
"""

from __future__ import annotations
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

BBoxTuple = Tuple[float, float, float, float]


class StrictContractModel(BaseModel):
    """Base contract forbidding undeclared keys and mutability."""
    model_config = ConfigDict(extra="forbid", frozen=True)


class ParagraphLayoutContract(StrictContractModel):
    """Validated paragraph layout record emitted by `_parse_pdf_layout_flow`."""
    type: Literal["paragraph", "caption", "table_caption"] = "paragraph"
    page_num: int = Field(..., ge=1)
    raw_text: str
    md_text: str = ""
    bbox: Optional[List[float]] = None
    font_name: str = "SimSun"
    font_size: float = Field(default=10.5, gt=0.0)
    custom_style: str = ""


class HeadingLayoutContract(StrictContractModel):
    """Validated section/chapter heading record emitted by `_parse_pdf_layout_flow`."""
    type: Literal["heading"] = "heading"
    page_num: int = Field(..., ge=1)
    level: int = Field(..., ge=1, le=6)
    title: str
    raw_text: str
    bbox: Optional[List[float]] = None
    font_name: str = "SimHei"
    font_size: float = Field(default=12.0, gt=0.0)
    custom_style: str = ""


class TableLayoutContract(StrictContractModel):
    """Validated table layout record (both PyMuPDF grid and 3-line reconstructed tables)."""
    type: Literal["table"] = "table"
    page_num: int = Field(..., ge=1)
    raw_md: str
    bbox: List[float]
    font_name: Literal["table"] = "table"
    font_size: float = Field(default=10.5, gt=0.0)
    caption_text: str = ""


class FigureLayoutContract(StrictContractModel):
    """Validated figure placeholder layout record."""
    type: Literal["figure"] = "figure"
    page_num: int = Field(..., ge=1)
    block_idx: int = Field(..., ge=0)
    raw_md: str
    bbox: List[float]
    font_name: Literal["figure"] = "figure"
    font_size: float = Field(default=10.5, gt=0.0)


class FootnoteLayoutContract(StrictContractModel):
    """Validated footnote definition layout record."""
    type: Literal["footnote"] = "footnote"
    page_num: int = Field(..., ge=1)
    fn_id: int
    tag: str
    content: str


class ImageBlockContract(StrictContractModel):
    """Validated image block coordinate contract for `extract_pdf_images`."""
    page_num: int = Field(..., ge=1)
    block_idx: int = Field(..., ge=0)
    bbox: List[float]
    page_w: float = Field(..., gt=0.0)
    page_h: float = Field(..., gt=0.0)


LayoutRecordContract = Annotated[
    Union[
        ParagraphLayoutContract,
        HeadingLayoutContract,
        TableLayoutContract,
        FigureLayoutContract,
        FootnoteLayoutContract,
    ],
    Field(discriminator="type"),
]

_LAYOUT_RECORD_ADAPTER: TypeAdapter[LayoutRecordContract] = TypeAdapter(LayoutRecordContract)


def validate_layout_record(record: Dict[str, Any]) -> LayoutRecordContract:
    """
    Validates a raw layout record dict against the discriminated `LayoutRecordContract`.
    Raises `pydantic.ValidationError` if any undeclared/hallucinated key is present
    or required field is missing.
    """
    return _LAYOUT_RECORD_ADAPTER.validate_python(record)


def validate_layout_records(records: List[Dict[str, Any]]) -> List[LayoutRecordContract]:
    """Batch-validates layout records from `_parse_pdf_layout_flow`."""
    return [_LAYOUT_RECORD_ADAPTER.validate_python(r) for r in records]
