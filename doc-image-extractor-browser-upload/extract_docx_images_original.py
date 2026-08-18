# -*- coding: utf-8 -*-
"""
Word (DOCX) 圖片自動提取工具
自動掃描「word 待提取圖片」資料夾內的所有 DOCX 檔案，提取內部嵌入圖片並分類儲存。
.docx 本質是 ZIP 壓縮檔，圖片存放於 word/media/ 目錄，無需第三方套件。
"""

import io
import os
import sys
import zipfile


def extract_images_from_docx(docx_path: str, output_dir: str) -> int:
    """
    從指定 .docx 檔案中提取所有圖片並儲存。

    Args:
        docx_path:  .docx 檔案的完整路徑
        output_dir: 圖片輸出目錄

    Returns:
        成功提取的圖片數量
    """
    if not zipfile.is_zipfile(docx_path):
        print(f"❌ 檔案不是有效的 .docx / ZIP 格式：{docx_path}")
        return 0

    os.makedirs(output_dir, exist_ok=True)
    count = 0

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif",
                        ".emf", ".wmf", ".svg", ".webp"}

    with zipfile.ZipFile(docx_path, "r") as z:
        # 列出 word/media/ 底下的所有媒體檔案
        media_entries = [
            name for name in z.namelist()
            if name.lower().startswith("word/media/")
            and not name.endswith("/")
        ]

        if not media_entries:
            print("⚠️  word/media/ 目錄中未發現任何圖片。")
            return 0

        print(f"📂 共找到 {len(media_entries)} 個媒體檔案，開始提取…")

        for entry in sorted(media_entries):
            filename = os.path.basename(entry)
            ext = os.path.splitext(filename)[1].lower()

            if ext not in IMAGE_EXTENSIONS:
                print(f"  ⏭️  跳過非圖片檔案：{filename}")
                continue

            save_path = os.path.join(output_dir, filename)

            # 若檔名重複則加序號避免覆蓋
            if os.path.exists(save_path):
                base, extension = os.path.splitext(filename)
                i = 2
                while os.path.exists(save_path):
                    save_path = os.path.join(output_dir, f"{base}_{i}{extension}")
                    i += 1

            data = z.read(entry)
            size_kb = len(data) / 1024

            with open(save_path, "wb") as f:
                f.write(data)

            count += 1
            print(f"  ✅ {os.path.basename(save_path):35s}  {size_kb:8.1f} KB")

    return count


def main():
    # 強制 stdout/stderr 使用 UTF-8，避免 Windows CP950 編碼錯誤
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # ── 指定讀取資料夾：word 待提取圖片 ───────────────────────────
    input_folder = os.path.join(script_dir, "word 待提取圖片")
    os.makedirs(input_folder, exist_ok=True)

    # 搜尋所有 .docx 檔案（排除 ~$ 開頭的 Office 暫存檔）
    docx_files = [
        f for f in os.listdir(input_folder)
        if f.lower().endswith(".docx") and not f.startswith("~$")
    ]

    if not docx_files:
        print("=" * 60)
        print(f"⚠️  在「{input_folder}」中沒有找到任何 .docx 檔案！")
        print("請將欲提取圖片的 Word 檔放入該資料夾後再次執行。")
        print("=" * 60)
        return

    print("=" * 60)
    print(f"📁 來源資料夾 : {input_folder}")
    print(f"📑 找到 {len(docx_files)} 個 Word 檔案待處理")
    print("=" * 60 + "\n")

    total_images_all_files = 0

    for idx, docx_name in enumerate(docx_files, 1):
        docx_path = os.path.join(input_folder, docx_name)
        book_stem = os.path.splitext(docx_name)[0]
        output_dir = os.path.join(script_dir, f"images_{book_stem}")

        print(f"[{idx}/{len(docx_files)}] 正在處理：{docx_name}")
        print(f"👉 輸出目標：{output_dir}")

        count = extract_images_from_docx(docx_path, output_dir)
        total_images_all_files += count
        print(f"✨ 此檔案共提取 {count} 張圖片\n" + "-" * 50 + "\n")

    print("=" * 60)
    print(f"🎉 全部處理完成！共處理 {len(docx_files)} 個 Word 檔，累計提取 {total_images_all_files} 張圖片。")
    print("=" * 60)


if __name__ == "__main__":
    main()
