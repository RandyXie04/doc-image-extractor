import tkinter as tk
from tkinter import ttk
from typing import Optional
from core.annotation_profile import AnnotationProfile

class AnnotationReviewDialog:
    """
    註釋結構審查與確認彈窗 (Human Review Gate)
    對應模式 A (AI預判) 與模式 B (人工直接指定) 的介面實作。
    """
    
    def __init__(self, parent: tk.Tk, suggested_profile: AnnotationProfile):
        self.top = tk.Toplevel(parent)
        self.top.title("📖 註釋結構設定 (Human Gate)")
        self.top.geometry("450x350")
        self.top.grab_set() # Modal
        
        self.result_profile: Optional[AnnotationProfile] = None
        self.suggested = suggested_profile
        
        self._setup_ui()
        
    def _setup_ui(self):
        main_frame = ttk.Frame(self.top, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 1. AI 偵測結果提示
        if self.suggested.annotation_label:
            ai_msg = f"AI 偵測建議：標籤為【{self.suggested.annotation_label}】\n標記型態：{self.suggested.marker_type}"
            ttk.Label(main_frame, text=ai_msg, foreground="blue").pack(anchor=tk.W, pady=(0, 10))
            
        # 2. 標籤設定
        ttk.Label(main_frame, text="① 註釋區塊標籤 (若有)").pack(anchor=tk.W)
        self.label_var = tk.StringVar(value=self.suggested.annotation_label or "無標籤")
        label_combo = ttk.Combobox(main_frame, textvariable=self.label_var, values=["無標籤", "校注", "注釋", "注解", "注", "考證"])
        label_combo.pack(fill=tk.X, pady=(2, 10))
        
        # 3. 標記型態設定
        ttk.Label(main_frame, text="② 腳註標記型態").pack(anchor=tk.W)
        self.marker_var = tk.StringVar(value=self.suggested.marker_type)
        marker_frame = ttk.Frame(main_frame)
        marker_frame.pack(fill=tk.X, pady=(2, 10))
        
        ttk.Radiobutton(marker_frame, text="①②③ (圓圈數字)", variable=self.marker_var, value="circled_number").pack(anchor=tk.W)
        ttk.Radiobutton(marker_frame, text="[1][2][3] (方括號)", variable=self.marker_var, value="square_bracket").pack(anchor=tk.W)
        ttk.Radiobutton(marker_frame, text="〔1〕〔2〕 (中文括號)", variable=self.marker_var, value="chinese_bracket").pack(anchor=tk.W)
        ttk.Radiobutton(marker_frame, text="純數字 (1, 2)", variable=self.marker_var, value="plain_number").pack(anchor=tk.W)
        
        # 4. 按鈕
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        
        ttk.Button(btn_frame, text="🚀 確認並鎖定設定", command=self._on_confirm).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.top.destroy).pack(side=tk.RIGHT)
        
    def _on_confirm(self):
        label = self.label_var.get()
        if label == "無標籤":
            label = None
            
        self.result_profile = AnnotationProfile(
            annotation_label=label,
            marker_type=self.marker_var.get(),
            marker_scope=self.suggested.marker_scope,
            numbering_scope=self.suggested.numbering_scope,
            footnote_location=self.suggested.footnote_location,
            extraction_strategy="explicit_label" if label else "marker_based",
            confidence=1.0,
            is_locked=True # 關鍵：由人工確認後鎖定
        )
        self.top.destroy()
        
    @classmethod
    def show(cls, parent_tk: tk.Tk, suggested_profile: AnnotationProfile) -> Optional[AnnotationProfile]:
        dialog = cls(parent_tk, suggested_profile)
        parent_tk.wait_window(dialog.top)
        return dialog.result_profile
