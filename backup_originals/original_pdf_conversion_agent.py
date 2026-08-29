import os
import fitz  # PyMuPDF
from pdf2docx import Converter
from tqdm import tqdm  # 用於顯示進度條

class PDFConversionAgent:
    """
    PDF 轉換代理物件：負責將包含頁眉/頁尾的 PDF 檔案，
    透過動態邊界偵測與自動裁切，轉換為乾淨的 Word (Docx) 檔案。
    
    Attributes:
        input_pdf (str): 來源 PDF 檔案路徑。
        output_docx (str): 輸出的 Word 檔案路徑。
        preview_dir (str): 存放視覺化對照圖片的資料夾名稱。
        temp_cropped_pdf (str): 過程中的暫存裁切 PDF 檔名。
    """

    def __init__(self, input_pdf: str, output_docx: str, preview_dir: str = "previews"):
        self.input_pdf = input_pdf
        self.output_docx = output_docx
        self.preview_dir = preview_dir
        self.temp_cropped_pdf = "temp_cropped_optimized.pdf"
        os.makedirs(preview_dir, exist_ok=True)

    def plan_crop_parameters(self) -> dict:
        """
        讀取 PDF 屬性，規劃初始裁切參數與抽樣策略。
        
        Returns:
            dict: 包含頁面尺寸、邊界閾值與抽樣頁碼列表的設定字典。
        """
        doc = fitz.open(self.input_pdf)
        first_page = doc[0]
        rect = first_page.rect
        doc.close()

        return {
            "page_width": rect.width,
            "page_height": rect.height,
            "header_threshold": rect.height * 0.08, # 預設頂部 8% 為頁眉區
            "footer_threshold": rect.height * 0.92, # 預設底部 8% 為頁尾區
            "sample_pages": [0, 1, -1]              # 抽樣首頁、第二頁與最後一頁
        }

    def _detect_page_boundaries(self, page: fitz.Page, plan: dict):
        """
        [核心] 傳入單一頁面，分析該頁的文字區塊，回傳動態計算的專屬裁切邊界。
        
        Args:
            page (fitz.Page): 欲分析的 PDF 頁面物件。
            plan (dict): 由 plan_crop_parameters 產生的設定。
            
        Returns:
            tuple: (頂部裁切Y座標, 底部裁切Y座標, 偵測到的頁眉文字, 偵測到的頁尾文字)
        """
        rect = page.rect
        blocks = page.get_text("blocks")

        detected_header_y = 0.0
        detected_footer_y = rect.height
        header_text = "(無)"
        footer_text = "(無)"

        for b in blocks:
            x0, y0, x1, y1, text, *_ = b
            clean_text = text.strip()
            if not clean_text:
                continue

            # 判斷是否為頁眉 (在頂部閾值內，且字數短)
            if y1 <= plan["header_threshold"] and len(clean_text) < 30:
                detected_header_y = max(detected_header_y, y1)
                header_text = clean_text.replace("\n", " ")
            # 判斷是否為頁尾 (在底部閾值內，且為純數字或字數短)
            elif y0 >= plan["footer_threshold"] and (clean_text.isdigit() or len(clean_text) < 15):
                detected_footer_y = min(detected_footer_y, y0)
                footer_text = clean_text.replace("\n", " ")

        # 加上 5pt 安全緩衝，避免裁切太貼近文字
        final_top = detected_header_y + 5 if detected_header_y > 0 else 0.0
        final_bottom = detected_footer_y - 5 if detected_footer_y < rect.height else rect.height

        return final_top, final_bottom, header_text, footer_text

    def generate_verification_report(self, plan: dict):
        """
        針對抽樣頁面產生視覺化對照預覽圖，並評估裁切風險。
        
        Returns:
            tuple: (報告數據列表, 是否觸發危險閾值警告)
        """
        doc = fitz.open(self.input_pdf)
        report_data = []
        has_any_warning = False
        total_pages = len(doc)

        for page_idx in plan["sample_pages"]:
            actual_idx = total_pages + page_idx if page_idx < 0 else page_idx
            
            if actual_idx >= total_pages or actual_idx < 0:
                continue
            
            page = doc[actual_idx]
            rect = page.rect
            
            final_top, final_bottom, header_text, footer_text = self._detect_page_boundaries(page, plan)

            # 繪製紅線預覽圖並輸出
            crop_rect = fitz.Rect(0, final_top, rect.width, final_bottom)
            page.draw_rect(crop_rect, color=(1, 0, 0), width=2)
            preview_path = os.path.join(self.preview_dir, f"preview_page_{actual_idx + 1}.png")
            pix = page.get_pixmap(dpi=150)
            pix.save(preview_path)

            # 異常邊界偵測：若裁切掉超過 15% 頁面，標記警告
            is_edge_case = (final_top / rect.height > 0.15) or ((rect.height - final_bottom) / rect.height > 0.15)
            if is_edge_case:
                has_any_warning = True

            report_data.append({
                "page": actual_idx + 1,
                "header_detected": header_text,
                "header_cut_y": f"{final_top:.2f} pt",
                "footer_detected": footer_text,
                "footer_cut_y": f"{final_bottom:.2f} pt",
                "preview_img": preview_path,
                "status": "WARN" if is_edge_case else "PASS"
            })

        doc.close()
        return report_data, has_any_warning

    def request_human_approval(self, reason: str, report: list) -> str:
        """
        當偵測到極端裁切時，暫停程式並印出報告，要求使用者決定處置方式。
        """
        print("\n" + "=" * 50)
        print("[ALERT: REQUIRES HUMAN APPROVAL]")
        print(f"- 觸發原因：{reason}")
        print("- 驗證對照報告摘要 (每頁動態裁切)：")
        for item in report:
            print(f"  * 頁碼 {item['page']} | 頁眉: [{item['header_detected']}] (頂部: {item['header_cut_y']})")
            print(f"    頁尾: [{item['footer_detected']}] (底部: {item['footer_cut_y']})")
            print(f"    判定: {item['status']}")
        print("- 建議選項：")
        print("  [1] 確認動態數值無誤，強制繼續執行轉檔 (維持每頁自適應)")
        print("  [2] 手動輸入自訂裁切數值 (將強制套用至所有頁面，取消動態)")
        print("  [3] 中止流程")
        print("=" * 50 + "\n")

        return input("請輸入選項代號 (1/2/3): ").strip()

    def execute_pipeline(self):
        """
        主控流程：執行規劃、驗證、人工確認、動態裁切與最終轉檔。
        """
        plan = self.plan_crop_parameters()
        report, has_warning = self.generate_verification_report(plan)

        print(">>> 驗證步驟完成，產出對照報告中...")
        for r in report:
            print(f"抽樣頁面 {r['page']} -> 頂部: {r['header_cut_y']} | 底部: {r['footer_cut_y']} | 預覽圖: {r['preview_img']}")

        custom_crop = None
        if has_warning:
            user_choice = self.request_human_approval("部分抽樣頁面裁切幅度超出安全閾值（>15% 頁高）", report)
            if user_choice == "2":
                top_manual = float(input("請輸入全域強制頂部裁切高度 (pt): "))
                bottom_manual = float(input("請輸入全域強制底部保留高度 (pt): "))
                custom_crop = (top_manual, bottom_manual)
            elif user_choice == "1":
                custom_crop = None
            else:
                print("流程已由人工中止。")
                return

        print("\n>>> 覆核通過，開始執行批次動態裁切...")
        doc = fitz.open(self.input_pdf)
        
        # 使用 tqdm 顯示單頁裁切進度條
        for page in tqdm(doc, desc="動態計算與裁切進度", unit="頁"):
            rect = page.rect
            
            if custom_crop:
                apply_top, apply_bottom = custom_crop
            else:
                apply_top, apply_bottom, _, _ = self._detect_page_boundaries(page, plan)
            
            page.set_cropbox(fitz.Rect(rect.x0, apply_top, rect.x1, apply_bottom))

        doc.save(self.temp_cropped_pdf, deflate=True)
        doc.close()

        print("\n>>> 裁切完成！開始進行 PDF 轉 Word (此步驟耗時較長，請耐心等候)...")
        try:
            cv = Converter(self.temp_cropped_pdf)
            cv.convert(self.output_docx, start=0, end=None)
            cv.close()
        finally:
            # 無論轉檔成功與否，確保安全清理暫存檔
            if os.path.exists(self.temp_cropped_pdf):
                try:
                    os.remove(self.temp_cropped_pdf)
                except OSError:
                    pass

        print(f"\n[SUCCESS] 轉檔完成！已產出: {self.output_docx}")

# ==========================================
# 導入與執行方式 (How to Import and Run)
# ==========================================
if __name__ == "__main__":
    # 確保你已在終端機安裝套件: 
    # pip install pymupdf pdf2docx tqdm
    
    # 將 "input.pdf" 替換成你的來源檔案名，"output.docx" 替換為想要的檔名
    pipeline = PDFConversionAgent("input.pdf", "output.docx")
    pipeline.execute_pipeline()
