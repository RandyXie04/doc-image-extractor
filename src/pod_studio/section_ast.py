# -*- coding: utf-8 -*-
"""
Section AST
===========
Chunks whole-book Markdown documents into isolated, verifiable Section AST units
(sec_000.md ~ sec_XXX.md) to avoid line-number drift and LLM context window overflows.
"""

from __future__ import annotations
import re
import json
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional


@dataclass
class SectionUnit:
    """Represents an isolated chunk/chapter/recipe of a book in the AST."""
    section_id: str
    title: str
    level: int = 2
    raw_content: str = ""
    processed_content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def effective_content(self) -> str:
        """Returns processed_content if present and non-empty, otherwise raw_content."""
        return self.processed_content if self.processed_content.strip() else self.raw_content

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SectionUnit:
        return cls(
            section_id=data.get("section_id", ""),
            title=data.get("title", ""),
            level=data.get("level", 2),
            raw_content=data.get("raw_content", ""),
            processed_content=data.get("processed_content", ""),
            metadata=dict(data.get("metadata", {})),
        )


class SectionAST:
    """Manages splitting, serialization, workspace caching, and reassembly of sections."""

    @staticmethod
    def from_markdown(md_text: str, split_level: int = 2) -> List[SectionUnit]:
        """
        Splits Markdown text into SectionUnits based on headings up to split_level (e.g. ## for level 2).
        Heading 1 (#) and Heading 2 (##) boundaries are respected.
        """
        # Match headings: e.g., ^(#{1,split_level})\s+(.*)$
        heading_pattern = re.compile(r'^(#{1,' + str(split_level) + r'})\s+(.+?)(?:\s*\{#[^\}]+\})?\s*$', re.MULTILINE)
        matches = list(heading_pattern.finditer(md_text))

        sections: List[SectionUnit] = []
        if not matches:
            # Whole document is a single section
            sections.append(SectionUnit(
                section_id="sec_001",
                title="__DOCUMENT__",
                level=1,
                raw_content=md_text.strip(),
            ))
            return sections

        # Preamble before the first heading
        first_start = matches[0].start()
        if first_start > 0:
            preamble_text = md_text[:first_start].strip()
            if preamble_text:
                sections.append(SectionUnit(
                    section_id="sec_000",
                    title="__PREAMBLE__",
                    level=0,
                    raw_content=preamble_text,
                ))

        for i, m in enumerate(matches):
            sec_idx = len(sections)
            sec_id = f"sec_{sec_idx:03d}"
            level = len(m.group(1))
            title = m.group(2).strip()

            start_pos = m.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)

            content = md_text[start_pos:end_pos].strip()
            sections.append(SectionUnit(
                section_id=sec_id,
                title=title,
                level=level,
                raw_content=content,
            ))

        return sections

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
                "processed_len": len(sec.processed_content),
            })

        catalog_path = ws_path / "catalog.json"
        with open(catalog_path, "w", encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)

        return ws_path

    @staticmethod
    def load_from_workspace(workspace_dir: str | Path) -> List[SectionUnit]:
        """Loads section units back from a workspace folder."""
        ws_path = Path(workspace_dir)
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
                # Extract title from first heading if present
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
