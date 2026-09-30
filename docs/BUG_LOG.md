# BUG LOG

## BUG-004: Every indented paragraph is split after the first line
**Status:** CLOSED
**Description:** The user reported that "unexplained line breaks became more severe". My previous fix changed the logic to flush the paragraph if the block is NOT indented but the `current_para_x0` was indented. This caused the first line of every normally indented paragraph to be split from the rest of its paragraph.
**Expected Behavior:** A normally indented paragraph (first line indented, subsequent lines not indented) should be treated as a single paragraph. Kaiti quotes (all lines indented) should also be treated as a single paragraph.
**Actual Behavior:** The first line of a normal paragraph is split into its own paragraph.
**Root Cause:** The logic `elif not is_indented and (current_para_x0 - base_x0) >= 12.0: should_flush = True` is flawed. It flushes when a non-indented line follows an indented line, which is exactly the structure of a normal paragraph.
**Decision Required:** No new design decision is required.

## BUG-005: UnicodeEncodeError for emoji in book_layout_extractor.py
**Status:** CLOSED
**Description:** When running `pdf_engine_dispatcher.py --engine pymupdf`, it fails with `UnicodeEncodeError: 'cp950' codec can't encode character '\u2705'`.
**Expected Behavior:** Should print successfully without crashing on Windows consoles.
**Actual Behavior:** Crashes due to un-encodeable emoji on `cp950` terminal.
**Root Cause:** Hardcoded emoji characters `✅` and `⚠️` in `print()` statements caused a `UnicodeEncodeError` when running via subprocess on Windows with `cp950` default encoding.
**Fix:** Removed emojis from the print statements. No new design decision was required.

## BUG-006: AttributeError in Surya OCR layout detection
**Status:** CLOSED
**Description:** When running `pdf_engine_dispatcher.py --engine suryaocr`, `process_ocr.py` fails with `AttributeError: 'dict' object has no attribute 'pause_token_id'` inside `batch_layout_detection`.
**Expected Behavior:** Should run layout detection successfully.
**Actual Behavior:** Crashes because `model.config.decoder` appears to be a dict instead of an object with attributes in the newer Transformers/Surya version.
**Root Cause:** The `layout_model` was incorrectly instantiated using the `load_model` function from `surya.model.detection.model` instead of the correct `load_model` function from `surya.model.layout.model`. Detection models use a different architecture, leading to mismatched configs when passed to `batch_layout_detection`.
**Fix:** Updated imports in `process_ocr.py` to use `load_layout_model` and `load_layout_processor` from the `surya.model.layout` module. Removed the invalid `checkpoint` kwarg from `load_layout_processor()`. No new design decision was required.
