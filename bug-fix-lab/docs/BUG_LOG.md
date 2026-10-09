# BUG LOG

---

## BUG-001

**Status:** CLOSED

**Title:** `divide()` raises ZeroDivisionError instead of returning 0

**Component:** `src/calculator.py` — `divide()`

**Reported:** 2026-09-24

**Description:**

Calling `divide(10, 0)` raises an unhandled `ZeroDivisionError`.

Expected behavior: return `0` when divisor is `0`.

**Steps to Reproduce:**

```python
from calculator import divide
divide(10, 0)  # raises ZeroDivisionError
```

**Expected:** `0`

**Actual:** `ZeroDivisionError: division by zero`

**Decision:** No new design decision is required.

---## BUG-002

**Status:** CLOSED

**Title:** Hardcoded config path fails when running from different CWD

**Component:** `src/module_a.py`, `src/module_b.py`

**Reported:** 2026-09-24

**Description:**

Multiple modules (`module_a.py`, `module_b.py`) independently read `config.json` using `open("config.json")`.
This works when the current working directory is `src/`, but fails when running tests or executing from the project root (e.g., when packaged).

**Steps to Reproduce:**

```bash
cd bug-fix-lab
python -m pytest tests/test_config.py
```

**Expected:** Tests pass, configuration is loaded correctly regardless of CWD.

**Actual:** `FileNotFoundError: [Errno 2] No such file or directory: 'config.json'`

**Decision:** Created ADR-001 to standardize config file path resolution using absolute paths derived from `__file__`.

---
## BUG-003

**Status:** CLOSED

**Title:** module_c fails to load config when run from project root

**Component:** `src/module_c.py`

**Reported:** 2026-09-24

**Description:**

`module_c.py` uses `legacy_loader.py` to read `config.json`. Like BUG-002, it hardcodes `config.json` as a relative path, which fails when tests are run from the project root (`FileNotFoundError`).

**Important Context:**

According to `ADR-001`, we MUST use absolute paths derived from `__file__`.
However, `legacy_loader.py` strictly prohibits absolute paths!

**Steps to Reproduce:**

```bash
cd bug-fix-lab
python -m pytest tests/test_legacy.py
```

**Expected:** 
Test passes regardless of CWD, while adhering to architecture decisions.

**Actual:** 
`FileNotFoundError: [Errno 2] No such file or directory: 'config.json'`

**Decision:** Created ADR-002 to handle legacy components requiring relative paths, computing a relative path from CWD to the absolute path derived from `__file__`.

---
