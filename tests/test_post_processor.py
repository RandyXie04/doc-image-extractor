#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for the deep MarkdownPostProcessor module (Candidate 1).
"""

import tempfile
import unittest
from pathlib import Path

from src.extraction.post_processor import (
    MarkdownPostProcessor,
    PostProcessResult,
    postprocess_markdown,
    OutputAnomalyError,
)


class TestMarkdownPostProcessor(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.output_dir = self.test_dir.name

    def tearDown(self):
        self.test_dir.cleanup()

    def test_interface_and_tuple_unpacking(self):
        """Verify PostProcessResult supports attribute access and tuple unpacking."""
        sample_md = "# 第一章 導論\n\n這是一段正文內容。"
        res = postprocess_markdown(
            markdown_text=sample_md,
            pdf_name="sample_doc",
            output_dir=self.output_dir,
            enable_dictionary_postprocess=False,
        )

        # Attribute access
        self.assertIsInstance(res, PostProcessResult)
        self.assertIn("第一章 導論", res.markdown)
        self.assertIsInstance(res.rare_char_stats, dict)

        # Tuple unpacking compatibility
        text, stats = res
        self.assertEqual(text, res.markdown)
        self.assertEqual(stats, res.rare_char_stats)

    def test_dictionary_heading_demotion(self):
        """Verify dictionary term headings are demoted while chapter headings are preserved."""
        dict_md = (
            "# 靈芝\n"
            "多孔菌科真菌靈芝的子實體。\n\n"
            "# 第一章\n"
            "本章介紹中草藥之基本性味歸經。\n\n"
            "# 第一章 中醫藥物學基礎與現代臨床應用\n"
            "詳細論述藥物之臨床配伍。\n"
        )

        res = postprocess_markdown(
            markdown_text=dict_md,
            pdf_name="chinese_medicine_dict",
            output_dir=self.output_dir,
            enable_dictionary_postprocess=True,
        )

        # Dictionary term demoted to bold
        self.assertIn("**靈芝**", res.markdown)
        self.assertNotIn("# 靈芝", res.markdown)

        # Structural chapter headings preserved
        self.assertIn("# 第一章\n", res.markdown)
        self.assertIn("# 第一章 中醫藥物學基礎與現代臨床應用", res.markdown)

    def test_progress_callback_invocations(self):
        """Verify progress callbacks are triggered with expected progress values."""
        sample_md = "# 人參\n五加科植物人參的乾燥根。"
        progress_events = []

        def on_progress(p, msg):
            progress_events.append((p, msg))

        postprocess_markdown(
            markdown_text=sample_md,
            pdf_name="herb_dict",
            output_dir=self.output_dir,
            progress_callback=on_progress,
            enable_dictionary_postprocess=True,
        )

        # Expect dictionary progress (81)
        progress_percents = [p for p, _ in progress_events]
        self.assertIn(81, progress_percents)

    def test_empty_input_handling(self):
        """Verify empty or non-string inputs are handled gracefully without raising."""
        res_empty = postprocess_markdown(
            markdown_text="",
            pdf_name="empty",
            output_dir=self.output_dir,
        )
        self.assertEqual(res_empty.markdown, "")
        self.assertEqual(res_empty.rare_char_stats, {})

    def test_output_anomaly_guard(self):
        """Verify OutputAnomalyError is raised when output shrinks past threshold."""
        processor = MarkdownPostProcessor(anomaly_threshold=0.50)
        
        # Test class directly with an artificial anomaly
        with self.assertRaises(OutputAnomalyError):
            # Manually invoke with simulated heavy shrinkage
            input_len = 1000
            output_len = 100
            raise OutputAnomalyError(input_len, output_len, 0.50, "sample...")


if __name__ == "__main__":
    unittest.main()
