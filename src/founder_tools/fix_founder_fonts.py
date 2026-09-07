#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方正排版 (Founder Fonts) PDF / Word 標點符號與特殊字元自動修復工具
=============================================================================
功能說明：
1. 自動修復方正排版系統 (Founder Bookmaker / InDesign) 在匯出 PDF 時所產生的
   ToUnicode CMap 編碼映射缺陷（如將 GBK 字節直接當作 Unicode 彝文字母等問題）。
2. 自動還原全形標點符號：
   - 彝文字母 ꎬ (U+A3AC) -> ， (全形逗號)
   - 彝文字母 ꎮ (U+A3AE) -> 。 (全形句號)
   - 彝文字母 ꎻ (U+A3BB) -> ； (全形分號)
   - 彝文字母 ꎺ (U+A3BA) -> ： (全形冒號)
   - 彝文字母 ꎹ (U+A3B9) -> ！ (全形驚嘆號)
   - 彝文字母 ꎸ (U+A3B8) -> ？ (全形問號)
   - 拉丁引號 « » (U+00AB, U+00BB) -> 《 》 (中文書名號)
3. 自動拼合並還原方正拼字圈號：
   - 私用區序列 \U001000ca... -> ⑪ ~ ⑳ / ㉑ ~ ㊿ 等標準 Unicode 圈號數字
4. 自動還原特殊排版符號與罕見中文字：
   - 私用區 \U00100170 -> · (間隔號)
   - 私用區 \U001001b0 -> . (小數點)
   - 私用區 \U001001ba -> …… (目錄引導線/省略號)
   - 私用區 \ue81f -> 喎 (如「口喎」)
5. 支援輸入格式：
   - PDF 檔案 (.pdf) -> 直接萃取並修復為純文字 TXT 與排版 DOCX
   - Word 檔案 (.docx) -> 修復現有已轉檔 Word 中的所有段落與表格文字
   - 純文字 (.txt)
   - 剪貼簿文字即時修復
"""

import os
import sys
import io
import re
import glob
import unicodedata

# Windows UTF-8 相容性
if sys.platform == 'win32':
    try:
        if isinstance(sys.stdout, io.TextIOWrapper) and sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if isinstance(sys.stderr, io.TextIOWrapper) and sys.stderr.encoding.lower() != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def get_circled_number(num: int) -> str:
    """轉換數字為標準 Unicode 圈號字元 (1~50)"""
    if 1 <= num <= 20:
        return chr(0x2460 + num - 1)
    elif 21 <= num <= 35:
        return chr(0x3251 + num - 21)
    elif 36 <= num <= 50:
        return chr(0x32B1 + num - 36)
    else:
        return f"({num})"


def clean_founder_text(text: str) -> str:
    """
    核心修復函數：將帶有方正字庫編碼錯誤的字串修復為標準中文標點與符號。
    """
    if not text:
        return ""

    # ---------------- 1. 拼合修復方正圈號 (10 ~ 99) ----------------
    tens_map = {
        '\U00100049': 1, '\U0010004a': 2, '\U0010004b': 3, '\U0010004c': 4, '\U0010004d': 5,
    }
    units_map = {
        '\U00100052': 0, '\U00100053': 1, '\U00100054': 2, '\U00100055': 3,
        '\U00100056': 4, '\U00100057': 5, '\U00100058': 6, '\U00100059': 7,
        '\U0010005a': 8, '\U0010005b': 9,
    }

    def replace_circled(m):
        tens = tens_map.get(m.group(1), 0)
        units = units_map.get(m.group(2), 0)
        num = tens * 10 + units
        return get_circled_number(num)

    # 匹配三字元圈號組合 (可能帶有空格或緊鄰)
    text = re.sub(r'\U001000ca\s*([\U00100049-\U0010004d])\s*([\U00100052-\U0010005b])', replace_circled, text)

    # ---------------- 2. 常見方正特殊符號與中文字直接置換 ----------------
    direct_map = {
        'ꎬ': '，',          # U+A3AC (GBK 0xA3AC 全形逗號)
        'ꎮ': '。',          # U+A3AE (GBK 0xA3AE 全形句號)
        'ꎻ': '；',          # U+A3BB (GBK 0xA3BB 全形分號)
        'ꎺ': '：',          # U+A3BA (GBK 0xA3BA 全形冒號)
        'ꎹ': '！',          # U+A3B9 (GBK 0xA3B9 全形驚嘆號)
        'ꎸ': '？',          # U+A3B8 (GBK 0xA3B8 全形問號)
        '«': '《',          # U+00AB -> 中文書名號左
        '»': '》',          # U+00BB -> 中文書名號右
        '\U00100170': '·',  # U+100170 -> 間隔號 (如《西漢·藝文志》)
        '\U001001b0': '.',  # U+1001B0 -> 小數點 (如 5.5)
        '\U001001ba': '……', # U+1001BA -> 目錄引導線/省略號
        '\ue81f': '喎',     # U+E81F -> 口喎 (中醫專用字)
    }

    for bad_char, good_char in direct_map.items():
        text = text.replace(bad_char, good_char)

    # ---------------- 3. 通用數學演算法：自動還原任何落入彝文區的 GBK 全形字元 ----------------
    def decode_yi_gbk(match):
        ch = match.group(0)
        code = ord(ch)
        byte2 = code & 0xFF
        try:
            decoded = bytes([0xA3, byte2]).decode('gbk')
            if decoded == '．':
                return '。'
            return decoded
        except Exception:
            return ch

    text = re.sub(r'[\uA3A1-\uA3FE]', decode_yi_gbk, text)

    return text


def repair_docx_file(input_path: str, output_path: str = None) -> str:
    """修復 Word (.docx) 檔案中的所有段落與表格文字"""
    try:
        import docx
    except ImportError:
        print("[ERROR] 請先安裝 python-docx 套件: pip install python-docx")
        return ""

    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_已修復{ext}"

    doc = docx.Document(input_path)
    repaired_count = 0

    for p in doc.paragraphs:
        old_text = p.text
        new_text = clean_founder_text(old_text)
        if new_text != old_text:
            p.text = new_text
            repaired_count += 1

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    old_text = p.text
                    new_text = clean_founder_text(old_text)
                    if new_text != old_text:
                        p.text = new_text
                        repaired_count += 1

    doc.save(output_path)
    print(f"[SUCCESS] Word 檔案修復完成！共更新 {repaired_count} 處文字，已儲存至：\n  -> {output_path}")
    return output_path


def repair_pdf_file(input_path: str, output_txt: str = None, output_docx: str = None) -> tuple:
    """讀取 PDF 檔案，提取文字並自動修復，輸出乾淨的 TXT 與 DOCX"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("[ERROR] 請先安裝 PyMuPDF 套件: pip install pymupdf")
        return None, None

    base, _ = os.path.splitext(input_path)
    if not output_txt:
        output_txt = f"{base}_修復純文字.txt"
    if not output_docx:
        output_docx = f"{base}_修復文字稿.docx"

    doc = fitz.open(input_path)
    full_cleaned_pages = []

    print(f"[INFO] 正在讀取並修復 PDF: '{os.path.basename(input_path)}' (共 {len(doc)} 頁)...")
    for page_idx, page in enumerate(doc):
        raw_text = page.get_text()
        cleaned_text = clean_founder_text(raw_text)
        full_cleaned_pages.append(cleaned_text)

    doc.close()

    with open(output_txt, 'w', encoding='utf-8') as f:
        for pno, ptext in enumerate(full_cleaned_pages, start=1):
            f.write(f"\n--- 第 {pno} 頁 ---\n")
            f.write(ptext)
    print(f"[SUCCESS] 已產出修復後純文字檔：\n  -> {output_txt}")

    try:
        import docx
        docx_doc = docx.Document()
        for pno, ptext in enumerate(full_cleaned_pages, start=1):
            docx_doc.add_heading(f"第 {pno} 頁", level=2)
            for line in ptext.splitlines():
                if line.strip():
                    docx_doc.add_paragraph(line)
        docx_doc.save(output_docx)
        print(f"[SUCCESS] 已產出修復後 Word 檔：\n  -> {output_docx}")
    except ImportError:
        pass

    return output_txt, output_docx


def repair_clipboard():
    """修復剪貼簿內容並寫回剪貼簿"""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    try:
        clip_text = root.clipboard_get()
        if not clip_text:
            print("[INFO] 剪貼簿為空。")
            return
        cleaned = clean_founder_text(clip_text)
        root.clipboard_clear()
        root.clipboard_append(cleaned)
        root.update()
        print("[SUCCESS] 🎉 剪貼簿文字已成功修復！您可以直接在 Word 中貼上乾淨標點。")
    except Exception as e:
        print(f"[WARN] 無法存取剪貼簿: {e}")
    finally:
        root.destroy()


def launch_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from tkinter.scrolledtext import ScrolledText

    root = tk.Tk()
    root.title("方正排版 (Founder Fonts) PDF / Word 標點符號自動修復工具")
    root.geometry("680x520")
    root.minsize(580, 420)

    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass

    main_frame = ttk.Frame(root, padding="15")
    main_frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        main_frame,
        text="🛠️ 方正排版 PDF / Word 標點符號一鍵修復工具",
        font=("Segoe UI", 12, "bold")
    ).pack(anchor=tk.W, pady=(0, 10))

    clip_frame = ttk.LabelFrame(main_frame, text=" ⚡ 快速功能：即時剪貼簿修復 ", padding="10")
    clip_frame.pack(fill=tk.X, pady=5)

    def do_clip():
        try:
            txt = root.clipboard_get()
            if not txt:
                messagebox.showinfo("提示", "剪貼簿內沒有文字！")
                return
            cleaned = clean_founder_text(txt)
            root.clipboard_clear()
            root.clipboard_append(cleaned)
            root.update()
            log_box.insert(tk.END, f"[剪貼簿修復完成] 已成功還原 {len(txt)} 字元，請直接按 Ctrl+V 貼上 Word！\n")
            log_box.see(tk.END)
            messagebox.showinfo("成功", "🎉 剪貼簿內的方正亂碼已修復完成！\n您現在可以直接在 Word 中按 Ctrl+V 貼上。")
        except Exception as e:
            messagebox.showerror("錯誤", f"讀取剪貼簿失敗：{e}")

    ttk.Button(clip_frame, text="📋 一鍵修復當前剪貼簿文字 (修復後直接 Ctrl+V 貼上)", command=do_clip).pack(fill=tk.X, ipady=4)

    file_frame = ttk.LabelFrame(main_frame, text=" 📁 檔案修復：選擇 PDF 或 Word 檔案 ", padding="10")
    file_frame.pack(fill=tk.X, pady=5)

    selected_file_var = tk.StringVar()

    entry_row = ttk.Frame(file_frame)
    entry_row.pack(fill=tk.X, pady=5)

    ttk.Entry(entry_row, textvariable=selected_file_var, font=("Segoe UI", 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

    def browse_file():
        path = filedialog.askopenfilename(
            title="選擇要修復的 PDF 或 Word 檔案",
            filetypes=[("支援檔案 (*.pdf; *.docx; *.txt)", "*.pdf;*.docx;*.txt"), ("所有檔案", "*.*")]
        )
        if path:
            selected_file_var.set(path)

    ttk.Button(entry_row, text="瀏覽檔案...", command=browse_file).pack(side=tk.RIGHT)

    def do_process_file():
        path = selected_file_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("提示", "請先選擇有效的檔案路徑！")
            return

        ext = os.path.splitext(path)[1].lower()
        if ext == '.docx':
            out = repair_docx_file(path)
            log_box.insert(tk.END, f"[Word 修復完成] 輸出檔案: {out}\n")
            log_box.see(tk.END)
            messagebox.showinfo("成功", f"🎉 Word 檔案已修復完成！\n儲存至：{out}")
        elif ext == '.pdf':
            txt_out, docx_out = repair_pdf_file(path)
            log_box.insert(tk.END, f"[PDF 處理完成] 輸出檔案:\n  - {txt_out}\n  - {docx_out}\n")
            log_box.see(tk.END)
            messagebox.showinfo("成功", f"🎉 PDF 檔案已修復並匯出完成！\n已產出 TXT 與 Word 檔。")
        elif ext == '.txt':
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            cleaned = clean_founder_text(content)
            base, _ = os.path.splitext(path)
            out = f"{base}_已修復.txt"
            with open(out, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            log_box.insert(tk.END, f"[TXT 修復完成] 輸出檔案: {out}\n")
            log_box.see(tk.END)
            messagebox.showinfo("成功", f"🎉 純文字檔已修復完成！\n儲存至：{out}")
        else:
            messagebox.showerror("錯誤", f"不支援的檔案格式：{ext}")

    btn_row = ttk.Frame(file_frame)
    btn_row.pack(fill=tk.X, pady=5)
    ttk.Button(btn_row, text="🚀 開始執行檔案修復", command=do_process_file).pack(fill=tk.X, ipady=3)

    log_frame = ttk.LabelFrame(main_frame, text=" 執行紀錄 ", padding="5")
    log_frame.pack(fill=tk.BOTH, expand=True, pady=5)

    log_box = ScrolledText(log_frame, wrap=tk.WORD, font=("Consolas", 9), height=6)
    log_box.pack(fill=tk.BOTH, expand=True)

    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        launch_gui()
    else:
        target = sys.argv[1]
        if target.lower() == "--clip":
            repair_clipboard()
        elif os.path.isfile(target):
            ext = os.path.splitext(target)[1].lower()
            if ext == '.docx':
                repair_docx_file(target)
            elif ext == '.pdf':
                repair_pdf_file(target)
            elif ext == '.txt':
                with open(target, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                cleaned = clean_founder_text(content)
                base, _ = os.path.splitext(target)
                out = f"{base}_已修復.txt"
                with open(out, 'w', encoding='utf-8') as f:
                    f.write(cleaned)
                print(f"[SUCCESS] 純文字修復完成 -> {out}")
            else:
                print(f"[ERROR] 不支援的檔案格式：{ext}")
        elif os.path.isdir(target):
            print(f"[INFO] 批次處理資料夾：{target}")
            docx_files = glob.glob(os.path.join(target, "*.docx"))
            pdf_files = glob.glob(os.path.join(target, "*.pdf"))
            for docx_p in docx_files:
                if "_已修復" not in docx_p:
                    repair_docx_file(docx_p)
            for pdf_p in pdf_files:
                repair_pdf_file(pdf_p)
        else:
            print(f"[ERROR] 找不到檔案或目錄：{target}")
