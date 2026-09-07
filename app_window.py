import webview
import threading
import uvicorn
import socket
import time
import sys
from pathlib import Path

# 將專案根目錄加入 sys.path
root_dir = Path(__file__).parent.absolute()
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.web.app import app

def find_available_port(start_port=8000, max_attempts=20):
    """尋找本機可用的通訊埠"""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start_port

def wait_for_server(port, timeout=5.0):
    """等待 FastAPI 伺服器在背景就緒，避免視窗載入過早顯示空白"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.1)
    return False

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    
    port = find_available_port(8000)
    
    def start_server():
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    # 背景非同步啟動 FastAPI
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    
    # 確保伺服器已成功聆聽通訊埠
    wait_for_server(port, timeout=3.0)

    # 彈出原生桌面視窗 (WebView2)
    window = webview.create_window(
        title="書籍轉檔與 AI 公式萃取數位化工具箱",
        url=f"http://127.0.0.1:{port}",
        width=1180,
        height=820,
        resizable=True
    )
    
    # 啟動桌面視窗主迴圈
    webview.start()
