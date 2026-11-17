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
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

BBoxTuple = Tuple[float, float, float, float]
PaddedBoxTuple = Tuple[int, int, int, int]
FormulaCategory = Literal["inline", "isolated"]


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


class FormulaDetectionContract(StrictContractModel):
    """
    Validated formula detection item emitted by Stage 1 FormulaDetector.
    Coordinates represent un-padded bounding box in source image space.
    Strictly immutable with extra fields forbidden.
    """
    box: Tuple[float, float, float, float] = Field(
        ..., description="Bounding box in original image coordinates (x1, y1, x2, y2)"
    )
    score: float = Field(..., ge=0.0, le=1.0, description="Detection confidence score")
    category: FormulaCategory = Field(
        ..., description="Formula type: inline (Class 0) or isolated (Class 1)"
    )
    class_id: Literal[0, 1] = Field(
        ..., description="Raw model class ID (0: inline, 1: isolated)"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> FormulaDetectionContract:
        # Enforce category and class_id alignment
        if self.class_id == 0 and self.category != "inline":
            raise ValueError(f"class_id 0 requires category='inline', got '{self.category}'")
        if self.class_id == 1 and self.category != "isolated":
            raise ValueError(f"class_id 1 requires category='isolated', got '{self.category}'")

        # Enforce valid positive box coordinates
        x1, y1, x2, y2 = self.box
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Invalid bounding box: width and height must be positive, got {self.box}")
        if x1 < 0.0 or y1 < 0.0:
            raise ValueError(f"Invalid bounding box: coordinates cannot be negative, got {self.box}")
        return self


class FormulaCroppedItemContract(StrictContractModel):
    """
    Validated item metadata emitted by Stage 2 FormulaCropper.
    Carries padded coordinates, aspect ratio, and source detection record.
    """
    item_id: str = Field(..., min_length=1, description="Unique item identifier")
    original_index: int = Field(..., ge=0, description="0-based document detection index")
    detection: FormulaDetectionContract = Field(..., description="Source detection record")
    padded_box: PaddedBoxTuple = Field(
        ...,
        description="Clamped integer bounding box [x1, y1, x2, y2] after safety padding",
    )
    aspect_ratio: float = Field(..., gt=0.0, description="Aspect ratio w / max(1, h)")

    @model_validator(mode="after")
    def validate_padded_invariants(self) -> FormulaCroppedItemContract:
        x1, y1, x2, y2 = self.padded_box
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Invalid padded box: width and height must be positive, got {self.padded_box}")
        if x1 < 0 or y1 < 0:
            raise ValueError(f"Invalid padded box: coordinates cannot be negative, got {self.padded_box}")
        return self


class FormulaRecognitionContract(StrictContractModel):
    """
    Validated recognition record emitted by Stage 3 SuryaOCR RecognitionPredictor.
    """
    item_id: str = Field(..., min_length=1, description="Matching item identifier")
    original_index: int = Field(..., ge=0, description="0-based document detection index")
    latex: str = Field(..., description="Transcribed LaTeX string with math and CJK characters")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Recognition confidence score")


class FormulaResultContract(StrictContractModel):
    """
    Final multi-format extraction result emitted by FormulaExporter.
    """
    item_id: str = Field(..., min_length=1, description="Unique item identifier")
    original_index: int = Field(..., ge=0, description="0-based document detection index")
    category: FormulaCategory = Field(..., description="Formula type: inline or isolated")
    box: Tuple[float, float, float, float] = Field(..., description="Original detection box [x1, y1, x2, y2]")
    padded_box: PaddedBoxTuple = Field(..., description="Clamped padded box [x1, y1, x2, y2]")
    latex: str = Field(..., description="Format 1: Sanitized clean LaTeX string")
    mathml: str = Field(..., description="Format 2: Valid, parseable MathML XML representation")
    image_path: str = Field(..., description="Format 3: High-resolution PNG crop exported at imgsz=1600")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence score")
    page_idx: Optional[int] = Field(default=None, ge=0, description="0-based document page index")


# Formula type adapters & validation helpers
FORMULA_DETECTION_ADAPTER: TypeAdapter[FormulaDetectionContract] = TypeAdapter(FormulaDetectionContract)
FORMULA_CROPPED_ITEM_ADAPTER: TypeAdapter[FormulaCroppedItemContract] = TypeAdapter(FormulaCroppedItemContract)
FORMULA_RECOGNITION_ADAPTER: TypeAdapter[FormulaRecognitionContract] = TypeAdapter(FormulaRecognitionContract)
FORMULA_RESULT_ADAPTER: TypeAdapter[FormulaResultContract] = TypeAdapter(FormulaResultContract)


def validate_formula_detection(record: Dict[str, Any]) -> FormulaDetectionContract:
    """Validates a dictionary against FormulaDetectionContract."""
    return FORMULA_DETECTION_ADAPTER.validate_python(record)


def validate_formula_detections(records: List[Dict[str, Any]]) -> List[FormulaDetectionContract]:
    """Batch-validates dictionaries against FormulaDetectionContract."""
    return [FORMULA_DETECTION_ADAPTER.validate_python(r) for r in records]


def validate_formula_cropped_item(record: Dict[str, Any]) -> FormulaCroppedItemContract:
    """Validates a dictionary against FormulaCroppedItemContract."""
    return FORMULA_CROPPED_ITEM_ADAPTER.validate_python(record)


def validate_formula_recognition(record: Dict[str, Any]) -> FormulaRecognitionContract:
    """Validates a dictionary against FormulaRecognitionContract."""
    return FORMULA_RECOGNITION_ADAPTER.validate_python(record)


def validate_formula_result(record: Dict[str, Any]) -> FormulaResultContract:
    """Validates a dictionary against FormulaResultContract."""
    return FORMULA_RESULT_ADAPTER.validate_python(record)


def validate_formula_results(records: List[Dict[str, Any]]) -> List[FormulaResultContract]:
    """Batch-validates dictionaries against FormulaResultContract."""
    return [FORMULA_RESULT_ADAPTER.validate_python(r) for r in records]


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


def validate_layout_records(records: List[Dict[str, Any]]) -> List[LayoutRecordContract]:
    """Batch-validates layout records from `_parse_pdf_layout_flow`."""
    return [_LAYOUT_RECORD_ADAPTER.validate_python(r) for r in records]
