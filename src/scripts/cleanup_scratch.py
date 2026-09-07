import os
import shutil
import datetime
from pathlib import Path

# // 清理根目錄 scratch 資料夾內之暫存快取 (每月 1 號執行完全刪除)
def cleanup_scratch(force: bool = False, log_fn=print) -> bool:
    today = datetime.date.today()
    project_root = Path(__file__).parent.parent.resolve()
    scratch_dir = project_root / "scratch"
    
    if not scratch_dir.exists():
        os.makedirs(scratch_dir, exist_ok=True)
        return False

    if not force and today.day != 1:
        log_fn(f"[Scratch] Today is {today} (not the 1st of month), skipping auto cleanup.")
        return False

    log_fn(f"[Scratch] Triggered cleanup (Date: {today}, Force={force}): Purging scratch/ directory...")
    deleted_count = 0

    for item in scratch_dir.iterdir():
        # // Keep .gitkeep and README.md
        if item.name in [".gitkeep", "README.md"]:
            continue
        try:
            if item.is_file() or item.is_symlink():
                os.remove(item)
                deleted_count += 1
            elif item.is_dir():
                shutil.rmtree(item)
                deleted_count += 1
        except Exception as e:
            log_fn(f"[Scratch ERROR] Failed to remove {item.name}: {e}")

    log_fn(f"[Scratch SUCCESS] Permanently cleaned {deleted_count} temporary items.")
    return True

if __name__ == "__main__":
    import argparse
    # // Command line interface for scratch cleanup
    parser = argparse.ArgumentParser(description="Scratch cache directory cleanup utility")
    parser.add_argument("--force", action="store_true", help="Force immediate purge of all scratch files")
    args = parser.parse_args()
    
    cleanup_scratch(force=args.force)
