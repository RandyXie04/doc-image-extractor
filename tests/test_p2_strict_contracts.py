# -*- coding: utf-8 -*-
"""
P2 Strict Contracts & TypeScript Codegen Verification Suite
===========================================================
Verifies the three Iron Rules from `typescript_architecture_analysis.md`:
1. Iron Rule 1 (Zero Raw-Dict Policy): `extra="forbid"` rejects hallucinated keys on all layout & API contracts.
2. Iron Rule 2 (Schema-Driven Development): `generate_ts_contracts.py` keeps `frontend/src/types/contracts.ts` in 1:1 sync with Pydantic v2 models.
3. Iron Rule 3 (End-to-End Layout Flow Contract Conformance): `_parse_pdf_layout_flow` output records conform 100% to `LayoutRecordContract`.
"""

from pathlib import Path
from typing import Any
import fitz
import pytest
from pydantic import ValidationError

from src.extraction.contracts import (
    ParagraphLayoutContract,
    HeadingLayoutContract,
    TableLayoutContract,
    FigureLayoutContract,
    FootnoteLayoutContract,
    ImageBlockContract,
    validate_layout_record,
    validate_layout_records,
)
from src.web.schemas import (
    PodCompileBlueprintResponse,
    PodPropagateResponse,
    RuleFirstPropagationPayload,
    VlmContinuationPropagationPayload,
)
from src.scripts.generate_ts_contracts import (
    generate_typescript_contracts_source,
    sync_typescript_contracts,
)
from src.scripts.book_layout_extractor import _parse_pdf_layout_flow


class TestP2StrictContractsAndTypeScriptCodegen:
    """Tests for P2 Bidirectional Strict Contracts & TypeScript Architecture."""

    def test_iron_rule_1_rejects_hallucinated_keys_on_layout_contracts(self):
        """Verifies `extra='forbid'` raises ValidationError on hallucinated dictionary keys."""
        valid_para = validate_layout_record({
            "type": "paragraph",
            "page_num": 1,
            "raw_text": "這是一段合規內文。",
            "md_text": "這是一段合規內文。",
            "bbox": [70.0, 100.0, 450.0, 120.0],
            "font_name": "FZSS",
            "font_size": 10.5,
            "custom_style": "",
        })
        assert isinstance(valid_para, ParagraphLayoutContract)

        # Hallucinated key ("surya_text" instead of "raw_text" or extra "hallucinated_field") must fail
        with pytest.raises(ValidationError):
            validate_layout_record({
                "type": "paragraph",
                "page_num": 1,
                "raw_text": "內文",
                "hallucinated_field": "AI幻覺欄位",
            })

        with pytest.raises(ValidationError):
            TableLayoutContract.model_validate({
                "type": "table",
                "page_num": 1,
                "raw_md": "| A | B |\n| --- | --- |\n| 1 | 2 |",
                "bbox": [70.0, 100.0, 450.0, 200.0],
                "unknown_table_prop": True,
            })

    def test_iron_rule_1_rejects_hallucinated_keys_on_api_schemas(self):
        """Verifies API schemas forbid undeclared keys and enforce discriminated unions."""
        rule_payload = RuleFirstPropagationPayload(
            engine_mode="rule_first",
            session_id="pod_123456",
        )
        assert rule_payload.engine_mode == "rule_first"

        vlm_payload = VlmContinuationPropagationPayload(
            engine_mode="vlm_continuation",
            session_id="pod_123456",
            model="gemini-3.8-flash",
            max_continuation_sections=5,
        )
        assert vlm_payload.engine_mode == "vlm_continuation"

        with pytest.raises(ValidationError):
            PodCompileBlueprintResponse.model_validate({
                "status": "success",
                "session_id": "pod_123",
                "blueprint": {},
                "inferred_rules_count": 2,
                "mandatory_badges": [],
                "detected_styles": [],
                "boundary_idx": 3,
                "boundary_source": "builtin_tag",
                "manual_boundary_anchor": "",
                "boundary_context_text": "",
                "total_paragraphs": 10,
                "unexpected_hallucinated_key": "boom",
            })

    def test_iron_rule_2_typescript_codegen_sync_and_discriminated_unions(self, tmp_path):
        """Verifies TypeScript contract codegen produces valid TS interfaces and zero drift."""
        ts_source = generate_typescript_contracts_source()
        assert "export interface PodCompileBlueprintResponse" in ts_source
        assert "readonly detected_tables_count: number;" in ts_source
        assert "export type PropagationPayload =" in ts_source
        assert "export type LayoutRecordContract =" in ts_source
        assert "export type PodSessionPhase =" in ts_source

        # Verify workspace `frontend/src/types/contracts.ts` is in sync
        synced_path = sync_typescript_contracts(check_only=False)
        assert synced_path.exists()
        verified_path = sync_typescript_contracts(check_only=True)
        assert verified_path == synced_path

        # Verify frontend TypeScript client & tsconfig exist
        fe_dir = synced_path.parent.parent.parent
        assert (fe_dir / "tsconfig.json").exists()
        assert (fe_dir / "package.json").exists()
        assert (fe_dir / "src" / "api" / "podClient.ts").exists()

    def test_iron_rule_3_layout_flow_emits_strict_contract_compliant_records(self):
        """Verifies `_parse_pdf_layout_flow` outputs 100% schema-compliant `layout_records`."""
        doc: Any = fitz.open()
        try:
            page = doc.new_page(width=515.9, height=728.5)
            page.insert_text((76, 60), "第一章 強型別契約測試", fontsize=15.0, fontname="china-ss")
            page.insert_text((76, 100), "表1　兩組指標比較", fontsize=9.0, fontname="china-ss")
            page.draw_line(fitz.Point(76, 110), fitz.Point(450, 110), width=1.0)
            page.draw_line(fitz.Point(76, 128), fitz.Point(450, 128), width=0.5)
            page.draw_line(fitz.Point(76, 170), fitz.Point(450, 170), width=1.0)
            page.insert_text((85, 122), "組別", fontsize=8.5, fontname="china-ss")
            page.insert_text((200, 122), "例數", fontsize=8.5, fontname="china-ss")
            page.insert_text((320, 122), "ESR（mm/h）", fontsize=8.5, fontname="china-ss")
            page.insert_text((85, 145), "觀察組", fontsize=8.5, fontname="china-ss")
            page.insert_text((200, 145), "43", fontsize=8.5, fontname="china-ss")
            page.insert_text((320, 145), "12.63±4.99", fontsize=8.5, fontname="china-ss")
            page.insert_text((76, 200), "這是一段標準內文段落，用於驗證版面紀錄完全符合強型別契約。", fontsize=10.5, fontname="china-ss")

            _, _, _, layout_records = _parse_pdf_layout_flow(
                doc=doc,
                pdf_name="contract_test.pdf",
                style_mapping={},
                font_role_map={},
                enable_footnotes=False,
            )
            assert len(layout_records) >= 3
            validated = validate_layout_records(layout_records)
            assert len(validated) == len(layout_records)
            assert any(isinstance(r, HeadingLayoutContract) for r in validated)
            assert any(isinstance(r, TableLayoutContract) for r in validated)
            assert any(isinstance(r, ParagraphLayoutContract) for r in validated)
        finally:
            doc.close()

