---
description: Shared context for all workflows - agent reads this once per session
---

# Common Context

**Repo type:** Desktop app — no repo CLAUDE.md; this file carries the repo deltas.

## Communication

> Communication, decision, research, formatting, sustainability, and policy rules: global `~/.claude/commands/__common.md` (§Decision Filter, §Default Stance, §Universal Policies, §Unified Decision Communication Contract, §Research Discipline, §Self-Install Policy, §Formatting Conventions, §Starter Prompt Block, §Context Budget, §Scope Discipline).

## Project Stack
- **Language**: Python 3.12
- **Speech-to-text**: faster-whisper (CTranslate2, CUDA GPU acceleration)
- **Audio capture**: sounddevice (PortAudio)
- **Global hotkeys**: keyboard library
- **System tray**: pystray + Pillow
- **Text output**: pyautogui + pyperclip (clipboard paste)
- **LLM post-processing**: Ollama HTTP API (Phase 2+)
- **Vocabulary DB**: SQLite (Phase 3+)
- **Android**: Kotlin + whisper.cpp RecognitionService (Phase 4+)
- **Config**: PyYAML
- **Deployment**: Local desktop app — no server, no Docker, no VPS

## Command routing (non-obvious cases only)
- `/wrap` is mid-session pause only — not needed after `/run`.

## Lane Authority
Invariant + the shared `docs/feature-lists/` (active) / `docs/feature-lists/archive/` (historical) lane: global `~/.claude/commands/__common.md` §Lane Authority. Repo-specific lanes:
- `docs/braindumps/` = active user intent (unprocessed ideas, feature requests).
- `docs/braindumps/archive/` = processed braindumps (implemented or tracked in a feature list).
- `docs/feature-lists/FEATURE_LIST_TRANSCRIBER.md` = master plan.

## Stack Discipline
When a workflow introduces a new tool, library, or service, follow `~/.claude/commands/__base-stack-discipline.md` (run it if uncertain whether a trigger category applies). `MEMORY.md` preferences are defaults, not absolutes — verify use-case fit.

## Risk Tiers
Default R0–R3 ladder: global `~/.claude/commands/__common.md` §Risk Tiers (default ladder). Repo deltas only:
- **R2** — verification command = `python -m py_compile` on changed files.
- **R3** — trigger scope here = vocabulary DB structure change / destructive / irreversible.

## Verification Commands
| Check | Command | When |
|-------|---------|------|
| Syntax check | `python -m py_compile <file>` | Any Python file changed (automatic) |
| Manual smoke test | Run `python app.py`, test hotkey, verify transcription | After functional changes |
| Type check | `mypy <file> --ignore-missing-imports` | When type contracts change (automatic) |

### Windows encoding
This project runs on Windows, where `open()` defaults to cp1252 encoding. **Always use `python -m py_compile <file>` for syntax checks** — never `ast.parse(open(...).read())` or similar. `py_compile` handles encoding correctly; raw `open()` without `encoding='utf-8'` will crash on UTF-8 files. If you must read a Python file programmatically, always pass `encoding='utf-8'`.

### Test policy
Verification uses `py_compile` syntax checks (free, fast) and manual smoke tests. pytest suite exists for vocabulary DB (`test_brain.py`), prompt builder (`test_prompt_builder.py`), learning (`test_learning.py`), and postprocessor (`test_postprocessor.py`).

## Skills
Project skills in `.claude/skills/` — MUST be consulted when working in that area:
- `desktop-transcriber-patterns`: faster-whisper, sounddevice, pystray, keyboard, clipboard — the core desktop voice pipeline.
- `ollama-sqlite-desktop`: Ollama HTTP API integration, SQLite vocabulary DB patterns — for Phase 2+ and Phase 3+.
- `python-dev-patterns`: Debugging discipline, testing anti-patterns, root-cause investigation.

## Issue Management
- Issue files: `docs/known_issues/current/`. Template and lifecycle: see `~/.claude/commands/__base-diag.md` §Issue Template (library sourced by `/plan` in fix-mode).
- Only mark RESOLVED after explicit user confirmation, then move to `solved/`.
- For AWAITING VERIFICATION, check in with user before moving.
