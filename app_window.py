import webview
import threading
import uvicorn
import socket
import time
import sys
from pathlib import Path

# // Append project root directory to sys.path
root_dir = Path(__file__).parent.absolute()
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.web.app import app

def find_available_port(start_port=8000, max_attempts=20):
    # // Find available local port
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return start_port

def wait_for_server(port, timeout=5.0):
    # // Wait for FastAPI server to be ready
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
    
    # // Run hardware probe & setup
    from src.scripts.hardware_probe import ensure_optimal_accelerator
    ensure_optimal_accelerator()
    
    port = find_available_port(8000)
    
    def start_server():
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

    # // Start FastAPI in background daemon thread
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    
    # // Ensure server is listening
    wait_for_server(port, timeout=3.0)

    # // Create native WebView2 window (Unicode escaped title for ASCII compliance)
    window = webview.create_window(
        title="\u66f8\u7c4d\u8f49\u6a94\u8207 AI \u516c\u5f0f\u8403\u53d6\u6578\u4f4d\u5316\u5de5\u5177\u7bb1",
        url=f"http://127.0.0.1:{port}",
        width=1180,
        height=820,
        resizable=True
    )
    
    # // Start desktop UI loop
    webview.start()
