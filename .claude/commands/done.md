---
description: Task wrap-up - documentation review, verification, local commit, and push
---

> See `.claude/commands/__common.md` for repo context.
> Base: `C:\Users\metsc\.claude\commands\__base-done.md` — read and apply first.

## Repo Overrides

### §2 Post-Implementation Check

Build the checklist from changed files and include only applicable rows:
- Syntax validity (`python -m py_compile` on changed files)
- Manual smoke test (run `python app.py`, test hotkey, verify transcription)
- Config validation (if config.py or config.yaml changed)
- Type contracts (if type annotations changed — `mypy <file> --ignore-missing-imports`)
- Vocabulary DB safety (if brain.py changed — no data loss paths)

### §4 Documentation Review

If behavior/architecture changed, update:
- `docs/feature-lists/FEATURE_LIST_TRANSCRIBER.md` (resume pack, phase status)
- Relevant `docs/feature-lists/*.md`

### §5 Deploy

No deploy target. Push to `origin master` per base §5 push flow. No additional steps.
