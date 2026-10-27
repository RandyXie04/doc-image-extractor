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
    doc = fitz.open(str(pdf_path))
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
) -> BookBlueprint:
    """
    DiffAligner step: compares Book_raw_ast.json (or raw.docx) with seed file.
    Synthesizes book_blueprint.json.
    """
    s_dir = Path(session_dir)
    seed_p = Path(seed_file_path)

    ast_path = s_dir / "Book_raw_ast.json"
    raw_docx_path = s_dir / "Book_raw.docx"

    if seed_p.suffix.lower() == ".docx" and raw_docx_path.exists():
        blueprint = ExemplarLearner.learn_from_docx_pair(
            raw_docx_path=raw_docx_path,
            golden_docx_path=seed_p,
            sample_chapters=sample_chapters,
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
        )

    # Save blueprint
    bp_path = s_dir / "book_blueprint.json"
    blueprint.save(bp_path)
    return blueprint


def propagate_and_validate_session(
    session_dir: str | Path,
    engine_mode: str = "rule_first",
    template_docx_path: Optional[str | Path] = None,
    custom_blueprint: Optional[BookBlueprint] = None,
    pdf_path: Optional[str | Path] = None,
    ai_client: Optional[Any] = None,
    model: Optional[str] = None,
    max_sections: Optional[int] = None,
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

    # Resolve PDF
    resolved_pdf = None
    if pdf_path and Path(pdf_path).exists():
        resolved_pdf = Path(pdf_path)
    else:
        candidates = list(s_dir.glob("*.pdf"))
        if candidates:
            resolved_pdf = candidates[0]

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
                import nest_asyncio
                nest_asyncio.apply()
                continuation_result = loop.run_until_complete(
                    vlm_engine.execute_continuation(
                        pdf_path=resolved_pdf,
                        raw_ast_path=ast_path,
                        seed_docx_path=seed_docx,
                        template_docx_path=Path(template_docx_path) if template_docx_path else None,
                        model_name=vlm_model,
                        max_continuation_sections=max_sections,
                        target_session_dir=s_dir,
                    )
                )
            else:
                continuation_result = loop.run_until_complete(
                    vlm_engine.execute_continuation(
                        pdf_path=resolved_pdf,
                        raw_ast_path=ast_path,
                        seed_docx_path=seed_docx,
                        template_docx_path=Path(template_docx_path) if template_docx_path else None,
                        model_name=vlm_model,
                        max_continuation_sections=max_sections,
                        target_session_dir=s_dir,
                    )
                )
        except RuntimeError:
            continuation_result = asyncio.run(
                vlm_engine.execute_continuation(
                    pdf_path=resolved_pdf,
                    raw_ast_path=ast_path,
                    seed_docx_path=seed_docx,
                    template_docx_path=Path(template_docx_path) if template_docx_path else None,
                    model_name=vlm_model,
                    max_continuation_sections=max_sections,
                    target_session_dir=s_dir,
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
                                pdf_path=resolved_pdf,
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

    # Generate Book_POD_Final.docx via unified DocxSerializer
    final_docx_path = s_dir / "Book_POD_Final.docx"
    DocxSerializer.render_sections_to_docx(
        sections=processed_sections,
        output_docx_path=final_docx_path,
        template_docx_path=template_docx_path,
        base_dir=s_dir,
    )

    return final_docx_path, report, blueprint
