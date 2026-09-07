import uvicorn
import os
import sys
from pathlib import Path

# 將專案根目錄加入路徑
sys.path.append(str(Path(__file__).parent.parent))

if __name__ == "__main__":
    print("=" * 60)
    print("啟動 PDF 公式萃取 Web 伺服器...")
    print("請開啟瀏覽器並前往： http://127.0.0.1:8000")
    print("=" * 60)
    
    # 執行 uvicorn 伺服器，對應 src/web/app.py 裡面的 app 變數
    uvicorn.run("src.web.app:app", host="127.0.0.1", port=8000, reload=True)
