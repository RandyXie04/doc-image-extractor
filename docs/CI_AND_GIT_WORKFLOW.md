# CI/CD Pipeline & Git Branch Workflow Guide

This document defines the repository's GitHub Actions CI architecture, mandatory local verification checks, and Git branching/PR policy for major feature fixes and new project modules.

---

## 1. Git Branch & PR Workflow (Mandatory Policy)

All **major feature fixes**, **architectural refactors**, and **new project modules** must follow a branch-and-PR workflow:

1. **Sync & Branch from `main`** (never commit directly to `main`; never use the legacy `master` branch):
   ```bash
   git fetch origin
   git checkout main
   git pull --ff-only origin main
   git checkout -b feat/<module-or-feature>   # or fix/<issue>, refactor/<scope>, ci/<scope>
   ```
2. **Implement strictly within scope** and add/update unit & regression tests under `tests/`.
3. **Run all 4 local CI checks** (see Section 2) before pushing.
4. **Push to your dedicated branch and open a PR to `main`**:
   ```bash
   git push -u origin <your-branch>
   ```
5. **Merge only after GitHub Actions `CI Gate` is green**.

### Recommended GitHub Branch Protection Settings (`main`)
- Require a pull request before merging.
- Require status checks to pass before merging: select **`CI Gate`** (aggregator job in `.github/workflows/ci.yml`).
- Disable force pushes and branch deletion on `main`.

---

## 2. Local Pre-Push CI Verification Commands

Run these commands from the repository root before pushing your branch.

### Pillar 1 — Lint
```powershell
# Python critical lint gate (configured in pyproject.toml)
ruff check src main.py config tests

# Validate JSON configs
python -c "import json, pathlib; [json.loads(pathlib.Path(f).read_text(encoding='utf-8-sig')) for f in ['pyrightconfig.json','version.json','frontend/package.json','frontend/tsconfig.json','config/fonts.json','config/symbol_mapping.json']]; print('JSON configs OK')"
```

### Pillar 2 — Typecheck
```powershell
# Python strict typecheck gate (contracts, API routers, plugins, entrypoints)
python -m pyright main.py src/web/app.py src/web/dependencies.py src/web/schemas.py src/web/routers/ocr_router.py src/web/routers/pod_router.py src/web/routers/system_router.py src/web/routers/tools_router.py src/extraction/contracts.py src/plugins src/scripts/generate_ts_contracts.py

# Also typecheck any modified Python files
python -m pyright <your_modified_files>

# Frontend TypeScript & JS (checkJs) typecheck
Set-Location frontend; npm run typecheck; Set-Location ..
```

### Pillar 3 — Build & Contract Parity
```powershell
# Python bytecode compile check (catches syntax/indentation errors across the codebase)
python -m compileall -q -f src main.py config tests

# Verify Pydantic v2 -> TypeScript contract parity
python src/scripts/generate_ts_contracts.py --check

# Frontend build check
Set-Location frontend; npm run build; Set-Location ..
```

### Pillar 4 — Unit & Regression Tests (Non-Heavy)
```powershell
$env:HF_HUB_OFFLINE = "1"
$env:YOLO_CONFIG_DIR = "$env:TEMP\ultralytics"
python -m pytest --ignore=tests/e2e --ignore=tests/test_formula_recognizer_stress.py -m "not heavy" -k "not test_recognition_predictor_blank_crop_short_circuit_with_index_preservation"
```

> **Heavy / GPU / GUI / `surya`-Coupled Tests**:
> - Tests marked `@pytest.mark.heavy` (including `tests/e2e/`, `tests/test_adversarial_formula_detector.py`, `tests/test_formula_detector.py`, `tests/test_formula_detector_adversarial.py`, `tests/test_ocr_crop_clamp_adversarial.py`, `tests/test_ocr_layout_and_crop_stress.py`, and live CUDA/MFD tests) are automatically deselected by `-m "not heavy"`.
> - `tests/test_formula_recognizer_stress.py` and `test_recognition_predictor_blank_crop_short_circuit_with_index_preservation` import/patch `surya.recognition`, which is omitted from lightweight `requirements-ci.txt` to avoid multi-GB ML installs in CI.
> Run these suites manually on local workstations with models, `surya-ocr`, and desktop GUI available when touching those subsystems.

---

## 3. GitHub Actions CI Architecture (`.github/workflows/ci.yml`)

| Job | Runner | Responsibility | Blocking |
| :--- | :--- | :--- | :--- |
| `lint` | `ubuntu-latest` | `ruff check` (`E9`, `F63`, `F7`, `F82` via `pyproject.toml`) + JSON config validation | Yes |
| `typecheck-python` | `ubuntu-latest` | `pyright` strict gate on contracts/API/plugins + advisory full-repo baseline report | Strict gate: Yes; Full baseline: Advisory |
| `build-and-check` | `ubuntu-latest` | `python -m compileall`, `generate_ts_contracts.py --check`, `npm run build` (`tsc --noEmit --pretty false`) | Yes |
| `test-unit-regression` | `windows-latest` | Non-heavy `pytest` unit & regression suite + `coverage.xml` artifact (uses `requirements-ci.txt` with `defusedxml`, `pypandoc-binary`, `onnx`, `google-genai` + CPU-only `torch`) | Yes |
| `security-scan` | `ubuntu-latest` | `bandit -r src main.py -ll` (Medium & High SAST, baseline clean as of `496a3c2`) + advisory `pip-audit -r requirements-ci.txt` | Bandit `-ll`: Yes; `pip-audit`: Advisory |
| `ci-gate` | `ubuntu-latest` | Aggregates all 5 jobs for a single Branch Protection required check | Yes |

### Triggers
- `push` to `main`, `feat/**`, `fix/**`, `ci/**`, `refactor/**`, `chore/**`
- `pull_request` targeting `main`
- `workflow_dispatch` (manual trigger)

---

## 4. Historical Context (Why Previous CI/CD Broke or Disappeared)

- **Deleted CD workflow (`.github/workflows/release.yml`)**: Originally added in `a9a60322` / `059125b0` for tag-triggered PyInstaller EXE releases. Intentionally deleted in `d06b7822` (`refactor: modularize codebase...`) when the application migrated from a PyInstaller/pywebview desktop executable to a FastAPI web application. `origin/master` was left frozen at `2c409ff` (over 120 commits behind `main`).
- **Previous `ci.yml` gaps (introduced in `a3cd38f7`)**:
  1. Installed full `requirements.txt` (including broken `opencv-python==5.0.0.93` pin and multi-GB CUDA `torch`/`ultralytics`/`surya-ocr`) even for the 10-minute `frontend-typecheck` job.
  2. Lacked Python lint (`ruff`), Python typecheck (`pyright`), Python build/compile checks, and a unified `CI Gate` aggregator job.
  3. Ran `pytest -m "not heavy"` without excluding un-marked tests requiring gitignored local ONNX/Surya weights or CUDA GPUs, and lacked Pandoc (`pypandoc-binary`) and `beautifulsoup4`/`latex2mathml` in CI dependencies.
  4. `pyrightconfig.json` previously hardcoded a personal local path (`C:/Users/randy/...`) and Python `3.13`.
