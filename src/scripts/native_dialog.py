import sys
import os
import io
import json
import shutil
import tkinter as tk
from tkinter import filedialog

# Force UTF-8 encoding on stdout for cross-platform and non-ASCII file paths
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except Exception:
        pass

def main():
    if len(sys.argv) < 3:
        print(json.dumps({"status": "error", "message": "參數不足，需提供來源路徑與建議檔名"}, ensure_ascii=False))
        return

    source_path = sys.argv[1]
    suggested_filename = sys.argv[2]

    if not os.path.exists(source_path):
        print(json.dumps({"status": "error", "message": f"來源檔案不存在: {source_path}"}, ensure_ascii=False))
        return

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.lift()
        root.attributes('-topmost', True)
        root.focus_force()

        ext = suggested_filename.split(".")[-1] if "." in suggested_filename else "*"
        type_label = f"{ext.upper()} 文件" if ext != "*" else "所有檔案"

        # Explicitly pass parent=root so the save dialog inherits HWND_TOPMOST and gains focus
        file_path = filedialog.asksaveasfilename(
            parent=root,
            title="請選擇儲存位置與檔名",
            initialfile=suggested_filename,
            defaultextension=f".{ext}" if ext != "*" else None,
            filetypes=[(type_label, f"*.{ext}"), ("所有檔案", "*.*")]
        )

        if file_path:
            # Copy source file to selected destination
            shutil.copy2(source_path, file_path)
            print(json.dumps({"status": "success", "saved_path": file_path}, ensure_ascii=False))
        else:
            print(json.dumps({"status": "cancelled", "message": "使用者取消另存新檔"}, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
    finally:
        if root:
            try:
                root.destroy()
            except Exception:
                pass

if __name__ == "__main__":
    main()
