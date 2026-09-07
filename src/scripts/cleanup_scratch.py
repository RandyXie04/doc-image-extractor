import os
import shutil
import datetime
from pathlib import Path

def cleanup_scratch(force: bool = False, log_fn=print) -> bool:
    """
    清理根目錄 scratch 資料夾內之暫存快取。
    若非 force 模式，僅在每月 1 號執行完全刪除（不經過資源回收桶）。
    """
    today = datetime.date.today()
    project_root = Path(__file__).parent.parent.resolve()
    scratch_dir = project_root / "scratch"
    
    if not scratch_dir.exists():
        os.makedirs(scratch_dir, exist_ok=True)
        return False

    if not force and today.day != 1:
        log_fn(f"[Scratch] 今日為 {today} (非每月 1 號)，略過自動清空。")
        return False

    log_fn(f"[Scratch] 觸發清理機制 (日期: {today}, Force={force})：正在永久清空 scratch/ 暫存區...")
    deleted_count = 0

    for item in scratch_dir.iterdir():
        # 保留說明文件與 gitkeep
        if item.name in [".gitkeep", "README.md"]:
            continue
        try:
            if item.is_file() or item.is_symlink():
                os.remove(item)  # 直接自檔案系統刪除，不進入回收桶
                deleted_count += 1
            elif item.is_dir():
                shutil.rmtree(item)  # 遞迴永久刪除
                deleted_count += 1
        except Exception as e:
            log_fn(f"[Scratch ERROR] 無法刪除 {item.name}: {e}")

    log_fn(f"[Scratch SUCCESS] 已永久清理 {deleted_count} 個項目/暫存檔案。")
    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scratch 暫存資料夾完全清理工具")
    parser.add_argument("--force", action="store_true", help="強制立即完全刪除所有暫存快取")
    args = parser.parse_args()
    
    cleanup_scratch(force=args.force)
