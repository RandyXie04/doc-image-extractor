# -*- coding: utf-8 -*-
"""
Backward-compatibility wrapper for process_ocr_no_footnote.
This shim delegates all functionality to src.scripts.process_ocr
with no_footnote=True, eliminating ~750 lines of code duplication.
"""
from __future__ import annotations

import functools
import sys
from src.scripts.process_ocr import *
import src.scripts.process_ocr as _base_module

_orig_process_page_footnotes = _base_module.process_page_footnotes


@functools.wraps(_orig_process_page_footnotes)
def process_page_footnotes(*args, **kwargs):
    kwargs.setdefault("no_footnote", True)
    return _orig_process_page_footnotes(*args, **kwargs)


_orig_main = _base_module.main


@functools.wraps(_orig_main)
def main(args=None):
    if args is not None:
        setattr(args, "no_footnote", True)
    return _orig_main(args)


if __name__ == '__main__':
    if "--no_footnote" not in sys.argv:
        sys.argv.append("--no_footnote")
    main()
