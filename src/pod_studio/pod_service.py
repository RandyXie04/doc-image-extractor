# -*- coding: utf-8 -*-
"""
POD Production Service Layer
============================
Encapsulates the 3-stage POD automated styling and verification pipeline:
1. extract_raw: Generates Book_raw.docx and Book_raw_ast.json preserving page_num & bbox.
2. compile_blueprint: Uses DiffAligner (LCS) to infer styling rules without domain hardcoding.
3. propagate_and_validate: Executes deterministic AST propagation, visual fallback, and CJK skeleton validation.
"""

from __future__ import annotations
import re
import json
import uuid
import os
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import fitz
import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Inches

from .blueprint_schema import BookBlueprint, StyleTriggerRule, ValidationConfig
from .section_ast import SectionAST, SectionUnit, ParagraphUnit, BookAST, SectionAdapter
from .exemplar_learner import ExemplarLearner, DiffAligner
from .propagation_engine import PropagationEngine
from .pod_validator import PodValidator, ValidationReport
from .cjk_validator import PODIntegrityValidator
from .visual_fallback_repair import repair_corrupted_section_with_vlm
from .docx_writer import DocxSerializer

try:
    from src.scripts.book_layout_extractor import extract_book_vector_ast
except ImportError:
    try:
        from scripts.book_layout_extractor import extract_book_vector_ast
    except ImportError:
        extract_book_vector_ast = None


def extract_raw_from_pdf(
    pdf_path: str | Path,
    session_dir: str | Path,
    split_level: int = 2,
    use_vector_ast: bool = False,
    ai_kaiti: bool = False,
    enable_footnotes: bool = True,
    page_range: Optional[Tuple[int, int]] = None,
) -> Tuple[List[SectionUnit], Path, Path]:
    """
    Extracts text and geometric coordinates from PDF.
    Produces Book_raw_ast.json and Book_raw.docx in session_dir.

    When use_vector_ast is True, uses the high-precision BookAST engine
    (extract_book_vector_ast) preserving paragraph bbox, 1-based page_num,
    font metadata, and footnotes while session_dir owns file outputs.
    When use_vector_ast is False, falls back to legacy loop for backward parity.
    """
    s_dir = Path(session_dir)
    s_dir.mkdir(parents=True, exist_ok=True)
    pdf_p = Path(pdf_path)

    if not pdf_p.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_p}")

    if use_vector_ast and extract_book_vector_ast is not None:
        book_ast = extract_book_vector_ast(
            pdf_path=pdf_p,
            split_level=split_level,
            ai_kaiti=ai_kaiti,
            enable_footnotes=enable_footnotes,
            page_range=page_range,
        )
        if book_ast is None:
            raise RuntimeError(f"Failed to extract vector AST from PDF: {pdf_p}")

        # Automated layout architecture mode: extract raster images to session_dir / "images"
        images_dir = s_dir / "images"
        image_path_map = {}
        if getattr(book_ast, "image_blocks", None):
            try:
                from src.scripts.pdf_image_extractor import extract_pdf_images
                image_path_map = extract_pdf_images(
                    pdf_path=str(pdf_p),
                    image_blocks=book_ast.image_blocks,
                    output_dir=str(images_dir),
                )
            except Exception:
                image_path_map = {}

        def _repl_img(m):
            pn = int(m.group(1))
            bn = int(m.group(2))
            saved = image_path_map.get((pn, bn))
            if saved:
                rel = os.path.relpath(saved, str(s_dir)).replace("\\", "/")
                return f"![]({rel}){{width=80%}}"
            return ""

        sections = SectionAdapter.to_sections(book_ast)
        for sec in sections:
            for p in sec.paragraphs:
                if "_IMG_PLACEHOLDER_" in p.raw_text:
                    p.raw_text = re.sub(r'!\[__IMG_PLACEHOLDER_(\d+)_(\d+)__\]\(\)', _repl_img, p.raw_text)
            sec.raw_content = sec.effective_content

        # Save Book_raw_ast.json
        ast_path = s_dir / "Book_raw_ast.json"
        SectionAST.dump_book_ast_json(sections, ast_path)

        # Save Book_raw.docx
        raw_docx_path = s_dir / "Book_raw.docx"
        doc_out = docx.Document()
        for sec in sections:
            if sec.title != "__PREAMBLE__":
                h_style = f"Heading {min(sec.level, 3)}"
                doc_out.add_paragraph(sec.title, style=h_style)
            for p in sec.paragraphs:
                p_txt = p.raw_text.strip()
                if not p_txt:
                    continue
                m_h = re.match(r'^(#+)\s+(.+)$', p_txt)
                if m_h:
                    h_txt = m_h.group(2).strip()
                    if sec.title != "__PREAMBLE__" and h_txt == sec.title:
                        continue
                    h_lvl = min(len(m_h.group(1)), 3)
                    doc_out.add_paragraph(h_txt, style=f"Heading {h_lvl}")
                else:
                    doc_out.add_paragraph(p_txt)
        doc_out.save(str(raw_docx_path))

        return sections, ast_path, raw_docx_path

    # Legacy loop (ensures fitz.Document is closed properly)
    doc: Any = fitz.open(str(pdf_path))
    try:
        sections: List[SectionUnit] = []
        current_sec = SectionUnit(
            section_id="sec_000",
            title="__PREAMBLE__",
            level=0,
        )
        sections.append(current_sec)

        heading_re = re.compile(r'^(#{1,' + str(split_level) + r'})\s+(.+)$')
        para_counter = 1

        for page_idx, page in enumerate(doc, 1):
            if page_range and not (page_range[0] <= page_idx <= page_range[1]):
                continue
            # Extract structured text blocks with font and coordinates
            blocks = page.get_text("dict").get("blocks", [])
            for b in blocks:
                if b.get("type") != 0:  # Text blocks only
                    continue
                lines = b.get("lines", [])
                block_lines_text = []
                primary_font = ""
                primary_size = 0.0

                for l in lines:
                    spans = l.get("spans", [])
                    line_text = "".join(s.get("text", "") for s in spans).strip()
                    if line_text:
                        block_lines_text.append(line_text)
                        if spans and not primary_font:
                            primary_font = spans[0].get("font", "")
                            primary_size = spans[0].get("size", 0.0)

                full_block_text = " ".join(block_lines_text).strip()
                if not full_block_text:
                    continue

                bbox = list(b.get("bbox", [0, 0, 0, 0]))

                # Check if block acts as a section heading (or starts with #)
                m = heading_re.match(full_block_text)
                if m:
                    level = len(m.group(1))
                    title = m.group(2).strip()
                    sec_id = f"sec_{len(sections):03d}"
                    current_sec = SectionUnit(
                        section_id=sec_id,
                        title=title,
                        level=level,
                        raw_content=f"{m.group(1)} {title}",
                    )
                    sections.append(current_sec)
                    para_counter = 1
                    continue
                elif primary_size >= 14.0 and len(full_block_text) <= 30:
                    # Potential title by font size
                    sec_id = f"sec_{len(sections):03d}"
                    current_sec = SectionUnit(
                        section_id=sec_id,
                        title=full_block_text,
                        level=2,
                        raw_content=f"## {full_block_text}",
                    )
                    sections.append(current_sec)
                    para_counter = 1
                    continue

                # Standard paragraph
                p_unit = ParagraphUnit(
                    para_id=f"{current_sec.section_id}_p{para_counter:03d}",
                    raw_text=full_block_text,
                    page_num=page_idx,
                    bbox=bbox,
                    font_name=primary_font,
                    font_size=primary_size,
                )
                current_sec.paragraphs.append(p_unit)
                para_counter += 1

        # Reconstruct raw_content for all sections
        for sec in sections:
            para_texts = [p.raw_text for p in sec.paragraphs]
            if sec.title != "__PREAMBLE__":
                sec.raw_content = f"{'#' * sec.level} {sec.title}\n\n" + "\n\n".join(para_texts)
            else:
                sec.raw_content = "\n\n".join(para_texts)

        # Save Book_raw_ast.json
        ast_path = s_dir / "Book_raw_ast.json"
        SectionAST.dump_book_ast_json(sections, ast_path)

        # Save Book_raw.docx
        raw_docx_path = s_dir / "Book_raw.docx"
        doc_out = docx.Document()
        for sec in sections:
            if sec.title != "__PREAMBLE__":
                h_style = f"Heading {min(sec.level, 3)}"
                doc_out.add_paragraph(sec.title, style=h_style)
            for p in sec.paragraphs:
                doc_out.add_paragraph(p.raw_text)
        doc_out.save(str(raw_docx_path))

        return sections, ast_path, raw_docx_path
    finally:
        doc.close()


def extract_raw_from_pdf_ast(
    pdf_path: str | Path,
    session_dir: str | Path,
    split_level: int = 2,
    ai_kaiti: bool = False,
    enable_footnotes: bool = True,
    page_range: Optional[Tuple[int, int]] = None,
) -> Tuple[List[SectionUnit], Path, Path]:
    """
    Convenience function that explicitly invokes the high-precision BookAST extraction path.
    """
    return extract_raw_from_pdf(
        pdf_path=pdf_path,
        session_dir=session_dir,
        split_level=split_level,
        use_vector_ast=True,
        ai_kaiti=ai_kaiti,
        enable_footnotes=enable_footnotes,
        page_range=page_range,
    )


def extract_raw_from_markdown(
    md_text: str,
    session_dir: str | Path,
    split_level: int = 2,
) -> Tuple[List[SectionUnit], Path, Path]:
    """Extracts raw sections from Markdown string or file and serializes Book_raw_ast.json."""
    s_dir = Path(session_dir)
    s_dir.mkdir(parents=True, exist_ok=True)

    sections = SectionAST.from_markdown(md_text, split_level=split_level)
    ast_path = s_dir / "Book_raw_ast.json"
    SectionAST.dump_book_ast_json(sections, ast_path)

    # Create Book_raw.docx
    raw_docx_path = s_dir / "Book_raw.docx"
    doc_out = docx.Document()
    for sec in sections:
        if sec.title != "__PREAMBLE__":
            doc_out.add_paragraph(sec.title, style=f"Heading {min(sec.level, 3)}")
        for p in sec.paragraphs:
            doc_out.add_paragraph(p.raw_text)
    doc_out.save(str(raw_docx_path))

    return sections, ast_path, raw_docx_path


def compile_blueprint_from_seed(
    session_dir: str | Path,
    seed_file_path: str | Path,
    sample_chapters: int = 3,
    manual_boundary_anchor: Optional[str] = None,
    manual_boundary_idx: Optional[int] = None,
) -> BookBlueprint:
    """
    DiffAligner step: compares Book_raw_ast.json (or raw.docx) with seed file.
    Synthesizes book_blueprint.json.
    """
    s_dir = Path(session_dir)
    seed_p = Path(seed_file_path)

    # Ensure seed docx is saved as Book_seed.docx in session_dir
    standard_seed = s_dir / "Book_seed.docx"
    if seed_p.suffix.lower() == ".docx" and seed_p.resolve() != standard_seed.resolve():
        try:
            shutil.copy2(str(seed_p), str(standard_seed))
        except Exception:
            pass

    ast_path = s_dir / "Book_raw_ast.json"
    raw_docx_path = s_dir / "Book_raw.docx"

    if seed_p.suffix.lower() == ".docx" and raw_docx_path.exists():
        blueprint = ExemplarLearner.learn_from_docx_pair(
            raw_docx_path=raw_docx_path,
            golden_docx_path=seed_p,
            sample_chapters=sample_chapters,
            manual_boundary_anchor=manual_boundary_anchor,
            manual_boundary_idx=manual_boundary_idx,
        )
    elif seed_p.suffix.lower() == ".docx":
        blueprint = ExemplarLearner.learn_from_docx_pair(
            raw_docx_path="",
            golden_docx_path=seed_p,
            sample_chapters=sample_chapters,
            manual_boundary_anchor=manual_boundary_anchor,
            manual_boundary_idx=manual_boundary_idx,
        )
    else:
        # Load raw from AST
        sections = SectionAST.load_book_ast_json(ast_path) if ast_path.exists() else []
        raw_md = SectionAST.to_markdown(sections)
        gold_md = seed_p.read_text(encoding="utf-8") if seed_p.suffix.lower() == ".md" else ""
        if not gold_md and seed_p.suffix.lower() == ".docx":
            gold_doc = docx.Document(str(seed_p))
            gold_md = "\n\n".join(p.text for p in gold_doc.paragraphs if p.text.strip())

        raw_md_path = s_dir / "temp_raw.md"
        gold_md_path = s_dir / "temp_gold.md"
        raw_md_path.write_text(raw_md, encoding="utf-8")
        gold_md_path.write_text(gold_md, encoding="utf-8")

        blueprint = ExemplarLearner.learn_from_md_pair(
            raw_md_path=raw_md_path,
            golden_md_path=gold_md_path,
            sample_chapters=sample_chapters,
            manual_boundary_anchor=manual_boundary_anchor,
            manual_boundary_idx=manual_boundary_idx,
        )

    # Record seed docx path in blueprint metadata
    if seed_p.suffix.lower() == ".docx":
        blueprint.metadata["seed_docx_path"] = str(standard_seed.resolve() if standard_seed.exists() else seed_p.resolve())

    # Save blueprint
    bp_path = s_dir / "book_blueprint.json"
    blueprint.save(bp_path)
    return blueprint


_DOCX_TRAILING_HEADING_RE = re.compile(
    r'^(.+[。！？；）\)”’])\s+'
    r'(\d+(?:\.\d+){0,2}[\s\u3000]+[\u4e00-\u9fff]{2,20}|'
    r'[一二三四五六七八九十百]+、[\u4e00-\u9fff]{2,20}|'
    r'[（\(][一二三四五六七八九十]+[）\)][\s\u3000]*[\u4e00-\u9fff]{2,20})\s*$',
    re.DOTALL,
)

_DOCX_STANDALONE_HEADING_RE = re.compile(
    r'^(?:\d+(?:\.\d+){0,2}[\s\u3000]+[\u4e00-\u9fff]{2,20}|'
    r'[一二三四五六七八九十百]+、[\u4e00-\u9fff]{2,20}|'
    r'[（\(][一二三四五六七八九十]+[）\)][\s\u3000]*[\u4e00-\u9fff]{2,20})$'
)


def _is_markdown_pipe_table(text: str) -> bool:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return (
        len(lines) >= 2
        and lines[0].startswith("|")
        and lines[0].endswith("|")
        and bool(re.match(r'^\|[\s\-:|]+\|$', lines[1]))
    )


def _parse_markdown_pipe_table(text: str) -> Tuple[List[str], List[List[str]]]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rows_data: List[List[str]] = []
    for line in lines:
        if re.match(r'^\|[\s\-:|]+\|$', line):
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line[1:-1].split("|")]
            rows_data.append(cells)
    if not rows_data:
        return [], []
    return rows_data[0], rows_data[1:]


def _upgrade_flattened_tables_and_split_headings_in_docx(
    seed_doc: Any,
    ast_sections: List[SectionUnit],
    last_modified_idx: int,
    blueprint: BookBlueprint,
    resolved_pdf: Optional[Path] = None,
) -> Tuple[int, int]:
    """
    Upgrades flattened plain-text tables after `last_modified_idx` in `seed_doc` into real
    Word `Table Grid` (`w:tbl`) objects using reconstructed tables from `Book_raw_ast.json`
    (or `resolved_pdf`), and splits trailing merged headings (e.g. `...。 4 讨论`) into
    standalone Heading paragraphs.

    Returns (upgraded_tables_count, split_headings_count).
    """
    table_source_sections = ast_sections
    has_ast_tables = any(
        p.font_name == "table" or _is_markdown_pipe_table(p.raw_text.strip())
        for sec in ast_sections
        for p in sec.paragraphs
    )
    if not has_ast_tables and resolved_pdf and resolved_pdf.exists() and extract_book_vector_ast is not None:
        try:
            pdf_book_ast = extract_book_vector_ast(resolved_pdf, enable_footnotes=False)
            if pdf_book_ast and pdf_book_ast.sections:
                table_source_sections = pdf_book_ast.sections
        except Exception:
            pass

    flat_ast_paras_with_sec: List[Tuple[SectionUnit, ParagraphUnit]] = [
        (sec, p) for sec in table_source_sections for p in sec.paragraphs
    ]
    reconstructed_tables: List[Dict[str, Any]] = []
    for idx, (sec_obj, p_ast) in enumerate(flat_ast_paras_with_sec):
        raw_t = p_ast.raw_text.strip()
        if p_ast.font_name == "table" or _is_markdown_pipe_table(raw_t):
            headers, rows = _parse_markdown_pipe_table(raw_t)
            if not headers:
                continue
            table_id = ""
            caption_text = ""
            for back_k in range(idx - 1, max(-1, idx - 4), -1):
                cand_txt = flat_ast_paras_with_sec[back_k][1].raw_text.strip()
                m_cap = re.match(r'^表\s*(\d+)', cand_txt)
                if m_cap and not re.match(r'^表\s*\d+\s*(?:示|显示|结果|表明|可见)', cand_txt):
                    table_id = f"表{m_cap.group(1)}"
                    caption_text = cand_txt
                    break
            if not table_id and sec_obj.title:
                m_sec_cap = re.match(r'^表\s*(\d+)', sec_obj.title.strip())
                if m_sec_cap:
                    table_id = f"表{m_sec_cap.group(1)}"
                    caption_text = sec_obj.title.strip()
            cell_corpus = "".join(
                re.sub(r'\s+', '', c)
                for c in (headers + [c for r in rows for c in r])
            )
            reconstructed_tables.append({
                "table_id": table_id,
                "caption_text": caption_text,
                "headers": headers,
                "rows": rows,
                "cell_corpus": cell_corpus,
                "used": False,
            })

    upgraded_tables_count = 0
    if reconstructed_tables:
        paras_list = list(seed_doc.paragraphs)
        i = max(0, last_modified_idx + 1)
        while i < len(paras_list):
            cap_p = paras_list[i]
            cap_txt = ExemplarLearner.strip_boundary_tags(cap_p.text).strip()
            m_cap = re.match(r'^表\s*(\d+)', cap_txt)
            if not m_cap or re.match(r'^表\s*\d+\s*(?:示|显示|结果|表明|可见)', cap_txt):
                i += 1
                continue

            cand_table_id = f"表{m_cap.group(1)}"
            matched_entry = None
            for entry in reconstructed_tables:
                if not entry["used"] and entry["table_id"] == cand_table_id:
                    matched_entry = entry
                    break

            if matched_entry is None:
                i += 1
                continue

            # Skip if already followed by a real Word table (w:tbl)
            next_el = cap_p._p.getnext()
            if next_el is not None and next_el.tag.endswith("}tbl"):
                matched_entry["used"] = True
                i += 1
                continue

            # Collect contiguous flattened table remnant paragraphs following cap_p
            corpus = matched_entry["cell_corpus"]
            remnants_to_remove = []
            j = i + 1
            while j < len(paras_list):
                rem_p = paras_list[j]
                rem_txt = ExemplarLearner.strip_boundary_tags(rem_p.text).strip()
                if not rem_txt:
                    j += 1
                    continue
                if (
                    re.match(r'^注[：:]', rem_txt)
                    or re.match(r'^(?:表\s*\d+\s*(?:示|显示|结果|表明|可见)|由表\s*\d+|从表\s*\d+|见表\s*\d+)', rem_txt)
                    or re.match(r'^表\s*\d+[\s\u3000]', rem_txt)
                    or rem_txt.endswith("。")
                    or rem_txt.endswith("；")
                    or ExemplarLearner.is_pure_boundary_tag(rem_p.text)
                    or _DOCX_STANDALONE_HEADING_RE.match(rem_txt)
                ):
                    break

                tokens = [re.sub(r'\s+', '', t) for t in re.split(r'[\s\u3000|]+', rem_txt) if t.strip()]
                if not tokens:
                    break
                matched_tokens = sum(1 for t in tokens if t in corpus)
                compact_rem = re.sub(r'[\s\u3000|]+', '', rem_txt)
                matched_chars = sum(1 for ch in compact_rem if ch in corpus)
                token_ratio = matched_tokens / len(tokens)
                char_ratio = matched_chars / max(1, len(compact_rem))

                if token_ratio >= 0.5 or char_ratio >= 0.7:
                    remnants_to_remove.append(rem_p)
                    j += 1
                else:
                    break

            headers = matched_entry["headers"]
            rows = matched_entry["rows"]
            num_cols = len(headers)
            num_rows = 1 + len(rows)
            table = seed_doc.add_table(rows=num_rows, cols=num_cols)
            try:
                table.style = "Table Grid"
            except Exception:
                pass
            table.alignment = WD_TABLE_ALIGNMENT.CENTER

            for col_idx, h_text in enumerate(headers):
                cell = table.cell(0, col_idx)
                cell.text = ""
                p_cell = cell.paragraphs[0]
                try:
                    p_cell.style = "Normal"
                except Exception:
                    pass
                p_cell.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p_cell.add_run(h_text)
                run.bold = True

            for row_idx, r_data in enumerate(rows, start=1):
                for col_idx in range(num_cols):
                    val = r_data[col_idx] if col_idx < len(r_data) else ""
                    cell = table.cell(row_idx, col_idx)
                    cell.text = ""
                    p_cell = cell.paragraphs[0]
                    try:
                        p_cell.style = "Normal"
                    except Exception:
                        pass
                    p_cell.alignment = WD_ALIGN_PARAGRAPH.CENTER if col_idx > 0 else WD_ALIGN_PARAGRAPH.LEFT
                    p_cell.add_run(val)

            cap_p._p.addnext(table._tbl)
            for rem_p in remnants_to_remove:
                p_el = rem_p._element
                if p_el.getparent() is not None:
                    p_el.getparent().remove(p_el)

            matched_entry["used"] = True
            upgraded_tables_count += 1
            i = j

    # Part B: Split trailing merged section headings (e.g. "...（疗效对比时剔除）。 4 　讨论")
    split_headings_count = 0
    paras_after_tables = list(seed_doc.paragraphs)
    for idx, p_obj in enumerate(paras_after_tables):
        if idx <= last_modified_idx:
            continue
        raw_p_txt = p_obj.text.strip()
        if not raw_p_txt:
            continue
        m_split = _DOCX_TRAILING_HEADING_RE.match(raw_p_txt)
        if m_split:
            body_part = m_split.group(1).strip()
            heading_part = m_split.group(2).strip()
            p_obj.text = body_part

            new_h_p = seed_doc.add_paragraph(heading_part)
            is_sub = bool(
                re.match(r'^\d+\.\d+', heading_part)
                or re.match(r'^[（\(][一二三四五六七八九十]+[）\)]', heading_part)
            )
            h_key = "H3" if is_sub else "H2"
            fallback_h_style = "Heading 3" if is_sub else "Heading 2"
            target_h_style = (blueprint.heading_hierarchy or {}).get(h_key, fallback_h_style)
            try:
                new_h_p.style = target_h_style
            except Exception:
                try:
                    new_h_p.style = fallback_h_style
                except Exception:
                    pass
            p_obj._p.addnext(new_h_p._p)
            split_headings_count += 1

    return upgraded_tables_count, split_headings_count


def propagate_and_validate_session(
    session_dir: str | Path,
    engine_mode: str = "rule_first",
    template_docx_path: Optional[str | Path] = None,
    custom_blueprint: Optional[BookBlueprint] = None,
    pdf_path: Optional[str | Path] = None,
    ai_client: Optional[Any] = None,
    model: Optional[str] = None,
    max_sections: Optional[int] = None,
    manual_boundary_anchor: Optional[str] = None,
    manual_boundary_idx: Optional[int] = None,
) -> Tuple[Path, ValidationReport, BookBlueprint]:
    """
    Executes batch AST propagation across all sections, runs visual fallback if needed,
    and runs PODIntegrityValidator. Outputs Book_POD_Final.docx and audit_report.json.

    engine_mode:
        - "rule_first": High-speed 0-token state machine + targeted VLM badge fallback.
        - "vlm_continuation": End-to-end multimodal visual infilling (Gemini / Ollama).
    """
    s_dir = Path(session_dir)
    ast_path = s_dir / "Book_raw_ast.json"
    if not ast_path.exists():
        raise FileNotFoundError(f"Missing {ast_path} in session workspace.")

    sections = SectionAST.load_book_ast_json(ast_path)

    # Resolve blueprint
    if custom_blueprint:
        blueprint = custom_blueprint
    else:
        bp_path = s_dir / "book_blueprint.json"
        if not bp_path.exists():
            raise FileNotFoundError(f"Missing {bp_path} in session workspace.")
        blueprint = BookBlueprint.load(bp_path)

    if blueprint.metadata is None:
        blueprint.metadata = {}

    if manual_boundary_anchor and manual_boundary_anchor.strip():
        blueprint.metadata["manual_boundary_anchor"] = manual_boundary_anchor.strip()
        blueprint.metadata["boundary_source"] = "manual_anchor"
    if manual_boundary_idx is not None and int(manual_boundary_idx) >= 0:
        blueprint.metadata["manual_boundary_idx"] = int(manual_boundary_idx)
        blueprint.metadata["seed_last_modified_idx"] = int(manual_boundary_idx)
        blueprint.metadata["boundary_source"] = "manual_idx"

    effective_anchor = (
        manual_boundary_anchor.strip()
        if (manual_boundary_anchor and manual_boundary_anchor.strip())
        else blueprint.metadata.get("manual_boundary_anchor")
    )
    effective_idx = (
        int(manual_boundary_idx)
        if (manual_boundary_idx is not None and int(manual_boundary_idx) >= 0)
        else blueprint.metadata.get("manual_boundary_idx")
    )

    # Resolve PDF
    resolved_pdf = None
    if pdf_path and Path(pdf_path).exists():
        resolved_pdf = Path(pdf_path)
    else:
        candidates = list(s_dir.glob("*.pdf"))
        if candidates:
            resolved_pdf = candidates[0]

    engine = PropagationEngine(blueprint)

    if engine_mode == "vlm_continuation":
        # Resolve seed docx
        seed_candidates = list(s_dir.glob("*seed*.docx")) + list(s_dir.glob("*Seed*.docx"))
        seed_docx = seed_candidates[0] if seed_candidates else (s_dir / "Book_seed.docx")

        from .vlm_continuation_engine import SecureVLMContinuationEngine
        import asyncio

        vlm_engine = SecureVLMContinuationEngine(workspace_base=s_dir.parent)
        vlm_model = model or os.getenv("DEFAULT_AI_MODEL") or "gemini-3.8-flash"

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # In nested event loop environment
                import nest_asyncio  # type: ignore[import-not-found]
                nest_asyncio.apply()
                continuation_result = loop.run_until_complete(
                    vlm_engine.execute_continuation(
                        pdf_path=resolved_pdf or Path(""),
                        raw_ast_path=ast_path,
                        seed_docx_path=seed_docx,
                        template_docx_path=Path(template_docx_path) if template_docx_path else None,
                        model_name=vlm_model,
                        max_continuation_sections=max_sections,
                        target_session_dir=s_dir,
                        manual_boundary_anchor=effective_anchor,
                        manual_boundary_idx=effective_idx,
                    )
                )
            else:
                continuation_result = loop.run_until_complete(
                    vlm_engine.execute_continuation(
                        pdf_path=resolved_pdf or Path(""),
                        raw_ast_path=ast_path,
                        seed_docx_path=seed_docx,
                        template_docx_path=Path(template_docx_path) if template_docx_path else None,
                        model_name=vlm_model,
                        max_continuation_sections=max_sections,
                        target_session_dir=s_dir,
                        manual_boundary_anchor=effective_anchor,
                        manual_boundary_idx=effective_idx,
                    )
                )
        except RuntimeError:
            continuation_result = asyncio.run(
                vlm_engine.execute_continuation(
                    pdf_path=resolved_pdf or Path(""),
                    raw_ast_path=ast_path,
                    seed_docx_path=seed_docx,
                    template_docx_path=Path(template_docx_path) if template_docx_path else None,
                    model_name=vlm_model,
                    max_continuation_sections=max_sections,
                    target_session_dir=s_dir,
                    manual_boundary_anchor=effective_anchor,
                    manual_boundary_idx=effective_idx,
                )
            )

        processed_sections = continuation_result.processed_sections or sections

    else:
        # Step A: Deterministic Rule Propagation
        engine = PropagationEngine(blueprint)
        processed_sections = engine.process_all(sections)

        # Step B: Visual Fallback Repair (if PDF provided and sections miss required badges)
        if resolved_pdf and blueprint.mandatory_section_badges:
            for sec in processed_sections:
                if sec.title == "__PREAMBLE__":
                    continue
                existing_badges = set(re.findall(r'【([^】]+)】|\[([^\]]+)\]', sec.effective_content))
                flattened = {b[0] or b[1] for b in existing_badges}
                missing = [b for b in blueprint.mandatory_section_badges if b not in flattened]
                if missing and sec.paragraphs:
                    first_p = sec.paragraphs[0]
                    if first_p.page_num > 0:
                        try:
                            repaired_md = repair_corrupted_section_with_vlm(
                                pdf_path=resolved_pdf or Path(""),
                                page_num=first_p.page_num,
                                corrupted_raw_md=sec.effective_content,
                                blueprint=blueprint,
                                ai_client=ai_client,
                                bbox=first_p.bbox,
                                missing_badges=missing,
                                model=model,
                            )
                            if not repaired_md.startswith("<!--"):
                                sec.processed_content = repaired_md
                        except Exception:
                            pass

    # ── Step B2: Automatic Completion & Refinement of Subsequent Unmodified Paragraphs in Seed DOCX ──
    seed_docx_candidates = [
        s_dir / "Book_seed.docx",
    ]
    if blueprint.metadata and blueprint.metadata.get("seed_docx_path"):
        seed_docx_candidates.append(Path(blueprint.metadata["seed_docx_path"]))
    for f in s_dir.glob("*.docx"):
        if f.name not in ("Book_raw.docx", "Book_POD_Final.docx", "template.docx"):
            seed_docx_candidates.append(f)

    seed_docx_path = None
    for cand in seed_docx_candidates:
        if cand and Path(cand).exists() and Path(cand).suffix.lower() == ".docx":
            seed_docx_path = Path(cand)
            break

    final_docx_path = s_dir / "Book_POD_Final.docx"

    if engine_mode != "vlm_continuation":
        if seed_docx_path:
            seed_doc = docx.Document(str(seed_docx_path))
            last_modified_idx = int(blueprint.metadata.get("seed_last_modified_idx", 0)) if blueprint.metadata else 0

            if effective_idx is not None and int(effective_idx) >= 0:
                last_modified_idx = min(int(effective_idx), max(0, len(seed_doc.paragraphs) - 1))
                blueprint.metadata["seed_last_modified_idx"] = last_modified_idx
            elif effective_anchor:
                anchor_matches = [
                    i for i, p in enumerate(seed_doc.paragraphs)
                    if effective_anchor in p.text
                ]
                if anchor_matches:
                    last_modified_idx = anchor_matches[-1]
                    blueprint.metadata["seed_last_modified_idx"] = last_modified_idx

            if last_modified_idx == 0 and blueprint.metadata.get("boundary_source") not in ("manual_idx", "manual_anchor", "builtin_tag"):
                generic_styles = {
                    "normal", "body text", "內文", "標準",
                    "heading 1", "heading 2", "heading 3", "heading 4", "heading 5",
                    "title", "subtitle", "標題 1", "標題 2", "標題 3"
                }
                custom_indices = [
                    i for i, p in enumerate(seed_doc.paragraphs)
                    if p.style and p.style.name and p.style.name.strip().lower() not in generic_styles and p.text.strip()
                ]
                if custom_indices:
                    last_modified_idx = max(custom_indices)
                else:
                    non_normal = [
                        i for i, p in enumerate(seed_doc.paragraphs)
                        if p.style and p.style.name not in ("Normal", "Body Text", "內文", "標準") and p.text.strip()
                    ]
                    last_modified_idx = max(non_normal) if non_normal else 0

            # Upgrade flattened three-line tables into Word Table Grid objects and split merged headings
            upgraded_tbls, split_hdgs = _upgrade_flattened_tables_and_split_headings_in_docx(
                seed_doc=seed_doc,
                ast_sections=sections,
                last_modified_idx=last_modified_idx,
                blueprint=blueprint,
                resolved_pdf=resolved_pdf,
            )
            if blueprint.metadata is not None:
                blueprint.metadata["upgraded_tables_count"] = upgraded_tbls
                blueprint.metadata["split_headings_count"] = split_hdgs

            # Extract subsequent paragraphs that were unmodified by human editor
            subsequent_paras = [
                (i, ExemplarLearner.strip_boundary_tags(p.text))
                for i, p in enumerate(seed_doc.paragraphs)
                if i > last_modified_idx and ExemplarLearner.strip_boundary_tags(p.text)
            ]

            # Hybrid deterministic + Gemini AI paragraph classification
            classified_styles = engine.classify_paragraphs_hybrid(
                subsequent_paras,
                ai_client=ai_client,
                model=model,
            )

            # Apply target styles to subsequent paragraphs in seed_doc
            text_to_style: Dict[str, str] = {}
            for p_idx, target_style in classified_styles.items():
                if target_style and target_style != "Normal":
                    p_obj = seed_doc.paragraphs[p_idx]
                    try:
                        p_obj.style = target_style
                    except Exception:
                        pass
                    text_to_style[ExemplarLearner.strip_boundary_tags(p_obj.text)] = target_style

            # Strip any temporary in-document boundary marker tags before saving final output
            for p_obj in list(seed_doc.paragraphs):
                if ExemplarLearner.is_pure_boundary_tag(p_obj.text):
                    p_el = p_obj._element
                    if p_el.getparent() is not None:
                        p_el.getparent().remove(p_el)
                elif any(tag in p_obj.text for tag in ExemplarLearner.BOUNDARY_TAGS):
                    p_obj.text = ExemplarLearner.strip_boundary_tags(p_obj.text)

            # Direct perfection of the same .docx as final output
            seed_doc.save(str(final_docx_path))

            # Synchronize AST processed_sections for Markdown & Validator
            for sec in processed_sections:
                sec.paragraphs = [
                    p_ast for p_ast in sec.paragraphs
                    if not ExemplarLearner.is_pure_boundary_tag(p_ast.raw_text)
                ]
                for p_ast in sec.paragraphs:
                    if any(tag in p_ast.raw_text for tag in ExemplarLearner.BOUNDARY_TAGS):
                        p_ast.raw_text = ExemplarLearner.strip_boundary_tags(p_ast.raw_text)
                    raw_txt = p_ast.raw_text.strip()
                    if text_to_style and not p_ast.custom_style and raw_txt in text_to_style:
                        p_ast.custom_style = text_to_style[raw_txt]
                sec.raw_content = ExemplarLearner.strip_boundary_tags(sec.raw_content)
                sec.processed_content = ExemplarLearner.strip_boundary_tags(sec.effective_content)
        else:
            # Fallback to synthesizing new document from processed sections via unified DocxSerializer
            DocxSerializer.render_sections_to_docx(
                sections=processed_sections,
                output_docx_path=final_docx_path,
                template_docx_path=template_docx_path,
                base_dir=s_dir,
            )
    else:
        # VLM Continuation mode: render full continued sections to Book_POD_Final.docx
        DocxSerializer.render_sections_to_docx(
            sections=processed_sections,
            output_docx_path=final_docx_path,
            template_docx_path=template_docx_path,
            base_dir=s_dir,
        )

    # Step C: Defensive Verification Gatekeeper
    validator = PodValidator(
        blueprint=blueprint,
        template_docx_path=template_docx_path,
    )
    report = validator.validate_all(processed_sections)

    # Save audit_report.json
    audit_path = s_dir / "audit_report.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

    # Automated layout architecture mode: Export Book_POD_Final.md
    final_md_path = s_dir / "Book_POD_Final.md"
    full_md_content = "\n\n".join(sec.effective_content for sec in processed_sections)
    final_md_path.write_text(full_md_content, encoding="utf-8")

    return final_docx_path, report, blueprint
