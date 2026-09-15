import webview
import threading
import uvicorn
import socket
import time
import sys
from pathlib import Path
import logging
import datetime
import threading
from src.utils.path_helper import is_frozen, get_log_dir

# // Setup global exception logging for PyInstaller console=False environment
log_dir = get_log_dir()
log_dir.mkdir(parents=True, exist_ok=True)
log_path = log_dir / "app_error.log"
logging.basicConfig(
    filename=str(log_path),
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def _log_fatal_exception(exc_type, exc_value, exc_traceback, thread_name="MainThread"):
    import traceback
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    err_msg = (
        f"\n{'='*60}\n"
        f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [FATAL] Uncaught Exception\n"
        f"Thread: {thread_name}\n"
        f"Frozen: {is_frozen()}\n"
        f"Executable: {sys.executable if is_frozen() else 'Local Python'}\n"
        f"Traceback:\n{tb_str}"
        f"{'='*60}\n"
    )
    logging.error(err_msg)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    _log_fatal_exception(exc_type, exc_value, exc_traceback)

def handle_thread_exception(args):
    _log_fatal_exception(args.exc_type, args.exc_value, args.exc_traceback, thread_name=args.thread.name if args.thread else "UnknownThread")

sys.excepthook = handle_exception
threading.excepthook = handle_thread_exception

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
    
    import sys
    # // 支援 PyInstaller 封裝下透過 sys.executable 執行其他 .py 腳本
    if getattr(sys, 'frozen', False) and len(sys.argv) > 1 and sys.argv[1].endswith('.py'):
        import runpy
        script_path = sys.argv[1]
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        runpy.run_path(script_path, run_name="__main__")
        sys.exit(0)
    
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
