# 方正書版亂碼修復模組

修復「方正書版 (Founder Bookmaker)」排版系統產生的 CMap 編碼缺陷與亂碼。

## 功能

- CMap 編碼修復（亂碼、特殊字串、中英文標點）
- 支援 PDF 與 DOCX 輸入
- 標題與排版重建（`HeadingDetector`、`toc_parser.py`）
- 自動化校註注入（`auto_footnote.py`），支援 `(1)`、`[1]`、`1` 等多種標記格式
- 以 `template.docx` 為範本骨架產出修復後 Word 檔

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
