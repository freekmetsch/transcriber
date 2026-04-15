---
description: Discovery and insight refiner - ingest raw ideas, map context, and clarify intent without premature deferral
---

> See `.claude/commands/__common.md` for shared context.

Convert raw idea dumps into technically validated, agent-ready feature lists.
Primary use: intake and structuring when ideas are still broad. Default to the active feature lane unless the user explicitly frames the work as later/backlog.

Constraint: definition only. Do not implement app code in this workflow.

Use `/3h` when the user wants an execution-ready phased plan for the current or next context window.

## 0. Communication Mode

Default `No Decision Needed`. Switch to `Decision Required` only when ambiguity requires user choice.

## 1. Input Phase

Read the raw user dump first without restructuring it.

## 2. Analysis and Vocalization

For each item, state assumptions explicitly:

- File-path hunting: identify likely affected files (`bot.py`, `config.py`, `processor.py`, `vault.py`, `memory.py`, `transcriber.py`, `models.py`, `prompts/`). Use `docs/FLOW.md` to trace which pipeline stages and files an idea touches.
- Technical logic check: validate against current stack (Python, python-telegram-bot, Pydantic AI, markdown vault).
- Ambiguity detection: flag vague phrases that cannot be executed reliably.

## 3. Intent Clarification

Refine into executable tickets:

- Offer concrete path options for vague items.
- Ask for confirmation on critical assumptions.
- Ask only the minimum clarifying questions required.
- When confirmation requires choice, use `Decision Required` mode with 2-3 options.

## 4. Finalization

Choose the lane explicitly:
- Default: create or update `docs/feature-lists/FEATURE_LIST_[NAME].md`
- Only if the user explicitly says backlog/later/defer or confirms that choice in chat: create or update `docs/feature-lists/backlog/BACKLOG_[NAME].md`.

Template:

```markdown
# Feature List: [Name]

Date: YYYY-MM-DD
Status: Draft
Scope: [Short scope]
Owner: [Optional]

## [Category]
- [ ] **Feature: [Clear scope title]**
- **Status**: Unresolved
- **Context**: `[@path/to/file]`
- **Instruction**: [Specific technical constraint]
- **Unresolved**: [Any remaining ambiguity]
```

Hand-off line:
"The artifact is ready in [path]."
