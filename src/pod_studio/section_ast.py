# -*- coding: utf-8 -*-
"""
Section AST & Book AST Serialization
====================================
Chunks whole-book Markdown documents into isolated, verifiable Section AST units
(sec_000.md ~ sec_XXX.md) to avoid line-number drift and LLM context window overflows.
Stores paragraph-level geometry (page_num, bbox, font_name, font_size) in Book_raw_ast.json.
"""

from __future__ import annotations
import re
import json
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Sequence


@dataclass
class ParagraphUnit:
    """Represents a fine-grained paragraph with optional PDF geometric coordinates."""
    para_id: str
    raw_text: str
    processed_text: str = ""
    page_num: int = 0
    bbox: Optional[List[float]] = None     # [x0, y0, x1, y1]
    font_name: str = ""
    font_size: float = 0.0
    custom_style: str = ""
    injected_badge: Optional[str] = None
    is_deleted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ParagraphUnit:
        return cls(
            para_id=data.get("para_id", ""),
            raw_text=data.get("raw_text", ""),
            processed_text=data.get("processed_text", ""),
            page_num=data.get("page_num", 0),
            bbox=data.get("bbox"),
            font_name=data.get("font_name", ""),
            font_size=data.get("font_size", 0.0),
            custom_style=data.get("custom_style", ""),
            injected_badge=data.get("injected_badge"),
            is_deleted=data.get("is_deleted", False),
        )


@dataclass
class SectionUnit:
    """Represents an isolated chunk/chapter/unit of a book in the AST."""
    section_id: str
    title: str
    level: int = 2
    raw_content: str = ""
    processed_content: str = ""
    paragraphs: List[ParagraphUnit] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def effective_content(self) -> str:
        """Returns rendered content from paragraphs if populated, else processed_content or raw_content."""
        if self.paragraphs:
            chunks = []
            for p in self.paragraphs:
                if p.is_deleted:
                    continue
                txt = p.processed_text if p.processed_text.strip() else p.raw_text
                if p.injected_badge and not txt.startswith(p.injected_badge):
                    txt = f"{p.injected_badge}{txt}"
                if p.custom_style and p.custom_style != "Normal" and "custom-style=" not in txt:
                    txt = f'::: {{custom-style="{p.custom_style}"}}\n{txt}\n:::'
                if txt.strip():
                    chunks.append(txt.strip())
            return "\n\n".join(chunks)

        return self.processed_content if self.processed_content.strip() else self.raw_content

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["paragraphs"] = [p.to_dict() if isinstance(p, ParagraphUnit) else p for p in self.paragraphs]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SectionUnit:
        paras = [ParagraphUnit.from_dict(p) if isinstance(p, dict) else p for p in data.get("paragraphs", [])]
        return cls(
            section_id=data.get("section_id", ""),
            title=data.get("title", ""),
            level=data.get("level", 2),
            raw_content=data.get("raw_content", ""),
            processed_content=data.get("processed_content", ""),
            paragraphs=paras,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class BookAST:
    """Represents the complete structured in-memory AST of a book."""
    sections: List[SectionUnit]
    image_blocks: List[Dict[str, Any]] = field(default_factory=list)
    audit_data: Dict[str, Any] = field(default_factory=dict)
    pdf_name: str = ""
    total_pages: int = 0
    doc_profile: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pdf_name": self.pdf_name,
            "total_pages": self.total_pages,
            "doc_profile": self.doc_profile,
            "sections": [s.to_dict() for s in self.sections],
            "image_blocks": self.image_blocks,
            "audit_data": self.audit_data,
        }


class SectionAdapter:
    """Adapts a BookAST to existing consumers expecting List[SectionUnit]."""
    @staticmethod
    def to_sections(ast: Optional[BookAST]) -> List[SectionUnit]:
        if ast is None:
            return []
        return ast.sections


class SectionAST:
    """Manages splitting, serialization, workspace caching, and reassembly of sections."""

    @staticmethod
    def from_markdown(md_text: str, split_level: int = 2, populate_paragraphs: bool = True) -> List[SectionUnit]:
        """
        Splits Markdown text into SectionUnits based on headings up to split_level (e.g. ## for level 2).
        Heading 1 (#) and Heading 2 (##) boundaries are respected.
        """
        heading_pattern = re.compile(
            r'^(#{1,' + str(split_level) + r'})\s+(.+?)(?:\s*\{#[^\}]+\})?\s*$',
            re.MULTILINE
        )
        matches = list(heading_pattern.finditer(md_text))

        sections: List[SectionUnit] = []
        global_para_idx = 1

        if not matches:
            sec = SectionUnit(
                section_id="sec_001",
                title="__DOCUMENT__",
                level=1,
                raw_content=md_text.strip(),
            )
            if populate_paragraphs:
                sec.paragraphs = SectionAST._text_to_paragraphs(sec.raw_content, sec.section_id)
            sections.append(sec)
            return sections

        # Preamble before the first heading
        first_start = matches[0].start()
        if first_start > 0:
            preamble_text = md_text[:first_start].strip()
            if preamble_text:
                p_sec = SectionUnit(
                    section_id="sec_000",
                    title="__PREAMBLE__",
                    level=0,
                    raw_content=preamble_text,
                )
                if populate_paragraphs:
                    p_sec.paragraphs = SectionAST._text_to_paragraphs(preamble_text, p_sec.section_id)
                sections.append(p_sec)

        for i, m in enumerate(matches):
            sec_idx = len(sections)
            sec_id = f"sec_{sec_idx:03d}"
            level = len(m.group(1))
            title = m.group(2).strip()

            start_pos = m.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)

            content = md_text[start_pos:end_pos].strip()
            sec = SectionUnit(
                section_id=sec_id,
                title=title,
                level=level,
                raw_content=content,
            )
            if populate_paragraphs:
                sec.paragraphs = SectionAST._text_to_paragraphs(content, sec_id)
            sections.append(sec)

        return sections

    @staticmethod
    def _text_to_paragraphs(text: str, section_id: str) -> List[ParagraphUnit]:
        """Converts raw text into a list of ParagraphUnit instances."""
        paragraphs: List[ParagraphUnit] = []
        raw_paras = [p.strip() for p in text.split("\n\n") if p.strip()]
        for idx, p in enumerate(raw_paras, 1):
            p_id = f"{section_id}_p{idx:03d}"
            paragraphs.append(ParagraphUnit(
                para_id=p_id,
                raw_text=p,
            ))
        return paragraphs

    @staticmethod
    def to_markdown(sections: List[SectionUnit], use_processed: bool = True) -> str:
        """Reassembles section units back into a complete Markdown document."""
        chunks = []
        for sec in sections:
            content = sec.effective_content if use_processed else sec.raw_content
            if content.strip():
                chunks.append(content.strip())
        return "\n\n".join(chunks) + "\n"

    @staticmethod
    def dump_book_ast_json(sections: List[SectionUnit], file_path: str | Path) -> Path:
        """Serializes full document AST with geometric coordinates to Book_raw_ast.json."""
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = [s.to_dict() for s in sections]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return p

    @staticmethod
    def load_book_ast_json(file_path: str | Path) -> List[SectionUnit]:
        """Loads sections with full paragraph metadata from Book_raw_ast.json."""
        p = Path(file_path)
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [SectionUnit.from_dict(item) for item in data]

    @staticmethod
    def dump_to_workspace(workspace_dir: str | Path, sections: List[SectionUnit]) -> Path:
        """
        Dumps each section to an individual Markdown file in workspace_dir
        and creates a catalog.json index for rapid random access.
        """
        ws_path = Path(workspace_dir)
        ws_path.mkdir(parents=True, exist_ok=True)

        catalog: List[Dict[str, Any]] = []
        for sec in sections:
            filename = f"{sec.section_id}.md"
            sec_file = ws_path / filename

            # Write content
            with open(sec_file, "w", encoding="utf-8") as f:
                f.write(sec.effective_content)

            catalog.append({
                "section_id": sec.section_id,
                "title": sec.title,
                "level": sec.level,
                "file": filename,
                "metadata": sec.metadata,
                "raw_len": len(sec.raw_content),
                "processed_len": len(sec.effective_content),
                "paragraph_count": len(sec.paragraphs),
            })

        catalog_path = ws_path / "catalog.json"
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)

        # Also store Book_raw_ast.json inside workspace for full geometric tracking
        SectionAST.dump_book_ast_json(sections, ws_path / "Book_raw_ast.json")

        return ws_path

    @staticmethod
    def load_from_workspace(workspace_dir: str | Path) -> List[SectionUnit]:
        """Loads section units back from a workspace folder."""
        ws_path = Path(workspace_dir)
        ast_path = ws_path / "Book_raw_ast.json"
        if ast_path.exists():
            return SectionAST.load_book_ast_json(ast_path)

        catalog_path = ws_path / "catalog.json"
        sections: List[SectionUnit] = []
        if catalog_path.exists():
            with open(catalog_path, "r", encoding="utf-8") as f:
                catalog = json.load(f)
            for item in catalog:
                sec_file = ws_path / item["file"]
                content = sec_file.read_text(encoding="utf-8") if sec_file.exists() else ""
                sections.append(SectionUnit(
                    section_id=item["section_id"],
                    title=item["title"],
                    level=item.get("level", 2),
                    raw_content=content,
                    processed_content=content,
                    metadata=item.get("metadata", {}),
                ))
        else:
            # Fallback: scan for sec_*.md
            for sec_file in sorted(ws_path.glob("sec_*.md")):
                content = sec_file.read_text(encoding="utf-8")
                sec_id = sec_file.stem
                first_line = content.splitlines()[0] if content.splitlines() else ""
                m = re.match(r'^(#+)\s+(.+)', first_line)
                level = len(m.group(1)) if m else 2
                title = m.group(2).strip() if m else sec_id
                sections.append(SectionUnit(
                    section_id=sec_id,
                    title=title,
                    level=level,
                    raw_content=content,
                    processed_content=content,
                ))

        return sections


def main():
    parser = argparse.ArgumentParser(description="Section AST Utility for POD Studio")
    parser.add_argument("--split", help="Path to input Markdown file to split into sections")
    parser.add_argument("--out-dir", default="scratch/pod_workspace", help="Workspace folder")
    parser.add_argument("--join", help="Path to workspace directory to reassemble into Markdown")
    parser.add_argument("--output", help="Output Markdown path for join")
    args = parser.parse_args()

    if args.split:
        p = Path(args.split)
        if not p.exists():
            print(f"Error: {p} does not exist")
            return
        content = p.read_text(encoding="utf-8")
        secs = SectionAST.from_markdown(content)
        out_ws = SectionAST.dump_to_workspace(args.out_dir, secs)
        print(f"Successfully split {len(secs)} sections into {out_ws}")

    elif args.join:
        secs = SectionAST.load_from_workspace(args.join)
        md_text = SectionAST.to_markdown(secs)
        out_path = Path(args.output or "reassembled.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md_text, encoding="utf-8")
        print(f"Successfully joined {len(secs)} sections into {out_path}")


if __name__ == "__main__":
    main()
