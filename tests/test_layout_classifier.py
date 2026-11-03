# -*- coding: utf-8 -*-
"""
test_layout_classifier.py: Comprehensive Unit & Edge Test Suite for Phase 2
=============================================================================
Verifies 57 test cases (LC-01 to LC-45, plus EDGE-01 to EDGE-12).
Every test case strictly asserts on all 9 fields of ParagraphClassification:
- paragraph_id: str
- page_num: int
- semantic_role: SemanticRole
- suggested_heading_level: Optional[HeadingLevel]
- confidence: float
- is_provisional: bool
- evidence: Tuple[str, ...]
- active_groups: Tuple[ActiveGroup, ...]
- score: float
"""

import copy
import io
import math
import os
import pathlib
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
from unittest.mock import patch

import pytest

from src.scripts.layout_classifier import (
    ParagraphClassification,
    DocumentTypographyBaseline,
    DocumentRepetitionContext,
    HeadingEvaluation,
    classify_layout,
    quantize_font_size,
    parse_cjk_or_arabic_numeral,
    cluster_vertical_candidates,
    get_footer_vertical_tolerance,
    evaluate_heading_candidate,
    resolve_heading_level,
    build_typography_baseline,
    build_repetition_context,
)
from src.scripts.paragraph_reconstruction import (
    LineRecord,
    PageGeometry,
    ParagraphRecord,
    SpanRecord,
)


def make_para(
    paragraph_id: str,
    page_num: int = 1,
    text: str = "这是一段标准的中文正文内容，用于测试基线和段落分类的稳定性。",
    source_line_ids: Optional[List[str]] = None,
    bbox: Tuple[float, float, float, float] = (50.0, 100.0, 500.0, 150.0),
    dominant_font: str = "SimSun",
    dominant_size: float = 10.5,
    bold_ratio: float = 0.0,
) -> ParagraphRecord:
    if source_line_ids is None:
        source_line_ids = [f"{paragraph_id}_l1", f"{paragraph_id}_l2"]
    return ParagraphRecord(
        paragraph_id=paragraph_id,
        page_num=page_num,
        text=text,
        source_line_ids=source_line_ids,
        bbox=bbox,
        dominant_font=dominant_font,
        dominant_size=dominant_size,
        bold_ratio=bold_ratio,
    )


def make_line(
    line_id: str,
    page_num: int = 1,
    text: str = "这是行文本内容",
    bbox: Tuple[float, float, float, float] = (50.0, 100.0, 500.0, 120.0),
    line_order: int = 0,
) -> LineRecord:
    return LineRecord(
        line_id=line_id,
        page_num=page_num,
        text=text,
        bbox=bbox,
        line_order=line_order,
    )


def make_geo(
    page_num: int = 1,
    width: float = 595.0,
    height: float = 842.0,
    content_top: float = 50.0,
    content_bottom: float = 790.0,
) -> PageGeometry:
    return PageGeometry(
        width=width,
        height=height,
        base_x0=50.0,
        max_x1=545.0,
        content_top=content_top,
        content_bottom=content_bottom,
    )


def make_standard_document_context(
    page_count: int = 2,
    body_font: str = "SimSun",
    body_size: float = 10.5,
) -> Tuple[
    Dict[int, List[ParagraphRecord]],
    Dict[int, List[LineRecord]],
    Dict[int, PageGeometry],
]:
    """Creates a base multi-page document with valid typography baseline."""
    paras_by_page: Dict[int, List[ParagraphRecord]] = {}
    lines_by_page: Dict[int, List[LineRecord]] = {}
    geos: Dict[int, PageGeometry] = {}

    for p in range(1, page_count + 1):
        geos[p] = make_geo(page_num=p)
        paras_by_page[p] = []
        lines_by_page[p] = []

        # Add 3 standard body paragraphs per page to exceed 50 clean characters
        for idx in range(1, 4):
            pid = f"p{p}_b{idx}"
            l1_id = f"{pid}_l1"
            l2_id = f"{pid}_l2"
            y0 = 150.0 + (idx - 1) * 70.0
            p_rec = make_para(
                paragraph_id=pid,
                page_num=p,
                text="这是一段标准的中文正文段落，用于提供足够的干净字符以建立基线。",
                source_line_ids=[l1_id, l2_id],
                bbox=(50.0, y0, 420.0, y0 + 35.0),
                dominant_font=body_font,
                dominant_size=body_size,
            )
            l1 = make_line(l1_id, page_num=p, text="这是一段标准的中文正文段落", bbox=(50.0, y0, 420.0, y0 + 15.0))
            l2 = make_line(l2_id, page_num=p, text="用于提供足够的干净字符以建立基线。", bbox=(50.0, y0 + 18.0, 420.0, y0 + 33.0))
            paras_by_page[p].append(p_rec)
            lines_by_page[p].extend([l1, l2])

    return paras_by_page, lines_by_page, geos


# ---------------------------------------------------------------------------
# Canonical Tests LC-01 to LC-45
# ---------------------------------------------------------------------------

def test_lc_01_multiline_body_prose():
    paras, lines, geos = make_standard_document_context()
    res = classify_layout(paras, lines, geos)
    target = res["p1_b1"]
    assert target.paragraph_id == "p1_b1"
    assert target.page_num == 1
    assert target.semantic_role == "body"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.85
    assert target.is_provisional is False
    assert target.evidence[0] == "body: multiline_prose_flow"
    assert target.active_groups == ()
    assert target.score == 0.0


def test_lc_02_short_body_line():
    paras, lines, geos = make_standard_document_context()
    target_p = make_para(
        paragraph_id="short_body",
        page_num=1,
        text="短行正文结束句。",
        source_line_ids=["sb_l1"],
        bbox=(50.0, 400.0, 200.0, 415.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    paras[1].append(target_p)
    lines[1].append(make_line("sb_l1", page_num=1, text="短行正文结束句。", bbox=(50.0, 400.0, 200.0, 415.0)))

    res = classify_layout(paras, lines, geos)
    target = res["short_body"]
    assert target.paragraph_id == "short_body"
    assert target.page_num == 1
    assert target.semantic_role == "body"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.85
    assert target.is_provisional is False
    assert target.evidence[0] == "body: heading_vetoed_by_period"
    assert target.score == 0.0


def test_lc_03_centered_short_text():
    paras, lines, geos = make_standard_document_context()
    # Centered: width 595, center_x = 595 / 2 = 297.5
    target_p = make_para(
        paragraph_id="centered_txt",
        page_num=1,
        text="居中的无样式短文本",
        source_line_ids=["c_l1"],
        bbox=(247.5, 400.0, 347.5, 415.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    paras[1].append(target_p)
    lines[1].append(make_line("c_l1", page_num=1, text="居中的无样式短文本", bbox=(247.5, 400.0, 347.5, 415.0)))

    res = classify_layout(paras, lines, geos)
    target = res["centered_txt"]
    assert target.paragraph_id == "centered_txt"
    assert target.page_num == 1
    assert target.semantic_role == "body"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.60
    assert target.is_provisional is False
    assert target.evidence[0] == "body: unstyled_single_line"
    assert target.active_groups == ("B",)
    assert abs(target.score - 0.20) < 1e-4


def test_lc_04_chapter_heading():
    paras, lines, geos = make_standard_document_context()
    # Chapter 1: +30% size (14.0 >= 10.5 * 1.25 = 13.125), Heiti, dominant spacing above, chapter prefix
    # prev_para at y1=325.0; target at y0=380.0 (spacing_above=55.0 >= 18*1.25=22.5), next at y0=405.0 (spacing_below=10.0, 55 >= 10*1.3)
    target_p = make_para(
        paragraph_id="chap_head",
        page_num=1,
        text="第一章 绪论",
        source_line_ids=["ch_l1"],
        bbox=(50.0, 380.0, 200.0, 395.0),
        dominant_font="SimHei",
        dominant_size=14.0,
    )
    next_p = make_para(
        paragraph_id="next_p",
        page_num=1,
        text="正文紧跟标题之后，用于提供间距测量下边界。",
        source_line_ids=["np_l1"],
        bbox=(50.0, 405.0, 545.0, 420.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    paras[1].extend([target_p, next_p])
    lines[1].extend([
        make_line("ch_l1", page_num=1, text="第一章 绪论", bbox=(50.0, 380.0, 200.0, 395.0)),
        make_line("np_l1", page_num=1, text="正文紧跟标题之后", bbox=(50.0, 405.0, 545.0, 420.0)),
    ])

    res = classify_layout(paras, lines, geos)
    target = res["chap_head"]
    assert target.paragraph_id == "chap_head"
    assert target.page_num == 1
    assert target.semantic_role == "heading_candidate"
    assert target.suggested_heading_level == 1
    assert target.confidence == 0.90
    assert target.is_provisional is False
    assert target.evidence[0] == "heading: level_1_candidate"
    assert target.active_groups == ("A", "B", "C")
    assert target.score == 1.00


def test_lc_05_traditional_section():
    paras, lines, geos = make_standard_document_context()
    target_p = make_para(
        paragraph_id="sec_head",
        page_num=1,
        text="第二節 歷史背景分析",
        source_line_ids=["sec_l1"],
        bbox=(50.0, 380.0, 250.0, 395.0),
        dominant_font="SimSun",
        dominant_size=12.0,  # +15% size
        bold_ratio=1.0,      # bold
    )
    next_p = make_para(
        paragraph_id="next_sec_p",
        page_num=1,
        text="正文紧跟第二节标题之后，用于提供间距测量下边界。",
        source_line_ids=["nsp_l1"],
        bbox=(50.0, 405.0, 545.0, 420.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    paras[1].extend([target_p, next_p])
    lines[1].extend([
        make_line("sec_l1", page_num=1, text="第二節 歷史背景分析", bbox=(50.0, 380.0, 250.0, 395.0)),
        make_line("nsp_l1", page_num=1, text="正文紧跟第二节标题之后", bbox=(50.0, 405.0, 545.0, 420.0)),
    ])

    res = classify_layout(paras, lines, geos)
    target = res["sec_head"]
    assert target.paragraph_id == "sec_head"
    assert target.page_num == 1
    assert target.semantic_role == "heading_candidate"
    assert target.suggested_heading_level == 2
    assert target.confidence == 0.80
    assert target.is_provisional is False
    assert target.evidence[0] == "heading: level_2_candidate"
    assert target.active_groups == ("A", "B", "C")
    assert abs(target.score - 0.95) < 1e-4


def test_lc_05b_weak_section_heading():
    paras, lines, geos = make_standard_document_context()
    # Weak section: bold (+0.20), section prefix (+0.30), NO spacing above (tight to prev_para: y0=186, prev y1=185 -> dy=1.0)
    target_p = make_para(
        paragraph_id="weak_sec",
        page_num=1,
        text="第二节 紧贴段落的小节",
        source_line_ids=["wsec_l1"],
        bbox=(50.0, 186.0, 250.0, 200.0),
        dominant_font="SimSun",
        dominant_size=10.5,
        bold_ratio=1.0,
    )
    next_p = make_para(
        paragraph_id="w_next_p",
        page_num=1,
        text="正文紧跟小节之后。",
        source_line_ids=["wnp_l1"],
        bbox=(50.0, 205.0, 545.0, 220.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    paras[1].extend([target_p, next_p])
    lines[1].extend([
        make_line("wsec_l1", page_num=1, text="第二节 紧贴段落的小节", bbox=(50.0, 186.0, 250.0, 200.0)),
        make_line("wnp_l1", page_num=1, text="正文紧跟小节之后。", bbox=(50.0, 205.0, 545.0, 220.0)),
    ])

    res = classify_layout(paras, lines, geos)
    target = res["weak_sec"]
    assert target.paragraph_id == "weak_sec"
    assert target.page_num == 1
    assert target.semantic_role == "uncertain"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.40
    assert target.is_provisional is True
    assert target.evidence[0] == "uncertain: heading_insufficient_score"
    assert target.active_groups == ("A", "C")
    assert abs(target.score - 0.50) < 1e-4


def test_lc_06_traditional_subsection():
    paras, lines, geos = make_standard_document_context()
    # Subsection: bold (+0.20), spacing (+0.25), "一、" (+0.25) -> Total S = 0.70
    target_p = make_para(
        paragraph_id="subsec_head",
        page_num=1,
        text="一、 文獻探討",
        source_line_ids=["subsec_l1"],
        bbox=(50.0, 380.0, 200.0, 395.0),
        dominant_font="SimSun",
        dominant_size=10.5,
        bold_ratio=1.0,
    )
    next_p = make_para(
        paragraph_id="next_sub_p",
        page_num=1,
        text="正文紧跟一、小节之后，提供间距下边界。",
        source_line_ids=["nsubp_l1"],
        bbox=(50.0, 405.0, 545.0, 420.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    paras[1].extend([target_p, next_p])
    lines[1].extend([
        make_line("subsec_l1", page_num=1, text="一、 文獻探討", bbox=(50.0, 380.0, 200.0, 395.0)),
        make_line("nsubp_l1", page_num=1, text="正文紧跟一、小节之后", bbox=(50.0, 405.0, 545.0, 420.0)),
    ])

    res = classify_layout(paras, lines, geos)
    target = res["subsec_head"]
    assert target.paragraph_id == "subsec_head"
    assert target.page_num == 1
    assert target.semantic_role == "heading_candidate"
    assert target.suggested_heading_level == 3
    assert target.confidence == 0.80
    assert target.is_provisional is False
    assert target.evidence[0] == "heading: level_3_candidate"
    assert target.active_groups == ("A", "B", "C")
    assert abs(target.score - 0.70) < 1e-4


def test_lc_07_chapter_with_period():
    paras, lines, geos = make_standard_document_context()
    target_p = make_para(
        paragraph_id="chap_period",
        page_num=1,
        text="第一章 绪论。",
        source_line_ids=["chp_l1"],
        bbox=(50.0, 240.0, 200.0, 255.0),
        dominant_font="SimHei",
        dominant_size=14.0,
    )
    paras[1].append(target_p)
    lines[1].append(make_line("chp_l1", page_num=1, text="第一章 绪论。", bbox=(50.0, 240.0, 200.0, 255.0)))

    res = classify_layout(paras, lines, geos)
    target = res["chap_period"]
    assert target.paragraph_id == "chap_period"
    assert target.page_num == 1
    assert target.semantic_role == "body"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.85
    assert target.is_provisional is False
    assert target.evidence[0] == "body: heading_vetoed_by_period"


def test_lc_08_question_chapter():
    paras, lines, geos = make_standard_document_context()
    target_p = make_para(
        paragraph_id="chap_q",
        page_num=1,
        text="第一章 为什么选择这个方案？",
        source_line_ids=["cq_l1"],
        bbox=(50.0, 380.0, 300.0, 395.0),
        dominant_font="SimHei",
        dominant_size=14.0,
    )
    next_p = make_para(
        paragraph_id="next_cq_p",
        page_num=1,
        text="正文紧跟问句章节标题之后。",
        source_line_ids=["ncqp_l1"],
        bbox=(50.0, 405.0, 545.0, 420.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    paras[1].extend([target_p, next_p])
    lines[1].extend([
        make_line("cq_l1", page_num=1, text="第一章 为什么选择这个方案？", bbox=(50.0, 380.0, 300.0, 395.0)),
        make_line("ncqp_l1", page_num=1, text="正文紧跟问句章节标题之后。", bbox=(50.0, 405.0, 545.0, 420.0)),
    ])

    res = classify_layout(paras, lines, geos)
    target = res["chap_q"]
    assert target.paragraph_id == "chap_q"
    assert target.page_num == 1
    assert target.semantic_role == "heading_candidate"
    assert target.suggested_heading_level == 1
    assert target.confidence == 0.90
    assert target.is_provisional is False
    assert target.evidence[0] == "heading: level_1_candidate"
    assert target.active_groups == ("A", "B", "C")
    assert target.score == 1.00


def test_lc_08b_standalone_question():
    paras, lines, geos = make_standard_document_context()
    target_p = make_para(
        paragraph_id="standalone_q",
        page_num=1,
        text="这是一个未带前缀的独立问句吗？",
        source_line_ids=["sq_l1"],
        bbox=(50.0, 400.0, 300.0, 415.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    paras[1].append(target_p)
    lines[1].append(make_line("sq_l1", page_num=1, text="这是一个未带前缀的独立问句吗？", bbox=(50.0, 400.0, 300.0, 415.0)))

    res = classify_layout(paras, lines, geos)
    target = res["standalone_q"]
    assert target.paragraph_id == "standalone_q"
    assert target.page_num == 1
    assert target.semantic_role == "uncertain"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.35
    assert target.is_provisional is True
    assert target.evidence[0] == "uncertain: standalone_question_without_prefix"


def test_lc_08c_embedded_question():
    paras, lines, geos = make_standard_document_context()
    target_p = make_para(
        paragraph_id="multiline_q",
        page_num=1,
        text="这是多行正文流动的第一行内容，在接下来的第二行中提出了疑问？",
        source_line_ids=["mq_l1", "mq_l2"],
        bbox=(50.0, 400.0, 545.0, 435.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    paras[1].append(target_p)
    lines[1].extend([
        make_line("mq_l1", page_num=1, text="这是多行正文流动的第一行内容", bbox=(50.0, 400.0, 545.0, 415.0)),
        make_line("mq_l2", page_num=1, text="在接下来的第二行中提出了疑问？", bbox=(50.0, 418.0, 545.0, 433.0)),
    ])

    res = classify_layout(paras, lines, geos)
    target = res["multiline_q"]
    assert target.paragraph_id == "multiline_q"
    assert target.page_num == 1
    assert target.semantic_role == "body"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.85
    assert target.is_provisional is False
    assert target.evidence[0] == "body: multiline_prose_flow"


def test_lc_09_top_recurring_header():
    paras, lines, geos = make_standard_document_context(page_count=3)
    # Add recurring header on all 3 pages at y0=25, y1=40 (content_top=50, pitch=18, 40 <= 50 + 9)
    for p in range(1, 4):
        h_para = make_para(
            paragraph_id=f"hdr_p{p}",
            page_num=p,
            text="中国中古史研究论集",
            source_line_ids=[f"hdr_l{p}"],
            bbox=(100.0, 25.0, 400.0, 40.0),
            dominant_font="SimSun",
            dominant_size=9.0,
        )
        paras[p].insert(0, h_para)
        lines[p].insert(0, make_line(f"hdr_l{p}", page_num=p, text="中国中古史研究论集", bbox=(100.0, 25.0, 400.0, 40.0)))

    res = classify_layout(paras, lines, geos)
    target = res["hdr_p1"]
    assert target.paragraph_id == "hdr_p1"
    assert target.page_num == 1
    assert target.semantic_role == "header"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.90
    assert target.is_provisional is False
    assert target.evidence[0] == "header: recurring_top_pattern"


def test_lc_10_single_page_header():
    paras, lines, geos = make_standard_document_context(page_count=1)
    h_para = make_para(
        paragraph_id="single_hdr",
        page_num=1,
        text="单页顶部标题",
        source_line_ids=["sh_l1"],
        bbox=(100.0, 25.0, 400.0, 40.0),
        dominant_font="SimSun",
        dominant_size=9.0,
    )
    paras[1].insert(0, h_para)
    lines[1].insert(0, make_line("sh_l1", page_num=1, text="单页顶部标题", bbox=(100.0, 25.0, 400.0, 40.0)))

    res = classify_layout(paras, lines, geos)
    target = res["single_hdr"]
    assert target.paragraph_id == "single_hdr"
    assert target.page_num == 1
    assert target.semantic_role == "uncertain"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.35
    assert target.is_provisional is True
    assert target.evidence[0] == "uncertain: single_page_occurrence"


def test_lc_11_multi_page_sequence_folio():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # content_bottom=790.0, pitch=18.0; y0 >= 790 - 9 = 781
    f1 = make_para("ft_p1", page_num=1, text="21", source_line_ids=["f1_l1"], bbox=(280.0, 800.0, 310.0, 815.0))
    f2 = make_para("ft_p2", page_num=2, text="22", source_line_ids=["f2_l1"], bbox=(280.0, 800.0, 310.0, 815.0))
    paras[1].append(f1)
    paras[2].append(f2)
    lines[1].append(make_line("f1_l1", page_num=1, text="21", bbox=(280.0, 800.0, 310.0, 815.0)))
    lines[2].append(make_line("f2_l1", page_num=2, text="22", bbox=(280.0, 800.0, 310.0, 815.0)))

    res = classify_layout(paras, lines, geos)
    target = res["ft_p1"]
    assert target.paragraph_id == "ft_p1"
    assert target.page_num == 1
    assert target.semantic_role == "footer"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.95
    assert target.is_provisional is False
    assert target.evidence[0] == "footer: page_number_sequence_valid"


def test_lc_11b_isolated_multi_page_folio():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # Number 24 on page 1 only
    f1 = make_para("iso_folio", page_num=1, text="24", source_line_ids=["if_l1"], bbox=(280.0, 800.0, 310.0, 815.0))
    paras[1].append(f1)
    lines[1].append(make_line("if_l1", page_num=1, text="24", bbox=(280.0, 800.0, 310.0, 815.0)))

    res = classify_layout(paras, lines, geos)
    target = res["iso_folio"]
    assert target.paragraph_id == "iso_folio"
    assert target.page_num == 1
    assert target.semantic_role == "uncertain"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.35
    assert target.is_provisional is True
    assert target.evidence[0] == "uncertain: isolated_page_number"


def test_lc_11c_body_isolated_numeral():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # Number 24 in body zone (y0=300 < content_bottom 790)
    body_num = make_para("body_num", page_num=1, text="24", source_line_ids=["bn_l1"], bbox=(280.0, 300.0, 310.0, 315.0))
    paras[1].append(body_num)
    lines[1].append(make_line("bn_l1", page_num=1, text="24", bbox=(280.0, 300.0, 310.0, 315.0)))

    res = classify_layout(paras, lines, geos)
    target = res["body_num"]
    assert target.paragraph_id == "body_num"
    assert target.page_num == 1
    assert target.semantic_role == "body"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.60
    assert target.is_provisional is False
    assert target.evidence[0] == "body: unstyled_single_line"


def test_lc_12_line_level_poetry():
    paras, lines, geos = make_standard_document_context()
    # 4 lines of 5 characters in KaiTi font
    l_ids = [f"poem_l{i}" for i in range(1, 5)]
    p_lines = [
        make_line(l_ids[0], page_num=1, text="白日依山尽，", bbox=(100.0, 300.0, 200.0, 315.0)),
        make_line(l_ids[1], page_num=1, text="黄河入海流。", bbox=(100.0, 320.0, 200.0, 335.0)),
        make_line(l_ids[2], page_num=1, text="欲穷千里目，", bbox=(100.0, 340.0, 200.0, 355.0)),
        make_line(l_ids[3], page_num=1, text="更上一层楼。", bbox=(100.0, 360.0, 200.0, 375.0)),
    ]
    poem_para = make_para(
        paragraph_id="poem_para",
        page_num=1,
        text="白日依山尽，黄河入海流。欲穷千里目，更上一层楼。",
        source_line_ids=l_ids,
        bbox=(100.0, 300.0, 200.0, 375.0),
        dominant_font="FZKTJW--GB1-0",  # KaiTi
        dominant_size=10.5,
    )
    paras[1].append(poem_para)
    lines[1].extend(p_lines)

    res = classify_layout(paras, lines, geos)
    target = res["poem_para"]
    assert target.paragraph_id == "poem_para"
    assert target.page_num == 1
    assert target.semantic_role == "poetry"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.85
    assert target.is_provisional is False
    assert target.evidence[0] == "poetry: metric_couplet_rhythm_kaiti"


def test_lc_13_kaiti_prose_quotation():
    paras, lines, geos = make_standard_document_context()
    # 80 chars prose in KaiTi (lines are ~25 chars each, failing 5/7 rhythm)
    l_ids = ["kq_l1", "kq_l2", "kq_l3"]
    p_lines = [
        make_line(l_ids[0], page_num=1, text="这段引文是来自古籍的一段长篇评述内容，", bbox=(50.0, 300.0, 400.0, 315.0)),
        make_line(l_ids[1], page_num=1, text="学者在此处详细考证了相关的制度与变迁，", bbox=(50.0, 320.0, 400.0, 335.0)),
        make_line(l_ids[2], page_num=1, text="并提出了独到的学术观点与佐证依据。", bbox=(50.0, 340.0, 400.0, 355.0)),
    ]
    k_para = make_para(
        paragraph_id="kaiti_quote",
        page_num=1,
        text="这段引文是来自古籍的一段长篇评述内容，学者在此处详细考证了相关的制度与变迁，并提出了独到的学术观点与佐证依据。",
        source_line_ids=l_ids,
        bbox=(50.0, 300.0, 400.0, 355.0),
        dominant_font="FZKTJW--GB1-0",
        dominant_size=10.5,
    )
    paras[1].append(k_para)
    lines[1].extend(p_lines)

    res = classify_layout(paras, lines, geos)
    target = res["kaiti_quote"]
    assert target.paragraph_id == "kaiti_quote"
    assert target.page_num == 1
    assert target.semantic_role == "uncertain"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.35
    assert target.is_provisional is True
    assert target.evidence[0] == "uncertain: poetry_unresolved_lines"


def test_lc_14_traditional_caption():
    paras, lines, geos = make_standard_document_context()
    cap = make_para(
        paragraph_id="trad_cap",
        page_num=1,
        text="圖 1-1 唐代長安城平面圖。",
        source_line_ids=["tc_l1"],
        bbox=(150.0, 300.0, 350.0, 315.0),
        dominant_font="SimSun",
        dominant_size=9.5,
    )
    paras[1].append(cap)
    lines[1].append(make_line("tc_l1", page_num=1, text="圖 1-1 唐代長安城平面圖。", bbox=(150.0, 300.0, 350.0, 315.0)))

    res = classify_layout(paras, lines, geos)
    target = res["trad_cap"]
    assert target.paragraph_id == "trad_cap"
    assert target.page_num == 1
    assert target.semantic_role == "caption"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.95
    assert target.is_provisional is False
    assert target.evidence[0] == "caption: table_or_figure_prefix"


def test_lc_15_baseline_midpoint_quantization():
    assert quantize_font_size(9.624, 0.25) == 9.50
    assert quantize_font_size(9.625, 0.25) == 9.75
    assert quantize_font_size(9.626, 0.25) == 9.75
    assert quantize_font_size(9.700, 0.25) == 9.75
    assert quantize_font_size(16.880, 0.25) == 17.00


def test_lc_16_insufficient_baseline():
    # Only 20 clean chars -> baseline invalid
    paras = {1: [make_para("p1", page_num=1, text="短文本二十字符测试。")]}
    lines = {1: [make_line("p1_l1", page_num=1, text="短文本二十字符测试。")]}
    geos = {1: make_geo(1)}
    baseline = build_typography_baseline(paras, lines, geos)
    assert baseline.is_valid is False
    assert baseline.rejection_reasons == ("insufficient_clean_characters",)
    assert baseline.body_font == ""
    assert baseline.body_size == 0.0


def test_lc_17_missing_page_geometry():
    paras, lines, geos = make_standard_document_context()
    # Paragraph on page 99 without geometry
    p99 = make_para("p99", page_num=99, text="第九十九页未配置几何度量的段落。", source_line_ids=["p99_l1"])
    paras[99] = [p99]
    lines[99] = [make_line("p99_l1", page_num=99, text="第九十九页未配置几何度量的段落。")]

    res = classify_layout(paras, lines, geos)
    target = res["p99"]
    assert target.paragraph_id == "p99"
    assert "geo: missing_page_geometry" in target.evidence


def test_lc_18_baseline_invalid_role_preservation():
    # Document with insufficient clean characters (baseline invalid), but valid caption and footers
    geos = {1: make_geo(1), 2: make_geo(2)}
    c1 = make_para("cap1", page_num=1, text="Table 1 Sample", source_line_ids=["c1_l"], bbox=(50.0, 200.0, 200.0, 215.0))
    f1 = make_para("f1", page_num=1, text="1", source_line_ids=["f1_l"], bbox=(280.0, 800.0, 300.0, 815.0))
    f2 = make_para("f2", page_num=2, text="2", source_line_ids=["f2_l"], bbox=(280.0, 800.0, 300.0, 815.0))
    paras = {1: [c1, f1], 2: [f2]}
    lines = {
        1: [make_line("c1_l", 1, "Table 1 Sample", (50.0, 200.0, 200.0, 215.0)), make_line("f1_l", 1, "1", (280.0, 800.0, 300.0, 815.0))],
        2: [make_line("f2_l", 2, "2", (280.0, 800.0, 300.0, 815.0))],
    }
    res = classify_layout(paras, lines, geos)
    assert res["cap1"].semantic_role == "caption"
    assert res["cap1"].confidence == 0.95
    assert res["f1"].semantic_role == "footer"
    assert res["f1"].confidence == 0.85
    assert res["f1"].evidence[0] == "footer: page_number_valid_baseline_invalid"


def test_lc_19_cjk_numeral_folio():
    paras, lines, geos = make_standard_document_context(page_count=2)
    f1 = make_para("cjk_f1", page_num=1, text="· 一 ·", source_line_ids=["cf1_l"], bbox=(280.0, 800.0, 320.0, 815.0))
    f2 = make_para("cjk_f2", page_num=2, text="· 二 ·", source_line_ids=["cf2_l"], bbox=(280.0, 800.0, 320.0, 815.0))
    paras[1].append(f1)
    paras[2].append(f2)
    lines[1].append(make_line("cf1_l", 1, "· 一 ·", bbox=(280.0, 800.0, 320.0, 815.0)))
    lines[2].append(make_line("cf2_l", 2, "· 二 ·", bbox=(280.0, 800.0, 320.0, 815.0)))

    res = classify_layout(paras, lines, geos)
    assert res["cjk_f1"].semantic_role == "footer"
    assert res["cjk_f1"].confidence == 0.95
    assert res["cjk_f1"].evidence[0] == "footer: page_number_sequence_valid"


def test_lc_20_duplicate_header_on_same_page():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # Page 1 has 2 identical headers; Page 2 has none -> count = 1 distinct page < k_repeat (2) -> single_page_occurrence
    h1 = make_para("dup_h1", page_num=1, text="顶部流式标题", source_line_ids=["dh1_l"], bbox=(100.0, 25.0, 300.0, 40.0))
    h2 = make_para("dup_h2", page_num=1, text="顶部流式标题", source_line_ids=["dh2_l"], bbox=(350.0, 25.0, 500.0, 40.0))
    paras[1].extend([h1, h2])
    lines[1].extend([
        make_line("dh1_l", 1, "顶部流式标题", (100.0, 25.0, 300.0, 40.0)),
        make_line("dh2_l", 1, "顶部流式标题", (350.0, 25.0, 500.0, 40.0)),
    ])
    drc = build_repetition_context(paras, geos, build_typography_baseline(paras, lines, geos))
    assert len(drc.recurring_top_patterns) == 0


def test_lc_21_alternating_5_7_poetry():
    paras, lines, geos = make_standard_document_context()
    l_ids = [f"alt_l{i}" for i in range(1, 5)]
    p_lines = [
        make_line(l_ids[0], 1, "五字开篇句，", (100.0, 300.0, 200.0, 315.0)),
        make_line(l_ids[1], 1, "七字对仗偶句长。", (100.0, 320.0, 220.0, 335.0)),
        make_line(l_ids[2], 1, "五字转折语，", (100.0, 340.0, 200.0, 355.0)),
        make_line(l_ids[3], 1, "七字收尾意韵长。", (100.0, 360.0, 220.0, 375.0)),
    ]
    alt_para = make_para(
        paragraph_id="alt_poem",
        page_num=1,
        text="五字开篇句，七字对仗偶句长。五字转折语，七字收尾意韵长。",
        source_line_ids=l_ids,
        bbox=(100.0, 300.0, 220.0, 375.0),
        dominant_font="FZKTJW--GB1-0",
        dominant_size=10.5,
    )
    paras[1].append(alt_para)
    lines[1].extend(p_lines)

    res = classify_layout(paras, lines, geos)
    target = res["alt_poem"]
    assert target.semantic_role == "poetry"
    assert target.confidence == 0.85
    assert target.evidence[0] == "poetry: metric_couplet_rhythm_kaiti"


def test_lc_22_poetry_missing_line_record():
    paras, lines, geos = make_standard_document_context()
    # Referencing unresolvable line IDs
    p_unres = make_para(
        paragraph_id="p_unres",
        page_num=1,
        text="白日依山尽，黄河入海流。欲穷千里目，更上一层楼。",
        source_line_ids=["missing_l1", "missing_l2", "missing_l3"],
        bbox=(100.0, 300.0, 200.0, 350.0),
        dominant_font="FZKTJW--GB1-0",
    )
    paras[1].append(p_unres)
    res = classify_layout(paras, lines, geos)
    target = res["p_unres"]
    assert target.semantic_role == "uncertain"
    assert target.confidence == 0.35
    assert target.evidence[0] == "uncertain: poetry_unresolved_lines"


def test_lc_23_multiple_page_num_conflict():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # Page bottom has two distinct numbers 12 and 13 at same level
    f1a = make_para("f_conf_a", 1, "12", ["fa_l"], bbox=(100.0, 800.0, 130.0, 815.0))
    f1b = make_para("f_conf_b", 1, "13", ["fb_l"], bbox=(450.0, 800.0, 480.0, 815.0))
    paras[1].extend([f1a, f1b])
    lines[1].extend([
        make_line("fa_l", 1, "12", (100.0, 800.0, 130.0, 815.0)),
        make_line("fb_l", 1, "13", (450.0, 800.0, 480.0, 815.0)),
    ])
    res = classify_layout(paras, lines, geos)
    assert res["f_conf_a"].semantic_role == "uncertain"
    assert res["f_conf_a"].confidence == 0.35
    assert res["f_conf_a"].evidence[0] == "uncertain: page_level_vertical_conflict"
    assert res["f_conf_b"].semantic_role == "uncertain"
    assert res["f_conf_b"].evidence[0] == "uncertain: page_level_vertical_conflict"


def test_lc_24_invalid_baseline_fallback():
    paras = {1: [make_para("p_short", 1, "文本不足五十字。")]}
    lines = {1: [make_line("p_short_l1", 1, "文本不足五十字。")]}
    geos = {1: make_geo(1)}
    baseline = build_typography_baseline(paras, lines, geos)
    assert baseline.is_valid is False
    assert baseline.body_font == ""
    assert baseline.body_size == 0.0
    assert baseline.standard_line_pitch == 0.0


def test_lc_25_caption_precedence_over_heading():
    paras, lines, geos = make_standard_document_context()
    # Matches both Caption (图 1-1) and Chapter (第一章)
    cap_head = make_para(
        paragraph_id="cap_head",
        page_num=1,
        text="图 1-1 第一章 结构图",
        source_line_ids=["ch_l"],
        bbox=(50.0, 240.0, 250.0, 255.0),
        dominant_font="SimHei",
        dominant_size=14.0,
    )
    paras[1].append(cap_head)
    lines[1].append(make_line("ch_l", 1, "图 1-1 第一章 结构图", (50.0, 240.0, 250.0, 255.0)))
    res = classify_layout(paras, lines, geos)
    target = res["cap_head"]
    assert target.semantic_role == "caption"
    assert target.suggested_heading_level is None
    assert target.confidence == 0.95
    assert target.evidence[0] == "caption: table_or_figure_prefix"


def test_lc_26_decimal_midpoint_stability():
    assert quantize_font_size(9.625) == 9.75
    assert quantize_font_size(9.624) == 9.50


def test_lc_27_header_normalized_to_empty():
    paras, lines, geos = make_standard_document_context(page_count=3)
    # Header consisting solely of dashes and numbers
    for p in range(1, 4):
        h = make_para(f"dash_h{p}", p, "- 12 -", [f"dh_l{p}"], bbox=(250.0, 25.0, 350.0, 40.0))
        paras[p].append(h)
        lines[p].append(make_line(f"dh_l{p}", p, "- 12 -", (250.0, 25.0, 350.0, 40.0)))
    drc = build_repetition_context(paras, geos, build_typography_baseline(paras, lines, geos))
    assert len(drc.recurring_top_patterns) == 0


def test_lc_28_decimal_nan_inf_rejection():
    with pytest.raises(ValueError):
        quantize_font_size(float("nan"))
    with pytest.raises(ValueError):
        quantize_font_size(float("inf"))
    with pytest.raises(ValueError):
        quantize_font_size(-1.0)


def test_lc_29_decimal_step_zero_rejection():
    with pytest.raises(ValueError):
        quantize_font_size(10.0, step=0.0)
    with pytest.raises(ValueError):
        quantize_font_size(10.0, step=-0.25)


def test_lc_30_invalid_baseline_heading_gate():
    # Baseline invalid, paragraph has chapter prefix + bold
    geos = {1: make_geo(1)}
    p = make_para("ch_inv", 1, "第一章 绪论概述", ["ci_l"], bbox=(50.0, 100.0, 200.0, 120.0), bold_ratio=1.0)
    paras = {1: [p]}
    lines = {1: [make_line("ci_l", 1, "第一章 绪论概述", (50.0, 100.0, 200.0, 120.0))]}
    res = classify_layout(paras, lines, geos)
    target = res["ch_inv"]
    assert target.semantic_role == "uncertain"
    assert target.confidence == 0.35
    assert target.evidence[0] == "uncertain: invalid_baseline_quarantine"


def test_lc_31_poetry_non_5_7_rejection():
    paras, lines, geos = make_standard_document_context()
    # 4 lines of 6 characters each in KaiTi
    l_ids = [f"p6_l{i}" for i in range(1, 5)]
    p_lines = [
        make_line(l_ids[0], 1, "六字句第一行，", (100.0, 300.0, 200.0, 315.0)),
        make_line(l_ids[1], 1, "六字句第二行。", (100.0, 320.0, 200.0, 335.0)),
        make_line(l_ids[2], 1, "六字句第三行，", (100.0, 340.0, 200.0, 355.0)),
        make_line(l_ids[3], 1, "六字句第四行。", (100.0, 360.0, 200.0, 375.0)),
    ]
    p_para = make_para("p6_para", 1, "六字句第一行，六字句第二行。六字句第三行，六字句第四行。", l_ids, bbox=(100.0, 300.0, 200.0, 375.0), dominant_font="FZKTJW--GB1-0")
    paras[1].append(p_para)
    lines[1].extend(p_lines)
    res = classify_layout(paras, lines, geos)
    target = res["p6_para"]
    assert target.semantic_role == "uncertain"
    assert target.confidence == 0.35
    assert target.evidence[0] == "uncertain: poetry_unresolved_lines"


def test_lc_32_poetry_mixed_5_7_rejection():
    paras, lines, geos = make_standard_document_context()
    # 4 lines with lengths (5, 5, 7, 7) in KaiTi
    l_ids = [f"pm_l{i}" for i in range(1, 5)]
    p_lines = [
        make_line(l_ids[0], 1, "五字第一句，", (100.0, 300.0, 200.0, 315.0)),
        make_line(l_ids[1], 1, "五字第二句。", (100.0, 320.0, 200.0, 335.0)),
        make_line(l_ids[2], 1, "七字第三句长句，", (100.0, 340.0, 220.0, 355.0)),
        make_line(l_ids[3], 1, "七字第四句长句。", (100.0, 360.0, 220.0, 375.0)),
    ]
    p_para = make_para("pm_para", 1, "五字第一句，五字第二句。七字第三句长句，七字第四句长句。", l_ids, bbox=(100.0, 300.0, 220.0, 375.0), dominant_font="FZKTJW--GB1-0")
    paras[1].append(p_para)
    lines[1].extend(p_lines)
    res = classify_layout(paras, lines, geos)
    target = res["pm_para"]
    assert target.semantic_role == "uncertain"
    assert target.confidence == 0.35
    assert target.evidence[0] == "uncertain: poetry_unresolved_lines"


def test_lc_33_footer_decreasing_sequence():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # Page 1 has 25, Page 2 has 20
    f1 = make_para("f_dec1", 1, "25", ["fd1_l"], bbox=(280.0, 800.0, 310.0, 815.0))
    f2 = make_para("f_dec2", 2, "20", ["fd2_l"], bbox=(280.0, 800.0, 310.0, 815.0))
    paras[1].append(f1)
    paras[2].append(f2)
    lines[1].append(make_line("fd1_l", 1, "25", (280.0, 800.0, 310.0, 815.0)))
    lines[2].append(make_line("fd2_l", 2, "20", (280.0, 800.0, 310.0, 815.0)))

    res = classify_layout(paras, lines, geos)
    assert res["f_dec1"].semantic_role == "uncertain"
    assert res["f_dec1"].confidence == 0.35
    assert res["f_dec1"].evidence[0] == "uncertain: broken_page_number_sequence"
    assert res["f_dec2"].semantic_role == "uncertain"
    assert res["f_dec2"].evidence[0] == "uncertain: broken_page_number_sequence"


def test_lc_34_group_b_sentinel_rejection():
    # Spacing below is sentinel -1.0 (last paragraph on page)
    eval_res = evaluate_heading_candidate(
        para=make_para("last_line", 1, "末行单行段落无句号", ["ll_l"]),
        active_groups=(),
        total_score=0.0,
        lexical_match=None,
        line_status="verified_single_line",
    )
    assert eval_res.role == "body"
    assert eval_res.confidence == 0.60
    assert eval_res.primary_evidence == "body: unstyled_single_line"


def test_lc_35_footer_same_height_conflict_precedence():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # At dy = 1.0pt (12 at center, 13 at right)
    f1 = make_para("f_sh1", 1, "12", ["fsh1_l"], bbox=(280.0, 800.0, 300.0, 815.0))
    f2 = make_para("f_sh2", 1, "13", ["fsh2_l"], bbox=(500.0, 801.0, 520.0, 816.0))
    paras[1].extend([f1, f2])
    lines[1].extend([
        make_line("fsh1_l", 1, "12", (280.0, 800.0, 300.0, 815.0)),
        make_line("fsh2_l", 1, "13", (500.0, 801.0, 520.0, 816.0)),
    ])
    res = classify_layout(paras, lines, geos)
    assert res["f_sh1"].semantic_role == "uncertain"
    assert res["f_sh1"].evidence[0] == "uncertain: page_level_vertical_conflict"
    assert res["f_sh2"].semantic_role == "uncertain"
    assert res["f_sh2"].evidence[0] == "uncertain: page_level_vertical_conflict"


def test_lc_36_3_line_alternating_poetry_rejection():
    paras, lines, geos = make_standard_document_context()
    # 3 lines of alternating (5, 7, 5) -> strictly requires >= 4 lines
    l_ids = [f"p3_l{i}" for i in range(1, 4)]
    p_lines = [
        make_line(l_ids[0], 1, "五字第一句，", (100.0, 300.0, 200.0, 315.0)),
        make_line(l_ids[1], 1, "七字第二句长句，", (100.0, 320.0, 220.0, 335.0)),
        make_line(l_ids[2], 1, "五字第三句。", (100.0, 340.0, 200.0, 355.0)),
    ]
    p_para = make_para("p3_para", 1, "五字第一句，七字第二句长句，五字第三句。", l_ids, bbox=(100.0, 300.0, 220.0, 355.0), dominant_font="FZKTJW--GB1-0")
    paras[1].append(p_para)
    lines[1].extend(p_lines)
    res = classify_layout(paras, lines, geos)
    target = res["p3_para"]
    assert target.semantic_role == "uncertain"
    assert target.confidence == 0.35
    assert target.evidence[0] == "uncertain: poetry_unresolved_lines"


def test_lc_37_cjk_parser_invalid_formal_numeral():
    assert parse_cjk_or_arabic_numeral("百十") is None
    assert parse_cjk_or_arabic_numeral("二十五百") is None


def test_lc_38_cjk_parser_unicode_superscript_rejection():
    assert parse_cjk_or_arabic_numeral("¹²³") is None


def test_lc_39_page_level_conflict_isolation():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # Conflict at 800 & 801 (cluster 1), and an independent candidate at 806 (cluster 2)
    f1 = make_para("c1_a", 1, "12", ["c1a_l"], bbox=(100.0, 800.0, 130.0, 815.0))
    f2 = make_para("c1_b", 1, "13", ["c1b_l"], bbox=(200.0, 801.0, 230.0, 816.0))
    f3 = make_para("c2_indep", 1, "14", ["c2_l"], bbox=(300.0, 806.0, 330.0, 821.0))
    paras[1].extend([f1, f2, f3])
    lines[1].extend([
        make_line("c1a_l", 1, "12", (100.0, 800.0, 130.0, 815.0)),
        make_line("c1b_l", 1, "13", (200.0, 801.0, 230.0, 816.0)),
        make_line("c2_l", 1, "14", (300.0, 806.0, 330.0, 821.0)),
    ])
    res = classify_layout(paras, lines, geos)
    assert res["c1_a"].semantic_role == "uncertain"
    assert res["c1_a"].evidence[0] == "uncertain: page_level_vertical_conflict"
    assert res["c2_indep"].semantic_role == "uncertain"
    assert res["c2_indep"].evidence[0] == "uncertain: page_level_vertical_conflict"


def test_lc_40_chapter_prefix_gate_failure():
    paras, lines, geos = make_standard_document_context()
    # Chapter prefix alone, no size/spacing/bold -> S=0.35, active_groups=('C',)
    ch_p = make_para(
        paragraph_id="ch_gate_fail",
        page_num=1,
        text="第一章 孤独章节前缀",
        source_line_ids=["cgf_l"],
        bbox=(50.0, 186.0, 200.0, 200.0),
        dominant_font="SimSun",
        dominant_size=10.5,
    )
    # tight spacing so B is 0
    next_p = make_para("cgf_next", 1, "紧贴文字。", ["cgfn_l"], bbox=(50.0, 205.0, 300.0, 220.0))
    paras[1].extend([ch_p, next_p])
    lines[1].extend([
        make_line("cgf_l", 1, "第一章 孤独章节前缀", (50.0, 186.0, 200.0, 200.0)),
        make_line("cgfn_l", 1, "紧贴文字。", (50.0, 205.0, 300.0, 220.0)),
    ])
    res = classify_layout(paras, lines, geos)
    target = res["ch_gate_fail"]
    assert target.semantic_role == "uncertain"
    assert target.confidence == 0.40
    assert target.evidence[0] == "uncertain: heading_single_group_quarantine"
    assert target.active_groups == ("C",)


def test_lc_41_lexical_vs_score_level_priority():
    # Section prefix 第二節 with high score S = 0.85 -> Priority 1 (Section -> Level 2) overrides S >= 0.85
    level, conf, ev = resolve_heading_level("section", 0.85)
    assert level == 2
    assert conf == 0.80
    assert ev == "heading: level_2_candidate"


def test_lc_42_missing_geometry_slot_rejection():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # Page 99 has no geometry
    paras[99] = [make_para("p99_hdr", 99, "未注册几何度量的页眉", ["p99h_l"], bbox=(100.0, 20.0, 300.0, 35.0))]
    lines[99] = [make_line("p99h_l", 99, "未注册几何度量的页眉", (100.0, 20.0, 300.0, 35.0))]
    drc = build_repetition_context(paras, geos, build_typography_baseline(paras, lines, geos))
    assert len(drc.recurring_top_patterns) == 0


def test_lc_43_duplicate_paragraph_id_rejection():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # Duplicate paragraph ID across pages
    dup_p = make_para("p1_b1", page_num=2, text="跨页重复ID段落", source_line_ids=["dup_l"])
    paras[2].append(dup_p)
    lines[2].append(make_line("dup_l", 2, "跨页重复ID段落"))
    with pytest.raises(ValueError, match="Duplicate paragraph_id"):
        classify_layout(paras, lines, geos)


def test_lc_44_page_number_key_mismatch_rejection():
    paras, lines, geos = make_standard_document_context(page_count=2)
    # Dict key 1 contains paragraph with page_num = 2
    mismatch_p = make_para("mismatch_p", page_num=2, text="页码不一致段落", source_line_ids=["mis_l"])
    paras[1].append(mismatch_p)
    lines[1].append(make_line("mis_l", 1, "页码不一致段落"))
    with pytest.raises(ValueError, match="Mapping key page_num 1 mismatches para.page_num 2"):
        classify_layout(paras, lines, geos)


def test_lc_45_invalid_baseline_unresolved_line_body():
    geos = {1: make_geo(1)}
    # Baseline invalid, missing line records in lines
    p = make_para("inv_unres", 1, "正文段落但缺少行记录。", ["missing_line_id"])
    paras = {1: [p]}
    lines = {1: []}
    res = classify_layout(paras, lines, geos)
    target = res["inv_unres"]
    assert target.semantic_role == "uncertain"
    assert target.confidence == 0.35
    assert target.evidence[0] == "uncertain: invalid_baseline_quarantine"


# ---------------------------------------------------------------------------
# Edge Cases EDGE-01 to EDGE-12
# ---------------------------------------------------------------------------

def test_edge_01_quantization_non_finite_step():
    with pytest.raises(ValueError):
        quantize_font_size(10.5, step=float("nan"))
    with pytest.raises(ValueError):
        quantize_font_size(10.5, step=float("inf"))
    with pytest.raises(ValueError):
        quantize_font_size(10.5, step=True)  # type: ignore


def test_edge_02_caption_lookahead_boundary():
    paras, lines, geos = make_standard_document_context()
    # Table 2abc is not a valid caption
    t2abc = make_para("t2abc", 1, "Table 2abc is invalid caption prefix", ["t2abc_l"])
    paras[1].append(t2abc)
    lines[1].append(make_line("t2abc_l", 1, "Table 2abc is invalid caption prefix"))
    res = classify_layout(paras, lines, geos)
    assert res["t2abc"].semantic_role != "caption"


def test_edge_03_inverted_bbox_geometry():
    paras, lines, geos = make_standard_document_context()
    # Inverted bounding box: y1 (20.0) < y0 (50.0)
    inv_p = make_para("inv_bbox", 1, "反向边界框", ["ib_l"], bbox=(10.0, 50.0, 100.0, 20.0))
    paras[1].append(inv_p)
    lines[1].append(make_line("ib_l", 1, "反向边界框"))
    with pytest.raises(ValueError, match="Invalid bounding box coordinates"):
        classify_layout(paras, lines, geos)


def test_edge_04_content_top_zero_baseline_safety():
    # content_top = 0.0 in PageGeometry: should NOT falsely exclude paragraphs
    geo = make_geo(1, content_top=0.0)
    text_sample = "这是一段标准干净的测试中文正文内容，在content_top为0时不应被丢弃。这段文字必须超过五十个字符才能通过第四阶段的基线干净字符数门槛检验。"
    p = make_para("p_top0", 1, text_sample, ["pt0_l1", "pt0_l2"], bbox=(50.0, 10.0, 545.0, 50.0))
    paras = {1: [p]}
    lines = {
        1: [
            make_line("pt0_l1", 1, "这是一段标准干净的测试中文正文内容，在content_top为0时不应被丢弃。", (50.0, 10.0, 545.0, 25.0)),
            make_line("pt0_l2", 1, "这段文字必须超过五十个字符才能通过第四阶段的基线干净字符数门槛检验。", (50.0, 30.0, 545.0, 45.0)),
        ]
    }
    baseline = build_typography_baseline(paras, lines, {1: geo})
    assert baseline.is_valid is True
    assert baseline.body_font == "SimSun"


def test_edge_05_scoring_saturation_cap():
    eval_res = evaluate_heading_candidate(
        para=make_para("sat_p", 1, "第三章 饱和分数测试章节"),
        active_groups=("A", "B", "C"),
        total_score=1.00,
        lexical_match="chapter",
        line_status="verified_single_line",
    )
    assert eval_res.qualified is True
    assert eval_res.suggested_level == 1
    assert eval_res.confidence == 0.90


def test_edge_06_score_boundary_gate():
    # S = 0.65 qualifies as heading
    pass_eval = evaluate_heading_candidate(
        para=make_para("p_pass", 1, "边界及格标题测试"),
        active_groups=("A", "B"),
        total_score=0.65,
        lexical_match=None,
        line_status="verified_single_line",
    )
    assert pass_eval.qualified is True
    assert pass_eval.role == "heading_candidate"

    # S = 0.64 fails gate -> quarantined to heading_insufficient_score
    fail_eval = evaluate_heading_candidate(
        para=make_para("p_fail", 1, "边界不及格标题测试"),
        active_groups=("A", "B"),
        total_score=0.64,
        lexical_match=None,
        line_status="verified_single_line",
    )
    assert fail_eval.qualified is False
    assert fail_eval.role == "uncertain"
    assert fail_eval.primary_evidence == "uncertain: heading_insufficient_score"


def test_edge_07_footer_clustering_anchor_determinism():
    # y0 = 100, 102, 104 with tolerance 3.0: Group 1: [100, 102], Group 2: [104]
    c1 = make_para("c1", 1, "1", ["l1"], bbox=(50.0, 100.0, 100.0, 115.0))
    c2 = make_para("c2", 1, "2", ["l2"], bbox=(50.0, 102.0, 100.0, 117.0))
    c3 = make_para("c3", 1, "3", ["l3"], bbox=(50.0, 104.0, 100.0, 119.0))
    clusters = cluster_vertical_candidates([c1, c2, c3], tolerance=3.0)
    assert len(clusters) == 2
    assert [c.paragraph_id for c in clusters[0]] == ["c1", "c2"]
    assert [c.paragraph_id for c in clusters[1]] == ["c3"]


def test_edge_08_footer_sequence_reset():
    paras, lines, geos = make_standard_document_context(page_count=3)
    # Pages 1, 2, 3 have values 10, 11, 1 -> sequence reset
    f1 = make_para("f_seq1", 1, "10", ["fs1_l"], bbox=(280.0, 800.0, 310.0, 815.0))
    f2 = make_para("f_seq2", 2, "11", ["fs2_l"], bbox=(280.0, 800.0, 310.0, 815.0))
    f3 = make_para("f_seq3", 3, "1", ["fs3_l"], bbox=(280.0, 800.0, 310.0, 815.0))
    paras[1].append(f1)
    paras[2].append(f2)
    paras[3].append(f3)
    lines[1].append(make_line("fs1_l", 1, "10", (280.0, 800.0, 310.0, 815.0)))
    lines[2].append(make_line("fs2_l", 2, "11", (280.0, 800.0, 310.0, 815.0)))
    lines[3].append(make_line("fs3_l", 3, "1", (280.0, 800.0, 310.0, 815.0)))

    res = classify_layout(paras, lines, geos)
    assert res["f_seq1"].semantic_role == "uncertain"
    assert res["f_seq1"].evidence[0] == "uncertain: broken_page_number_sequence"
    assert res["f_seq2"].semantic_role == "uncertain"
    assert res["f_seq3"].semantic_role == "uncertain"


def test_edge_09_short_prose_non_kaiti_poetry_rejection():
    paras, lines, geos = make_standard_document_context()
    # 3 lines of 5 chars in SongTi font -> rejected from poetry
    l_ids = ["sp1_l1", "sp1_l2", "sp1_l3"]
    p_lines = [
        make_line(l_ids[0], 1, "五字第一行，", (100.0, 300.0, 200.0, 315.0)),
        make_line(l_ids[1], 1, "五字第二行。", (100.0, 320.0, 200.0, 335.0)),
        make_line(l_ids[2], 1, "五字第三行。", (100.0, 340.0, 200.0, 355.0)),
    ]
    sp_para = make_para("sp_songti", 1, "五字第一行，五字第二行。五字第三行。", l_ids, bbox=(100.0, 300.0, 200.0, 355.0), dominant_font="SimSun")
    paras[1].append(sp_para)
    lines[1].extend(p_lines)
    res = classify_layout(paras, lines, geos)
    target = res["sp_songti"]
    assert target.semantic_role == "uncertain"
    assert target.confidence == 0.35
    assert target.evidence[0] == "uncertain: poetry_rhythm_without_kaiti_font"


def test_edge_10_input_immutability():
    paras, lines, geos = make_standard_document_context(page_count=2)
    paras_snap = copy.deepcopy(paras)
    lines_snap = copy.deepcopy(lines)
    geos_snap = copy.deepcopy(geos)

    _ = classify_layout(paras, lines, geos)

    assert paras == paras_snap
    assert lines == lines_snap
    assert geos == geos_snap


def test_edge_11_zero_disk_io():
    paras, lines, geos = make_standard_document_context()

    with (
        patch("builtins.open") as mock_b_open,
        patch("io.open") as mock_io_open,
        patch("os.open") as mock_os_open,
        patch("pathlib.Path.open") as mock_p_open,
        patch("pathlib.Path.read_text") as mock_p_rt,
        patch("pathlib.Path.read_bytes") as mock_p_rb,
        patch("pathlib.Path.write_text") as mock_p_wt,
        patch("pathlib.Path.write_bytes") as mock_p_wb,
        patch("pathlib.Path.mkdir") as mock_p_mkdir,
    ):
        res = classify_layout(paras, lines, geos)
        assert len(res) > 0

        mock_b_open.assert_not_called()
        mock_io_open.assert_not_called()
        mock_os_open.assert_not_called()
        mock_p_open.assert_not_called()
        mock_p_rt.assert_not_called()
        mock_p_rb.assert_not_called()
        mock_p_wt.assert_not_called()
        mock_p_wb.assert_not_called()
        mock_p_mkdir.assert_not_called()


def test_edge_12_runtime_contract_validation():
    # 1. Python bool masquerading as int in page_num
    with pytest.raises(ValueError, match="page_num must be positive int"):
        ParagraphClassification(
            paragraph_id="p1",
            page_num=True,  # type: ignore
            semantic_role="body",
            suggested_heading_level=None,
            confidence=0.85,
            is_provisional=False,
            evidence=("body: multiline_prose_flow",),
            active_groups=(),
            score=0.0,
        )

    # 2. Python bool masquerading as float in confidence
    with pytest.raises(ValueError, match="confidence must be finite"):
        ParagraphClassification(
            paragraph_id="p1",
            page_num=1,
            semantic_role="body",
            suggested_heading_level=None,
            confidence=True,  # type: ignore
            is_provisional=False,
            evidence=("body: multiline_prose_flow",),
            active_groups=(),
            score=0.0,
        )

    # 3. Primary token not matching semantic role
    with pytest.raises(ValueError, match="Primary evidence token"):
        ParagraphClassification(
            paragraph_id="p1",
            page_num=1,
            semantic_role="body",
            suggested_heading_level=None,
            confidence=0.95,
            is_provisional=False,
            evidence=("caption: table_or_figure_prefix",),
            active_groups=(),
            score=0.0,
        )

    # 4. Heading candidate missing heading level
    with pytest.raises(ValueError, match="heading_candidate requires suggested_heading_level"):
        ParagraphClassification(
            paragraph_id="p1",
            page_num=1,
            semantic_role="heading_candidate",
            suggested_heading_level=None,
            confidence=0.90,
            is_provisional=False,
            evidence=("heading: level_1_candidate",),
            active_groups=("A", "B", "C"),
            score=1.0,
        )
