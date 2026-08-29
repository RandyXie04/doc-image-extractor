#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF 智慧轉換與 AI 公式萃取全功能工作站 (PDFConversionAgent Pipeline & GUI)
=============================================================================
整合功能說明：
1. 【任務一：動態裁切與轉檔 Word】
   透過 PyMuPDF 動態分析頁首與頁尾邊界、自動裁切掉頁眉頁碼雜訊，並轉換為排版乾淨的 Word (.docx) 文件。

2. 【任務二：AI 深度學習數學公式萃取】
   利用 Pix2Text 開源之 MathFormulaDetector (MFD) 深度學習模型，針對原始未裁切 PDF 以 300 DPI 高解析度渲染，
   自動偵測獨立公式，具備「夾縫中文字檢查 (防誤合併)」與「全形/半形括號編號右界自適應擴展 (防雜圖)」雙重防呆機制，
   最後裁切為高畫質 PNG 公式截圖並自動封裝為 ZIP 壓縮檔。

3. 【雙模啟動介面】
   - 雙擊執行 / 無參數呼叫：開啟 Tkinter 原生全功能視窗介面 (GUI)，可自由勾選任務一、任務二或一鍵雙開。
   - 命令列模式 (CLI)：支援帶參數背景自動化批次執行。
"""

import os
import sys
import io
import glob
import re
import zipfile
import threading
from pathlib import Path

# 集中設定中心：路徑由 pathlib 動態計算，API 金鑰/設定值由 .env 載入
from config import PATHS, AI, CFG

# Windows 終端 UTF-8 輸出相容性設定
if sys.platform == 'win32':
    try:
        if isinstance(sys.stdout, io.TextIOWrapper) and sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if isinstance(sys.stderr, io.TextIOWrapper) and sys.stderr.encoding.lower() != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import fitz  # PyMuPDF
import cv2
import numpy as np
from tqdm import tqdm
from pix2text import MathFormulaDetector

# pdf2docx 延遲/防呆載入
try:
    from pdf2docx import Converter
    HAS_PDF2DOCX = True
except ImportError:
    HAS_PDF2DOCX = False



import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from src.core_agent import PDFConversionAgent

def launch_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from tkinter.scrolledtext import ScrolledText

    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 統一使用 config.PATHS 定義好的路徑
    input_dir = str(PATHS.input_dir)
    default_formula_dir = str(PATHS.formula_dir_v2)
    default_preview_dir = str(PATHS.preview_dir)
    
    # 確保目錄存在
    PATHS.ensure_all()

    root = tk.Tk()
    root.title("PDF 智慧轉換與 AI 公式萃取全功能工作站")
    root.geometry("720x720")
    root.minsize(620, 600)

    # 設置 ttk 風格
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass

    # ---------------- 變數綁定 ----------------
    selected_pdf_path = tk.StringVar()
    output_docx_var = tk.StringVar()
    formula_dir_var = tk.StringVar(value=default_formula_dir)
    do_convert_docx = tk.BooleanVar(value=True)
    do_extract_mfd = tk.BooleanVar(value=True)
    start_page_var = tk.StringVar()
    end_page_var = tk.StringVar()
    is_running = tk.BooleanVar(value=False)
    
    # 邊界探測比例
    header_ratio_var = tk.DoubleVar(value=0.15)
    footer_ratio_var = tk.DoubleVar(value=0.92)
    
    # 進度條狀態
    progress_val_var = tk.DoubleVar(value=0.0)
    progress_txt_var = tk.StringVar(value="準備就緒")

    pdf_file_map = {}
    preview_image_ref = []  # 防止圖片被 GC 回收

    def scan_and_refresh_pdfs():
        pdf_file_map.clear()
        files = sorted(glob.glob(os.path.join(input_dir, "*.pdf")))
        display_names = []
        for f in files:
            name = os.path.basename(f)
            size_mb = os.path.getsize(f) / (1024 * 1024)
            label = f"{name} ({size_mb:.1f} MB)"
            pdf_file_map[label] = f
            display_names.append(label)

        pdf_combo['values'] = display_names
        if display_names:
            pdf_combo.current(0)
            on_pdf_selected(pdf_file_map[display_names[0]])
        else:
            pdf_combo.set("（待提取資料夾內尚無 PDF 檔案）")
            selected_pdf_path.set("")
            output_docx_var.set("")

    def on_pdf_selected(pdf_path):
        selected_pdf_path.set(pdf_path)
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        output_docx_var.set(os.path.join(script_dir, f"{base_name}_已轉檔.docx"))

    def open_preview_dialog():
        pdf_path = selected_pdf_path.get().strip()
        if not pdf_path or not os.path.exists(pdf_path):
            messagebox.showwarning("提示", "請先選擇有效的 PDF 檔案！")
            return

        preview_win = tk.Toplevel(root)
        preview_win.title("邊界裁切預覽與微調")
        preview_win.geometry("900x700")
        preview_win.minsize(800, 600)

        # Main layout
        left_frame = ttk.Frame(preview_win)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        right_frame = ttk.Frame(preview_win, width=300)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        
        canvas = tk.Canvas(left_frame, bg="#2e2e2e")
        canvas.pack(fill=tk.BOTH, expand=True)

        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
        except Exception as e:
            messagebox.showerror("錯誤", f"無法開啟 PDF: {e}")
            preview_win.destroy()
            return
            
        current_page = tk.IntVar(value=1)
        
        def update_preview(*args):
            page_idx = current_page.get() - 1
            if page_idx < 0: page_idx = 0
            if page_idx >= total_pages: page_idx = total_pages - 1
            
            page = doc[page_idx]
            
            # 使用目前的滑桿數值建立代理來計算邊界
            agent = PDFConversionAgent(
                input_pdf=pdf_path, 
                header_ratio=header_ratio_var.get(), 
                footer_ratio=footer_ratio_var.get()
            )
            plan = agent.plan_crop_parameters()
            final_top, final_bottom, _, _ = agent._detect_page_boundaries(page, plan)
            
            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            if cw <= 1 or ch <= 1:
                cw, ch = 600, 800
                
            rect = page.rect
            scale = min((cw - 40) / rect.width, (ch - 40) / rect.height)
            if scale <= 0: scale = 1.0
            
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
            
            from PIL import Image, ImageTk
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            photo = ImageTk.PhotoImage(image=img)
            
            preview_image_ref.clear()
            preview_image_ref.append(photo)
            
            canvas.delete("all")
            img_x = (cw - pix.width) / 2
            img_y = (ch - pix.height) / 2
            canvas.create_image(img_x, img_y, anchor=tk.NW, image=photo)
            
            # 實際裁切紅藍線
            top_y_px = img_y + final_top * scale
            bottom_y_px = img_y + final_bottom * scale
            
            canvas.create_line(img_x, top_y_px, img_x + pix.width, top_y_px, fill="red", width=2)
            canvas.create_line(img_x, bottom_y_px, img_x + pix.width, bottom_y_px, fill="blue", width=2)
            
            # 探測極限虛線
            scan_top_px = img_y + plan["header_threshold"] * scale
            scan_bottom_px = img_y + plan["footer_threshold"] * scale
            canvas.create_line(img_x, scan_top_px, img_x + pix.width, scan_top_px, fill="pink", width=1, dash=(4, 4))
            canvas.create_line(img_x, scan_bottom_px, img_x + pix.width, scan_bottom_px, fill="lightblue", width=1, dash=(4, 4))
            
            canvas.create_text(img_x + 5, top_y_px - 10, text=f"裁切點 (Top): {final_top:.1f}pt", fill="red", anchor=tk.W, font=("Arial", 10, "bold"))
            canvas.create_text(img_x + 5, bottom_y_px + 10, text=f"裁切點 (Bottom): {final_bottom:.1f}pt", fill="blue", anchor=tk.W, font=("Arial", 10, "bold"))

        # Right panel
        ttk.Label(right_frame, text="🔍 邊界預覽與設定", font=("Segoe UI", 12, "bold")).pack(pady=(0, 15))
        
        # 翻頁
        nav_frame = ttk.Frame(right_frame)
        nav_frame.pack(fill=tk.X, pady=10)
        ttk.Label(nav_frame, text="預覽頁碼:").pack(side=tk.LEFT)
        ttk.Button(nav_frame, text="<", width=3, command=lambda: current_page.set(max(1, current_page.get()-1))).pack(side=tk.LEFT, padx=5)
        page_entry = ttk.Entry(nav_frame, textvariable=current_page, width=5, justify="center")
        page_entry.pack(side=tk.LEFT)
        ttk.Label(nav_frame, text=f"/ {total_pages}").pack(side=tk.LEFT, padx=5)
        ttk.Button(nav_frame, text=">", width=3, command=lambda: current_page.set(min(total_pages, current_page.get()+1))).pack(side=tk.LEFT)
        
        # 滑桿
        ttk.Label(right_frame, text="\n頁眉探測範圍 (0% ~ 30%)").pack(anchor=tk.W)
        header_scale = ttk.Scale(right_frame, from_=0.0, to=0.3, orient=tk.HORIZONTAL, variable=header_ratio_var)
        header_scale.pack(fill=tk.X, pady=5)
        ttk.Label(right_frame, text="往下尋找頁眉的最大深度\n實心紅線：最終裁切\n粉紅虛線：探測極限", foreground="gray", font=("Segoe UI", 9)).pack(anchor=tk.W)
        
        ttk.Label(right_frame, text="\n頁尾探測範圍 (70% ~ 100%)").pack(anchor=tk.W)
        footer_scale = ttk.Scale(right_frame, from_=0.7, to=1.0, orient=tk.HORIZONTAL, variable=footer_ratio_var)
        footer_scale.pack(fill=tk.X, pady=5)
        ttk.Label(right_frame, text="往上尋找頁尾的最大深度\n實心藍線：最終裁切\n淺藍虛線：探測極限", foreground="gray", font=("Segoe UI", 9)).pack(anchor=tk.W)
        
        resize_timer = [None]
        def on_change(*args):
            if resize_timer[0]: preview_win.after_cancel(resize_timer[0])
            resize_timer[0] = preview_win.after(100, update_preview)
            
        header_scale.config(command=on_change)
        footer_scale.config(command=on_change)
        current_page.trace_add("write", lambda *a: on_change())
        canvas.bind("<Configure>", on_change)
        
        ttk.Button(right_frame, text="✅ 儲存並關閉", command=preview_win.destroy, style="Accent.TButton").pack(side=tk.BOTTOM, fill=tk.X, pady=20)
        preview_win.after(150, update_preview)

    # ---------------- UI 佈局 ----------------
    main_frame = ttk.Frame(root, padding="15")
    main_frame.pack(fill=tk.BOTH, expand=True)

    # 標題
    ttk.Label(
        main_frame,
        text="🛠️ PDF 智慧轉檔 (Word) 與 AI 公式萃取工作站",
        font=("Segoe UI", 13, "bold")
    ).pack(anchor=tk.W, pady=(0, 10))

    # 區塊 1: 來源 PDF
    file_frame = ttk.LabelFrame(main_frame, text=" 1. 選擇來源 PDF 檔案 ", padding="8")
    file_frame.pack(fill=tk.X, pady=4)

    combo_row = ttk.Frame(file_frame)
    combo_row.pack(fill=tk.X)

    pdf_combo = ttk.Combobox(combo_row, state="readonly", font=("Segoe UI", 9))
    pdf_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

    def on_combo_change(event):
        chosen = pdf_combo.get()
        if chosen in pdf_file_map:
            on_pdf_selected(pdf_file_map[chosen])

    pdf_combo.bind("<<ComboboxSelected>>", on_combo_change)

    def browse_pdf():
        path = filedialog.askopenfilename(
            title="選擇 PDF 檔案",
            filetypes=[("PDF 檔案", "*.pdf"), ("所有檔案", "*.*")]
        )
        if path:
            name = os.path.basename(path)
            label = f"[自訂] {name}"
            pdf_file_map[label] = path
            vals = list(pdf_combo['values'])
            if label not in vals:
                vals.append(label)
                pdf_combo['values'] = vals
            pdf_combo.set(label)
            on_pdf_selected(path)

    ttk.Button(combo_row, text="瀏覽檔案...", command=browse_pdf).pack(side=tk.RIGHT)

    # 區塊 2: 執行任務勾選
    task_frame = ttk.LabelFrame(main_frame, text=" 2. 選擇處理任務 (可同時執行) ", padding="8")
    task_frame.pack(fill=tk.X, pady=4)

    # 任務 1: Word 轉檔
    docx_chk_row = ttk.Frame(task_frame)
    docx_chk_row.pack(fill=tk.X, pady=(2, 2))
    docx_chk = ttk.Checkbutton(docx_chk_row, text="任務 A：動態去除頁首/頁尾，乾淨轉檔為 Word (.docx)", variable=do_convert_docx)
    docx_chk.pack(side=tk.LEFT)
    ttk.Button(docx_chk_row, text="🔍 預覽與微調邊界", command=open_preview_dialog).pack(side=tk.LEFT, padx=(10, 0))

    docx_row = ttk.Frame(task_frame)
    docx_row.pack(fill=tk.X, padx=(20, 0), pady=(0, 6))
    ttk.Label(docx_row, text="輸出 Word：").pack(side=tk.LEFT)
    docx_entry = ttk.Entry(docx_row, textvariable=output_docx_var, font=("Segoe UI", 8))
    docx_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

    def browse_docx_save():
        p = filedialog.asksaveasfilename(
            title="儲存 Word 檔案",
            defaultextension=".docx",
            filetypes=[("Word 檔案", "*.docx")]
        )
        if p:
            output_docx_var.set(p)

    ttk.Button(docx_row, text="變更路徑...", command=browse_docx_save).pack(side=tk.RIGHT)

    # 任務 2: AI 公式萃取
    mfd_chk = ttk.Checkbutton(task_frame, text="任務 B：Pix2Text AI 深度學習數學公式精準萃取 (.png / .zip)", variable=do_extract_mfd)
    mfd_chk.pack(anchor=tk.W, pady=(4, 2))

    mfd_row = ttk.Frame(task_frame)
    mfd_row.pack(fill=tk.X, padx=(20, 0), pady=(0, 2))
    ttk.Label(mfd_row, text="公式目錄：").pack(side=tk.LEFT)
    mfd_entry = ttk.Entry(mfd_row, textvariable=formula_dir_var, font=("Segoe UI", 8))
    mfd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

    def browse_mfd_dir():
        d = filedialog.askdirectory(title="選擇公式存放目錄", initialdir=formula_dir_var.get())
        if d:
            formula_dir_var.set(d)

    ttk.Button(mfd_row, text="變更目錄...", command=browse_mfd_dir).pack(side=tk.RIGHT)

    # 頁碼範圍設定
    range_row = ttk.Frame(task_frame)
    range_row.pack(fill=tk.X, padx=(20, 0), pady=(4, 2))
    ttk.Label(range_row, text="公式頁碼：").pack(side=tk.LEFT)
    ttk.Label(range_row, text="起始 ").pack(side=tk.LEFT)
    ttk.Entry(range_row, textvariable=start_page_var, width=6).pack(side=tk.LEFT, padx=(0, 10))
    ttk.Label(range_row, text="結束 ").pack(side=tk.LEFT)
    ttk.Entry(range_row, textvariable=end_page_var, width=6).pack(side=tk.LEFT, padx=(0, 10))
    ttk.Label(range_row, text="(留空代表整本掃描)", foreground="gray").pack(side=tk.LEFT)

    # 區塊 3: 執行按鈕
    action_frame = ttk.Frame(main_frame)
    action_frame.pack(fill=tk.X, pady=8)

    run_btn = ttk.Button(action_frame, text="🚀 一鍵啟動自動化處理管線", style="Accent.TButton")
    run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)
    
    # --- 新增的 UI 視覺化進度條區塊 ---
    prog_frame = ttk.Frame(main_frame)
    prog_frame.pack(fill=tk.X, pady=(0, 5))
    ttk.Label(prog_frame, textvariable=progress_txt_var, font=("Segoe UI", 9, "bold")).pack(side=tk.TOP, anchor=tk.W)
    prog_bar = ttk.Progressbar(prog_frame, variable=progress_val_var, maximum=100.0)
    prog_bar.pack(side=tk.TOP, fill=tk.X, expand=True)

    # 區塊 4: 日誌輸出視窗
    log_frame = ttk.LabelFrame(main_frame, text=" 執行即時進度日誌 ", padding="5")
    log_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

    log_box = ScrolledText(log_frame, wrap=tk.WORD, font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
    log_box.pack(fill=tk.BOTH, expand=True)
    
    # 幫日誌設定顏色標籤
    log_box.tag_config("INFO", foreground="#a6e22e")
    log_box.tag_config("WARN", foreground="#fd971f")
    log_box.tag_config("ERROR", foreground="#f92672")

    class OutputRedirector:
        def __init__(self, text_widget):
            self.text_widget = text_widget

        def write(self, string):
            root.after(0, self._write, string)

        def flush(self):
            pass

        def _write(self, string):
            # 過濾掉只包含空白或 tqdm 回車符號的空行，避免洗版
            if not string.strip() or string == '\r':
                return
            
            clean_str = string.replace('\r', '')
            
            # 自動標色系統與過濾 tqdm 百分比
            # 若字串看起來像 tqdm 的純文字進度條 (例如包含 100%|██████████| 或類似格式)，直接丟棄不印出
            if "|" in clean_str and "%" in clean_str and ("[" in clean_str or "]" in clean_str):
                return
                
            tag = None
            if "[WARN" in clean_str: tag = "WARN"
            elif "[ERROR" in clean_str: tag = "ERROR"
            elif "[INFO" in clean_str: tag = "INFO"
            elif "[SUCCESS" in clean_str: tag = "INFO"
            
            # 如果沒有以換行結尾，手動補上，確保格式整齊
            if not clean_str.endswith('\n'):
                clean_str += '\n'
            
            if tag:
                self.text_widget.insert(tk.END, clean_str, tag)
            else:
                self.text_widget.insert(tk.END, clean_str)
            self.text_widget.see(tk.END)

    sys.stdout = OutputRedirector(log_box)
    sys.stderr = OutputRedirector(log_box)

    def append_log(msg):
        print(msg)
        
    def gui_update_progress(current, total, task_name="處理中"):
        percent = (current / total) * 100 if total > 0 else 0
        def _update():
            progress_val_var.set(percent)
            progress_txt_var.set(f"[{task_name}] 目前進度: {current} / {total} 頁 ({percent:.1f}%)")
        root.after(0, _update)

    # ---------------- 執行邏輯 ----------------
    def start_pipeline():
        pdf = selected_pdf_path.get().strip()
        if not pdf or not os.path.exists(pdf):
            messagebox.showwarning("提示", "請先選擇有效的 PDF 檔案！")
            return

        conv_word = do_convert_docx.get()
        extr_mfd = do_extract_mfd.get()

        if not conv_word and not extr_mfd:
            messagebox.showwarning("提示", "請至少勾選一項任務（轉檔 Word 或 公式萃取）！")
            return

        out_docx = output_docx_var.get().strip()
        out_fdir = formula_dir_var.get().strip()

        sp_str = start_page_var.get().strip()
        ep_str = end_page_var.get().strip()
        start_idx = 0
        end_idx = None

        if sp_str:
            if not sp_str.isdigit() or int(sp_str) < 1:
                messagebox.showerror("錯誤", "起始頁碼必須為大於或等於 1 的整數！")
                return
            start_idx = int(sp_str) - 1

        if ep_str:
            if not ep_str.isdigit() or int(ep_str) < 1:
                messagebox.showerror("錯誤", "結束頁碼必須為大於或等於 1 的整數！")
                return
            end_idx = int(ep_str) - 1
            if end_idx < start_idx:
                messagebox.showerror("錯誤", "結束頁碼不能小於起始頁碼！")
                return

        is_running.set(True)
        run_btn.config(state=tk.DISABLED, text="⏳ 工作管線處理中，請稍候...")
        log_box.delete("1.0", tk.END)

        def worker():
            try:
                agent = PDFConversionAgent(
                    input_pdf=pdf,
                    output_docx=out_docx,
                    preview_dir=default_preview_dir,
                    formula_dir=out_fdir,
                    header_ratio=header_ratio_var.get(),
                    footer_ratio=footer_ratio_var.get()
                )
                agent.execute_pipeline(
                    convert_word=conv_word,
                    extract_formulas=extr_mfd,
                    formula_dpi=300,
                    start_page_idx=start_idx,
                    end_page_idx=end_idx,
                    log_fn=append_log,
                    progress_callback=gui_update_progress
                )
                root.after(0, lambda: messagebox.showinfo("成功", "🎉 所有勾選任務已順利完成！"))
            except Exception as e:
                append_log(f"\n[EXCEPTION] 執行出錯：{e}")
                root.after(0, lambda err=e: messagebox.showerror("錯誤", f"執行過程中發生錯誤：\n{err}"))
            finally:
                root.after(0, restore_ui)

        def restore_ui():
            is_running.set(False)
            run_btn.config(state=tk.NORMAL, text="🚀 一鍵啟動自動化處理管線")

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    run_btn.config(command=start_pipeline)

    scan_and_refresh_pdfs()
    root.mainloop()


# =========================================================================
# 主入口 (CLI 與 GUI 雙模分流)
# =========================================================================
if __name__ == "__main__":
    import argparse

    if len(sys.argv) == 1:
        try:
            launch_gui()
        except Exception as gui_err:
            print(f"[提示] 無法啟動 GUI 視窗 ({gui_err})，切換至純終端模式...")
            base = os.path.dirname(os.path.abspath(__file__))
            default_pdf = os.path.join(base, "待提取公式檔案", "110175-01  具身智能  从理论到实践.pdf")
            agent = PDFConversionAgent(default_pdf)
            agent.execute_pipeline(convert_word=False, extract_formulas=True)
    else:
        parser = argparse.ArgumentParser(description="PDF 智慧轉換與 AI 公式萃取全功能工作站")
        parser.add_argument("--pdf", required=True, help="來源 PDF 檔案路徑")
        parser.add_argument("--docx", default=None, help="輸出的 Word 檔案路徑")
        parser.add_argument("--formula_dir", default="extracted_formulas_mfd-2", help="公式 PNG 輸出資料夾")
        parser.add_argument("--no_word", action="store_true", help="跳過 Word 轉檔")
        parser.add_argument("--no_formula", action="store_true", help="跳過公式萃取")
        parser.add_argument("--start", type=int, default=None, help="公式起始頁碼（1-based）")
        parser.add_argument("--end", type=int, default=None, help="公式結束頁碼（1-based）")
        args = parser.parse_args()

        start_idx = (args.start - 1) if args.start is not None else 0
        end_idx = (args.end - 1) if args.end is not None else None

        agent = PDFConversionAgent(
            input_pdf=args.pdf,
            output_docx=args.docx,
            formula_dir=args.formula_dir
        )
        agent.execute_pipeline(
            convert_word=(not args.no_word),
            extract_formulas=(not args.no_formula),
            start_page_idx=start_idx,
            end_page_idx=end_idx
        )
