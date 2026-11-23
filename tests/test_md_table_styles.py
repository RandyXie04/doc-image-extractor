# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
import docx
import pypandoc

from src.scripts.md_to_docx import apply_table_styles_to_docx
from src.utils.path_helper import get_template_path


class TestMdTableStyles(unittest.TestCase):
    """
    驗證自動整稿管線中表格製作樣式：
    - 表格樣式設為「表格格線」 (Table Grid)
    - 表格內文字段落無任何特殊樣式設定 (移除 Compact 等 pStyle，套用 Normal 內文)
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_tbl_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_apply_table_styles_with_template(self):
        docx_path = os.path.join(self.temp_dir, "test_with_template.docx")
        template_path = str(get_template_path())

        md_content = """# 測試標題

這是一般本文段落。

| 欄位 A | 欄位 B |
| :--- | ---: |
| 內容 **粗體** | 內容 *斜體* |
| 第一列 | 第二列 |
"""
        pypandoc.convert_text(
            md_content,
            "docx",
            format="gfm",
            outputfile=docx_path,
            extra_args=[f"--reference-doc={template_path}"] if os.path.exists(template_path) else []
        )

        # 執行表格樣式後處理
        apply_table_styles_to_docx(docx_path)

        doc = docx.Document(docx_path)
        self.assertEqual(len(doc.tables), 1)
        tbl = doc.tables[0]

        # 驗證表格樣式為 Table Grid (表格格線)
        if os.path.exists(template_path):
            self.assertEqual(tbl.style.name, "Table Grid")
            self.assertEqual(tbl.style.style_id, "afe")
        else:
            self.assertIn("TableGrid", tbl._tbl.tblPr.xml)

        # 驗證文字段落無特殊樣式設定 (移除 Compact，為預設 Normal，且無殘留 pStyle 標籤)
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    self.assertEqual(p.style.name, "Normal")
                    pPr = p._p.pPr
                    if pPr is not None:
                        # 確保無任何 pStyle (例如 Compact)
                        pStyle = pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pStyle")
                        self.assertIsNone(pStyle)

    def test_apply_table_styles_without_template(self):
        docx_path = os.path.join(self.temp_dir, "test_no_template.docx")

        md_content = """
| 項目 | 數量 |
| --- | --- |
| 蘋果 | 10 |
"""
        pypandoc.convert_text(
            md_content,
            "docx",
            format="gfm",
            outputfile=docx_path
        )

        apply_table_styles_to_docx(docx_path)

        doc = docx.Document(docx_path)
        self.assertEqual(len(doc.tables), 1)
        tbl = doc.tables[0]
        self.assertIn("TableGrid", tbl._tbl.tblPr.xml)

        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    self.assertEqual(p.style.name, "Normal")
                    pPr = p._p.pPr
                    if pPr is not None:
                        pStyle = pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pStyle")
                        self.assertIsNone(pStyle)

    def test_width_normalization_tbl_header_and_cant_split(self):
        """
        Narrow <=72-col Markdown tables (which Pandoc initially emits as w:type='auto')
        must be normalized to 100% page width (5000 pct), with tblHeader on row 0 and cantSplit on all rows.
        """
        from docx.oxml.ns import qn

        docx_path = os.path.join(self.temp_dir, "test_narrow_table.docx")
        template_path = str(get_template_path())

        md_content = """
| 甲 | 乙 |
| --- | --- |
| 1 | 2 |
| 3 | 4 |
"""
        pypandoc.convert_text(
            md_content,
            "docx",
            format="gfm",
            outputfile=docx_path,
            extra_args=[f"--reference-doc={template_path}"] if os.path.exists(template_path) else [],
        )
        apply_table_styles_to_docx(docx_path)

        doc = docx.Document(docx_path)
        self.assertEqual(len(doc.tables), 1)
        tbl = doc.tables[0]
        tblW = tbl._tbl.tblPr.find(qn("w:tblW"))
        self.assertIsNotNone(tblW)
        self.assertEqual(tblW.get(qn("w:w")), "5000")
        self.assertEqual(tblW.get(qn("w:type")), "pct")

        trs = tbl._tbl.findall(qn("w:tr"))
        self.assertEqual(len(trs), 3)
        for r_idx, tr in enumerate(trs):
            trPr = tr.find(qn("w:trPr"))
            self.assertIsNotNone(trPr)
            self.assertIsNotNone(trPr.find(qn("w:cantSplit")))
            if r_idx == 0:
                self.assertIsNotNone(trPr.find(qn("w:tblHeader")))
            else:
                self.assertIsNone(trPr.find(qn("w:tblHeader")))

    def test_coalesce_adjacent_compatible_docx_tables_and_guards(self):
        """
        apply_table_styles_to_docx must coalesce adjacent compatible tables separated by
        empty paragraphs or '续表'/'續表', strip repeated headers, and keep tables separate
        when body prose, column counts, or un-marked differing headers intervene.
        """
        from docx.oxml.ns import qn

        docx_path = os.path.join(self.temp_dir, "test_coalesce.docx")
        doc = docx.Document()

        # Table A + "续表" + Table B (repeated header) -> merge
        t1 = doc.add_table(rows=2, cols=2)
        t1.rows[0].cells[0].text = "序号"
        t1.rows[0].cells[1].text = "药材"
        t1.rows[1].cells[0].text = "1"
        t1.rows[1].cells[1].text = "八角"

        doc.add_paragraph("续表")

        t2 = doc.add_table(rows=2, cols=2)
        t2.rows[0].cells[0].text = "序号"
        t2.rows[0].cells[1].text = "药材"
        t2.rows[1].cells[0].text = "2"
        t2.rows[1].cells[1].text = "扁豆"

        # Empty paragraph + "續表" + Table C (data-only continuation with stale tblHeader on row 0) -> merge & strip stale tblHeader
        doc.add_paragraph("")
        doc.add_paragraph("續表")

        t3 = doc.add_table(rows=1, cols=2)
        t3.rows[0].cells[0].text = "3"
        t3.rows[0].cells[1].text = "百合"
        from docx.oxml import OxmlElement
        t3_trPr = OxmlElement("w:trPr")
        t3_trPr.append(OxmlElement("w:tblHeader"))
        t3._tbl.findall(qn("w:tr"))[0].insert(0, t3_trPr)

        # Real prose separates next table -> MUST NOT merge
        doc.add_paragraph("正文说明段落，不能跨越合并。")

        t4 = doc.add_table(rows=2, cols=2)
        t4.rows[0].cells[0].text = "序号"
        t4.rows[0].cells[1].text = "药材"
        t4.rows[1].cells[0].text = "1"
        t4.rows[1].cells[1].text = "独立表"

        # Different header with no 续表 -> MUST NOT merge
        doc.add_paragraph("")
        t5 = doc.add_table(rows=2, cols=2)
        t5.rows[0].cells[0].text = "项目"
        t5.rows[0].cells[1].text = "数值"
        t5.rows[1].cells[0].text = "A"
        t5.rows[1].cells[1].text = "10"

        # Section break empty paragraph between tables -> MUST NOT merge or remove sectPr
        sec_p = doc.add_paragraph("")
        sec_pPr = OxmlElement("w:pPr")
        sec_pPr.append(OxmlElement("w:sectPr"))
        sec_p._p.insert(0, sec_pPr)

        t6 = doc.add_table(rows=2, cols=2)
        t6.rows[0].cells[0].text = "项目"
        t6.rows[0].cells[1].text = "数值"
        t6.rows[1].cells[0].text = "B"
        t6.rows[1].cells[1].text = "20"

        doc.save(docx_path)
        apply_table_styles_to_docx(docx_path)

        reloaded = docx.Document(docx_path)
        self.assertEqual(len(reloaded.tables), 4)

        merged_tbl = reloaded.tables[0]
        self.assertEqual(len(merged_tbl.rows), 4)  # header + 3 rows
        self.assertEqual([c.text.strip() for c in merged_tbl.rows[0].cells], ["序号", "药材"])
        self.assertEqual([c.text.strip() for c in merged_tbl.rows[1].cells], ["1", "八角"])
        self.assertEqual([c.text.strip() for c in merged_tbl.rows[2].cells], ["2", "扁豆"])
        self.assertEqual([c.text.strip() for c in merged_tbl.rows[3].cells], ["3", "百合"])
        self.assertFalse(any(p.text.strip() in ("续表", "續表") for p in reloaded.paragraphs))
        self.assertGreaterEqual(len(reloaded.sections), 2)

        # Check tblW, tblHeader (ONLY on row 0), cantSplit on coalesced table
        tblW = merged_tbl._tbl.tblPr.find(qn("w:tblW"))
        self.assertEqual(tblW.get(qn("w:w")), "5000")
        self.assertEqual(tblW.get(qn("w:type")), "pct")
        trs = merged_tbl._tbl.findall(qn("w:tr"))
        self.assertIsNotNone(trs[0].find(qn("w:trPr")).find(qn("w:tblHeader")))
        self.assertTrue(all(tr.find(qn("w:trPr")).find(qn("w:tblHeader")) is None for tr in trs[1:]))
        self.assertTrue(all(tr.find(qn("w:trPr")).find(qn("w:cantSplit")) is not None for tr in trs))

    def test_pandoc_mixed_auto_and_pct_tables_coalesce_with_proportional_grid(self):
        """
        When Pandoc emits a <=72-col 'auto' table followed by '续表' and a >72-col 'pct'
        table, apply_table_styles_to_docx coalesces them, normalizes to 5000 pct, and adopts
        the non-uniform proportional tblGrid.
        """
        from docx.oxml.ns import qn

        docx_path = os.path.join(self.temp_dir, "test_mixed_pandoc.docx")
        md_content = """
| 序号 | 名称 | 功效 |
| --- | --- | --- |
| 1 | A | B |

续表

| 序号 | 名称 | 功效 |
| --- | ------------------------ | ------------------------------------------------------------ |
| 2 | 白扁豆花白扁豆花白扁豆花 | 健脾化湿，和中消暑，这是一个超长测试句子超过七十二字元寬度用來觸發Pandoc比例計算機制 |
"""
        pypandoc.convert_text(
            md_content,
            "docx",
            format="markdown-implicit_figures-subscript+raw_html+tex_math_dollars",
            outputfile=docx_path,
        )
        apply_table_styles_to_docx(docx_path)

        doc = docx.Document(docx_path)
        self.assertEqual(len(doc.tables), 1)
        tbl = doc.tables[0]
        self.assertEqual(len(tbl.rows), 3)
        tblW = tbl._tbl.tblPr.find(qn("w:tblW"))
        self.assertEqual(tblW.get(qn("w:w")), "5000")
        self.assertEqual(tblW.get(qn("w:type")), "pct")
        grid_ws = [int(g.get(qn("w:w"))) for g in tbl._tbl.tblGrid.findall(qn("w:gridCol"))]
        self.assertGreater(len(set(grid_ws)), 1)


if __name__ == "__main__":
    unittest.main()
