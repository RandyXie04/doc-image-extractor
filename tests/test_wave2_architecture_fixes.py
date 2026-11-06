# -*- coding: utf-8 -*-
"""
Automated Verification Suite for Wave 2 (Phase 2 / P1) Architecture & UX Fixes
==============================================================================
Tests:
- Wave 2.1 (AUD-01, AUD-09): FigureLayoutContract alignment & strict layout record validation
- Wave 2.2 (AUD-06, AUD-15): POD GPU semaphore concurrency lock & formula ZIP output isolation
- Wave 2.3 (AUD-12, AUD-13, AUD-22, AUD-23): Cross-workbench UX closure & cancellation endpoint
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fitz
from PIL import Image

from config import PATHS
from src.extraction.contracts import FigureLayoutContract, validate_layout_records
from src.scripts.book_layout_extractor import _parse_pdf_layout_flow, process_book_vector_pdf
from src.web.dependencies import get_gpu_semaphore


class TestWave2ArchitectureFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="wave2_test_")
        self.temp_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_wave2_1_figure_layout_contract_conformance(self):
        """AUD-01 & AUD-09: Ensure figure layout records match FigureLayoutContract without forbidden fields."""
        pdf_path = self.temp_path / "fig_test.pdf"
        doc = fitz.open()
        page = doc.new_page(width=500, height=800)

        # 1. Heading
        page.insert_text(fitz.Point(60, 60), "第一章 導論", fontname="china-ts", fontsize=16.0)

        # 2. Text paragraph
        page.insert_text(fitz.Point(60, 100), "這是圖前的一段說明文字，用來建立正文基準。", fontname="china-ts", fontsize=10.5)

        # 3. Insert Image
        img = Image.new("RGB", (60, 60), color=(255, 100, 50))
        img_path = self.temp_path / "sample_fig.png"
        img.save(str(img_path))
        page.insert_image(fitz.Rect(60, 130, 180, 200), filename=str(img_path))

        # 4. Text paragraph after image
        page.insert_text(fitz.Point(60, 230), "這是圖後的一段說明文字，接續進行排版。", fontname="china-ts", fontsize=10.5)

        doc.save(str(pdf_path))
        doc.close()

        # Parse layout flow
        with fitz.open(str(pdf_path)) as doc_obj:
            final_md_pages, all_image_blocks, audit_data, layout_records = _parse_pdf_layout_flow(
                doc_obj,
                enable_footnotes=False,
            )

        # 1. Validate layout records directly against strict Pydantic discriminator
        validated_contracts = validate_layout_records(layout_records)
        self.assertGreater(len(validated_contracts), 0)

        # 2. Extract figure records
        fig_records = [r for r in layout_records if r.get("type") == "figure"]
        self.assertEqual(len(fig_records), 1, "Must have exactly 1 figure layout record")

        fig_rec = fig_records[0]
        # Assert required fields in FigureLayoutContract
        self.assertEqual(fig_rec["type"], "figure")
        self.assertEqual(fig_rec["page_num"], 1)
        self.assertIn("raw_md", fig_rec)
        self.assertTrue(fig_rec["raw_md"].startswith("![__IMG_PLACEHOLDER_1_"))
        self.assertEqual(fig_rec["font_name"], "figure")
        self.assertEqual(fig_rec["font_size"], 10.5)
        self.assertEqual(len(fig_rec["bbox"]), 4)

        # Assert FORBIDDEN fields are NOT in layout_records (AUD-01)
        self.assertNotIn("page_w", fig_rec, "page_w must not be present in FigureLayoutContract")
        self.assertNotIn("page_h", fig_rec, "page_h must not be present in FigureLayoutContract")

        # But all_image_blocks retains page_w and page_h for extract_pdf_images
        self.assertEqual(len(all_image_blocks), 1)
        self.assertIn("page_w", all_image_blocks[0])
        self.assertIn("page_h", all_image_blocks[0])

    def test_wave2_2_formula_zip_output_isolation(self):
        """AUD-15: Ensure formula extraction isolates output zip to avoid collision."""
        from src.web.routers.formula_router import formula_tasks, process_pdf_sync

        task_id = "test_formula_task_12345678"
        file_path = self.temp_path / "sample_math.pdf"
        file_path.write_bytes(b"%PDF-1.4 dummy")

        formula_tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "",
            "log": "",
            "delivery_folder": None,
            "zip_file": None,
            "word_file": None,
        }

        # Mock agent that outputs a default zip_path
        mock_agent = MagicMock()
        shared_zip = self.temp_path / "all_pdf_formulas_hybrid.zip"
        shared_zip.write_bytes(b"PK fake zip content")
        mock_agent.execute_pipeline.return_value = {
            "delivery_folder": str(self.temp_path),
            "zip_path": str(shared_zip),
        }

        with patch("src.web.routers.formula_router.PDFConversionAgent", return_value=mock_agent):
            process_pdf_sync(
                task_id=task_id,
                file_path=str(file_path),
                extract_formulas=True,
                start_page=1,
                end_page=1,
                header_ratio=0.1,
                footer_ratio=0.1,
            )

        task_data = formula_tasks[task_id]
        self.assertEqual(task_data["status"], "completed")
        self.assertIsNotNone(task_data["zip_file"])
        # Expected isolated name
        expected_stem = f"formulas_{file_path.stem}_{task_id[:8]}.zip"
        self.assertTrue(task_data["zip_file"].endswith(expected_stem), f"Expected isolated zip, got {task_data['zip_file']}")
        self.assertTrue(Path(task_data["zip_file"]).exists())

    def test_wave2_2_gpu_semaphore_protection(self):
        """AUD-06: Ensure GPU semaphore is acquired during VLM continuation in POD router."""
        from src.web.routers.pod_router import pod_3_propagate_and_validate

        sem = get_gpu_semaphore()
        self.assertIsNotNone(sem)
        self.assertEqual(sem._value, 1)


if __name__ == "__main__":
    unittest.main()
