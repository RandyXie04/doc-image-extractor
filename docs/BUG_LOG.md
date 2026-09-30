# BUG LOG

## BUG-004: Every indented paragraph is split after the first line
**Status:** CLOSED
**Description:** The user reported that "unexplained line breaks became more severe". My previous fix changed the logic to flush the paragraph if the block is NOT indented but the `current_para_x0` was indented. This caused the first line of every normally indented paragraph to be split from the rest of its paragraph.
**Expected Behavior:** A normally indented paragraph (first line indented, subsequent lines not indented) should be treated as a single paragraph. Kaiti quotes (all lines indented) should also be treated as a single paragraph.
**Actual Behavior:** The first line of a normal paragraph is split into its own paragraph.
**Root Cause:** The logic `elif not is_indented and (current_para_x0 - base_x0) >= 12.0: should_flush = True` is flawed. It flushes when a non-indented line follows an indented line, which is exactly the structure of a normal paragraph.
**Decision Required:** No new design decision is required.
