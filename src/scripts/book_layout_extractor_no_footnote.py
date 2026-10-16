# -*- coding: utf-8 -*-
"""
Backward-compatibility wrapper for book_layout_extractor_no_footnote.
This shim delegates all functionality to src.scripts.book_layout_extractor
with no_footnote=True, eliminating ~760 lines of code duplication.
"""
from __future__ import annotations

import functools
from src.scripts.book_layout_extractor import *
import src.scripts.book_layout_extractor as _base_module

_orig_process = _base_module.process_book_vector_pdf


@functools.wraps(_orig_process)
def process_book_vector_pdf(*args, **kwargs):
    kwargs.setdefault("no_footnote", True)
    return _orig_process(*args, **kwargs)
