# Domain Glossary (GLOSSARY.md)

This document establishes the ubiquitous language and architectural terminology for `doc-image-extractor`.

---

## 1. Domain Concepts

### Markdown Postprocessing
The stage following geometric layout reflow and OCR recognition that applies semantic domain rules, dictionary entry heading demotion, CMap character normalization, rare character analysis, and output length anomaly checks to finalized Markdown.

### Vector Extraction Pipeline (高速向量通道)
The extraction pipeline using PyMuPDF (`book_layout_extractor.py`) to parse digital vector PDFs by directly extracting native geometric text streams, font roles, and layout blocks without image rasterization.

### OCR Pipeline (深度辨識通道)
The visual recognition pipeline using Surya OCR (`process_ocr.py`) to segment layouts, determine reading order, and recognize Chinese text for scanned or flattened PDF documents.

### No-Footnote Mode (無腳注模式)
A parameterized mode (`enable_footnotes=False` / `--no_footnote`) that completely disables candidate footnote classification, anchor matching, and Pandoc footnote syntax generation, preserving all bottom-of-page numbered items as standard body paragraphs.

### Rare Character Review (生僻字覆核)
The process of inspecting Private Use Area (PUA) codes, Yi syllabary code points, and unrecognized glyphs produced by OCR against static dictionaries, outputting an audit report for manual human verification.

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
