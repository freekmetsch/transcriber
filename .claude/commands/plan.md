---
description: Full planning workflow — intake, discovery, harden audit, sustainable option selection, critique, and execution-ready handoff
---

> See `.claude/commands/__common.md` for repo context.
> Base: `C:\Users\metsc\.claude\commands\__base-plan.md` — read and apply first.

## Repo Overrides

### §2a Fix-Mode Discovery

Source `~/.claude/commands/__base-diag.md` before optioning. Apply these transcriber overrides on top:

**§4 Evidence matrix**
- Config state: env vars present/missing, provider selection.
- Data state: vault empty/populated, malformed markdown, missing folders.
- Environment: local/Docker, Windows/Linux, Python version.
- Timeline/regression window: what changed and when.
- Trace lineage (use `docs/FLOW.md` if its `Last verified` is current): caller → callee (e.g., `bot.py → processor.py → vault.py`).
- Trace lateral: similar working code paths vs failing path.

**§5 User-in-the-loop checks**
- What Telegram shows vs what the bot logs.
- Docker logs vs local run behavior.
- Specific message types that trigger vs don't trigger the issue.
- Edge cases (voice vs text, Dutch vs English, very long input, empty input).

**§6 Logging example**
`logging.debug('[DIAG-LOG] processor: classification result', extra={'input': text, 'result': result})`

### §3 Audits — the audit table for this repo

- **Harden** — execute `/harden` §2-3 on the scope. Skip only when scope is pure docs/copy (R0) with zero code change; state the reason.
- **Stack Discipline** (conditional) — when the plan introduces a new tool/library/service/framework in a trigger category (auth, payments, observability, hosting, ORM/DB, real-time, caching, email, file storage, forms, styling, state mgmt, background jobs, data fetching, feature flags), follow `~/.claude/commands/__base-stack-discipline.md`. Recommended tools become chosen-approach justifications; rejected alternatives become rejected-alternatives entries. Skip when no trigger category is touched; state the skip reason.

Run inline — findings feed option selection and critique.

### §4 Option Selection — tiebreaker

Point 2 = Idiomatic Python — modern patterns for the stack (async, Pydantic, PTB v20+).
