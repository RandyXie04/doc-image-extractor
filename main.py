"""
書籍轉檔與 AI 公式萃取數位化工具箱 - 主程式入口 (Main Entrypoint)

純網頁化服務架構 (Web Server Mode)：
以 FastAPI + Uvicorn 驅動，支援本機瀏覽器操作與公司區域網路 (LAN) 多人連線。
"""
import sys
import os
import socket
import argparse
import webbrowser
import threading
import time
from pathlib import Path

# 將專案根目錄加入 sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

def get_lan_ip() -> str:
    """取得本機在區域網路 (Wi-Fi / 乙太網路) 的 IP 位址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def find_available_port(start_port: int = 8000, max_attempts: int = 20) -> int:
    """自動尋找可用 Port 避免佔用衝突"""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except OSError:
                continue
    return start_port

def wait_and_open_browser(url: str, delay: float = 1.2):
    """延遲等待伺服器就緒後自動開啟預設瀏覽器"""
    time.sleep(delay)
    try:
        webbrowser.open(url)
    except Exception:
        pass

def main():
    parser = argparse.ArgumentParser(description="PDF Toolkit Web Server")
    parser.add_argument("--host", default="0.0.0.0", help="監聽主機 IP (預設 0.0.0.0 開放區網訪問)")
    parser.add_argument("--port", type=int, default=8000, help="監聽連接埠 (預設 8000)")
    parser.add_argument("--no-browser", action="store_true", help="啟動時不安裝/不自動開啟瀏覽器")
    parser.add_argument("--dev", action="store_true", help="以開發除錯模式啟動 (啟用詳細日誌)")
    args = parser.parse_args()

    # 設定運行環境模式
    if args.dev or os.environ.get("APP_MODE") == "dev":
        os.environ["APP_MODE"] = "dev"
        log_level = "debug"
    else:
        log_level = "info"

    # 硬體加速探測與設定
    try:
        from src.scripts.hardware_probe import ensure_optimal_accelerator
        ensure_optimal_accelerator()
    except Exception as e:
        print(f"[Warning] Hardware probe failed: {e}")

    # 載入 FastAPI 應用
    import uvicorn
    from src.web.app import app

    port = find_available_port(args.port)
    lan_ip = get_lan_ip()
    
    local_url = f"http://127.0.0.1:{port}"
    lan_url = f"http://{lan_ip}:{port}"
    
    print("\n" + "=" * 65)
    print("  \U0001F680 PDF Toolkit 網頁服務 (Web Server) 已啟動！")
    print("=" * 65)
    print(f"  \U0001F4BB 本機操作網址     : {local_url}")
    print(f"  \U0001F310 區網同仁訪問網址 : {lan_url}")
    print("=" * 65)
    print("  \U00002139\U0000FE0F  若要停止服務，請在此終端機視窗中按 Ctrl + C")
    print("=" * 65 + "\n")

    if not args.no_browser:
        threading.Thread(target=wait_and_open_browser, args=(local_url,), daemon=True).start()

    uvicorn.run(app, host=args.host, port=port, log_level=log_level)

if __name__ == '__main__':
    main()
