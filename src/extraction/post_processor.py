#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Markdown Postprocessing Deep Module
===================================
Encapsulates semantic dictionary heading adjustments, CMap normalization,
rare character verification, and output anomaly validation behind a unified seam.
"""

import logging
from pathlib import Path
from typing import NamedTuple, Dict, Optional, Callable, Any

logger = logging.getLogger(__name__)


class OutputAnomalyError(Exception):
    """Raised when postprocessing output length drops abnormally below safety threshold."""
    def __init__(self, input_len: int, output_len: int, threshold: float, sample: str):
        self.input_len = input_len
        self.output_len = output_len
        self.threshold = threshold
        super().__init__(
            f"Postprocessing anomaly check failed: input_len={input_len}, output_len={output_len}, "
            f"shrink_ratio={1.0 - (output_len / max(input_len, 1)):.1%} > threshold={threshold:.0%} | "
            f"Sample prefix: {sample!r}"
        )


class PostProcessResult(NamedTuple):
    """Result of markdown postprocessing, supporting tuple unpacking (markdown, rare_char_stats)."""
    markdown: str
    rare_char_stats: Dict[str, Any]


class MarkdownPostProcessor:
    """
    Deep module responsible for all Markdown text post-reconstruction steps.
    Combines dictionary demotion, static character mapping, and suspicious glyph auditing.
    """

    def __init__(self, anomaly_threshold: float = 0.60):
        self.anomaly_threshold = anomaly_threshold

    def process(
        self,
        markdown_text: str,
        pdf_name: str,
        output_dir: str,
        style_mapping: Optional[Dict] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        enable_dictionary_postprocess: bool = True,
    ) -> PostProcessResult:
        """
        Execute unified postprocessing on reconstructed Markdown.

        Args:
            markdown_text: Raw Markdown reconstructed from vector or OCR extraction.
            pdf_name: Stem or filename of the source document for reporting.
            output_dir: Output folder where audit review reports are stored.
            style_mapping: Optional Word style mapping dictionary.
            progress_callback: Optional callable(percent: int, message: str).
            enable_dictionary_postprocess: Whether to apply dictionary semantic demotion.

        Returns:
            PostProcessResult with .markdown and .rare_char_stats.
        """
        if not markdown_text or not isinstance(markdown_text, str):
            logger.warning("MarkdownPostProcessor: Received empty or invalid markdown text.")
            return PostProcessResult(markdown="", rare_char_stats={})

        input_len = len(markdown_text)
        current_text = markdown_text

        # ── Step 1: Dictionary Domain Demotion ──
        if enable_dictionary_postprocess:
            try:
                from src.scripts.dictionary_post_processor import postprocess_dictionary_markdown
                current_text = postprocess_dictionary_markdown(current_text, style_mapping)
                
                # Anomaly length safety check
                output_len = len(current_text)
                if input_len > 200 and output_len < (input_len * (1.0 - self.anomaly_threshold)):
                    sample = current_text[:100]
                    raise OutputAnomalyError(input_len, output_len, self.anomaly_threshold, sample)

                if progress_callback:
                    progress_callback(81, "[INFO] 已套用辭典專用語意修正器 (自動降級詞條標題與楷體區隔)")
            except OutputAnomalyError as e:
                logger.error(f"Dictionary postprocess anomaly: {e}")
                raise
            except Exception as e:
                logger.warning(f"無法套用 dictionary_post_processor: {e}")
                if progress_callback:
                    progress_callback(81, f"[WARN] 辭典語意修正略過: {e}")

        # ── Step 2: Rare Character & CMap Verification ──
        rare_char_stats = {}
        try:
            from src.scripts.ocr_rare_char_corrector import postprocess_ocr_markdown
            try:
                from config import PATHS
                data_dir = str(PATHS.data_dir)
            except ImportError:
                data_dir = str(Path(__file__).resolve().parents[2] / "data")

            current_text, rare_char_stats = postprocess_ocr_markdown(
                markdown_text=current_text,
                data_dir=data_dir,
                pdf_name=pdf_name,
                output_dir=output_dir,
            )

            corrected = rare_char_stats.get("corrections_applied", 0)
            suspicious = rare_char_stats.get("suspicious_chars_found", 0)

            if progress_callback:
                if corrected > 0:
                    progress_callback(88, f"[INFO] 靜態字典自動修正了 {corrected} 處已知錯字。")
                if suspicious > 0:
                    progress_callback(89, f"[REVIEW] ⚠️ 偵測到 {suspicious} 處可疑字元（疑似生僻字/亂碼），覆核報告已生成。")
        except ImportError as e:
            logger.warning(f"無法載入 ocr_rare_char_corrector: {e}")
        except Exception as e:
            logger.error(f"生僻字校驗處理失敗: {e}")

        return PostProcessResult(markdown=current_text, rare_char_stats=rare_char_stats)


def postprocess_markdown(
    markdown_text: str,
    pdf_name: str,
    output_dir: str,
    style_mapping: Optional[Dict] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    enable_dictionary_postprocess: bool = True,
) -> PostProcessResult:
    """Convenience function delegating to MarkdownPostProcessor."""
    processor = MarkdownPostProcessor()
    return processor.process(
        markdown_text=markdown_text,
        pdf_name=pdf_name,
        output_dir=output_dir,
        style_mapping=style_mapping,
        progress_callback=progress_callback,
        enable_dictionary_postprocess=enable_dictionary_postprocess,
    )


# Backward-compatible alias
run_unified_postprocessing = postprocess_markdown
