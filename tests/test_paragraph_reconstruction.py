# -*- coding: utf-8 -*-
"""
test_paragraph_reconstruction.py: Unit Tests for PDF Paragraph Reconstruction (Phase 1.2)
========================================================================================
Validates Phase 1.2 requirements:
- PR-01: Normal multiline CJK body smoothly reflowed.
- PR-02: Short standalone block isolated from subsequent body.
- PR-03: Inline font and style variation does not break paragraph.
- PR-04: Unclosed bracket/quotation continues across line boundaries.
- PR-05: Flush-left modern layout separated by vertical paragraph spacing.
- PR-06: Page-local cross-page continuation flags without cross-page merging.
- PR-07: Multi-span preservation and lineage tracking.
- PR-08: CJK fullwidth punctuation line joining does not insert ASCII spaces.
- PR-09: Conservative hyphen preservation (well-known, anti-inflammatory, HLA-B27, text-based).
- PR-10: Complete sentence ending at page bottom suppresses continuation_to_next.
- PR-11: Nested & interleaved delimiters (《...（...）...》) update stack properly.
- PR-12: Standalone block candidates do not produce heading semantics.
- PR-13: Continuation confidence is heuristic score in [0.0, 1.0] with explainable evidence.
- PR-14: Single-column reading order deterministic sorting contract.
- PR-15: Unclosed delimiter overrides inner terminal punctuation at page bottom.
- Typography character-weighted statistics and bounding box union accuracy.
"""

import unittest
from src.scripts.paragraph_reconstruction import (
    SpanRecord,
    LineRecord,
    PageGeometry,
    BoundaryEvidence,
    ParagraphRecord,
    reconstruct_page_paragraphs,
    compute_character_weighted_typography,
    union_line_bboxes,
    join_line_texts,
    is_cjk_boundary_character,
)


class TestParagraphReconstruction(unittest.TestCase):

    def setUp(self):
        self.default_page = PageGeometry(
            width=500.0,
            height=700.0,
            base_x0=60.0,
            max_x1=440.0,
            content_top=50.0,
            content_bottom=650.0,
        )

    def _make_line(
        self,
        line_id: str,
        text: str,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        font: str = "SimSun",
        size: float = 10.5,
        flags: int = 0,
        block_id: str = "b0",
        line_order: int = 0,
        page_num: int = 1,
    ) -> LineRecord:
        span = SpanRecord(
            text=text,
            bbox=(x0, y0, x1, y1),
            font_family=font,
            font_size=size,
            font_flags=flags,
        )
        return LineRecord(
            line_id=line_id,
            page_num=page_num,
            text=text,
            bbox=(x0, y0, x1, y1),
            spans=[span],
            block_id=block_id,
            line_order=line_order,
        )

    # ── PR-01: Normal multiline CJK body smoothly reflowed ───────────────────
    def test_pr01_normal_multiline_cjk_body_reflow(self):
        """Standard 2-character indented paragraph with 2 lines should merge into 1 paragraph."""
        l1 = self._make_line("l1", "强直性脊柱炎是一种以骶髂关节和脊柱附着点炎症为主要病理改变的", 81.0, 100.0, 440.0, 115.0)
        l2 = self._make_line("l2", "慢性进行性炎性疾病，临床多表现为晨僵、腰背部疼痛与活动受限。", 60.0, 118.0, 440.0, 133.0)

        paras = reconstruct_page_paragraphs([l1, l2], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        self.assertEqual(paras[0].source_line_ids, ["l1", "l2"])
        self.assertIn("主要病理改变的慢性进行性", paras[0].text)
        self.assertNotIn("改变的 慢性", paras[0].text)

    def test_ai_boundary_override_can_split_only_an_uncertain_pair(self):
        """A trusted review must correct a low-certainty join without changing source text."""
        l1 = self._make_line("l1", "短段落結束。", 60.0, 100.0, 180.0, 115.0)
        l2 = self._make_line("l2", "下一段開始。", 60.0, 118.0, 180.0, 133.0)

        paras = reconstruct_page_paragraphs(
            [l1, l2], self.default_page, standard_pitch=18.0, boundary_overrides={"l2": True}
        )

        self.assertEqual([para.text for para in paras], ["短段落結束。", "下一段開始。"])

    def test_ai_boundary_override_cannot_break_an_unclosed_delimiter_continuation(self):
        l1 = self._make_line("l1", "引文開始《未完成", 60.0, 100.0, 200.0, 115.0)
        l2 = self._make_line("l2", "後續文字》結束。", 60.0, 118.0, 200.0, 133.0)

        paras = reconstruct_page_paragraphs(
            [l1, l2], self.default_page, standard_pitch=18.0, boundary_overrides={"l2": True}
        )

        self.assertEqual(len(paras), 1)

    # ── PR-02: Short standalone block isolated from subsequent body ───────────
    def test_pr02_short_heading_isolation(self):
        """A short standalone line without terminal punctuation must NOT glue into body."""
        l1 = self._make_line("l1", "临床资料与方法", 60.0, 100.0, 180.0, 115.0, font="SimHei", size=12.0)
        l2 = self._make_line("l2", "本次临床观察共纳入符合诊断标准之中轴型脊柱关节炎患者八十六例，", 81.0, 135.0, 440.0, 150.0)
        l3 = self._make_line("l3", "所有患者均已签署知情同意书并按随机原则分为对照组与观察组。", 60.0, 153.0, 440.0, 168.0)

        paras = reconstruct_page_paragraphs([l1, l2, l3], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 2)
        self.assertEqual(paras[0].text, "临床资料与方法")
        self.assertEqual(paras[0].source_line_ids, ["l1"])
        self.assertEqual(paras[1].source_line_ids, ["l2", "l3"])
        self.assertNotIn("临床资料与方法本次临床观察", paras[0].text)

    # ── PR-03: Inline font and style variation does not break paragraph ───────
    def test_pr03_inline_font_variation_does_not_break_paragraph(self):
        """Font family or style changing mid-paragraph MUST NOT split into multiple paragraphs."""
        l1 = self._make_line("l1", "患者血清学检测指标中，", 81.0, 100.0, 250.0, 115.0, font="SimSun", size=10.5)
        l2 = self._make_line("l2", "HLA-B27", 250.0, 100.0, 320.0, 115.0, font="TimesNewRoman", size=10.5, flags=16)
        l3 = self._make_line("l3", "阳性表达率达到百分之九十以上，具有高度特异性诊断价值。", 60.0, 118.0, 440.0, 133.0, font="SimSun", size=10.5)

        paras = reconstruct_page_paragraphs([l1, l2, l3], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        self.assertEqual(paras[0].source_line_ids, ["l1", "l2", "l3"])
        self.assertIn("HLA-B27", paras[0].text)

    # ── PR-04: Unclosed bracket/quotation continuation ───────────────────────
    def test_pr04_unclosed_delimiter_continuation(self):
        """Line ending with unclosed book quote 《 must continue onto next line without break."""
        l1 = self._make_line("l1", "本研究所采用之经典方剂配伍源于清代温病学名著《温", 81.0, 100.0, 380.0, 115.0)
        l2 = self._make_line("l2", "病条辨》中之沙参麦冬汤，重在益气润燥、清热滋阴。", 60.0, 118.0, 440.0, 133.0)

        paras = reconstruct_page_paragraphs([l1, l2], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        self.assertIn("《温病条辨》", paras[0].text)

    # ── PR-05: Flush-left modern layout separated by vertical spacing ─────────
    def test_pr05_flush_left_vertical_spacing_splits_paragraphs(self):
        """Modern layout with 0 indentation must split paragraphs when vertical gap is large."""
        p1_l1 = self._make_line("p1_l1", "对照组患者接受常规针刺疗法，取穴以肾俞、大肠俞及夹脊穴为主，", 60.0, 100.0, 440.0, 115.0)
        p1_l2 = self._make_line("p1_l2", "留针三十分钟，每日一次，连续治疗四周时间观察疗效指标。", 60.0, 118.0, 440.0, 133.0)
        p2_l1 = self._make_line("p2_l1", "观察组在对照组基础上加用刺络拔罐疗法，隔日施术一次，", 60.0, 155.0, 440.0, 170.0)
        p2_l2 = self._make_line("p2_l2", "重点观察腰部压痛积分及脊柱前屈活动度的改善程度。", 60.0, 173.0, 440.0, 188.0)

        paras = reconstruct_page_paragraphs([p1_l1, p1_l2, p2_l1, p2_l2], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 2)
        self.assertEqual(paras[0].source_line_ids, ["p1_l1", "p1_l2"])
        self.assertEqual(paras[1].source_line_ids, ["p2_l1", "p2_l2"])

    # ── PR-06: Page-local cross-page continuation flags ───────────────────────
    def test_pr06_page_local_cross_page_continuation_flags(self):
        """Line near content_bottom without terminal punct must be flagged with continuation_to_next."""
        l1 = self._make_line("l1", "观察组患者在治疗期间未发生任何严重不良反应，且心电图与肝肾功能", 60.0, 640.0, 440.0, 655.0)

        paras = reconstruct_page_paragraphs([l1], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        self.assertTrue(paras[0].continuation_to_next)
        self.assertGreaterEqual(paras[0].continuation_confidence, 0.70)

    # ── PR-07: Multi-span preservation and lineage tracking ───────────────────
    def test_pr07_multi_span_preservation_and_lineage(self):
        """A line with multiple spans must preserve individual SpanRecords inside LineRecord."""
        span1 = SpanRecord(text="方中以", bbox=(60.0, 100.0, 110.0, 115.0), font_family="SimSun", font_size=10.5)
        span2 = SpanRecord(text="柴胡 12g", bbox=(110.0, 100.0, 180.0, 115.0), font_family="KaiTi", font_size=10.5)
        span3 = SpanRecord(text="为君药，疏肝升阳。", bbox=(180.0, 100.0, 300.0, 115.0), font_family="SimSun", font_size=10.5)

        line = LineRecord(
            line_id="multi_span_line",
            page_num=1,
            text="方中以柴胡 12g为君药，疏肝升阳。",
            bbox=(60.0, 100.0, 300.0, 115.0),
            spans=[span1, span2, span3],
        )

        paras = reconstruct_page_paragraphs([line], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        self.assertIn("multi_span_line", paras[0].source_line_ids)

    # ── PR-08: CJK punctuation line joining does not insert ASCII space ───────
    def test_pr08_cjk_punctuation_line_joining_no_spaces(self):
        """
        Validates both directions:
        - Punctuation to text: Line 1 ends in '，' or '》', Line 2 starts with Chinese.
        - Text to punctuation: Line 1 ends in Chinese, Line 2 starts with '（'.
        Must NOT insert ASCII space.
        """
        # Direction 1: Punctuation -> text
        l1 = self._make_line("l1", "这是一段文字，", 81.0, 100.0, 440.0, 115.0)
        l2 = self._make_line("l2", "接续下一行内容。", 60.0, 118.0, 440.0, 133.0)

        # Direction 2: Quotation marks
        l3 = self._make_line("l3", "深入研读《伤寒杂病论》", 81.0, 140.0, 440.0, 155.0)
        l4 = self._make_line("l4", "及后世历代医家注本。", 60.0, 158.0, 440.0, 173.0)

        res1 = join_line_texts([l1, l2])
        self.assertEqual(res1, "这是一段文字，接续下一行内容。")
        self.assertNotIn("文字， 接续", res1)

        res2 = join_line_texts([l3, l4])
        self.assertEqual(res2, "深入研读《伤寒杂病论》及后世历代医家注本。")
        self.assertNotIn("论》 及", res2)

    # ── PR-09: Conservative hyphen preservation ──────────────────────────────
    def test_pr09_conservative_hyphen_preservation(self):
        """
        Validates that hyphenated terms are preserved without destructive removal:
        - well-known
        - anti-inflammatory
        - HLA-B27
        - text-based
        """
        cases = [
            ("well-", "known", "well-known"),
            ("anti-", "inflammatory", "anti-inflammatory"),
            ("HLA-", "B27", "HLA-B27"),
            ("text-", "based", "text-based"),
        ]
        for pref, suff, expected in cases:
            l1 = self._make_line("l1", f"This study provides a {pref}", 60.0, 100.0, 440.0, 115.0)
            l2 = self._make_line("l2", f"{suff} perspective.", 60.0, 118.0, 440.0, 133.0)
            joined = join_line_texts([l1, l2])
            self.assertIn(expected, joined, f"Failed preserving hyphen for {expected}")
            self.assertNotIn(expected.replace("-", ""), joined)

    # ── PR-10: Complete sentence at page bottom suppresses continuation ───────
    def test_pr10_page_bottom_complete_sentence_suppressed(self):
        """A complete sentence ending with terminal punct near content_bottom must NOT continue."""
        l1 = self._make_line("l1", "本章全部临床观察至此结束，疗效统计结果显著。", 60.0, 640.0, 440.0, 655.0)

        paras = reconstruct_page_paragraphs([l1], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        self.assertFalse(paras[0].continuation_to_next)
        self.assertLessEqual(paras[0].continuation_confidence, 0.1)
        self.assertTrue(any("terminal_punctuation_present" in ev for ev in paras[0].continuation_evidence))

    # ── PR-11: Nested & interleaved delimiters stack handling ─────────────────
    def test_pr11_nested_interleaved_delimiters_stack_handling(self):
        """Nested delimiters like 《章节（补充说明）内容》 must update and clear stack properly."""
        l1 = self._make_line("l1", "详见第二篇《中西医结合诊疗方案（2023年修订试行版）临床实践指南》", 81.0, 100.0, 440.0, 115.0)
        l2 = self._make_line("l2", "所附之相关规定及用药剂量表。", 60.0, 118.0, 440.0, 133.0)

        paras = reconstruct_page_paragraphs([l1, l2], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        self.assertIn("实践指南》所附之相关", paras[0].text)

    # ── PR-12: Standalone block candidates do not produce heading semantics ───
    def test_pr12_standalone_block_no_heading_semantics(self):
        """A standalone block creates a separated paragraph but leaves heading semantics decoupled."""
        l1 = self._make_line("l1", "第二章 临床观察与病例统计", 60.0, 100.0, 240.0, 118.0, font="SimHei", size=14.0)
        l2 = self._make_line("l2", "纳入观察之患者共计一百二十例，均来自我院门诊与住院部。", 81.0, 145.0, 440.0, 160.0)

        paras = reconstruct_page_paragraphs([l1, l2], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 2)
        # Structural isolation verified
        self.assertEqual(paras[0].text, "第二章 临床观察与病例统计")
        self.assertTrue(paras[0].is_standalone_block)
        # Decoupling verified: Phase 1 leaves semantic classification to Phase 3
        self.assertEqual(paras[0].semantic_role, "uncertain")
        self.assertIsNone(paras[0].heading_level)
        self.assertTrue(any("standalone_block" in r for ev in paras[1].evidence for r in ev.reasons))

    # ── PR-13: Continuation confidence heuristic bounds & evidence ────────────
    def test_pr13_continuation_confidence_and_evidence(self):
        """Verifies continuation_confidence is bounded in [0.0, 1.0] and evidence is informative."""
        l1 = self._make_line("l1", "主要参考清代医家吴鞠通所撰《温病条辨（附评注", 60.0, 642.0, 440.0, 655.0)

        paras = reconstruct_page_paragraphs([l1], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        self.assertTrue(paras[0].continuation_to_next)
        self.assertGreaterEqual(paras[0].continuation_confidence, 0.85)
        self.assertLessEqual(paras[0].continuation_confidence, 1.0)
        self.assertTrue(any("unclosed_delimiter" in ev for ev in paras[0].continuation_evidence))

    # ── PR-14: Single-column reading order deterministic sorting ──────────────
    def test_pr14_single_column_reading_order_deterministic(self):
        """Validates that lines are sorted deterministically by (y0, x0) under the single-column contract."""
        l_bottom = self._make_line("l_bot", "这是靠下方的第二行文字。", 60.0, 118.0, 440.0, 133.0)
        l_top = self._make_line("l_top", "这是靠上方开头的首行文字。", 81.0, 100.0, 440.0, 115.0)

        # Input in reversed order
        paras = reconstruct_page_paragraphs([l_bottom, l_top], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        self.assertEqual(paras[0].source_line_ids, ["l_top", "l_bot"])
        self.assertTrue(paras[0].text.startswith("这是靠上方开头的首行文字。"))

    # ── PR-15: Unclosed delimiter overrides inner terminal punctuation at page bottom ──
    def test_pr15_unclosed_delimiter_overrides_inner_terminal_punctuation_at_bottom(self):
        """
        Unclosed quotation delimiter containing terminal punctuation at page bottom
        must NOT be suppressed by the terminal punctuation; continuation_to_next must be True.
        """
        l1 = self._make_line(
            "l1",
            "他在书中写道：“这是一段尚未结束的引用内容。",
            60.0,
            635.0,
            440.0,
            650.0,
        )

        paras = reconstruct_page_paragraphs([l1], self.default_page, standard_pitch=18.0)
        self.assertEqual(len(paras), 1)
        p = paras[0]
        self.assertTrue(p.continuation_to_next)
        self.assertGreaterEqual(p.continuation_confidence, 0.0)
        self.assertLessEqual(p.continuation_confidence, 1.0)
        self.assertEqual(p.continuation_confidence, 0.90)
        self.assertTrue(any("unclosed_delimiter" in ev for ev in p.continuation_evidence))
        self.assertTrue(any("unclosed delimiter overrides inner terminal punctuation" in ev for ev in p.continuation_evidence))

    # ── Typography statistics and bounding box union ─────────────────────────
    def test_character_weighted_typography_statistics(self):
        """Verify dominant_font, dominant_size, and bold_ratio are weighted by character count."""
        span_a = SpanRecord(
            text="这是一段非常长的中文句子用于确保宋体的字符总数远远超过后面紧接着的粗体字片段",
            bbox=(60.0, 100.0, 400.0, 115.0),
            font_family="SimSun",
            font_size=10.5,
        )
        span_b = SpanRecord(
            text="重点说明",
            bbox=(400.0, 100.0, 440.0, 115.0),
            font_family="SimHei",
            font_size=14.0,
            font_flags=16,
        )
        line = LineRecord(
            line_id="w_line",
            page_num=1,
            text=span_a.text + span_b.text,
            bbox=(60.0, 100.0, 440.0, 115.0),
            spans=[span_a, span_b],
        )

        font, size, bold_ratio = compute_character_weighted_typography([line])
        self.assertEqual(font, "SimSun")
        self.assertEqual(size, 10.5)
        expected_bold_ratio = round(len(span_b.text) / (len(span_a.text) + len(span_b.text)), 4)
        self.assertEqual(bold_ratio, expected_bold_ratio)

    def test_bounding_box_union(self):
        """Bounding box of paragraph must be the tight minimal enclosing union."""
        l1 = self._make_line("l1", "第一行", 70.0, 100.0, 300.0, 115.0)
        l2 = self._make_line("l2", "第二行更宽", 60.0, 120.0, 350.0, 138.0)

        union_box = union_line_bboxes([l1, l2])
        self.assertEqual(union_box, (60.0, 100.0, 350.0, 138.0))


if __name__ == "__main__":
    unittest.main()
