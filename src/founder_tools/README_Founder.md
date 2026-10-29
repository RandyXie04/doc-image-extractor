# 方正書版亂碼修復模組

修復「方正書版 (Founder Bookmaker)」排版系統產生的 CMap 編碼缺陷與亂碼。
遵循「Zero-Unexplained Error」校驗標準，支援自動化修復 PDF 與 DOCX 稿件，並以統一 DOCX 格式交付排版。

## 核心功能

- **CMap 編碼修復**：透過 `fix_founder_fonts.py` 與 Unicode 映射庫還原亂碼、特殊字元與中英文標點。
- **無損樣式保留**：Virtual Run Slicer 技術切分標記的同時，完整保留原始粗體、斜體與字型樣式。
- **範本骨架綁定**：產出 Word 檔案強制套用 `template.docx` 樣式骨架，確保與後續排版軟體相容。
- **標題與排版重建**：結合 `HeadingDetector` 與 `toc_parser.py` 解析目錄與章節層級。
- **自動化校註注入**：`auto_footnote.py` 支援 `(1)`、`[1]`、`①` 與純數字等多種註腳標記。
- **Web API 整合**：由後端 `/api/founder/repair` 端點統一提供非同步修復服務。

## 目錄結構

```text
founder_tools/
├── auto_footnote.py        # 校註系統入口
├── fix_founder_fonts.py    # 方正字庫 CMap 修復
├── template.docx           # Word 樣式範本
├── core/
│   ├── heading_detector.py     # 標題偵測
│   ├── toc_parser.py           # 目錄解析
│   ├── annotation_analyzer.py  # 註釋分析
│   ├── footnote_matcher.py     # 腳註匹配
│   ├── marker_detector.py      # 標記偵測
│   ├── run_slicer.py           # Virtual Run 切分
│   ├── openxml_builder.py      # OpenXML 建構
│   ├── preflight_auditor.py    # 前置審計
│   ├── postflight_validator.py # 後置驗證
│   ├── template_resolver.py    # 範本解析
│   ├── document_model.py       # 文件模型
│   ├── annotation_profile.py   # 註釋設定
│   ├── ai_heading_classifier.py    # AI 標題分類
│   └── ai_kaiti_classifier.py      # AI 楷體分類
└── parsers/
    ├── docx_parser.py      # DOCX 解析
    └── pdf_parser.py       # PDF 解析
```
