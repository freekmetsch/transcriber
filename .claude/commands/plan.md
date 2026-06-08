---
description: Full planning workflow — intake, discovery, harden audit, sustainable option selection, critique, and execution-ready handoff
---

> See `.claude/commands/__common.md` for repo context.
> Base: `C:\Users\metsc\.claude\commands\__base-plan.md` — read and apply first.

## Repo Overrides

### §2a Fix-Mode Discovery

Source `~/.claude/commands/__base-diag.md` before optioning. Apply these transcriber overrides on top:

**§4 Evidence matrix**
- Config state: `config.yaml` / `config.local.yaml` present, active mode + provider selection.
- Data state: `brain.db` vocabulary populated/empty, malformed config, missing model cache.
- Environment: Windows desktop, GPU/CUDA available vs CPU-only, Python version, faster-whisper model downloaded.
- Timeline/regression window: what changed and when.
- Trace lineage: caller → callee (e.g., `app.py → recorder.py → transcriber.py → postprocessor.py → output.py`).
- Trace lateral: a working mode's path vs the failing path.

**§5 User-in-the-loop checks**
- What the system-tray indicator / notification shows vs what `transcriber.log` records.
- GPU path vs CPU-fallback behavior.
- Specific inputs that trigger vs don't (active mode, language, very long dictation, silence/empty audio).

**§6 Logging example**
`logging.debug('[DIAG-LOG] transcriber: result', extra={'audio_len': n, 'mode': mode, 'text': text})`

### §3 Audits — the audit table for this repo

- **Harden** — execute `/harden` §2-3 on the scope. Skip only when scope is pure docs/copy (R0) with zero code change; state the reason.
- **Stack Discipline** (conditional) — when the plan introduces a new tool/library/service/framework in a trigger category (auth, payments, observability, hosting, ORM/DB, real-time, caching, email, file storage, forms, styling, state mgmt, background jobs, data fetching, feature flags), follow `~/.claude/commands/__base-stack-discipline.md`. Recommended tools become chosen-approach justifications; rejected alternatives become rejected-alternatives entries. Skip when no trigger category is touched; state the skip reason.

Run inline — findings feed option selection and critique.

### §4 Option Selection — tiebreaker

Point 2 = Idiomatic Python — modern patterns for the stack (clean threading for the capture/hotkey loop, faster-whisper + provider SDK usage, Pydantic/typed config).
