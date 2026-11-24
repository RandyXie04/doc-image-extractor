---
trigger: always_on
description: Mandatory Git branching, local CI verification, and PR workflow guardrails for major feature fixes and new project modules.
---

# Git Branch & CI Engineering Guardrails

These rules apply whenever implementing **major feature fixes**, **architectural refactors**, or **new project modules** (e.g., new routers, plugins, extraction engines, POD Studio workflows, or frontend modules).

## 1. Branch-First Rule (Never Work Directly on `main`)

- **Do NOT commit directly to `main`** for major feature fixes, refactors, or new modules.
- Always create a dedicated branch from up-to-date `main` before making edits:
  - New module / feature: `feat/<short-kebab-name>`
  - Major bug fix: `fix/<short-kebab-name>`
  - Refactor: `refactor/<short-kebab-name>`
  - CI / tooling / docs: `ci/<short-kebab-name>` or `chore/<short-kebab-name>`
- `origin/master` is an obsolete legacy branch and must **never** be used as a target or base branch. Always target `main`.

## 2. Mandatory Local CI Gate (Run Before Pushing)

Before pushing a branch or opening a Pull Request, run **all four CI pillars** locally and verify they pass:

1. **Lint**:
   - Python: `ruff check src main.py config tests` (configured in `pyproject.toml`).
   - Config JSON validity: verify modified JSON files parse cleanly.
2. **Typecheck**:
   - Python strict gate:
     ```bash
     python -m pyright main.py src/web/app.py src/web/dependencies.py src/web/schemas.py src/web/routers/ocr_router.py src/web/routers/pod_router.py src/web/routers/system_router.py src/web/routers/tools_router.py src/extraction/contracts.py src/plugins src/scripts/generate_ts_contracts.py
     ```
   - Also run `python -m pyright <modified_files>` on every Python file you added or changed to ensure zero new type errors.
   - Frontend (when Node.js is available or `frontend/` / `src/web/static/js/` is touched):
     ```bash
     cd frontend && npm run typecheck
     ```
3. **Build & Contract Parity**:
   - Python bytecode compilation: `python -m compileall -q -f src main.py config tests`
   - Pydantic -> TypeScript contract check: `python src/scripts/generate_ts_contracts.py --check`
   - Frontend build check (when Node.js is available): `cd frontend && npm run build`
4. **Unit & Regression Tests (Non-Heavy)**:
   - Run targeted tests for the changed module first, then run the full non-heavy CI regression suite:
     ```bash
     python -m pytest --ignore=tests/e2e --ignore=tests/test_formula_detector_adversarial.py -m "not heavy" -k "not (test_solid_color_and_random_noise_canvases or test_recognition_predictor_live_cuda_inference or test_full_m2_pipeline_dense_text_document or test_peak_vram_under_2500mb_at_batch_size_32 or test_pod_stage1_pdf_upload_and_stage2_inplace_table_upgrade)"
     ```
   - For Windows environments, set `YOLO_CONFIG_DIR` to a writable temp folder if running YOLO-touching tests.

## 3. Push to Branch & Pull Request Policy

- Push commits **only to the dedicated feature/fix branch** (`git push -u origin <branch-name>`) — never force-push `main`.
- Open a Pull Request targeting `main` and wait for the GitHub Actions **`CI Gate`** workflow (`.github/workflows/ci.yml`) to turn green before merging.
- Keep commits atomic and strictly scoped to the task; do not bundle unrelated edits or out-of-scope files.

## 4. Handling Pre-Existing Baselines & Missing Local Tools

- Never silently skip a CI pillar.
- If a local binary is unavailable (e.g., `ruff` or `node`/`tsc` not installed on a workstation) or a pre-existing baseline failure exists in untouched out-of-scope code, record it explicitly in your handoff / PR description and verify it passes in GitHub Actions `.github/workflows/ci.yml`.
- See `docs/CI_AND_GIT_WORKFLOW.md` for full local commands, CI job definitions, and heavy-vs-CI test separation.
