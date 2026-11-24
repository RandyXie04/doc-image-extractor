# -*- coding: utf-8 -*-
"""
Unit & Integration Tests for Physical Line Stitching Adapter & Interleaved Flow Ordering.
"""

from pathlib import Path
from typing import Any, Dict, List
import pytest

from src.scripts.book_layout_extractor import (
    _build_interleaved_flow_items,
    _process_single_pdf_page_layout,
    _stitch_body_lines_into_blocks,
    extract_book_vector_ast,
)
import src.scripts.paragraph_reconstruction as pr_mod


REPO_ROOT = Path(__file__).resolve().parent.parent
EMPIRICAL_PDF = REPO_ROOT / "data" / "01_input" / "0c7c0906-fc71-4677-bc29-76577e951601.pdf"


def _make_span(
    text: str,
    bbox: List[float],
    font: str = "SimSun",
    size: float = 10.5,
    flags: int = 0,
) -> Dict[str, Any]:
    return {
        "text": text,
        "bbox": list(bbox),
        "font": font,
        "size": size,
        "flags": flags,
        "origin": [bbox[0], bbox[3]],
    }


def _make_block(lines: List[Dict[str, Any]], bbox: List[float] | None = None) -> Dict[str, Any]:
    if bbox is None:
        x0 = min(ln["bbox"][0] for ln in lines)
        y0 = min(ln["bbox"][1] for ln in lines)
        x1 = max(ln["bbox"][2] for ln in lines)
        y1 = max(ln["bbox"][3] for ln in lines)
        bbox = [x0, y0, x1, y1]
    return {"type": 0, "bbox": list(bbox), "lines": lines}


def _make_line(spans: List[Dict[str, Any]], bbox: List[float] | None = None) -> Dict[str, Any]:
    if bbox is None:
        x0 = min(sp["bbox"][0] for sp in spans)
        y0 = min(sp["bbox"][1] for sp in spans)
        x1 = max(sp["bbox"][2] for sp in spans)
        y1 = max(sp["bbox"][3] for sp in spans)
        bbox = [x0, y0, x1, y1]
    return {"bbox": list(bbox), "wmode": 0, "dir": [1.0, 0.0], "spans": spans}


def _block_text(block: Dict[str, Any]) -> str:
    return "".join(
        sp.get("text", "")
        for ln in block.get("lines", [])
        for sp in ln.get("spans", [])
    )


def _require_stitch_physical_lines() -> None:
    assert hasattr(pr_mod, "stitch_physical_lines"), (
        "stitch_physical_lines must be defined in src.scripts.paragraph_reconstruction"
    )


class TestLineStitchingAdapter:
    """Synthetic PyMuPDF dict-block tests for _stitch_body_lines_into_blocks."""

    def test_plt_superscript_split_blocks_reordered_and_stitched(self):
        """Reproduces PyMuPDF splitting （PLT）低于100×10 and 9/L... into inverted-Y blocks."""
        _require_stitch_physical_lines()

        # Second half sits slightly higher (y0=539.51) than first half (y0=540.81),
        # so raw PyMuPDF order places the tail block before the head block.
        tail_block = _make_block([
            _make_line([
                _make_span("9", [165.2, 539.51, 168.5, 547.0], size=6.12),
                _make_span("/L，或有活动性出血者。", [168.5, 540.81, 310.0, 554.0], size=10.5),
            ], bbox=[165.2, 539.51, 310.0, 554.0])
        ])
        head_block = _make_block([
            _make_line([
                _make_span("（PLT）低于100×10", [70.87, 540.81, 165.0, 554.0], size=10.5),
            ])
        ])

        stitched = _stitch_body_lines_into_blocks([tail_block, head_block], body_size=10.5)
        assert len(stitched) == 1
        text = _block_text(stitched[0])
        assert text == "（PLT）低于100×109/L，或有活动性出血者。"
        assert "^" not in text
        assert "<sup>" not in text
        assert stitched[0]["bbox"] == [70.87, 539.51, 310.0, 554.0]

    def test_ca2_plus_superscript_split_blocks_stitched(self):
        """Reproduces Ca + 2+ superscript block fragmentation without markup or spaces."""
        _require_stitch_physical_lines()

        b_left = _make_block([
            _make_line([_make_span("血清Ca", [70.0, 300.8, 110.0, 314.0], size=10.5)])
        ])
        b_sup = _make_block([
            _make_line([_make_span("2+", [110.2, 299.2, 120.0, 307.0], size=6.5)])
        ])
        b_right = _make_block([
            _make_line([_make_span("浓度降低。", [120.2, 300.8, 175.0, 314.0], size=10.5)])
        ])

        stitched = _stitch_body_lines_into_blocks([b_sup, b_right, b_left], body_size=10.5)
        assert len(stitched) == 1
        assert _block_text(stitched[0]) == "血清Ca2+浓度降低。"
        assert "^" not in _block_text(stitched[0])

    def test_multiline_block_with_embedded_split_fragment_repacks_into_one_block(self):
        """A multi-line block with one line split into an external fragment stays a single block."""
        _require_stitch_physical_lines()

        main_block = _make_block([
            _make_line([_make_span("若患者出现血小板计数", [70.0, 520.0, 210.0, 533.0], size=10.5)]),
            _make_line([_make_span("（PLT）低于100×10", [70.0, 540.81, 165.0, 554.0], size=10.5)]),
            _make_line([_make_span("应立即暂停用药并复查。", [70.0, 560.0, 220.0, 573.0], size=10.5)]),
        ])
        sup_fragment = _make_block([
            _make_line([
                _make_span("9", [165.2, 539.51, 168.5, 547.0], size=6.12),
                _make_span("/L，或有活动性出血者，", [168.5, 540.81, 310.0, 554.0], size=10.5),
            ], bbox=[165.2, 539.51, 310.0, 554.0])
        ])

        stitched = _stitch_body_lines_into_blocks([sup_fragment, main_block], body_size=10.5)
        assert len(stitched) == 1
        lines = stitched[0]["lines"]
        assert len(lines) == 3
        line_texts = ["".join(sp["text"] for sp in ln["spans"]) for ln in lines]
        assert line_texts == [
            "若患者出现血小板计数",
            "（PLT）低于100×109/L，或有活动性出血者，",
            "应立即暂停用药并复查。",
        ]
        assert stitched[0]["bbox"] == [70.0, 520.0, 310.0, 573.0]

    def test_wide_gap_toc_or_columns_stay_separate_blocks(self):
        """Wide horizontal gaps (> 1.2 * body_size) remain distinct blocks left-to-right."""
        _require_stitch_physical_lines()

        left_col = _make_block([
            _make_line([_make_span("三、血小板减少", [70.0, 120.0, 160.0, 134.0], size=10.5)])
        ])
        right_col = _make_block([
            _make_line([_make_span("127", [480.0, 120.2, 500.0, 133.5], size=10.5)])
        ])

        stitched = _stitch_body_lines_into_blocks([right_col, left_col], body_size=10.5)
        assert len(stitched) == 2
        assert [_block_text(b) for b in stitched] == ["三、血小板减少", "127"]


class TestInterleavedFlowSorting:
    """Verify _build_interleaved_flow_items uses Y-tolerance row-band sorting."""

    def test_same_row_blocks_with_small_y_offset_sort_left_to_right(self):
        b_right = _make_block([_make_line([_make_span("9/L", [220.0, 539.51, 250.0, 553.0])])])
        b_left = _make_block([_make_line([_make_span("100×10", [70.0, 540.81, 219.0, 554.0])])])

        items = _build_interleaved_flow_items([b_right, b_left], [], [], [])
        assert [item["bbox"][0] for item in items] == [70.0, 220.0]

    def test_tables_and_figures_remain_interleaved_by_y(self):
        class _DummyTable:
            def __init__(self, bbox: List[float]):
                self.bbox = bbox

        b_top = _make_block([_make_line([_make_span("段落一", [60.0, 80.0, 300.0, 94.0])])])
        fig = {"type": 1, "bbox": [60.0, 120.0, 200.0, 200.0]}
        b_mid = _make_block([_make_line([_make_span("段落二", [60.0, 240.0, 300.0, 254.0])])])
        tbl = _DummyTable([60.0, 290.0, 400.0, 390.0])
        b_bot = _make_block([_make_line([_make_span("段落三", [60.0, 430.0, 300.0, 444.0])])])

        items = _build_interleaved_flow_items([b_bot, b_top, b_mid], [fig], [tbl], [])
        assert [it["type"] for it in items] == ["text", "figure", "text", "table", "text"]

    def test_multiline_block_stays_before_same_row_single_line_superscript_block(self):
        """Multi-line block starting at y0=100 must sort before a right-side single-line block at y0=100."""
        b_left_multi = _make_block([
            _make_line([_make_span("患者外周血白细胞计数大多增高，一般为（10 ～ 20）×10", [60.0, 100.0, 310.0, 113.0])]),
            _make_line([_make_span("以中性粒细胞为主。", [60.0, 116.0, 165.0, 129.0])]),
        ])
        b_right_single = _make_block([
            _make_line([
                _make_span("9", [325.0, 93.0, 329.0, 100.0], size=6.12),
                _make_span("/L，少数可高达（60 ～ 80） ×109/L，", [329.0, 100.0, 480.0, 113.0], size=10.5),
            ])
        ])

        items = _build_interleaved_flow_items([b_right_single, b_left_multi], [], [], [])
        assert [item["bbox"][0] for item in items] == [60.0, 325.0]

    def test_intraline_out_of_order_ltr_spans_reordered_in_stitch_adapter(self):
        """Out-of-order PDF stream spans within one LTR horizontal line must reorder left-to-right."""
        _require_stitch_physical_lines()
        out_of_order_block = _make_block([
            _make_line([
                _make_span("9", [325.2, 95.0, 329.0, 101.0], size=6.12),
                _make_span("/L，少数可高达（60 ～ 80） ×109/L，", [329.0, 100.0, 480.0, 113.0], size=10.5),
                _make_span("患者外周血白细胞计数大多增高，一般为（10 ～ 20）×10", [60.0, 100.0, 325.0, 113.0], size=10.5),
            ])
        ])
        stitched = _stitch_body_lines_into_blocks([out_of_order_block], body_size=10.5)
        assert len(stitched) == 1
        assert _block_text(stitched[0]) == "患者外周血白细胞计数大多增高，一般为（10 ～ 20）×109/L，少数可高达（60 ～ 80） ×109/L，"


class TestSyntheticPageLayoutIntegration:
    """End-to-end synthetic PyMuPDF dict flow through _process_single_pdf_page_layout."""

    def test_single_page_layout_stitches_plt_and_kg_m2_without_breaking_paragraphs(self):
        _require_stitch_physical_lines()

        class _Rect:
            width = 595.0
            height = 842.0

        class _MockPage:
            rect = _Rect()

            def __init__(self, blocks: List[Dict[str, Any]]):
                self._blocks = blocks

            def get_text(self, mode: str = "dict") -> Dict[str, Any]:
                return {"blocks": self._blocks}

            def find_tables(self):
                return None

        raw_blocks = [
            _make_block([
                _make_line([_make_span("三、血小板减少", [70.0, 120.0, 180.0, 136.0], font="SimHei", size=12.0, flags=16)]),
            ]),
            _make_block([
                _make_line([
                    _make_span("9", [210.5, 160.2, 214.0, 167.5], size=6.12),
                    _make_span("/L，或有活动性出血者，", [214.0, 161.5, 360.0, 174.5], size=10.5),
                ], bbox=[210.5, 160.2, 360.0, 174.5]),
            ]),
            _make_block([
                _make_line([
                    _make_span("　　外周血血小板计数（PLT）低于100×10", [70.0, 161.5, 210.0, 174.5], size=10.5),
                ]),
                _make_line([
                    _make_span("以及体表面积20kg/m", [70.0, 180.0, 175.0, 193.0], size=10.5),
                ]),
            ]),
            _make_block([
                _make_line([
                    _make_span("2", [175.2, 178.7, 179.0, 185.5], size=6.12),
                    _make_span("患者，需严密监测。", [179.0, 180.0, 290.0, 193.0], size=10.5),
                ], bbox=[175.2, 178.7, 290.0, 193.0]),
            ]),
        ]

        final_md_pages: List[str] = []
        all_images: List[Dict[str, Any]] = []
        layout_records: List[Dict[str, Any]] = []
        audit_data: Dict[str, Any] = {
            "headers_removed": 0,
            "footers_removed": 0,
            "headings_detected": [],
            "footnotes_matched": 0,
            "footnotes_fallback": 0,
            "footnotes_detail": [],
            "paragraphs_reflowed": 0,
            "ai_layout": {"decisions": []},
        }

        _process_single_pdf_page_layout(
            page=_MockPage(raw_blocks),
            page_num=127,
            body_size=10.5,
            body_font="simsun",
            toc_index={},
            toc_page_offset=[None],
            style_mapping={},
            font_role_map={},
            enable_footnotes=True,
            strip_headers_heuristic=False,
            ai_kaiti_classifier=None,
            ai_font_decision_cache={},
            retained_font_suggestions={},
            final_md_pages=final_md_pages,
            all_image_blocks=all_images,
            layout_records=layout_records,
            audit_data=audit_data,
        )

        joined = "\n\n".join(final_md_pages)
        assert "三、血小板减少" in joined
        assert "（PLT）低于100×109/L，或有活动性出血者" in joined
        assert "20kg/m2患者，需严密监测。" in joined
        assert "^" not in joined
        assert "<sup>" not in joined

    def test_bug017_both_superscript_reordering_cases_end_to_end(self):
        """End-to-end page layout integration for BUG-017 cases (10^9/L and 10^6 U)."""
        _require_stitch_physical_lines()

        class _Rect:
            width = 595.0
            height = 842.0

        class _MockPage:
            rect = _Rect()

            def __init__(self, blocks: List[Dict[str, Any]]):
                self._blocks = blocks

            def get_text(self, mode: str = "dict") -> Dict[str, Any]:
                return {"blocks": self._blocks}

            def find_tables(self):
                return None

        raw_blocks = [
            # Case 1: Short preceding line + superscript-split Line 1 ('9/L，...109/L，')
            _make_block([
                _make_line([_make_span("临床实验室检查：", [60.0, 86.0, 160.0, 99.0], size=10.5)]),
            ]),
            _make_block([
                _make_line([
                    _make_span("9", [325.2, 93.0, 329.0, 100.0], size=6.12),
                    _make_span("/L，少数可高达（60 ～ 80） ×10", [329.0, 100.0, 455.0, 113.0], size=10.5),
                    _make_span("9", [455.2, 93.0, 459.0, 100.0], size=6.12),
                    _make_span("/L，", [459.0, 100.0, 480.0, 113.0], size=10.5),
                ]),
            ]),
            _make_block([
                _make_line([
                    _make_span("　　患者外周血白细胞计数大多增高，一般为（10 ～ 20）×10", [60.0, 100.0, 325.0, 113.0], size=10.5),
                ]),
                _make_line([
                    _make_span("以中性粒细胞为主。", [60.0, 114.0, 165.0, 127.0], size=10.5),
                ]),
            ]),
            # Case 2: Tight 3-line paragraph with superscript '6 U肌内注射。' on final line
            _make_block([
                _make_line([
                    _make_span("　　用于免疫缺陷或全身播散者，可用阿昔洛韦5～7.5\u202fmg/kg，每8小时1次，连续5～7\u2002天。", [60.0, 160.0, 440.0, 173.2], size=10.5),
                ]),
                _make_line([
                    _make_span("也可每日静脉滴注或肌内注射单磷酸阿糖腺苷（Ara-AMP）5～10\u202fmg/kg，极严重者可加用干扰", [60.0, 173.5, 440.0, 186.7], size=10.5),
                ]),
                _make_line([
                    _make_span("素（IFN），每日（1～3）×10", [60.0, 187.0, 200.0, 200.2], size=10.5),
                ]),
            ]),
            _make_block([
                _make_line([
                    _make_span("6", [200.5, 180.0, 204.5, 187.0], size=6.12),
                    _make_span("\u202fU肌内注射。", [204.5, 187.0, 265.0, 200.2], size=10.5),
                ]),
            ]),
        ]

        final_md_pages: List[str] = []
        all_images: List[Dict[str, Any]] = []
        layout_records: List[Dict[str, Any]] = []
        audit_data: Dict[str, Any] = {
            "headers_removed": 0,
            "footers_removed": 0,
            "headings_detected": [],
            "footnotes_matched": 0,
            "footnotes_fallback": 0,
            "footnotes_detail": [],
            "paragraphs_reflowed": 0,
            "ai_layout": {"decisions": []},
        }

        _process_single_pdf_page_layout(
            page=_MockPage(raw_blocks),
            page_num=42,
            body_size=10.5,
            body_font="simsun",
            toc_index={},
            toc_page_offset=[None],
            style_mapping={},
            font_role_map={},
            enable_footnotes=False,
            strip_headers_heuristic=False,
            ai_kaiti_classifier=None,
            ai_font_decision_cache={},
            retained_font_suggestions={},
            final_md_pages=final_md_pages,
            all_image_blocks=all_images,
            layout_records=layout_records,
            audit_data=audit_data,
        )

        joined = "\n\n".join(final_md_pages)
        expected_p1 = "患者外周血白细胞计数大多增高，一般为（10 ～ 20）×109/L，少数可高达（60 ～ 80） ×109/L，以中性粒细胞为主。"
        expected_p2 = (
            "用于免疫缺陷或全身播散者，可用阿昔洛韦5～7.5\u202fmg/kg，每8小时1次，连续5～7\u2002天。"
            "也可每日静脉滴注或肌内注射单磷酸阿糖腺苷（Ara-AMP）5～10\u202fmg/kg，"
            "极严重者可加用干扰素（IFN），每日（1～3）×106\u202fU肌内注射。"
        )
        assert expected_p1 in joined
        assert expected_p2 in joined
        assert "干扰6\u202fU肌内注射。" not in joined
        assert "9/L，少数可高达（60 ～ 80） ×109/L，患者外周血" not in joined

    def test_bug017_real_pymupdf_superscript_pdf_sweep(self):
        """Real in-memory fitz PDF rendering with raised superscripts across pitches stays ordered."""
        _require_stitch_physical_lines()
        import fitz
        from src.scripts.book_layout_extractor import _parse_pdf_layout_flow

        font = "china-s"
        for raise_pt in (4.5, 6.5, 7.5):
            for pitch in (13.0, 14.5):
                doc: Any = fitz.open()
                try:
                    page = doc.new_page(width=700, height=842)
                    # Case 1
                    y0 = 100.0
                    t1a = "患者外周血白细胞计数大多增高，一般为（10～20）×10"
                    w1a = fitz.get_text_length(t1a, fontname=font, fontsize=10.5)
                    page.insert_text((81, y0), t1a, fontname=font, fontsize=10.5)
                    page.insert_text((81 + w1a, y0 - raise_pt), "9", fontname=font, fontsize=6.5)
                    w9 = fitz.get_text_length("9", fontname=font, fontsize=6.5)
                    t1b = "/L，少数可高达（60～80）×10"
                    page.insert_text((81 + w1a + w9, y0), t1b, fontname=font, fontsize=10.5)
                    w1b = fitz.get_text_length(t1b, fontname=font, fontsize=10.5)
                    page.insert_text((81 + w1a + w9 + w1b, y0 - raise_pt), "9", fontname=font, fontsize=6.5)
                    page.insert_text((81 + w1a + w9 + w1b + w9, y0), "/L，", fontname=font, fontsize=10.5)
                    page.insert_text((60, y0 + pitch), "以中性粒细胞为主。", fontname=font, fontsize=10.5)

                    # Case 2
                    y1 = 180.0
                    page.insert_text(
                        (81, y1),
                        "用于免疫缺陷或全身播散者，可用阿昔洛韦5～7.5 mg/kg，每8小时1次，连续5～7 天。",
                        fontname=font,
                        fontsize=10.5,
                    )
                    page.insert_text(
                        (60, y1 + pitch),
                        "也可每日静脉滴注或肌内注射单磷酸阿糖腺苷（Ara-AMP）5～10 mg/kg，极严重者可加用干扰",
                        fontname=font,
                        fontsize=10.5,
                    )
                    t2a = "素（IFN），每日（1～3）×10"
                    w2a = fitz.get_text_length(t2a, fontname=font, fontsize=10.5)
                    page.insert_text((60, y1 + 2 * pitch), t2a, fontname=font, fontsize=10.5)
                    page.insert_text((60 + w2a, y1 + 2 * pitch - raise_pt), "6", fontname=font, fontsize=6.5)
                    w6 = fitz.get_text_length("6", fontname=font, fontsize=6.5)
                    page.insert_text((60 + w2a + w6, y1 + 2 * pitch), " U肌内注射。", fontname=font, fontsize=10.5)

                    md_pages, _, _, _ = _parse_pdf_layout_flow(doc, enable_footnotes=False)
                finally:
                    doc.close()

                md = "\n\n".join(md_pages)
                assert (
                    "患者外周血白细胞计数大多增高，一般为（10～20）×109/L，少数可高达（60～80）×109/L，以中性粒细胞为主。"
                    in md
                ), f"Case 1 failed at raise={raise_pt}, pitch={pitch}: {md!r}"
                assert (
                    "极严重者可加用干扰素（IFN），每日（1～3）×106U肌内注射。" in md
                    or "极严重者可加用干扰素（IFN），每日（1～3）×106 U肌内注射。" in md
                ), f"Case 2 failed at raise={raise_pt}, pitch={pitch}: {md!r}"
                assert "干扰6" not in md
                assert "9/L，少数可高达（60～80）×109/L，患者外周血" not in md


@pytest.mark.skipif(
    not EMPIRICAL_PDF.is_file(),
    reason=f"Empirical PDF not present at {EMPIRICAL_PDF}",
)
class TestEmpiricalBookVectorLineStitching:
    """Integration checks on real PDF pages (skipped when empirical PDF is absent)."""

    @staticmethod
    def _page_texts(page_num: int, no_footnote: bool) -> List[str]:
        ast = extract_book_vector_ast(
            EMPIRICAL_PDF,
            no_footnote=no_footnote,
            ai_kaiti=False,
            page_range=(page_num, page_num),
        )
        return [
            p.raw_text
            for sec in ast.sections
            for p in sec.paragraphs
            if p.page_num == page_num
        ]

    @pytest.mark.parametrize("no_footnote", [True, False])
    def test_page_127_thrombocytopenia_stitched_both_footnote_modes(self, no_footnote: bool):
        texts = self._page_texts(127, no_footnote=no_footnote)
        combined = "\n".join(texts)
        assert "三、血小板减少" in combined
        assert "100×109/L" in combined
        assert not any(t.lstrip().startswith("9/L") for t in texts)
        assert "<sup>" not in combined

    def test_page_117_kg_m2_stitched(self):
        texts = self._page_texts(117, no_footnote=False)
        combined = "\n".join(texts)
        assert "20kg/m2" in combined

    def test_page_9_toc_preserved(self):
        texts = self._page_texts(9, no_footnote=False)
        assert len(texts) > 0

    def test_page_51_extracts_cleanly(self):
        texts = self._page_texts(51, no_footnote=False)
        assert len(texts) > 0

    def test_page_128_table_preserved(self):
        ast = extract_book_vector_ast(
            EMPIRICAL_PDF,
            no_footnote=False,
            ai_kaiti=False,
            page_range=(128, 128),
        )
        paras = [p for sec in ast.sections for p in sec.paragraphs if p.page_num == 128]
        assert any(p.font_name == "table" or "|" in p.raw_text for p in paras)
