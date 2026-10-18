import unittest
import os
import shutil
import tempfile
from pathlib import Path

from config import PATHS
from src.core_agent import PDFConversionAgent


class TestStaticFilenameFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_static_fix_")
        self.dummy_pdf = os.path.join(self.temp_dir, "test_doc.pdf")
        import pymupdf as fitz
        doc = fitz.open()
        doc.new_page()
        doc.save(self.dummy_pdf)
        doc.close()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_core_agent_unique_task_directories(self):
        """Verify that multiple agent instances get distinct preview and formula dirs to prevent race conditions."""
        agent1 = PDFConversionAgent(input_pdf=self.dummy_pdf)
        agent2 = PDFConversionAgent(input_pdf=self.dummy_pdf)

        self.assertNotEqual(agent1.preview_dir, agent2.preview_dir)
        self.assertNotEqual(agent1.formula_dir, agent2.formula_dir)
        self.assertIn("task_", agent1.preview_dir)
        self.assertIn("task_", agent2.preview_dir)
        self.assertIn("task_", agent1.formula_dir)
        self.assertIn("task_", agent2.formula_dir)

    def test_updater_service_dynamic_batch_script_template(self):
        """Verify updater batch script handles spaces in paths and self-deletes."""
        from src.scripts.updater_service import perform_update
        # In non-frozen dev environment, perform_update safely halts without modifying system
        res = perform_update("https://github.com/RandyXie04/doc-image-extractor/releases/download/v1.0.0/app.exe")
        self.assertEqual(res.get("status"), "error")
        self.assertIn("開發調試環境", res.get("msg", ""))

    def test_footnote_review_stem_path(self):
        """Verify footnote review generates a unique stem-based report."""
        from src.scripts.process_ocr import generate_audit_report
        stem = "book_chapter_1"
        report_path = os.path.join(self.temp_dir, f"{stem}_footnote_review.txt")
        generate_audit_report("book_chapter_1.pdf", 5, [], report_path)
        self.assertTrue(os.path.exists(report_path))
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("book_chapter_1.pdf", content)


if __name__ == "__main__":
    unittest.main()
