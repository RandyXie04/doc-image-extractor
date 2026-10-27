# Domain Glossary (GLOSSARY.md)

This document establishes the ubiquitous language and architectural terminology for `doc-image-extractor`.

---

## 1. Domain Concepts

### Vector Extraction Pipeline (高速向量通道)

The extraction pipeline using PyMuPDF (`src/scripts/book_layout_extractor.py`) to parse digital vector PDFs by directly extracting native geometric text streams, font roles, and layout blocks without image rasterization.

### OCR Pipeline (深度辨識通道)

The visual recognition pipeline using Surya OCR (`src/scripts/process_ocr.py`) to segment layouts, determine reading order, and recognize Chinese text for scanned or flattened PDF documents.

### Hybrid Vector/OCR Fallback (雙軌混合解析架構)

The architectural strategy in OCR pipelines where native geometric PDF text streams are preferentially mapped via PyMuPDF clipping, falling back to neural OCR only for scanned/rasterized regions or flattened graphics.

### Horizontal Projection Line Slicing (水平投影多行切片)

The algorithmic technique (`_slice_box_into_lines` in `src/scripts/process_ocr.py`) that calculates horizontal grayscale projection histograms to split multi-line layout bounding boxes into discrete single-line slices before feeding them into OCR recognition, eliminating sequence model hallucination.

### 2D Reading Flow Clustering (2D 橫帶/卡片圖文聚類排序)

Spatial sorting algorithm (`sort_blocks_2d_reading_order` in `src/scripts/process_ocr.py`) that groups horizontally adjacent text and figures into cohesive 2D bands, preventing figure/caption separation and dynamically setting relative image widths based on page width ratios.

### Text-Wrapping Paragraph Stitching (圖文環繞平滑拼接)

The mechanism (`_merge_wrapping_paragraphs` in `src/scripts/process_ocr.py`) that detects intra-sentence line breaks, unclosed quotes, or book title marks around illustrations to smoothly concatenate wrapped paragraph fragments into continuous text blocks without merging headings.

### No-Footnote Mode (無腳注模式)

A parameterized mode (`enable_footnotes=False` / `--no_footnote`) that completely disables candidate footnote classification, anchor matching, and Pandoc footnote syntax generation, preserving all bottom-of-page numbered items as standard body paragraphs.

### Lossless Image Extraction (圖片無損提取通道)

The extraction pipeline (`src/scripts/extract_images.py`, `src/scripts/pdf_image_extractor.py`) that parses Word OpenXML (`word/document.xml` active media references) and PDF XObject streams to isolate raster and vector figures without lossy re-encoding, while neutralizing transparency artifacts (Alpha-channel flattening against white background).

### YOLOv8 ONNX Formula Extractor (YOLOv8 ONNX 數學公式提取通道)

Object detection subsystem (`src/scripts/yolo_onnx_utils.py`, `src/core_agent.py`) leveraging YOLOv8 ONNX models and DirectML to detect mathematical and chemical formula bounding boxes in PDF documents with interactive 4-way cropping sliders and batch image export.

### Markdown Postprocessing

The stage following geometric layout reflow and OCR recognition that applies semantic domain rules, dictionary entry heading demotion, CMap character normalization, rare character analysis, and output length anomaly checks to finalized Markdown (`src/extraction/post_processor.py`).

### Symbol Normalization & Mapper (特殊符號配置化映射)

The rule-based postprocessor (`src/extraction/symbol_mapper.py`) driven by `config/symbol_mapping.json` that restores circled numbers (`①`~`⑳`), repairs truncated Chinese parentheses (e.g., `一)` -> `（一）`), normalizes tildes `~` to `～` to prevent Pandoc subscript syntax misinterpretations, and strips invalid empty image placeholders.

### Rare Character Review (生僻字覆核)

The process of inspecting Private Use Area (PUA) codes, Yi syllabary code points, and unrecognized glyphs produced by OCR against static dictionaries, outputting an audit report for manual human verification (`src/scripts/ocr_rare_char_corrector.py`).

### Font Metric & Role Analyzer (PDF 字型度量與角色分析器)

The tool (`src/scripts/pdf_font_analyzer.py`) inspecting embedded font frequency, point sizes, and line heights in PDFs to automatically assign structural roles (`heading`, `body`, `caption`, `ignore`) and output user-editable mapping configurations (`config/fonts.json`).

### TOC Anchor & Heading Detector (目錄錨定與標題偵測器)

Multi-layer heading detection subsystem (`src/founder_tools/core/heading_detector.py`, `src/founder_tools/core/toc_parser.py`) fusing regular expressions, relative font-size differentials, and TOC dot-leader page anchoring to prevent headings from degenerating into body paragraphs or sticking to adjacent lines.

### POD Diffusion Workflow (POD 範本學習與批量擴散工作流)

The four-layer hybrid workflow (5% Golden Seed + 85% rule engine propagation + 10% Agent/VLM local fallback repair) designed to format raw book drafts into publisher-grade Print-On-Demand (POD) Word documents without manual styling overhead.

### Golden Seed (人工精修範本 / Exemplar)

A pre-processed golden sample of 1~2 chapters handcrafted by human editors, used by `src/pod_studio/exemplar_learner.py` to extract document XML style properties, semantic triggers, and Few-Shot contrast pairs.

### Layout Blueprint (排版藍圖 / BookBlueprint)

The declarative JSON configuration (`src/pod_studio/blueprint_schema.py`) encapsulating book archetype, heading hierarchies, required section badges, regex style triggers, and quality gate tolerances.

### Section AST (單元切片抽象語法樹 / 切片工作區)

The discrete unit-level Markdown slicing mechanism (`src/pod_studio/section_ast.py`) that divides full-book drafts into standalone files (`sec_001.md` ~ `sec_XXX.md`) along major heading boundaries to eliminate line-offset drift and token context overflow.

### Deterministic Completion Gatekeeper (確定性驗收閘門 / PodValidator)

The non-probabilistic validator (`src/pod_studio/pod_validator.py`) enforcing character conservation (flowcheck), required semantic badges, circled number sequence continuity, and Word custom style whitelist legality before Pandoc compilation.

### Visual Fallback Repair (VLM 視覺多模態局部修復)

The repair strategy (`src/pod_studio/visual_fallback_repair.py`) targeting anomalous or corrupted section slices by taking 150 DPI page snapshots and prompting Vision Language Models (VLM) for multimodal structure and glyph reconstruction.

### Propagation Engine (狀態機擴散引擎)

The high-speed, zero-API-cost local state machine (`src/pod_studio/propagation_engine.py`) that executes regex matching, badge injection, and Pandoc custom style annotations (`::: {custom-style="..."}`) across section AST workspaces.

### Founder Bookmaker Repair (方正書版亂碼修復)

Subsystem (`src/founder_tools/`) resolving proprietary Founder Bookmaker (BDC) font encoding anomalies, non-standard CID mappings, and Yi syllabary (彝文區) code substitutions.

### Virtual Run Slicer (無損樣式分塊切分)

OpenXML run-slicing technique (`src/founder_tools/core/run_slicer.py`) that splits Word runs to inject footnote reference markers while preserving original character-level properties (bold, italic, font face, font size).

### Dual-Anchor Footnote Matcher (雙向標記匹配器)

Mechanism (`src/founder_tools/core/footnote_matcher.py`) reconciling in-text footnote anchors (`①`, `[1]`, `1.`) with bottom-of-page annotations across text boundaries while protecting decimal numbers (e.g., `31.5%`) and software versions (e.g., `v1.2`).

### Persistent SQLite Task Queue (輕量持久化任務佇列)

Zero-config embedded SQLite task queue (`src/utils/task_queue.py`) providing atomic status tracking, concurrency control (`_OCR_SEMAPHORE`), and crash recovery across application restarts.

### Ephemeral 24-Hour File Lifecycle (24小時無日誌留存生命週期)

Privacy-first zero-permanent-log storage policy enforcing automatic unlinking and directory pruning for any intermediate or output artifacts older than 24 hours (`purge_expired_files` in `src/utils/file_guard.py`), while shielding active jobs and template whitelists.

### Two-Tier Upload Body Guard (雙層上傳防禦機制)

Dual defense architecture comprising `MaxBodySizeMiddleware` (ASGI early Content-Length header filtering) and `save_upload_file_safely` (streaming 64KB chunk byte accumulator with immediate abort and partial file unlinking upon threshold breach in `src/utils/file_guard.py`).

### Hardware Prober & Graceful Degradation (硬體探測與優雅降級)

Dynamic accelerator resolver (`src/scripts/hardware_probe.py`) prioritizing DirectML (cross-vendor DirectX 12 GPUs on Windows) or PyTorch CUDA with seamless fallback to multi-threaded CPU execution.

### Native OS Dialog Bridge (原生系統對話框橋接)

Decoupled Tkinter-based Windows native File Open / Save As dialog bridge (`src/scripts/native_dialog.py`) managing Z-order window focus and releasing `WS_EX_TOPMOST` locks.

### Dual User Profiles (雙角色作業視角)

UI paradigm separating Publisher Editor Mode (focus on drag-and-drop, interactive crop sliders, Word template styling, native file dialogs) from Developer Debug Mode (GPU metrics, raw logs, AST outlines, font table inspection).

### Dual-Engine POD Pipeline (POD 雙軌擴散策略)

The third-stage execution architecture in POD Studio providing a parameter-driven choice between high-speed zero-token state machine propagation (`PropagationEngine` with localized VLM fallback) and multimodal few-shot visual infilling (`SecureVLMContinuationEngine`), while converging on a unified AST representation, `DocxSerializer`, and `PodValidator` defensive gatekeeper.

---

## 2. Architectural Design Vocabulary

- **Module**: A coherent unit of code with a well-defined interface and internal implementation.
- **Interface**: The surface exposed to callers (classes, functions, parameters, return types).
- **Implementation**: The hidden code and algorithms executing behind the interface.
- **Depth**: The ratio of internal complexity to interface surface area. Deep modules have small, intuitive interfaces that hide substantial work; shallow modules have interfaces nearly as wide as their implementation.
- **Seam**: The line across which two modules interact, enabling independent testing, substitution, and refactoring.
- **Adapter**: Code that bridges a seam to an external dependency or alternative implementation.
- **Leverage**: A high-leverage interface provides wide capability across multiple call sites with minimal caller complexity.
- **Locality**: Co-locating related behavior and change logic within a single module so defects concentrate rather than scattering across multiple files.
