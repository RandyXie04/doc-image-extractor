# -*- coding: utf-8 -*-
"""
Targeted Regression & Safety Gate Tests for BUG-007 / ADR-007
=============================================================
Covers:
1. Borderless Three-Line Table (三線表) 2D Coordinate Clustering Reconstruction
2. Top-of-page table header preservation (disabling heuristic header stripping by default)
3. False-positive 1x2 drop-cap / decorative frame filtering
4. Merged standalone & trailing section heading splitting ("1 临床资料", "...。 4 讨论")
5. POD Studio Stage 1 Original PDF upload + Stage 2 in-place flattened table upgrade to Word Table Grid
"""

import io
from pathlib import Path
from typing import Any
import fitz
import docx
import pytest
from fastapi.testclient import TestClient

from src.extraction.table_reconstructor import (
    TextSpan2D,
    TableRegion,
    ReconstructedTable,
    is_valid_pymupdf_table,
    detect_three_line_table_regions,
    extract_reconstructed_tables_from_page,
)
from src.scripts.book_layout_extractor import (
    extract_book_vector_ast,
    _split_merged_heading_blocks,
)
from src.pod_studio.pod_service import (
    compile_blueprint_from_seed,
    propagate_and_validate_session,
)
from src.web.app import app, CFG, PATHS


def _build_synthetic_table4_pdf(pdf_path: Path) -> Path:
    """
    Creates a synthetic PDF page mimicking Page 160 of the clinical manuscript:
    - Top-of-page Table 4 caption + 3 horizontal vector rules (no vertical borders)
    - Header row containing '/' ('ESR（mm/h）', 'CRP（mg/L）') near top of page
    - Vertically centered group cells ('刺络埋线组', '43') spanning 3 time rows
    - Merged trailing section heading '...（疗效对比时剔除）。 4 　讨论'
    """
    doc: Any = fitz.open()
    page = doc.new_page(width=515.9, height=728.5)

    # Caption at top of page
    page.insert_text(
        (135, 65),
        "表4　两组强直性脊柱炎患者治疗前后实验室指标比较（x±s）",
        fontsize=9.0,
        fontname="china-ss",
    )

    # Three horizontal rules (top, header-bottom, bottom) - ZERO vertical rules
    x_left, x_right = 76.0, 458.0
    y_top, y_mid, y_bot = 74.0, 91.0, 175.0
    page.draw_line(fitz.Point(x_left, y_top), fitz.Point(x_right, y_top), width=1.0)
    page.draw_line(fitz.Point(x_left, y_mid), fitz.Point(x_right, y_mid), width=0.5)
    page.draw_line(fitz.Point(x_left, y_bot), fitz.Point(x_right, y_bot), width=1.0)

    # Column X positions
    col_xs = [85.0, 155.0, 210.0, 290.0, 380.0]
    headers = ["组别", "例数", "时间", "ESR（mm/h）", "CRP（mg/L）"]
    for cx, h_txt in zip(col_xs, headers):
        page.insert_text((cx, 85.0), h_txt, fontsize=8.5, fontname="china-ss")

    # Group 1: vertically centered between y=102 and y=126 (around y=114)
    page.insert_text((col_xs[0], 114.0), "刺络埋线组", fontsize=8.5, fontname="china-ss")
    page.insert_text((col_xs[1], 114.0), "43", fontsize=8.5, fontname="china-ss")

    g1_rows = [
        (103.0, "治疗前", "28.56±13.97", "19.72±10.22"),
        (116.0, "治疗后", "12.63±4.99①", "7.91±3.56①"),
        (129.0, "差值", "15.93±12.68②", "11.81±8.97②"),
    ]
    for ry, t_label, esr_val, crp_val in g1_rows:
        page.insert_text((col_xs[2], ry), t_label, fontsize=8.5, fontname="china-ss")
        page.insert_text((col_xs[3], ry), esr_val, fontsize=8.5, fontname="china-ss")
        page.insert_text((col_xs[4], ry), crp_val, fontsize=8.5, fontname="china-ss")

    # Group 2: vertically centered between y=142 and y=168 (around y=155)
    page.insert_text((col_xs[0], 155.0), "药物组", fontsize=8.5, fontname="china-ss")
    page.insert_text((col_xs[1], 155.0), "43", fontsize=8.5, fontname="china-ss")

    g2_rows = [
        (143.0, "治疗前", "26.80±11.42", "18.89±9.88"),
        (156.0, "治疗后", "11.24±4.40①", "9.01±2.79①"),
        (169.0, "差值", "15.56±10.17", "9.88±8.96"),
    ]
    for ry, t_label, esr_val, crp_val in g2_rows:
        page.insert_text((col_xs[2], ry), t_label, fontsize=8.5, fontname="china-ss")
        page.insert_text((col_xs[3], ry), esr_val, fontsize=8.5, fontname="china-ss")
        page.insert_text((col_xs[4], ry), crp_val, fontsize=8.5, fontname="china-ss")

    # Table footnote below bottom rule
    page.insert_text(
        (76.0, 190.0),
        "注：与本组治疗前比较，① P <0.05；与药物组比较，② P <0.05。",
        fontsize=8.5,
        fontname="china-ss",
    )

    # Body paragraph + merged trailing heading
    page.insert_text(
        (76.0, 220.0),
        "埋线刺络组脱落2例，药物组脱落3例（疗效对比时剔除）。 4 　讨论",
        fontsize=10.5,
        fontname="china-ss",
    )

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestThreeLineTableAndHeadingFixes:
    """Gate 1 targeted tests for BUG-007 & ADR-007."""

    def test_false_positive_1x2_drop_cap_filtered(self):
        """Verifies narrow 1x2 decorative drop-cap frames are rejected while real tables pass."""
        drop_cap_matrix = [["", ""], ["", "第\n强"]]
        assert is_valid_pymupdf_table(drop_cap_matrix, (70.0, 100.0, 110.0, 150.0), 515.9) is False

        single_col_matrix = [["標題"], ["內容"]]
        assert is_valid_pymupdf_table(single_col_matrix, (70.0, 100.0, 450.0, 180.0), 515.9) is False

        valid_matrix = [
            ["组别", "例数", "时间", "ESR（mm/h）", "CRP（mg/L）"],
            ["刺络埋线组", "43", "治疗前", "28.56±13.97", "19.72±10.22"],
        ]
        assert is_valid_pymupdf_table(valid_matrix, (76.0, 74.0, 458.0, 175.0), 515.9) is True

    def test_three_line_table_reconstruction_and_header_preservation(self, tmp_path):
        """Verifies borderless three-line table reconstruction, header '/' preservation, and row-span snapping."""
        pdf_path = _build_synthetic_table4_pdf(tmp_path / "synth_table4.pdf")

        doc = fitz.open(str(pdf_path))
        try:
            page = doc[0]
            regions = detect_three_line_table_regions(page)
            assert len(regions) == 1
            tables = extract_reconstructed_tables_from_page(page)
            assert len(tables) == 1
            t4 = tables[0]
            assert isinstance(t4, ReconstructedTable)
            assert len(t4.headers) == 5
            assert "ESR（mm/h）" in t4.headers
            assert "CRP（mg/L）" in t4.headers
            assert len(t4.rows) == 6
            # Vertically centered group labels must snap to the first row ("治疗前") of each group
            assert t4.rows[0][0] == "刺络埋线组"
            assert t4.rows[0][1] == "43"
            assert t4.rows[0][2] == "治疗前"
            assert t4.rows[3][0] == "药物组"
            assert t4.rows[3][1] == "43"
            assert t4.rows[3][2] == "治疗前"
        finally:
            doc.close()

        # Verify full BookAST extraction preserves table header and splits trailing heading
        book_ast = extract_book_vector_ast(pdf_path, enable_footnotes=False)
        table_paras = [
            p for sec in book_ast.sections for p in sec.paragraphs if p.font_name == "table"
        ]
        assert len(table_paras) == 1
        assert "ESR（mm/h）" in table_paras[0].raw_text
        assert "刺络埋线组 | 43 | 治疗前" in table_paras[0].raw_text

        # Verify "4 　讨论" was split into a standalone section heading
        sec_titles = [sec.title for sec in book_ast.sections]
        assert any("4" in t and "讨论" in t for t in sec_titles)

    def test_real_manuscript_pages_156_159_160_if_available(self):
        """If the clinical test PDF is present in data/01_input, verify all 4 tables and headings."""
        real_pdf = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "01_input"
            / "POD測試檔_V1"
            / "551aefd9-6e96-41f3-b962-a5fab2bbee56.pdf"
        )
        if not real_pdf.exists():
            pytest.skip("Real clinical PDF fixture not present in workspace")

        book_ast = extract_book_vector_ast(
            real_pdf, enable_footnotes=False, page_range=(156, 160)
        )
        table_paras = [
            p for sec in book_ast.sections for p in sec.paragraphs if p.font_name == "table"
        ]
        assert len(table_paras) == 4
        # Table 4 on Page 160 must retain its header row with ESR（mm/h）
        t4_md = table_paras[3].raw_text
        assert "ESR（mm/h）" in t4_md
        assert "CRP（mg/L）" in t4_md
        assert "| 刺络埋线组 | 43 | 治疗前 | 32.81±10.00 | 21.56±11.86 |" in t4_md

        # Both "1　临床资料" (Page 156) and "4 　讨论" (Page 160) must be standalone section titles
        titles = [sec.title for sec in book_ast.sections]
        assert any("1" in t and "临床资料" in t for t in titles)
        assert any("4" in t and "讨论" in t for t in titles)

    def test_merged_heading_block_and_trailing_split(self):
        """Verifies _split_merged_heading_blocks separates tall-ascender heading lines from body lines."""
        synthetic_block = {
            "type": 0,
            "bbox": [76.0, 350.0, 458.0, 411.0],
            "lines": [
                {
                    "bbox": [76.0, 350.0, 458.0, 365.0],
                    "spans": [{"text": "探討埋線刺絡法的臨床療效，現報道如下。", "size": 10.5, "font": "FZSS"}],
                },
                {
                    "bbox": [76.0, 364.5, 200.0, 395.0],
                    "spans": [{"text": "1　臨床資料", "size": 12.0, "font": "FZHT"}],
                },
            ],
        }
        split_result = _split_merged_heading_blocks([synthetic_block])
        assert len(split_result) == 2
        line0_txt = "".join(s["text"] for l in split_result[0]["lines"] for s in l["spans"])
        line1_txt = "".join(s["text"] for l in split_result[1]["lines"] for s in l["spans"])
        assert line0_txt == "探討埋線刺絡法的臨床療效，現報道如下。"
        assert line1_txt == "1　臨床資料"

    def test_pod_stage1_pdf_upload_and_stage2_inplace_table_upgrade(self, tmp_path):
        """
        Verifies POD Studio Stage 1 accepts both seed_file (.docx) and pdf_file (.pdf),
        and Stage 2 upgrades flattened text tables after last_modified_idx into Word Table Grid
        while splitting trailing merged headings.
        """
        pdf_path = _build_synthetic_table4_pdf(tmp_path / "source_book.pdf")

        # Create a partially styled seed.docx where paragraphs 0..2 are human-styled,
        # paragraph 3 has 【人工整稿截止】, and subsequent paragraphs contain flattened Table 4
        seed_path = tmp_path / "seed_with_flattened_table4.docx"
        doc = docx.Document()
        p0 = doc.add_paragraph("第一章 強直性脊柱炎臨床研究", style="Heading 1")
        p1 = doc.add_paragraph("1　臨床資料", style="Heading 2")
        p2 = doc.add_paragraph("患者共86例，隨機分為兩組。【人工整稿截止】")

        # Subsequent unedited paragraphs (index > 2) with flattened Table 4 and merged heading
        doc.add_paragraph("表4　两组强直性脊柱炎患者治疗前后实验室指标比较（x±s）")
        doc.add_paragraph("治疗前 28.56±13.97 19.72±10.22")
        doc.add_paragraph("刺络埋线组 43 治疗后 12.63±4.99① 7.91±3.56①")
        doc.add_paragraph("差值 15.93±12.68② 11.81±8.97②")
        doc.add_paragraph("治疗前 26.80±11.42 18.89±9.88")
        doc.add_paragraph("药物组 43 治疗后 11.24±4.40① 9.01±2.79①")
        doc.add_paragraph("差值 15.56±10.17 9.88±8.96")
        doc.add_paragraph("注：与本组治疗前比较，① P <0.05；与药物组比较，② P <0.05。")
        doc.add_paragraph("埋线刺络组脱落2例，药物组脱落3例（疗效对比时剔除）。 4 　讨论")
        doc.save(str(seed_path))

        # Test Stage 1 API (/api/pod/2_compile_blueprint) with both seed_file and pdf_file
        client = TestClient(app)
        if CFG.auth_enabled and CFG.auth_password:
            client.headers["X-API-Key"] = CFG.auth_password
        with open(seed_path, "rb") as sf, open(pdf_path, "rb") as pf:
            res = client.post(
                "/api/pod/2_compile_blueprint",
                files={
                    "seed_file": ("seed.docx", sf, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                    "pdf_file": ("source_book.pdf", pf, "application/pdf"),
                },
            )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["has_source_pdf"] is True
        assert data["detected_tables_count"] == 1
        session_id = data["session_id"]

        # Test Stage 2 API (/api/pod/3_propagate_and_validate)
        res2 = client.post(
            "/api/pod/3_propagate_and_validate",
            data={"session_id": session_id, "engine_mode": "rule_first"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "success"

        # Inspect generated Book_POD_Final.docx
        final_docx_path = PATHS.output_dir / "pod_workspaces" / session_id / "Book_POD_Final.docx"
        assert final_docx_path.exists()

        final_doc = docx.Document(str(final_docx_path))
        # 1. Must contain 1 upgraded Word table (7 rows x 5 cols) with Table Grid style
        assert len(final_doc.tables) == 1
        tbl = final_doc.tables[0]
        assert len(tbl.rows) == 7
        assert len(tbl.columns) == 5
        header_cells = [c.text.strip() for c in tbl.rows[0].cells]
        assert header_cells == ["组别", "例数", "时间", "ESR（mm/h）", "CRP（mg/L）"]
        row1_cells = [c.text.strip() for c in tbl.rows[1].cells]
        assert row1_cells[:3] == ["刺络埋线组", "43", "治疗前"]

        # 2. Flattened table text lines must be removed from paragraphs, while caption and footnote remain
        para_texts = [p.text.strip() for p in final_doc.paragraphs if p.text.strip()]
        assert any(t.startswith("表4") for t in para_texts)
        assert any(t.startswith("注：与本组治疗前比较") for t in para_texts)
        assert not any(t.startswith("治疗前 28.56") for t in para_texts)
        assert not any(t.startswith("刺络埋线组 43 治疗后") for t in para_texts)

        # 3. Merged trailing heading "...。 4 　讨论" must be split into body + standalone Heading 2
        assert "埋线刺络组脱落2例，药物组脱落3例（疗效对比时剔除）。" in para_texts
        disc_paras = [p for p in final_doc.paragraphs if "4" in p.text and "讨论" in p.text]
        assert len(disc_paras) == 1
        assert disc_paras[0].text.strip() == "4 　讨论"
        assert disc_paras[0].style is not None and disc_paras[0].style.name in ("Heading 2", "標題 2")