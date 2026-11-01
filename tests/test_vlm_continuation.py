# -*- coding: utf-8 -*-
"""
Unit and integration tests for SecureVLMContinuationEngine
"""

import sys
import json
import asyncio
import unittest
import tempfile
from pathlib import Path
import docx
import fitz

# Ensure root directory is on sys.path
root_dir = Path(__file__).parent.parent.resolve()
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.pod_studio.vlm_continuation_engine import (
    SecureVLMContinuationEngine,
    ContinuationResult,
    VisualExemplarPair,
)
from src.pod_studio.section_ast import SectionUnit, ParagraphUnit, SectionAST


class TestVLMContinuation(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_engine_initialization(self):
        """驗證引擎初始化與工作區隔離建立"""
        t1 = self.tmp_path / "t1"
        engine = SecureVLMContinuationEngine(workspace_base=t1, max_concurrency=3)
        self.assertTrue(engine.workspace_base.exists())
        self.assertEqual(engine.max_concurrency, 3)
        self.assertEqual(engine.dpi, 150)

    def test_exemplar_extraction_and_alignment(self):
        """驗證從人工精修 DOCX 與生稿 AST 比對定位切分點"""
        t2 = self.tmp_path / "t2"
        engine = SecureVLMContinuationEngine(workspace_base=t2)

        # 1. 建立測試 PDF
        pdf_path = t2 / "test_book.pdf"
        t2.mkdir(parents=True, exist_ok=True)
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((50, 50), "第一章 數位出版緒論\n這是第一章內文，由人工精修。")
        p2 = doc.new_page()
        p2.insert_text((50, 50), "第二章 版面自動化排版\n這是第二章待接續內文。")
        doc.save(str(pdf_path))
        doc.close()

        # 2. 建立生稿 AST
        sec1 = SectionUnit(
            section_id="sec_001",
            title="第一章 數位出版緒論",
            level=1,
            paragraphs=[
                ParagraphUnit(para_id="p1", raw_text="這是第一章內文，由人工精修。", page_num=1)
            ]
        )
        sec2 = SectionUnit(
            section_id="sec_002",
            title="第二章 版面自動化排版",
            level=1,
            paragraphs=[
                ParagraphUnit(para_id="p2", raw_text="這是第二章待接續內文。", page_num=2)
            ]
        )
        raw_sections = [sec1, sec2]
        ast_path = t2 / "Book_raw_ast.json"
        SectionAST.dump_book_ast_json(raw_sections, ast_path)

        # 3. 建立前 10% 人工精修 DOCX (僅包含第一章)
        seed_docx = t2 / "Book_seed.docx"
        doc_seed = docx.Document()
        doc_seed.add_heading("第一章 數位出版緒論", level=1)
        doc_seed.add_paragraph("【導讀】這是第一章內文，由人工精修。")
        doc_seed.save(str(seed_docx))

        # 4. 執行示範萃取與切分比對
        exemplars, seed_count = engine.extract_seed_exemplars_sync(
            pdf_path=pdf_path,
            raw_sections=raw_sections,
            seed_docx_path=seed_docx,
        )

        self.assertEqual(seed_count, 1)
        self.assertEqual(len(exemplars), 1)
        self.assertEqual(exemplars[0].section_title, "第一章 數位出版緒論")
        self.assertGreater(len(exemplars[0].page_image_bytes), 0)

    def test_execute_continuation_flow(self):
        """驗證非同步完整接續流程與 DOCX/MD/JSON 產出"""
        t3 = self.tmp_path / "t3"
        engine = SecureVLMContinuationEngine(workspace_base=t3)

        pdf_path = t3 / "test_book.pdf"
        t3.mkdir(parents=True, exist_ok=True)
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((50, 50), "第1節 緒論")
        p2 = doc.new_page()
        p2.insert_text((50, 50), "第2節 排版原理")
        doc.save(str(pdf_path))
        doc.close()

        sec1 = SectionUnit(
            section_id="sec_001",
            title="第1節 緒論",
            level=2,
            paragraphs=[ParagraphUnit(para_id="p1", raw_text="緒論內容", page_num=1)]
        )
        sec2 = SectionUnit(
            section_id="sec_002",
            title="第2節 排版原理",
            level=2,
            paragraphs=[ParagraphUnit(para_id="p2", raw_text="排版原理與自動化規格", page_num=2)]
        )
        ast_path = t3 / "Book_raw_ast.json"
        SectionAST.dump_book_ast_json([sec1, sec2], ast_path)

        seed_docx = t3 / "Book_seed.docx"
        doc_seed = docx.Document()
        doc_seed.add_heading("第1節 緒論", level=2)
        doc_seed.add_paragraph("緒論內容")
        doc_seed.save(str(seed_docx))

        session_workspace = t3 / "test_session_123"

        result = asyncio.run(
            engine.execute_continuation(
                pdf_path=pdf_path,
                raw_ast_path=ast_path,
                seed_docx_path=seed_docx,
                target_session_dir=session_workspace,
                model_name="mock_test_model",
            )
        )

        self.assertEqual(result.session_id, "test_session_123")
        self.assertEqual(result.total_sections, 2)
        self.assertEqual(result.seed_sections_count, 1)
        self.assertEqual(result.continued_sections_count, 1)
        self.assertTrue(Path(result.completed_docx_path).exists())
        self.assertTrue(Path(result.completed_md_path).exists())
        self.assertTrue((session_workspace / "vlm_audit_report.json").exists())


if __name__ == "__main__":
    unittest.main()
