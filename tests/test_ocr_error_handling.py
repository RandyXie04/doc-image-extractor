# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
import json


class TestOcrErrorHandlingAndLayoutModel(unittest.TestCase):
    def test_surya_layout_model_import_source(self):
        """確認 process_ocr.py 從 surya.model.layout.model 正確載入版面分析模型，而非 detection.model"""
        script_path = Path(__file__).parent.parent / "src" / "scripts" / "process_ocr.py"
        content = script_path.read_text(encoding="utf-8")
        
        # 必須從 layout.model 匯入，不能從 detection.model 匯入
        self.assertIn("from surya.model.layout.model import load_model as load_layout_model", content)
        self.assertNotIn("from surya.model.detection.model import load_model as load_layout_model", content)

    def test_pdf_engine_dispatcher_verifies_target_file_existence(self):
        """確認 pdf_engine_dispatcher.py 在 OCR 結束後嚴格檢查產出檔案是否存在，防止靜默吞沒例外"""
        script_path = Path(__file__).parent.parent / "src" / "scripts" / "pdf_engine_dispatcher.py"
        content = script_path.read_text(encoding="utf-8")
        
        self.assertIn("if not os.path.exists(target_out):", content)
        self.assertIn("raise RuntimeError(", content)

    def test_app_py_verifies_md_file_before_marking_completed(self):
        """確認 app.py 在將任務標記為 completed 之前，必須檢驗 md_file 與 docx_file 之存在性"""
        app_path = Path(__file__).parent.parent / "src" / "web" / "app.py"
        content = app_path.read_text(encoding="utf-8")
        
        self.assertIn("if not md_file.exists():", content)
        self.assertIn('ocr_progress_dict[stem]["status"] = "failed"', content)
        self.assertIn("if md_proc.returncode != 0 or not docx_file.exists():", content)

    def test_ocr_pipeline_frontend_poll_status_guard(self):
        """確認 ocr_pipeline.html 僅在 status === 'completed' 時觸發完成，且在 failed 時呈現 onFailure 錯誤訊息"""
        html_path = Path(__file__).parent.parent / "src" / "web" / "static" / "ocr_pipeline.html"
        content = html_path.read_text(encoding="utf-8")
        
        self.assertIn("prog.status === 'failed'", content)
        self.assertIn("onFailure(", content)
        self.assertNotIn("prog.status === 'completed' || prog.progress === 100", content)


if __name__ == "__main__":
    unittest.main()
