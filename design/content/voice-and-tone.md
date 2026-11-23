# UX Content: Voice, Tone & Terminology

Guidelines for Traditional Chinese UI copy in `doc-image-extractor`.

## Core Principles

1. **Truthful Group Labels**: Section titles must accurately describe every item they contain (e.g., use `核心工作流程` for pipeline pages and `專項輔助工具` for standalone utilities; never label non-OCR utilities as OCR settings).
2. **Role-Consistent Mode Terminology**:
   - `editor` mode: `出版社編輯模式` (pill: `編輯`)
   - `dev` mode: `工程師除錯模式` (pill: `除錯`)
3. **WCAG 2.5.3 Label-in-Name**: Toggle controls display clear visible text (`外觀主題：淺色模式` / `外觀主題：深色模式`) and convey pressed state via `aria-pressed`, without conflicting `aria-label` strings that omit visible text.
4. **Contextual Quotas**: Read-only system guardrails (`200 MB` upload / `20 MB` template / `24 小時` retention) live in the system status popover and upload validation messages rather than permanently occupying primary settings space.
