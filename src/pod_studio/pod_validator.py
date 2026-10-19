# -*- coding: utf-8 -*-
"""
POD Validator (Completion Gatekeeper)
=====================================
CLI-friendly validation gatekeeper for Antigravity, Claude Code, and Codex.
Enforces book-specific quality gates without rigid hardcoded assumptions:
- Flowcheck: text conservation (adaptive threshold)
- Badges: only checked if the book archetype has mandatory recurring badges
- Numbering: only checked if the book uses sequential numbered items
- Styles: validates custom-style against template.docx / allowed styles
"""

from __future__ import annotations
import re
import sys
import zipfile
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Any

from .blueprint_schema import BookBlueprint, ValidationConfig
from .section_ast import SectionUnit, SectionAST

try:
    from src.extraction.post_processor import OutputAnomalyError
except ImportError:
    class OutputAnomalyError(Exception):
        pass


@dataclass
class ValidationViolation:
    section_id: str
    title: str
    check_type: str         # "flowcheck" | "badge" | "numbering" | "style"
    message: str
    severity: str = "ERROR" # "ERROR" | "WARNING"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationReport:
    total_sections: int
    passed_sections: int
    failed_sections: int
    violations: List[ValidationViolation] = field(default_factory=list)
    strict_mode: bool = False

    @property
    def is_valid(self) -> bool:
        if self.strict_mode:
            return len(self.violations) == 0
        return self.failed_sections == 0 and not any(v.severity == "ERROR" for v in self.violations)

    def summary(self) -> str:
        status_sym = "✅ PASS" if self.is_valid else "❌ FAIL"
        lines = [
            f"=== POD Validation Report: {status_sym} ===",
            f"Total Sections: {self.total_sections} | Passed: {self.passed_sections} | Failed: {self.failed_sections}",
            f"Total Violations: {len(self.violations)}",
        ]
        if self.violations:
            lines.append("\nViolations Breakdown:")
            for v in self.violations:
                lines.append(f"  [{v.severity}] [{v.check_type.upper()}] {v.section_id} ({v.title}): {v.message}")
        return "\n".join(lines)


class PodValidator:
    """Adaptive gatekeeper ensuring zero structural defects according to book blueprint."""

    CIRCLED_NUMS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]
    CHINESE_NUMS = ["（一）", "（二）", "（三）", "（四）", "（五）", "（六）", "（七）", "（八）", "（九）", "（十）"]

    def __init__(
        self,
        blueprint: BookBlueprint,
        template_docx_path: Optional[str | Path] = None,
        max_shrink_ratio: Optional[float] = None,
    ):
        self.blueprint = blueprint
        self.config: ValidationConfig = getattr(blueprint, "validation_config", ValidationConfig())

        # Override max_shrink_ratio if explicitly passed
        self.max_shrink_ratio = max_shrink_ratio if max_shrink_ratio is not None else self.config.max_shrink_ratio
        self.template_styles: Set[str] = set(blueprint.template_styles_used)

        if template_docx_path and Path(template_docx_path).exists():
            extracted_styles = self.extract_styles_from_docx(template_docx_path)
            self.template_styles.update(extracted_styles)

    @staticmethod
    def extract_styles_from_docx(docx_path: str | Path) -> Set[str]:
        """Reads word/styles.xml from a .docx file and returns all valid style names and IDs."""
        styles = set()
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        try:
            with zipfile.ZipFile(str(docx_path), "r") as z:
                if "word/styles.xml" in z.namelist():
                    tree = ET.fromstring(z.read("word/styles.xml"))
                    for style_elem in tree.findall("w:style", ns):
                        style_id = style_elem.get(f"{{{ns['w']}}}styleId")
                        if style_id:
                            styles.add(style_id)
                        name_elem = style_elem.find("w:name", ns)
                        if name_elem is not None:
                            val = name_elem.get(f"{{{ns['w']}}}val")
                            if val:
                                styles.add(val)
        except Exception:
            pass
        return styles

    def validate_section(self, section: SectionUnit) -> List[ValidationViolation]:
        """Validates a single section against configured quality dimensions."""
        violations: List[ValidationViolation] = []
        if section.title == "__PREAMBLE__" or section.level == 0:
            return violations

        content = section.effective_content

        # 1. Flowcheck (Text conservation check) - only if enabled
        if self.config.enable_flowcheck:
            raw_len = len(section.raw_content)
            proc_len = len(content)
            if raw_len > 100:
                shrink_ratio = (raw_len - proc_len) / raw_len
                if shrink_ratio > self.max_shrink_ratio:
                    violations.append(ValidationViolation(
                        section_id=section.section_id,
                        title=section.title,
                        check_type="flowcheck",
                        message=f"正文字數大幅縮水: 原文 {raw_len} 字 -> 處理後 {proc_len} 字 (縮減 {shrink_ratio:.1%} > 上限 {self.max_shrink_ratio:.0%})",
                        severity="ERROR",
                    ))

        # 2. Schema Check: Mandatory Badges - only if enabled AND book has mandatory badges
        if self.config.enable_badge_check and self.blueprint.mandatory_section_badges:
            existing_badges = set(re.findall(r'【([^】]+)】|\[([^\]]+)\]', content))
            prefix_badges = set(re.findall(r'(?:^|[\n\r])\s*([問答QA材料步驟作法解析案情評析提示注意要點病案分析]{1,6})[：:]', content))
            flattened_badges = {b[0] or b[1] for b in existing_badges} | prefix_badges

            for badge in self.blueprint.mandatory_section_badges:
                if badge not in flattened_badges:
                    violations.append(ValidationViolation(
                        section_id=section.section_id,
                        title=section.title,
                        check_type="badge",
                        message=f"缺少本篇必備排版標籤: 【{badge}】",
                        severity="ERROR",
                    ))

        # 3. Numbering Continuity Check - only if enabled for this book
        if self.config.enable_numbering_check:
            found_circled = [c for c in self.CIRCLED_NUMS if c in content]
            if len(found_circled) >= 2:
                indices = [self.CIRCLED_NUMS.index(c) for c in found_circled]
                expected_indices = list(range(indices[0], indices[0] + len(indices)))
                if indices != expected_indices:
                    missing = [self.CIRCLED_NUMS[i] for i in expected_indices if i not in indices]
                    violations.append(ValidationViolation(
                        section_id=section.section_id,
                        title=section.title,
                        check_type="numbering",
                        message=f"圓圈數字斷號或缺漏: 出現 {found_circled}，缺失 {missing}",
                        severity="WARNING",
                    ))

        # 4. Style Check: Pandoc Custom Style Validation - only if enabled
        if self.config.enable_style_check and self.template_styles:
            custom_styles = re.findall(r':::\s*\{\s*custom-style="([^"]+)"\s*\}', content)
            for s in custom_styles:
                if s not in self.template_styles and s != "Normal":
                    violations.append(ValidationViolation(
                        section_id=section.section_id,
                        title=section.title,
                        check_type="style",
                        message=f"使用了未在樣式庫定義的樣式: '{s}'",
                        severity="WARNING",
                    ))

        return violations

    def validate_all(self, sections: List[SectionUnit]) -> ValidationReport:
        """Validates all sections and aggregates the report."""
        all_violations: List[ValidationViolation] = []
        failed_count = 0

        for sec in sections:
            sec_violations = self.validate_section(sec)
            if sec_violations:
                all_violations.extend(sec_violations)
                if any(v.severity == "ERROR" for v in sec_violations):
                    failed_count += 1
                elif self.config.strict_mode:
                    failed_count += 1

        total = len([s for s in sections if s.title != "__PREAMBLE__"])
        passed = max(0, total - failed_count)

        return ValidationReport(
            total_sections=total,
            passed_sections=passed,
            failed_sections=failed_count,
            violations=all_violations,
            strict_mode=self.config.strict_mode,
        )


def main():
    parser = argparse.ArgumentParser(description="POD Validator CLI Gatekeeper")
    parser.add_argument("--workspace", help="Path to section AST workspace")
    parser.add_argument("--markdown", help="Path to full Markdown file to validate")
    parser.add_argument("--blueprint", required=True, help="Path to BookBlueprint JSON")
    parser.add_argument("--template", help="Path to template.docx to verify style compliance")
    parser.add_argument("--max-shrink", type=float, help="Override max allowed text shrink ratio")
    parser.add_argument("--disable-badge-check", action="store_true", help="Disable mandatory badge check")
    parser.add_argument("--disable-numbering-check", action="store_true", help="Disable numbering continuity check")
    parser.add_argument("--strict", action="store_true", help="Fail even on warnings")
    args = parser.parse_args()

    bp = BookBlueprint.load(args.blueprint)

    # CLI option overrides
    if args.disable_badge_check:
        bp.validation_config.enable_badge_check = False
    if args.disable_numbering_check:
        bp.validation_config.enable_numbering_check = False
    if args.strict:
        bp.validation_config.strict_mode = True

    if args.workspace:
        sections = SectionAST.load_from_workspace(args.workspace)
    elif args.markdown:
        md_text = Path(args.markdown).read_text(encoding="utf-8")
        sections = SectionAST.from_markdown(md_text)
    else:
        print("Error: Specify either --workspace or --markdown")
        sys.exit(2)

    validator = PodValidator(
        blueprint=bp,
        template_docx_path=args.template,
        max_shrink_ratio=args.max_shrink,
    )

    report = validator.validate_all(sections)
    print(report.summary())

    if not report.is_valid:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
