---
name: clear-project-cache
description: 清除所有此專案更新快取與測試檔案
---

# 清除專案快取與測試檔案 (Clear Project Cache & Test Files)

當使用者要求「清除快取」、「清理測試檔案」或執行清理任務時，請執行此技能。

## 清理步驟

請使用 `run_command` 執行以下 PowerShell 指令，以清除 Python 快取、編譯檔案及專案過程產生的暫存檔：

```powershell
# 1. 刪除 Python 相關快取
Get-ChildItem -Path . -Include __pycache__, .pytest_cache -Recurse -Directory -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem -Path . -Include *.pyc, *.pyo -Recurse -File -Force -ErrorAction SilentlyContinue | Remove-Item -Force

# 2. 清理測試與暫存產出檔案（排除 .gitkeep 與 README.md）
$targetDirs = @('data\02_intermediate', 'data\03_output', 'scratch')
foreach ($dir in $targetDirs) {
    if (Test-Path $dir) {
        Get-ChildItem -Path $dir -Recurse -File -Exclude .gitkeep, README.md -ErrorAction SilentlyContinue | Remove-Item -Force
        Write-Host "已清空資料夾內容: $dir"
    }
}

# 3. 刪除根目錄或已知位置的零星 temp 檔案
Get-ChildItem -Path . -Filter "temp_*" -File -ErrorAction SilentlyContinue | Remove-Item -Force
```

## 注意事項
- 僅刪除快取與暫存檔案，**絕對不要**刪除 `.pt`、`.onnx` 等模型權重檔，或是使用者的原始文件 (`database_text`)。
- 清除完成後，請向使用者回報已清理的項目，保持簡潔。

