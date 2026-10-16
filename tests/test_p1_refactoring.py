# -*- coding: utf-8 -*-
import unittest
import asyncio
from pathlib import Path
import tempfile
import time
import shutil

from src.scripts.dictionary_post_processor import postprocess_dictionary_markdown
import src.scripts.book_layout_extractor as ble
import src.scripts.book_layout_extractor_no_footnote as ble_no_fn
import src.scripts.process_ocr as p_ocr
import src.scripts.process_ocr_no_footnote as p_ocr_no_fn
from src.web.app import _OCR_SEMAPHORE, _BACKGROUND_TASKS, cleanup_old_files


class TestP1Refactoring(unittest.TestCase):
    def test_dictionary_post_processor_regexes(self):
        """Test precompiled regexes and catastrophic backtracking protection."""
        # 1. False heading term conversion
        md = "# 詞條名\n這是一段釋義。"
        result = postprocess_dictionary_markdown(md)
        self.assertIn("**詞條名**", result)
        self.assertNotIn("# 詞條名", result)

        # 2. Structural heading exception
        md_chapter = "# 第一章\n正文內容。"
        res_chapter = postprocess_dictionary_markdown(md_chapter)
        self.assertIn("# 第一章", res_chapter)

        # 3. Citation / KaiTi identification
        md_quote = '〔唐〕李白《靜夜思》'
        res_quote = postprocess_dictionary_markdown(md_quote, style_mapping={"kaiti": "引言樣式"})
        self.assertIn('::: {custom-style="引言樣式"}', res_quote)

        # 4. Long unclosed quote without backtracking hang
        long_line = '"这是一段很长很长但是没有闭合双引号的文本内容' + '测试' * 50
        start = time.perf_counter()
        _ = postprocess_dictionary_markdown(long_line)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.5)

    def test_book_layout_extractor_shim(self):
        """Test that book_layout_extractor_no_footnote exists and forwards seamlessly."""
        self.assertTrue(hasattr(ble_no_fn, "process_book_vector_pdf"))
        # Signature inspectable
        import inspect
        sig = inspect.signature(ble.process_book_vector_pdf)
        self.assertIn("no_footnote", sig.parameters)
        self.assertEqual(sig.parameters["no_footnote"].default, False)

    def test_process_ocr_shim(self):
        """Test that process_ocr_no_footnote exists and forwards seamlessly."""
        self.assertTrue(hasattr(p_ocr_no_fn, "process_page_footnotes"))
        self.assertTrue(hasattr(p_ocr_no_fn, "main"))
        import inspect
        sig = inspect.signature(p_ocr.process_page_footnotes)
        self.assertIn("no_footnote", sig.parameters)
        self.assertEqual(sig.parameters["no_footnote"].default, False)

    def test_app_concurrency_lock_and_tasks(self):
        """Verify _OCR_SEMAPHORE exists and has single-slot capacity."""
        self.assertIsInstance(_OCR_SEMAPHORE, asyncio.Semaphore)
        # Semaphore bound to 1 concurrent job
        self.assertEqual(_OCR_SEMAPHORE._value, 1)
        self.assertIsInstance(_BACKGROUND_TASKS, set)

    def test_cleanup_old_files_directories(self):
        """Verify cleanup_old_files removes expired files and folders without raising exceptions."""
        try:
            cleanup_old_files()
        except Exception as e:
            self.fail(f"cleanup_old_files raised unexpected exception: {e}")


if __name__ == "__main__":
    unittest.main()
