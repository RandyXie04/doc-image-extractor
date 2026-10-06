# PDF 數學公式提取

使用 YOLOv8 (ONNX) 模型定位 PDF 中的獨立公式 (Display Math) 並擷取為圖片。

## 功能

- YOLOv8 模型定位獨立公式區域
- 右界中文說明自動包含（條件說明、單位標註等預設納入截圖範圍）
- 輸出覆核清單 `formula_right_boundary_chinese_review.txt`，列出含中文判定的公式座標與原文
- 網頁畫布即時預覽與邊界微調

## 相關腳本

- `src/core_agent.py`：公式萃取與 Word 轉檔主流程
