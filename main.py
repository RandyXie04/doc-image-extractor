"""
書籍轉檔與 AI 公式萃取數位化工具箱 - 主程式入口 (Main Entrypoint)

此檔案為標準 Python 進入點，負責將執行導向至桌面視窗與應用服務 (app_window.py)。
"""
import sys
import runpy
from pathlib import Path

if __name__ == "__main__":
    app_window_path = Path(__file__).resolve().parent / "app_window.py"
    runpy.run_path(str(app_window_path), run_name="__main__")
