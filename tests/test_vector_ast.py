# -*- coding: utf-8 -*-
"""
Phase 2B Test Suite: Vector AST & Structured Paragraph Extraction
==================================================================
Tests for extract_book_vector_ast, BookAST, SectionAdapter, and paragraph geometry.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
import fitz

# Attempt import of Phase 2B components
try:
    from src.scripts.book_layout_extractor import extract_book_vector_ast, BookAST, SectionAdapter
except ImportError:
    try:
        from src.pod_studio.section_ast import BookAST, SectionAdapter
        from src.scripts.book_layout_extractor import extract_book_vector_ast
    except ImportError:
        extract_book_vector_ast = None
        BookAST = None
        SectionAdapter = None

from src.scripts.book_layout_extractor import process_book_vector_pdf
from src.pod_studio.section_ast import SectionUnit, ParagraphUnit
from src.pod_studio.blueprint_schema import BookBlueprint
from src.pod_studio.propagation_engine import PropagationEngine
from src.pod_studio.pod_validator import PodValidator
from src.pod_studio.visual_fallback_repair import render_page_crop


class TestVectorASTExtraction(unittest.TestCase):
    """Test suite for Phase 2B structured vector AST extraction."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_ast_"))
        self.sample_pdf = self.test_dir / "sample_book.pdf"
        self._generate_sample_pdf(self.sample_pdf)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _generate_sample_pdf(self, path: Path):
        """Generates a 3-page synthetic PDF with chapters, styled paragraphs, and footnotes."""
        doc = fitz.open()

        # Page 1: Chapter 1 + body paragraphs
        p1 = doc.new_page(width=500, height=700)
        p1.insert_text((60, 60), "第一章 數位出版技術", fontsize=16, fontname="china-ss")
        p1.insert_text(
            (60, 110),
            "這是第一章的第一段標準內文，用於檢驗段落邊界框與字體資訊。",
            fontsize=10.5,
            fontname="china-ss",
        )
        p1.insert_text(
            (60, 140),
            "這是第二段落，包含特殊排版與測試用的第二行文字。",
            fontsize=10.5,
            fontname="china-ss",
        )

        # Page 2: Chapter 2 + mixed formatting
        p2 = doc.new_page(width=500, height=700)
        p2.insert_text((60, 60), "第二章 版面幾何與語意", fontsize=16, fontname="china-ss")
        p2.insert_text(
            (60, 110),
            "第二章的開頭段落，探討結構化抽象語法樹的核心價值。",
            fontsize=10.5,
            fontname="china-ss",
        )
        p2.insert_text(
            (60, 150),
            "此段落特別驗證段落是否能正確歸屬至第二章節。",
            fontsize=10.5,
            fontname="china-ss",
        )

        # Page 3: Subheading and short block
        p3 = doc.new_page(width=500, height=700)
        p3.insert_text((60, 60), "2.1 幾何座標精確性", fontsize=13, fontname="china-ss")
        p3.insert_text(
            (60, 100),
            "終章結論與摘要說明。",
            fontsize=10.5,
            fontname="china-ss",
        )

        doc.save(str(path))
        doc.close()

    def test_01_api_exists_and_returns_book_ast(self):
        """Test that extract_book_vector_ast is importable and returns BookAST instance."""
        self.assertIsNotNone(extract_book_vector_ast, "extract_book_vector_ast must be implemented")
        self.assertIsNotNone(BookAST, "BookAST class must be defined")

        book_ast = extract_book_vector_ast(self.sample_pdf, ai_kaiti=False)
        self.assertIsInstance(book_ast, BookAST)
        self.assertIsInstance(book_ast.sections, list)
        self.assertGreater(len(book_ast.sections), 0)
        self.assertEqual(book_ast.total_pages, 3)
        self.assertEqual(book_ast.pdf_name, "sample_book.pdf")

    def test_02_paragraph_geometry_and_font_preservation(self):
        """Test that every ParagraphUnit retains valid 1-based page_num, bbox, and font metadata."""
        book_ast = extract_book_vector_ast(self.sample_pdf, ai_kaiti=False)

        all_paras = [p for sec in book_ast.sections for p in sec.paragraphs]
        self.assertGreater(len(all_paras), 0, "AST must contain paragraphs")

        for p in all_paras:
            # 1. 1-based page_num
            self.assertGreaterEqual(p.page_num, 1, f"Paragraph {p.para_id} page_num must be >= 1, got {p.page_num}")
            self.assertLessEqual(p.page_num, 3, f"Paragraph {p.para_id} page_num must be <= 3")

            # 2. Valid source-derived bbox [x0, y0, x1, y1]
            self.assertIsNotNone(p.bbox, f"Paragraph {p.para_id} bbox cannot be None")
            self.assertEqual(len(p.bbox), 4, f"Paragraph {p.para_id} bbox must be 4 floats")
            x0, y0, x1, y1 = p.bbox
            self.assertLess(x0, x1, f"Paragraph {p.para_id} invalid width: x0={x0}, x1={x1}")
            self.assertLess(y0, y1, f"Paragraph {p.para_id} invalid height: y0={y0}, y1={y1}")

            # Must not be a dummy page-wide box
            self.assertGreater(x0, 0.0, "x0 should not be 0.0 for indented/padded text")
            self.assertLess(x1, 500.0, "x1 should be within page bounds")

            # 3. Font metadata
            self.assertTrue(len(p.font_name) > 0, f"Paragraph {p.para_id} font_name must not be empty")
            self.assertGreater(p.font_size, 0.0, f"Paragraph {p.para_id} font_size must be positive")

    def test_03_deterministic_para_id_and_source_stability(self):
        """Test that running extraction multiple times yields identical section and para IDs."""
        ast1 = extract_book_vector_ast(self.sample_pdf, ai_kaiti=False)
        ast2 = extract_book_vector_ast(self.sample_pdf, ai_kaiti=False)

        sec_ids1 = [s.section_id for s in ast1.sections]
        sec_ids2 = [s.section_id for s in ast2.sections]
        self.assertEqual(sec_ids1, sec_ids2, "Section IDs must be deterministic")

        para_ids1 = [p.para_id for s in ast1.sections for p in s.paragraphs]
        para_ids2 = [p.para_id for s in ast2.sections for p in s.paragraphs]
        self.assertEqual(para_ids1, para_ids2, "Paragraph IDs must be deterministic")

    def test_04_zero_disk_io_and_dir_creation(self):
        """Test that extract_book_vector_ast performs ZERO file writes and ZERO directory creation."""
        import builtins
        file_writes = []
        orig_open = builtins.open

        def spy_open(file, mode='r', *args, **kwargs):
            if any(m in mode for m in ('w', 'a', 'x', '+')):
                file_writes.append((str(file), mode))
            return orig_open(file, mode, *args, **kwargs)

        dir_creations = []
        orig_makedirs = os.makedirs

        def spy_makedirs(name, *args, **kwargs):
            dir_creations.append(str(name))
            return orig_makedirs(name, *args, **kwargs)

        builtins.open = spy_open
        os.makedirs = spy_makedirs
        try:
            _ = extract_book_vector_ast(self.sample_pdf, ai_kaiti=False)
        finally:
            builtins.open = orig_open
            os.makedirs = orig_makedirs

        self.assertEqual(len(file_writes), 0, f"Expected 0 file writes, got: {file_writes}")
        self.assertEqual(len(dir_creations), 0, f"Expected 0 dir creations, got: {dir_creations}")

    def test_05_pdf_handle_released_on_success_and_failure(self):
        """Test that fitz.Document handle is closed properly on success and when an error occurs."""
        # 1. Success path
        _ = extract_book_vector_ast(self.sample_pdf, ai_kaiti=False)
        try:
            # On Windows, open handles prevent file removal
            self.sample_pdf.unlink()
        except PermissionError:
            self.fail("PDF file remained locked after extract_book_vector_ast success")

        # 2. Failure path (corrupt or missing file)
        with self.assertRaises(FileNotFoundError):
            extract_book_vector_ast(self.test_dir / "nonexistent.pdf")

    def test_06_section_adapter_consumer_compatibility(self):
        """Test that SectionAdapter.to_sections yields List[SectionUnit] consumable by POD modules."""
        self.assertIsNotNone(SectionAdapter, "SectionAdapter must be defined")
        # Recreate sample pdf
        self._generate_sample_pdf(self.sample_pdf)
        book_ast = extract_book_vector_ast(self.sample_pdf, ai_kaiti=False)

        sections = SectionAdapter.to_sections(book_ast)
        self.assertIsInstance(sections, list)
        self.assertTrue(all(isinstance(s, SectionUnit) for s in sections))

        # Consumer 1: PropagationEngine
        bp = BookBlueprint(book_name="sample")
        engine = PropagationEngine(bp)
        processed_sections = engine.process_all(sections)
        self.assertEqual(len(processed_sections), len(sections))

        # Consumer 2: PodValidator
        validator = PodValidator(bp)
        report = validator.validate_all(sections)
        self.assertIsNotNone(report)

    def test_07_visual_fallback_crop_integration(self):
        """Test that ParagraphUnit from BookAST works directly with render_page_crop."""
        self._generate_sample_pdf(self.sample_pdf)
        book_ast = extract_book_vector_ast(self.sample_pdf, ai_kaiti=False)

        paras = [p for s in book_ast.sections for p in s.paragraphs if p.bbox]
        self.assertGreater(len(paras), 0)

        target_para = paras[0]
        # Should render without raising IndexError
        png_bytes = render_page_crop(
            pdf_path=self.sample_pdf,
            page_num=target_para.page_num,
            bbox=target_para.bbox,
        )
        self.assertIsInstance(png_bytes, bytes)
        self.assertGreater(len(png_bytes), 100)

    def test_08_legacy_golden_baselines_unaffected(self):
        """Verify that legacy process_book_vector_pdf continues to produce exact Golden Baseline SHA-256."""
        # Baseline 1: synthetic_book
        synth_pdf = self.test_dir / "synth.pdf"
        doc = fitz.open()
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((260, 80), "目 錄", fontsize=16, fontname="china-ss")
        p1.insert_text((70, 130), "導論 .................................... 2", fontsize=11, fontname="china-ss")
        p1.insert_text((70, 160), "文化與自然的交織 ........................ 2", fontsize=11, fontname="china-ss")
        p2 = doc.new_page(width=595, height=842)
        p2.insert_text((70, 100), "導論", fontsize=14, fontname="china-ss")
        p2.insert_text((70, 135), "這是一段標準的書籍內文，用來建立全書的正文基準字級與左邊界座標參考值，確保統計準確。", fontsize=10.5, fontname="china-ss")
        p2.insert_text((70, 152), "這行在中間就結束了。", fontsize=10.5, fontname="china-ss")
        p2.insert_text((70, 195), "文化與自然的交織", fontsize=12, fontname="china-ss")
        p2.insert_text((70, 225), "第二段內文緊接在無編號小標之後，且故意不設首行縮排，檢驗系統是否能將標題與內文切開。", fontsize=10.5, fontname="china-ss")
        doc.save(str(synth_pdf))
        doc.close()

        out1 = self.test_dir / "out1"
        md1_path, _ = process_book_vector_pdf(str(synth_pdf), str(out1), ai_kaiti=False)
        import hashlib
        h1 = hashlib.sha256(Path(md1_path).read_bytes()).hexdigest()
        self.assertEqual(h1, "a08740086d3d6d182dbf48d3a2a32f48fa8ea648a730c65edd6cfcd603ec6cb3")


if __name__ == "__main__":
    unittest.main()
