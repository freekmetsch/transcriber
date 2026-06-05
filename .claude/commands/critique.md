---
description: Critique and refine a plan before execution
---

> See `.claude/commands/__common.md` for repo context.
> Base: `C:\Users\metsc\.claude\commands\__base-critique.md` — read and apply first.

## Repo Overrides

### §1 Critique Phase — items 3–5

3. Standards: idiomatic Python, clean async patterns, proper error handling.
4. Edge cases: network failure, missing env vars, empty/malformed input, Telegram API errors, LLM provider downtime.
5. Failure modes: enumerate realistic break paths and their blast radius. Cross-reference against the error handling table in `docs/FLOW.md` to verify all failure paths are covered.
