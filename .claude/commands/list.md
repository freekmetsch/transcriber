---
description: Discovery and insight refiner - ingest raw ideas, map context, and clarify intent without premature deferral
---

> See `.claude/commands/__common.md` for repo context.
> Base: `C:\Users\metsc\.claude\commands\__base-list.md` — read and apply first.

## Repo Overrides

### §2 Analysis and Vocalization

For each item, state assumptions explicitly:

- File-path hunting: identify likely affected files (`bot.py`, `config.py`, `processor.py`, `vault.py`, `memory.py`, `transcriber.py`, `models.py`, `prompts/`). Use `docs/FLOW.md` to trace which pipeline stages and files an idea touches.
- Technical logic check: validate against current stack (Python, python-telegram-bot, Pydantic AI, markdown vault).
- Ambiguity detection: flag vague phrases that cannot be executed reliably.
