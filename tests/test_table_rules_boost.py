# -*- coding: utf-8 -*-
"""
Comprehensive Unit, Integration, and Real-PDF Regression Tests for the 5 Auto-Manuscript Table Rules:
1. Trailing empty row & table-note detachment (split_trailing_table_notes, normalize_pymupdf_table_rows).
2. Cross-page merge tolerance for numbered continuation markers ('表X-Y（续）', '续表X-Y') and standalone page numbers.
3. Placeholder column header stripping ('欄1'/'欄2'/'Col 1') and redundant fragment table deduplication.
4. Merged cell rowspan/colspan preservation (PyMuPDF -> HTML <table> -> native Word OOXML vMerge/gridSpan).
5. Cell typography normalization (CJK/Roman/operator spacing, control chars) and superscript/subscript OOXML preservation.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import docx
from docx.oxml.ns import qn
import fitz
import pypandoc
import pytest

from src.extraction.table_reconstructor import (
    build_table_span_grid,
    clean_table_cell_text,
    extract_cell_text_with_scripts,
    is_continuation_table_marker,
    is_placeholder_header_row,
    is_standalone_page_number_text,
    merge_gfm_tables_if_compatible,
    normalize_pymupdf_table_rows,
    render_span_grid_to_html,
    split_trailing_table_notes,
)
from src.scripts.book_layout_extractor import (
    _merge_cross_page_layout_tables,
    _parse_pdf_layout_flow,
    _table_to_markdown,
)
from src.scripts.md_to_docx import (
    apply_table_styles_to_docx,
    extract_html_tables_for_pandoc,
    inject_html_tables_and_scripts_into_docx,
    protect_inline_scripts_for_pandoc,
)


# ── Rule 1: Trailing empty rows & table note detachment ─────────────────────────

def test_split_trailing_table_notes_table16_3_pattern():
    raw_rows = [
        ["类别", "标准", "GPA", "MPA", "EGPA"],
        ["临床标准", "鼻腔受累", "+3", "-3", ""],
        ["分类总分阈值", "", "≥5", "≥5", "﹥6"],
        ["", None, None, None, None],
        ["注：·GPA：肉芽肿性多血管炎；MPA：显微镜下多血管炎。", None, None, None, None],
        ["·\x07适用标准的得分相加（需满足入选", None, None, None, None],
        ["要求）。", None, None, None, None],
        ["·\x07ANCA：抗中性粒细胞胞浆抗体。", None, None, None, None],
    ]
    cleaned = normalize_pymupdf_table_rows(raw_rows)
    body_rows, notes = split_trailing_table_notes(cleaned)

    assert len(body_rows) == 3
    assert body_rows[-1][0] == "分类总分阈值"
    assert len(notes) == 3
    assert notes[0].startswith("注：·GPA：")
    assert notes[1] == "·适用标准的得分相加（需满足入选要求）。"
    assert "\x07" not in "".join(notes)
    assert notes[2] == "·ANCA：抗中性粒细胞胞浆抗体。"


def test_normalize_strips_trailing_empty_rows_without_touching_valid_last_row():
    raw_with_empty = [
        ["项目", "值"],
        ["甲", "10"],
        ["", ""],
        [None, "   "],
    ]
    cleaned = normalize_pymupdf_table_rows(raw_with_empty)
    assert cleaned == [["项目", "值"], ["甲", "10"]]

    # Non-note single-cell last row MUST NOT be detached as a note
    non_note = [["项目", "值"], ["甲", "10"], ["备注", ""]]
    body, notes = split_trailing_table_notes(non_note)
    assert body == non_note
    assert notes == []


# ── Rule 2: Cross-page merge tolerance (numbered continuation + page number) ──

@pytest.mark.parametrize(
    "text",
    [
        "续表",
        "續表",
        "（续表）",
        "（续前表）",
        "续表13-1",
        "續表 16-3 分类标准",
        "表13-1（续）",
        "表 13-1 (续表)",
        "表13-1　黑色素瘤TNM分期（续）",
        "表4-2 续",
        "Table 3-1 (continued)",
        "Table 2 (cont.)",
    ],
)
def test_is_continuation_table_marker_accepts_numbered_and_parenthesized_variants(text: str):
    assert is_continuation_table_marker(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "表13-1 黑色素瘤TNM分期",
        "详见续表说明。",
        "续表\n第二行正文",
        "这是一段包含续表字样的普通正文句子，不应被误判为续表标记。",
    ],
)
def test_is_continuation_table_marker_rejects_captions_and_prose(text: str):
    assert is_continuation_table_marker(text) is False


@pytest.mark.parametrize("text", ["256", "- 256 -", "·283·", "— 12 —", "256 / 444", "第 12 页", "第8頁"])
def test_is_standalone_page_number_text_positive(text: str):
    assert is_standalone_page_number_text(text) is True


@pytest.mark.parametrize("text", ["", "2022年标准", "1. 临床资料", "表13-1", "256例"])
def test_is_standalone_page_number_text_negative(text: str):
    assert is_standalone_page_number_text(text) is False


def test_merge_cross_page_layout_tables_bridges_numbered_continuation_and_page_number():
    t1 = "| 符号 | 描述 |\n| --- | --- |\n| T1 | ≤1.0 mm |"
    t2 = "| 符号 | 描述 |\n| --- | --- |\n| N3 | ≥4个淋巴结 |"
    t3 = "| 符号 | 描述 |\n| --- | --- |\n| M1 | 远处转移 |"

    snaps = [
        {
            "page_num": 1,
            "page_h": 800.0,
            "body_size": 10.5,
            "paragraphs": [t1, "255"],
            "records": [
                {"type": "table", "raw_md": t1, "bbox": [50, 400, 480, 680]},
                # Page number inside non-margin Y (e.g. cropped page)
                {"type": "paragraph", "raw_text": "255", "bbox": [250, 690, 275, 705]},
            ],
        },
        {
            "page_num": 2,
            "page_h": 800.0,
            "body_size": 10.5,
            "paragraphs": ["256", "表13-1（续）", t2],
            "records": [
                {"type": "paragraph", "raw_text": "256", "bbox": [250, 120, 275, 135]},
                {"type": "paragraph", "raw_text": "表13-1（续）", "bbox": [65, 140, 180, 155]},
                {"type": "table", "raw_md": t2, "bbox": [50, 160, 480, 320]},
            ],
        },
        {
            "page_num": 3,
            "page_h": 800.0,
            "body_size": 10.5,
            "paragraphs": ["正文中断段落，禁止跨段合并。", t3],
            "records": [
                {"type": "paragraph", "raw_text": "正文中断段落，禁止跨段合并。", "bbox": [65, 100, 320, 118]},
                {"type": "table", "raw_md": t3, "bbox": [50, 140, 480, 280]},
            ],
        },
    ]

    _merge_cross_page_layout_tables(snaps)

    assert len(snaps[0]["records"]) == 1
    merged_md = snaps[0]["records"][0]["raw_md"]
    assert "| T1 | ≤1.0 mm |" in merged_md
    assert "| N3 | ≥4个淋巴结 |" in merged_md
    assert merged_md.count("| 符号 | 描述 |") == 1
    assert snaps[1]["records"] == []
    assert len(snaps[2]["records"]) == 2  # prose guard still blocks page 3


# ── Rule 3: Placeholder headers & duplicate fragment table deduplication ──────

def test_placeholder_header_detection_and_gfm_dedup():
    assert is_placeholder_header_row(["欄1", "欄2", "欄3"]) is True
    assert is_placeholder_header_row(["栏1", "栏2"]) is True
    assert is_placeholder_header_row(["Col 1", "Col 2", ""]) is True
    assert is_placeholder_header_row(["Unnamed: 0", "Column 2"]) is True
    assert is_placeholder_header_row(["序号", "名称"]) is False
    assert is_placeholder_header_row(["欄1", "真实标题"]) is False
    assert is_placeholder_header_row(["", ""]) is False

    main_t = "| 符号 | 描述 |\n| --- | --- |\n| T1 | ≤1.0 mm |\n| T2 | 1.01～2.0 mm |"
    placeholder_cont = "| 欄1 | 欄2 |\n| --- | --- |\n| T3 | 2.01～4.0 mm |"
    merged = merge_gfm_tables_if_compatible(main_t, placeholder_cont, has_continuation_marker=False)
    assert merged is not None
    assert "欄1" not in merged
    assert "| T3 | 2.01～4.0 mm |" in merged

    dup_frag = "| 欄1 | 欄2 |\n| --- | --- |\n| T2 | 1.01～2.0 mm |"
    deduped = merge_gfm_tables_if_compatible(main_t, dup_frag, has_continuation_marker=False)
    assert deduped is not None
    assert deduped.count("| T2 | 1.01～2.0 mm |") == 1


def test_docx_coalesce_handles_numbered_continuation_page_num_placeholder_and_duplicate_fragment(tmp_path: Path):
    docx_path = tmp_path / "coalesce_rules.docx"
    doc = docx.Document()

    # Main table
    t1 = doc.add_table(rows=3, cols=2)
    t1.rows[0].cells[0].text, t1.rows[0].cells[1].text = "符号", "描述"
    t1.rows[1].cells[0].text, t1.rows[1].cells[1].text = "T1", "≤1.0 mm"
    t1.rows[2].cells[0].text, t1.rows[2].cells[1].text = "T2", "1.01～2.0 mm"

    # Unfiltered page number + numbered continuation marker
    doc.add_paragraph("256")
    doc.add_paragraph("表13-1（续）")

    # Continuation with placeholder header '欄1' | '欄2'
    t2 = doc.add_table(rows=2, cols=2)
    t2.rows[0].cells[0].text, t2.rows[0].cells[1].text = "欄1", "欄2"
    t2.rows[1].cells[0].text, t2.rows[1].cells[1].text = "T3", "2.01～4.0 mm"

    # Redundant duplicate fragment immediately following
    doc.add_paragraph("")
    t3 = doc.add_table(rows=2, cols=2)
    t3.rows[0].cells[0].text, t3.rows[0].cells[1].text = "栏1", "栏2"
    t3.rows[1].cells[0].text, t3.rows[1].cells[1].text = "T2", "1.01～2.0 mm"

    # Unrelated table separated by page number ONLY (no continuation marker, different real headers) -> MUST NOT merge
    doc.add_paragraph("257")
    t4 = doc.add_table(rows=2, cols=2)
    t4.rows[0].cells[0].text, t4.rows[0].cells[1].text = "厚度", "范围"
    t4.rows[1].cells[0].text, t4.rows[1].cells[1].text = "＞1 mm", "1.0 cm"

    doc.save(str(docx_path))
    apply_table_styles_to_docx(str(docx_path))

    reloaded = docx.Document(str(docx_path))
    assert len(reloaded.tables) == 2

    merged_rows = [[c.text.strip() for c in r.cells] for r in reloaded.tables[0].rows]
    assert merged_rows == [
        ["符号", "描述"],
        ["T1", "≤1.0 mm"],
        ["T2", "1.01～2.0 mm"],
        ["T3", "2.01～4.0 mm"],
    ]
    second_rows = [[c.text.strip() for c in r.cells] for r in reloaded.tables[1].rows]
    assert second_rows == [["厚度", "范围"], ["＞1 mm", "1.0 cm"]]


# ── Rule 4: Merged cell rowspan/colspan preservation (HTML -> DOCX OOXML) ─────

def test_build_span_grid_explicit_colspan_and_implicit_category_rowspan():
    # Case A: Explicit geometric colspan in PyMuPDF table_obj
    rows_explicit = [
        ["类别", "标准", "得分"],
        ["临床", "鼻腔受累", "+3"],
        ["总分阈值", "", "≥5"],
    ]
    fake_table = SimpleNamespace(
        rows=[
            SimpleNamespace(cells=[(0, 0, 100, 20), (100, 0, 260, 20), (260, 0, 320, 20)]),
            SimpleNamespace(cells=[(0, 20, 100, 40), (100, 20, 260, 40), (260, 20, 320, 40)]),
            SimpleNamespace(cells=[(0, 40, 260, 60), None, (260, 40, 320, 60)]),
        ]
    )
    grid, has_merges = build_table_span_grid(rows_explicit, table_obj=fake_table)
    assert has_merges is True
    html_out = render_span_grid_to_html(grid)
    assert '<td colspan="2">总分阈值</td>' in html_out

    # Case B: Implicit leading-column category rowspans (Table 16-3 pattern)
    rows_grouped = [
        ["类别", "标准", "GPA"],
        ["临床标准", "鼻腔受累", "+3"],
        ["", "软骨受累", "+2"],
        ["实验室标准", "PR3-ANCA", "+5"],
        ["", "MPO-ANCA", "-1"],
        ["分类总分阈值", "", "≥5"],
    ]
    grid2, has_merges2 = build_table_span_grid(rows_grouped)
    assert has_merges2 is True
    html2 = render_span_grid_to_html(grid2)
    assert '<td rowspan="2">临床标准</td>' in html2
    assert '<td rowspan="2">实验室标准</td>' in html2
    assert "<td>分类总分阈值</td><td></td><td>≥5</td>" in html2

    # Case C: Simple ungrouped table MUST stay flat (has_merges=False)
    rows_flat = [["符号", "描述", "附注"], ["T1", "≤1 mm", "a"], ["T2", "2 mm", "b"]]
    _, has_merges3 = build_table_span_grid(rows_flat)
    assert has_merges3 is False


def test_html_table_and_inline_scripts_roundtrip_to_word_ooxml(tmp_path: Path):
    md = (
        "前文 2~3次 不应误转下标。\n\n"
        "<table>\n"
        "<thead><tr><th>类别</th><th>标准</th><th>值</th></tr></thead>\n"
        "<tbody>\n"
        '<tr><td rowspan="2">临床标准</td><td>鼻腔受累</td><td>+3</td></tr>\n'
        "<tr><td>软骨受累</td><td>+2</td></tr>\n"
        '<tr><td colspan="2">总分阈值</td><td>10<sup>9</sup>/L</td></tr>\n'
        "</tbody>\n"
        "</table>\n\n"
        "| 项目 | 免疫表现型 |\n"
        "| --- | --- |\n"
        "| CBCL | HLA-DR/Ia<sup>+</sup>，H<sub>2</sub>O |\n"
    )
    rewritten, html_tables = extract_html_tables_for_pandoc(md)
    assert len(html_tables) == 1
    rewritten = protect_inline_scripts_for_pandoc(rewritten)

    out_docx = tmp_path / "roundtrip.docx"
    pypandoc.convert_text(
        rewritten,
        "docx",
        format="markdown-implicit_figures-subscript+raw_html+tex_math_dollars",
        outputfile=str(out_docx),
    )
    inject_html_tables_and_scripts_into_docx(str(out_docx), html_tables)
    apply_table_styles_to_docx(str(out_docx))

    doc = docx.Document(str(out_docx))
    assert len(doc.tables) == 2

    # Verify prose '2~3次' has NO subscript vertAlign
    prose_p = doc.paragraphs[0]
    assert "2~3次" in prose_p.text
    assert prose_p._p.findall(".//" + qn("w:vertAlign")) == []

    # Table 0: HTML table with rowspan=2, colspan=2, and 10^9/L superscript
    t0 = doc.tables[0]._tbl
    trs0 = t0.findall(qn("w:tr"))
    assert len(trs0) == 4
    # Row 1 col 0: vMerge restart
    r1_c0_vm = trs0[1].findall(qn("w:tc"))[0].find(qn("w:tcPr")).find(qn("w:vMerge"))
    assert r1_c0_vm is not None and r1_c0_vm.get(qn("w:val")) == "restart"
    # Row 2 col 0: vMerge continuation (no w:val)
    r2_c0_vm = trs0[2].findall(qn("w:tc"))[0].find(qn("w:tcPr")).find(qn("w:vMerge"))
    assert r2_c0_vm is not None and r2_c0_vm.get(qn("w:val")) is None
    # Row 3 col 0: gridSpan=2
    r3_c0_gs = trs0[3].findall(qn("w:tc"))[0].find(qn("w:tcPr")).find(qn("w:gridSpan"))
    assert r3_c0_gs is not None and r3_c0_gs.get(qn("w:val")) == "2"
    # Row 3 col 1: superscript '9'
    t0_vas = [va.get(qn("w:val")) for va in trs0[3].iter(qn("w:vertAlign"))]
    assert t0_vas == ["superscript"]

    # Table 1: GFM pipe table with both superscript '+' and subscript '2'
    t1 = doc.tables[1]._tbl
    t1_vas = [va.get(qn("w:val")) for va in t1.iter(qn("w:vertAlign"))]
    assert t1_vas == ["superscript", "subscript"]


# ── Rule 5: Cell typography normalization & PDF superscript/subscript spans ───

def test_clean_table_cell_text_typography_and_ascii_preservation():
    assert clean_table_cell_text("a：无溃疡及Ⅰ、Ⅱ层面；b：有溃疡或Ⅳ、Ⅴ\n层面") == "a：无溃疡及Ⅰ、Ⅱ层面；b：有溃疡或Ⅳ、Ⅴ层面"
    assert clean_table_cell_text("血 尿（ ＞ 10 个 RBC/HPF 或 尿 试 纸\n≥1+）") == "血尿（＞10个 RBC/HPF 或尿试纸≥1+）"
    assert clean_table_cell_text("影像学显示鼻/ 鼻窦炎或乳突炎") == "影像学显示鼻/鼻窦炎或乳突炎"
    assert clean_table_cell_text("·\x07适用标准") == "·适用标准"
    assert clean_table_cell_text("CD1、 CD20、CD22 阳性") == "CD1、CD20、CD22 阳性"
    assert clean_table_cell_text("1. 八珍粥\n2. 桂圆红枣粥") == "1. 八珍粥 2. 桂圆红枣粥"
    assert clean_table_cell_text("HLA-DR/Ia<sup>+</sup>") == "HLA-DR/Ia<sup>+</sup>"


def test_extract_cell_text_with_scripts_detects_sup_and_sub_from_pdf(tmp_path: Path):
    pdf_path = tmp_path / "scripts_cell.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    # Draw baseline text "Ia" at y=100, size=10, then raised "+" at y=95, size=6
    page.insert_text(fitz.Point(50, 100), "Ia", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(60, 95), "+", fontsize=6, fontname="helv")
    # Draw baseline "H" size=10, lowered "2" at y=103 size=6, baseline "O" at y=100 size=10
    page.insert_text(fitz.Point(100, 100), "H", fontsize=10, fontname="helv")
    page.insert_text(fitz.Point(108, 103), "2", fontsize=6, fontname="helv")
    page.insert_text(fitz.Point(113, 100), "O", fontsize=10, fontname="helv")
    doc.save(str(pdf_path))
    doc.close()

    with fitz.open(str(pdf_path)) as opened:
        extracted = extract_cell_text_with_scripts(opened[0], (40, 80, 140, 115))
    assert "Ia<sup>+</sup>" in extracted
    assert "H<sub>2</sub>O" in extracted


# ── Real-PDF Regression Gate (runs when book PDF is present locally) ──────────

def test_real_dermatology_pdf_five_table_rules_if_available(tmp_path: Path):
    pdf_path = Path("data/01_input/内文--S2556 内蒙古 皮肤科诊治要点与病例精讲.pdf")
    if not pdf_path.is_file():
        pytest.skip("Dermatology reference PDF not present in data/01_input")

    with fitz.open(str(pdf_path)) as doc:
        # 1 & 4 & 5: p.351 Table 16-3
        _, _, _, recs_351 = _parse_pdf_layout_flow(doc, enable_footnotes=False, page_range=(351, 351))
        tbls_351 = [r for r in recs_351 if r["type"] == "table"]
        assert len(tbls_351) == 1
        t351 = tbls_351[0]["raw_md"]
        assert '<td rowspan="6">临床标准</td>' in t351
        assert '<td rowspan="4">实验室标准</td>' in t351
        assert '<td rowspan="3">组织学标准</td>' in t351
        assert '<td rowspan="3">影像学标准</td>' in t351
        assert "注：" not in t351
        assert "血尿（＞10个 RBC/HPF 或尿试纸≥1+）" in t351
        # Notes detached as separate paragraphs right after table
        paras_351 = [r.get("raw_text", "") for r in recs_351 if r["type"] == "paragraph"]
        assert any(p.startswith("注：·GPA：") for p in paras_351)
        assert any("（需满足入选要求）。" in p for p in paras_351)

        # 2 & 5: p.255-256 Table 13-1 merged cleanly & Roman numeral spacing normalized
        _, _, _, recs_255 = _parse_pdf_layout_flow(doc, enable_footnotes=False, page_range=(255, 256))
        tbls_255 = [r for r in recs_255 if r["type"] == "table"]
        assert len(tbls_255) == 1
        assert "Ⅳ、Ⅴ层面" in tbls_255[0]["raw_md"]
        assert "| M1c |" in tbls_255[0]["raw_md"]

        # 5: p.259-260 Table 13-4 superscript '+' preserved
        _, _, _, recs_259 = _parse_pdf_layout_flow(doc, enable_footnotes=False, page_range=(259, 260))
        tbls_259 = [r for r in recs_259 if r["type"] == "table"]
        assert len(tbls_259) == 1
        assert "HLA-DR/Ia<sup>+</sup>" in tbls_259[0]["raw_md"]
        assert "CD1、CD20、CD22" in tbls_259[0]["raw_md"]
