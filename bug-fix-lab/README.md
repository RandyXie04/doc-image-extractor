# bug-fix-lab

A minimal closed-loop test environment for validating the three-skill bug-fix workflow in Antigravity.

## Purpose

Verify that three Skills can mutually constrain Agent behavior:

| Skill | Responsibility |
|---|---|
| `bug-fix` | Root cause analysis, main workflow control |
| `decision-log` | Check → reuse or create ADR |
| `regression-test` | Verify fix, detect regressions, return result |

## Validation Criteria (Phase 1)

| Test | Pass Condition |
|---|---|
| Root Cause | Agent identifies root cause, not just symptom |
| Decision Gate | Agent correctly judges ADR needed / not needed |
| Decision Reuse | Agent does not duplicate existing ADR |
| Regression | Agent always runs tests after code change |
| Failure Loop | FAIL in regression sends Agent back to bug-fix |

## Project Structure

```
bug-fix-lab/
├─ .agents/
│  ├─ skills/
│  │  ├─ bug-fix/SKILL.md
│  │  ├─ decision-log/SKILL.md
│  │  └─ regression-test/SKILL.md
│  └─ rules/
│     └─ completion-gate.md
├─ src/
│  └─ calculator.py
├─ tests/
│  └─ test_calculator.py
└─ docs/
   ├─ BUG_LOG.md
   └─ DECISIONS.md
```

## Running Tests

```bash
cd bug-fix-lab
python -m pytest tests/ -v
```

## Current Bugs

- BUG-001: `divide()` raises ZeroDivisionError instead of returning 0 — **OPEN**