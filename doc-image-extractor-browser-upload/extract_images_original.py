# -*- coding: utf-8 -*-
"""
PDF 圖片自動提取工具
自動掃描「pdf 待提取圖片」資料夾內的所有 PDF 檔案。
精確識別 PDF 內部色彩通道（包括 DeviceN 印刷墨水色通道），自動校正反相與色調，
所有圖片一律輸出為高品質無損 PNG 格式（嚴禁 JPEG）。
"""

import io
import os
import sys
import fitz  # PyMuPDF
from PIL import Image, ImageOps


def extract_images_from_pdf(pdf_path: str, output_dir: str) -> int:
    """
    從指定 PDF 檔案中提取所有圖片並儲存為正確色彩的正片 PNG 格式。

    Args:
        pdf_path:   PDF 檔案的完整路徑
        output_dir: 圖片輸出目錄

    Returns:
        成功提取的圖片數量
    """
    os.makedirs(output_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    count = 0

    print(f"📄 PDF 共 {len(doc)} 頁，開始提取圖片（精準色彩校正，一律輸出 PNG）…")

    for page_index in range(len(doc)):
        page = doc[page_index]
        image_list = page.get_images(full=True)

        for img_index, img_info in enumerate(image_list):
            xref = img_info[0]
            cs_name = img_info[5]       # 如 'DeviceN', 'DeviceGray', 'DeviceRGB'
            alt_cs = img_info[6]        # 如 'DeviceCMYK'

            try:
                base_image = doc.extract_image(xref)
                if not base_image or not base_image.get("image"):
                    continue

                raw_bytes = base_image["image"]
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                # 跳過極小的圖（裝飾性線條或遮罩）
                if width < 10 or height < 10:
                    continue

                # 使用 PIL 讀取原始圖片數據
                img = Image.open(io.BytesIO(raw_bytes))

                # ── 印刷色空間反相校正 ──────────────────────────────────
                # 當色彩空間為 DeviceN (如單色黑版墨水，基底為 CMYK 減法色)
                # 或色彩模式為 CMYK 時，0 代表無墨(白)，255 代表全墨(黑)，
                # 轉成 RGB (加法色) 顯示時必須進行反相處理，才能呈現正確正片！
                if cs_name == "DeviceN" or alt_cs == "DeviceCMYK" or img.mode == "CMYK":
                    if img.mode in ("L", "1"):
                        img = ImageOps.invert(img.convert("L"))
                    elif img.mode == "CMYK":
                        img = ImageOps.invert(img.convert("RGB"))
                    else:
                        img = ImageOps.invert(img.convert("L"))
                else:
                    # 一般色彩模式轉為 RGB / L
                    if img.mode in ("P", "PA", "LA", "RGBA"):
                        img = img.convert("RGBA" if "A" in img.mode else "RGB")
                    elif img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")

                filename = f"page{page_index + 1:04d}_img{img_index + 1:03d}.png"
                save_path = os.path.join(output_dir, filename)

                # 儲存為高品質 PNG
                img.save(save_path, format="PNG")

                count += 1
                note = " (DeviceN 墨水反相校正 -> 正片)" if (cs_name == "DeviceN" or alt_cs == "DeviceCMYK") else ""
                print(f"  ✅ 第 {page_index + 1:4d} 頁 | 圖 {img_index + 1:2d} | "
                      f"{width:4d}×{height:4d} px | {filename}{note}")

            except Exception as e:
                print(f"  ⚠️  第 {page_index + 1} 頁，圖片 {img_index + 1} 提取失敗：{e}")
                continue

    doc.close()
    return count


def main():
    # 強制 stdout/stderr 使用 UTF-8，避免 Windows CP950 編碼錯誤
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # ── 指定讀取資料夾：pdf 待提取圖片 ────────────────────────────
    input_folder = os.path.join(script_dir, "pdf 待提取圖片")
    os.makedirs(input_folder, exist_ok=True)

    # 搜尋所有 .pdf 檔案
    pdf_files = [f for f in os.listdir(input_folder) if f.lower().endswith(".pdf")]

    if not pdf_files:
        print("=" * 60)
        print(f"⚠️  在「{input_folder}」中沒有找到任何 .pdf 檔案！")
        print("請將欲提取圖片的 PDF 放入該資料夾後再次執行。")
        print("=" * 60)
        return

    print("=" * 60)
    print(f"📁 來源資料夾 : {input_folder}")
    print(f"📑 找到 {len(pdf_files)} 個 PDF 檔案待處理")
    print(f"🛡️  輸出標準   : 無損 PNG（精準識別印刷色墨水通道，自動校正反相負片）")
    print("=" * 60 + "\n")

    total_images_all_files = 0

    for idx, pdf_name in enumerate(pdf_files, 1):
        pdf_path = os.path.join(input_folder, pdf_name)
        book_stem = os.path.splitext(pdf_name)[0]
        output_dir = os.path.join(script_dir, f"images_{book_stem}")

        print(f"[{idx}/{len(pdf_files)}] 正在處理：{pdf_name}")
        print(f"👉 輸出目標：{output_dir}")

        count = extract_images_from_pdf(pdf_path, output_dir)
        total_images_all_files += count
        print(f"✨ 此檔案共提取 {count} 張 PNG 圖片\n" + "-" * 50 + "\n")

    print("=" * 60)
    print(f"🎉 全部處理完成！共處理 {len(pdf_files)} 個 PDF，累計提取 {total_images_all_files} 張 PNG 圖片。")
    print("=" * 60)


if __name__ == "__main__":
    main()
