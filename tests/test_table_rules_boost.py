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
from typing import Any

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
        "（续表13-1）",
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
    doc: Any = fitz.open()
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


# ── Adversarial Regression Tests (Mixed HTML/GFM, Multi-row Headers, Pandoc Scripts) ──

def test_mixed_html_and_gfm_cross_page_merge_and_dedup():
    html_p1 = (
        "<table>\n<thead>\n<tr><th>类别</th><th>标准</th><th>值</th></tr>\n</thead>\n"
        '<tbody>\n<tr><td rowspan="2">临床</td><td>鼻腔</td><td>+3</td></tr>\n'
        "<tr><td>软骨</td><td>+2</td></tr>\n</tbody>\n</table>"
    )
    gfm_p2 = "| 类别 | 标准 | 值 |\n| --- | --- | --- |\n| 影像 | 肺部 | +2 |"

    merged_hg = merge_gfm_tables_if_compatible(html_p1, gfm_p2, has_continuation_marker=True)
    assert merged_hg is not None
    assert '<td rowspan="2">临床</td>' in merged_hg
    assert "<td>肺部</td>" in merged_hg
    assert merged_hg.count("<th>类别</th>") == 1

    merged_gh = merge_gfm_tables_if_compatible(gfm_p2, html_p1, has_continuation_marker=True)
    assert merged_gh is not None
    assert '<td rowspan="2">临床</td>' in merged_gh
    assert "<td>肺部</td>" in merged_gh

    # Duplicate HTML fragment and duplicate GFM fragment against HTML main table must deduplicate
    html_dup = (
        "<table>\n<thead>\n<tr><th>栏1</th><th>栏2</th><th>栏3</th></tr>\n</thead>\n"
        '<tbody>\n<tr><td rowspan="2">临床</td><td>鼻腔</td><td>+3</td></tr>\n'
        "<tr><td>软骨</td><td>+2</td></tr>\n</tbody>\n</table>"
    )
    dedup_hh = merge_gfm_tables_if_compatible(html_p1, html_dup, has_continuation_marker=False)
    assert dedup_hh is not None and dedup_hh.count("鼻腔") == 1 and dedup_hh.count("软骨") == 1

    gfm_dup = "| 栏1 | 栏2 | 栏3 |\n| --- | --- | --- |\n| 临床 | 鼻腔 | +3 |\n|  | 软骨 | +2 |"
    dedup_hg = merge_gfm_tables_if_compatible(html_p1, gfm_dup, has_continuation_marker=False)
    assert dedup_hg is not None and dedup_hg.count("鼻腔") == 1 and dedup_hg.count("软骨") == 1


def test_explicit_colspan_coexists_with_implicit_category_rowspan():
    rows = [
        ["类别", "标准", "GPA"],
        ["临床标准", "鼻腔受累", "+3"],
        ["", "软骨受累", "+2"],
        ["实验室标准", "PR3-ANCA", "+5"],
        ["", "MPO-ANCA", "-1"],
        ["分类总分阈值", "", "≥5"],
    ]
    fake_tbl = SimpleNamespace(
        rows=[
            SimpleNamespace(cells=[(0, 0, 100, 20), (100, 0, 260, 20), (260, 0, 320, 20)]),
            SimpleNamespace(cells=[(0, 20, 100, 40), (100, 20, 260, 40), (260, 20, 320, 40)]),
            SimpleNamespace(cells=[(0, 40, 100, 60), (100, 40, 260, 60), (260, 40, 320, 60)]),
            SimpleNamespace(cells=[(0, 60, 100, 80), (100, 60, 260, 80), (260, 60, 320, 80)]),
            SimpleNamespace(cells=[(0, 80, 100, 100), (100, 80, 260, 100), (260, 80, 320, 100)]),
            SimpleNamespace(cells=[(0, 100, 260, 120), None, (260, 100, 320, 120)]),
        ]
    )
    grid, has_merges = build_table_span_grid(rows, table_obj=fake_tbl)
    assert has_merges is True
    html_out = render_span_grid_to_html(grid)
    assert '<td rowspan="2">临床标准</td>' in html_out
    assert '<td rowspan="2">实验室标准</td>' in html_out
    assert '<td colspan="2">分类总分阈值</td>' in html_out


def test_multi_row_merged_thead_preserves_html_structure_and_word_tbl_header(tmp_path: Path):
    rows = [
        ["项目", "实验组", ""],
        ["", "男", "女"],
        ["甲", "10", "12"],
    ]
    fake_tbl = SimpleNamespace(
        rows=[
            SimpleNamespace(cells=[(0, 0, 80, 40), (80, 0, 240, 20), None]),
            SimpleNamespace(cells=[None, (80, 20, 160, 40), (160, 20, 240, 40)]),
            SimpleNamespace(cells=[(0, 40, 80, 60), (80, 40, 160, 60), (160, 40, 240, 60)]),
        ]
    )
    grid, has_merges = build_table_span_grid(rows, table_obj=fake_tbl)
    assert has_merges is True
    html_out = render_span_grid_to_html(grid)
    assert "<thead>\n<tr><th rowspan=\"2\">项目</th><th colspan=\"2\">实验组</th></tr>\n<tr><th>男</th><th>女</th></tr>\n</thead>" in html_out

    rewritten, html_tables = extract_html_tables_for_pandoc(html_out)
    out_docx = tmp_path / "multi_thead.docx"
    pypandoc.convert_text(
        rewritten,
        "docx",
        format="markdown-implicit_figures-subscript+raw_html",
        outputfile=str(out_docx),
    )
    inject_html_tables_and_scripts_into_docx(str(out_docx), html_tables)
    apply_table_styles_to_docx(str(out_docx))

    reloaded = docx.Document(str(out_docx))
    trs = reloaded.tables[0]._tbl.findall(qn("w:tr"))
    assert len(trs) == 3
    hdr_flags = [tr.find(qn("w:trPr")).find(qn("w:tblHeader")) is not None for tr in trs]
    assert hdr_flags == [True, True, False]


def test_ooxml_html_table_preserves_fully_spanned_empty_tr_and_math_comparisons(tmp_path: Path):
    html_tbl = (
        "<table><tbody>"
        '<tr><td rowspan="2">A</td><td rowspan="2" colspan="2">x < 5 and y > 3</td></tr>'
        "<tr></tr>"
        "<tr><td>D</td><td>a &lt; b &amp; c &gt; d</td><td>F</td></tr>"
        "</tbody></table>"
    )
    rewritten, html_tables = extract_html_tables_for_pandoc(html_tbl)
    out_docx = tmp_path / "fullspan_math.docx"
    pypandoc.convert_text(
        rewritten,
        "docx",
        format="markdown-implicit_figures-subscript+raw_html",
        outputfile=str(out_docx),
    )
    inject_html_tables_and_scripts_into_docx(str(out_docx), html_tables)

    reloaded = docx.Document(str(out_docx))
    trs = reloaded.tables[0]._tbl.findall(qn("w:tr"))
    assert len(trs) == 3
    # Row 1 must hold the two vMerge continuation cells (col 0 width=1, cols 1-2 gridSpan=2)
    r1_tcs = trs[1].findall(qn("w:tc"))
    assert len(r1_tcs) == 2
    assert r1_tcs[1].find(qn("w:tcPr")).find(qn("w:gridSpan")).get(qn("w:val")) == "2"
    assert reloaded.tables[0].rows[0].cells[1].text == "x < 5 and y > 3"
    assert reloaded.tables[0].rows[2].cells[1].text == "a < b & c > d"


def test_inline_scripts_with_markdown_syntax_chars_survive_pandoc_roundtrip(tmp_path: Path):
    md = (
        "| 项目 | 指标 |\n"
        "| --- | --- |\n"
        "| 细胞 | A<sup>*</sup> 与 B<sup>*</sup> |\n"
        "| 基因 | X<sub>a_1</sub> 與 Y<sub>b_2</sub> |\n"
        "| 数值 | **10<sup>9</sup>/L** 與 2<sup>^3</sup> |\n"
    )
    rewritten, html_tables = extract_html_tables_for_pandoc(md)
    rewritten = protect_inline_scripts_for_pandoc(rewritten)
    out_docx = tmp_path / "markdown_chars_scripts.docx"
    pypandoc.convert_text(
        rewritten,
        "docx",
        format="markdown-implicit_figures-subscript+raw_html+tex_math_dollars",
        outputfile=str(out_docx),
    )
    inject_html_tables_and_scripts_into_docx(str(out_docx), html_tables)
    apply_table_styles_to_docx(str(out_docx))

    reloaded = docx.Document(str(out_docx))
    rows_out = [[c.text for c in r.cells] for r in reloaded.tables[0].rows]
    assert rows_out[1][1] == "A* 与 B*"
    assert rows_out[2][1] == "Xa_1 與 Yb_2"
    assert rows_out[3][1] == "109/L 與 2^3"
    vas = [va.get(qn("w:val")) for va in reloaded.tables[0]._tbl.iter(qn("w:vertAlign"))]
    assert vas == ["superscript", "superscript", "subscript", "subscript", "superscript", "superscript"]


def test_build_span_grid_avoids_false_rowspan_on_tall_neighbor_and_keeps_full_span_row():
    # Repeated tall box in col 0 must not pull row 2's top edge up to y=0 and falsely merge row 1 col 1
    rows_tall = [["A", "B", "C"], ["", "D", "E"], ["", "", "F"]]
    tbl_tall = SimpleNamespace(
        rows=[
            SimpleNamespace(cells=[(0, 0, 80, 60), (80, 0, 160, 20), (160, 0, 240, 20)]),
            SimpleNamespace(cells=[(0, 0, 80, 60), (80, 20, 160, 40), (160, 20, 240, 40)]),
            SimpleNamespace(cells=[(0, 0, 80, 60), None, (160, 40, 240, 60)]),
        ]
    )
    grid_tall, _ = build_table_span_grid(rows_tall, table_obj=tbl_tall)
    assert grid_tall[0][0] is not None and grid_tall[0][0].rowspan == 3
    assert grid_tall[1][1] is not None and grid_tall[1][1].rowspan == 1

    # Fully-spanned row (all None boxes) must still allow row-0 cells reaching row 2's top edge to span
    rows_full = [["A", "B", ""], ["", "", ""], ["C", "D", "E"]]
    tbl_full = SimpleNamespace(
        rows=[
            SimpleNamespace(cells=[(0, 0, 80, 40), (80, 0, 240, 40), None]),
            SimpleNamespace(cells=[None, None, None]),
            SimpleNamespace(cells=[(0, 40, 80, 60), (80, 40, 160, 60), (160, 40, 240, 60)]),
        ]
    )
    grid_full, has_merges = build_table_span_grid(rows_full, table_obj=tbl_full)
    assert has_merges is True
    assert grid_full[0][0] is not None and grid_full[0][0].rowspan == 2
    assert grid_full[0][1] is not None and grid_full[0][1].rowspan == 2 and grid_full[0][1].colspan == 2
    assert grid_full[1] == [None, None, None]


def test_merge_html_tables_never_slices_mid_rowspan_and_matches_mixed_colspan_header():
    prev_html = (
        "<table><thead>"
        '<tr><th rowspan="2">项目</th><th colspan="2">实验组</th></tr>'
        "<tr><th>男</th><th>女</th></tr>"
        "</thead><tbody><tr><td>甲</td><td>10</td><td>12</td></tr></tbody></table>"
    )
    # Continuation repeats 2-row thead with a slight OCR drift in sub-header row 1 ('女性' vs '女')
    curr_html_drift = (
        "<table><thead>"
        '<tr><th rowspan="2">项目</th><th colspan="2">实验组</th></tr>'
        "<tr><th>男</th><th>女性</th></tr>"
        "</thead><tbody><tr><td>乙</td><td>20</td><td>22</td></tr></tbody></table>"
    )
    merged_drift = merge_gfm_tables_if_compatible(prev_html, curr_html_drift, has_continuation_marker=True)
    assert merged_drift is not None
    assert "女性" not in merged_drift
    assert "<tr><td>乙</td><td>20</td><td>22</td></tr>" in merged_drift

    # Continuation in GFM repeats colspan header flattened across 3 columns
    curr_gfm = "| 项目 | 实验组 |  |\n| --- | --- | --- |\n| 乙 | 20 | 22 |"
    merged_mixed = merge_gfm_tables_if_compatible(prev_html, curr_gfm, has_continuation_marker=True)
    assert merged_mixed is not None
    assert merged_mixed.count("项目") == 1
    assert "<tr><td>乙</td><td>20</td><td>22</td></tr>" in merged_mixed


def test_docx_tbl_header_handles_pure_colspan_thead_staggered_vmerge_and_coalesce(tmp_path: Path):
    # 1. Pure-colspan 2-row <thead> without row-0 vMerge must still keep tblHeader on both header rows
    pure_colspan = (
        "<table><thead>"
        '<tr><th colspan="2">组A</th><th colspan="2">组B</th></tr>'
        "<tr><th>男</th><th>女</th><th>男</th><th>女</th></tr>"
        "</thead><tbody><tr><td>1</td><td>2</td><td>3</td><td>4</td></tr></tbody></table>"
    )
    out1 = tmp_path / "pure_colspan.docx"
    rw1, hts1 = extract_html_tables_for_pandoc(pure_colspan)
    pypandoc.convert_text(rw1, "docx", format="markdown-implicit_figures-subscript+raw_html", outputfile=str(out1))
    inject_html_tables_and_scripts_into_docx(str(out1), hts1)
    apply_table_styles_to_docx(str(out1))
    d1 = docx.Document(str(out1))
    flags1 = [tr.find(qn("w:trPr")).find(qn("w:tblHeader")) is not None for tr in d1.tables[0]._tbl.findall(qn("w:tr"))]
    assert flags1 == [True, True, False]

    # 2. Staggered vMerge starting in row 1 must not leak tblHeader into body row 2
    staggered = (
        "<table><thead>"
        '<tr><th rowspan="2">A</th><th>B</th><th>C</th></tr>'
        '<tr><th rowspan="2">B2</th><th>C2</th></tr>'
        "</thead><tbody>"
        "<tr><td>A3</td><td>C3</td></tr>"
        "<tr><td>A4</td><td>B4</td><td>C4</td></tr>"
        "</tbody></table>"
    )
    out2 = tmp_path / "staggered.docx"
    rw2, hts2 = extract_html_tables_for_pandoc(staggered)
    pypandoc.convert_text(rw2, "docx", format="markdown-implicit_figures-subscript+raw_html", outputfile=str(out2))
    inject_html_tables_and_scripts_into_docx(str(out2), hts2)
    apply_table_styles_to_docx(str(out2))
    d2 = docx.Document(str(out2))
    flags2 = [tr.find(qn("w:trPr")).find(qn("w:tblHeader")) is not None for tr in d2.tables[0]._tbl.findall(qn("w:tr"))]
    assert flags2 == [True, True, False, False]

    # 3. Coalescing two DOCX tables with identical 2-row merged headers must strip both header rows
    tbl_p1 = (
        "<table><thead>"
        '<tr><th rowspan="2">项目</th><th colspan="2">实验组</th></tr>'
        "<tr><th>男</th><th>女</th></tr>"
        "</thead><tbody><tr><td>甲</td><td>10</td><td>12</td></tr></tbody></table>"
    )
    tbl_p2 = tbl_p1.replace("甲", "乙").replace("10", "20").replace("12", "22")
    out3 = tmp_path / "coalesce_2row_hdr.docx"
    rw3, hts3 = extract_html_tables_for_pandoc(tbl_p1 + "\n\n续表\n\n" + tbl_p2)
    pypandoc.convert_text(rw3, "docx", format="markdown-implicit_figures-subscript+raw_html", outputfile=str(out3))
    inject_html_tables_and_scripts_into_docx(str(out3), hts3)
    apply_table_styles_to_docx(str(out3))
    d3 = docx.Document(str(out3))
    assert len(d3.tables) == 1
    assert [[c.text for c in r.cells] for r in d3.tables[0].rows] == [
        ["项目", "实验组", "实验组"],
        ["项目", "男", "女"],
        ["甲", "10", "12"],
        ["乙", "20", "22"],
    ]


def test_protected_inline_scripts_unescape_html_entities_in_docx(tmp_path: Path):
    md = (
        "| 项目 | 值 |\n"
        "| --- | --- |\n"
        "| 阈值 | A<sup>&lt;1</sup> 與 10<sup>&minus;3</sup> 與 X<sub>a&amp;b</sub> |\n"
    )
    rw, hts = extract_html_tables_for_pandoc(md)
    rw = protect_inline_scripts_for_pandoc(rw)
    out_docx = tmp_path / "script_entities.docx"
    pypandoc.convert_text(
        rw,
        "docx",
        format="markdown-implicit_figures-subscript+raw_html+tex_math_dollars",
        outputfile=str(out_docx),
    )
    inject_html_tables_and_scripts_into_docx(str(out_docx), hts)
    apply_table_styles_to_docx(str(out_docx))

    d = docx.Document(str(out_docx))
    assert d.tables[0].rows[1].cells[1].text == "A<1 與 10−3 與 Xa&b"
    vas = [va.get(qn("w:val")) for va in d.tables[0]._tbl.iter(qn("w:vertAlign"))]
    assert vas == ["superscript", "superscript", "subscript"]


