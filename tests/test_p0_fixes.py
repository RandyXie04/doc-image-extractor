import unittest
from pathlib import Path
import re
from src.scripts.book_layout_extractor import _replace_fn_markers_in_text
from src.founder_tools.fix_founder_fonts import clean_founder_text, _repair_paragraph_runs
from src.scripts.process_ocr import _clean_hallucinations


class TestP0Fixes(unittest.TestCase):
    def test_footnote_weak_marker_boundary_protection(self):
        """Verify that weak markers like '1.' do NOT replace decimals like '31.5%' or numbers."""
        page_footnotes = [
            {"id": 1, "marker": "1.", "matched": False},
            {"id": 2, "marker": "(2)", "matched": False},
            {"id": 3, "marker": "①", "matched": False},
        ]
        
        # Text containing decimals, numbers, and an isolated footnote marker
        text = "本季度成長率為 31.5% ，版本號為 v1.2 ，詳細請見 1. 說明。另外參見 (2) 與 ① 註釋。"
        result = _replace_fn_markers_in_text(text, page_footnotes, page_num=1)
        
        # 31.5% must remain intact
        self.assertIn("31.5%", result)
        # v1.2 must remain intact
        self.assertIn("v1.2", result)
        # Isolated '1.' should be replaced
        self.assertIn("[^p1_1]", result)
        # Isolated '(2)' should be replaced
        self.assertIn("[^p1_2]", result)
        # Strong marker '①' should be replaced
        self.assertIn("[^p1_3]", result)
        self.assertTrue(page_footnotes[0]["matched"])
        self.assertTrue(page_footnotes[1]["matched"])
        self.assertTrue(page_footnotes[2]["matched"])

    def test_bracket_and_variant_footnote_recognition(self):
        """Verify that square brackets [1], fullwidth ［2］, tortoise 〔3〕 markers are matched correctly."""
        page_footnotes = [
            {"id": 1, "marker": "[1]", "matched": False},
            {"id": 2, "marker": "[2]", "matched": False},
            {"id": 3, "marker": "［3］", "matched": False},
            {"id": 4, "marker": "〔4〕", "matched": False},
            {"id": 5, "marker": "[5]", "matched": False},
            {"id": 6, "marker": "[6]", "matched": False},
        ]
        sample_text = (
            '《经》云：“问其病，知其处，名曰工[1]。”又曰：“闭户塞牖，数问其情[2]”。'
            '实则谵语［3］，虚则郑声〔4〕。欲言手按腹者，腹中满痛[5]。'
            '此申[6]脉为生气之源。'
        )
        result = _replace_fn_markers_in_text(sample_text, page_footnotes, page_num=1)
        self.assertIn("名曰工[^p1_1]。”", result)
        self.assertIn("数问其情[^p1_2]”。", result)
        self.assertIn("实则谵语[^p1_3]，", result)
        self.assertIn("虚则郑声[^p1_4]。", result)
        self.assertIn("腹中满痛[^p1_5]。", result)
        self.assertIn("此申[^p1_6]脉为生气之源。", result)
        for fn in page_footnotes:
            self.assertTrue(fn["matched"], f"Footnote ID {fn['id']} failed to match")

    def test_hallucination_cleaning_safety(self):
        """Verify hallucination cleaning removes repeats without regex backtracking."""
        normal_text = "這是一段正常的中文文本，包含各種不同詞彙與標點符號。"
        self.assertEqual(_clean_hallucinations(normal_text), normal_text)

        # Repetitive hallucination
        hallucinated_text = "測試重複" * 20
        self.assertEqual(_clean_hallucinations(hallucinated_text), "")

    def test_path_traversal_is_relative_to_security(self):
        """Verify that is_relative_to blocks prefix bypass (e.g. data_evil)."""
        base_dir = Path("C:/project/data").resolve()
        safe_child = Path("C:/project/data/03_output/result.docx").resolve()
        evil_sibling = Path("C:/project/data_evil/secret.txt").resolve()

        self.assertTrue(safe_child.is_relative_to(base_dir))
        self.assertFalse(evil_sibling.is_relative_to(base_dir))
        # startswith would have incorrectly matched!
        self.assertTrue(str(evil_sibling).startswith(str(base_dir)))


if __name__ == "__main__":
    unittest.main()
