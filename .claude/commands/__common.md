---
description: Shared context for all workflows - agent reads this once per session
---

# Common Context

**Repo type:** Desktop app

## Your Role
AI-first software engineer. Optimize for model reasoning, regeneration, and debugging.

## Communication

> Communication, decision, research, formatting, and policy rules: see global `~/.claude/commands/__common.md` (§Decision Filter, §Default Stance, §Universal Policies, §Unified Decision Communication Contract, §Research Discipline, §Self-Install Policy, §Formatting Conventions, §Starter Prompt Block).
> Repo-specific deltas below override only the listed item, not the structure.

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

## Key Files
| File | Purpose |
|------|---------|
| `app.py` | Entry point: system tray icon, global hotkey, pipeline orchestration |
| `recorder.py` | Microphone recording via sounddevice (16kHz mono float32) |
| `transcriber.py` | faster-whisper inference (large-v3, CUDA with CPU fallback) |
| `output.py` | Clipboard paste with save/restore and thread-safe locking |
| `config.py` | YAML config loading with deep-merged defaults |
| `config.yaml` | User configuration (hotkey, audio, whisper settings) |
| `requirements.txt` | Python dependencies |

| `postprocessor.py` | Ollama /api/chat post-processing with fallback to raw text |
| `commands.py` | Formatting command definitions (EN + NL bilingual) |
| `notifications.py` | Windows toast notifications (winotify wrapper, graceful fallback) |
| `recording_indicator.py` | Win+H-style floating "Listening..." overlay during recording |
| `vocab_ui.py` | Vocabulary manager Toplevel window (tray-accessible) |
| `brain.py` | SQLite vocabulary database, CRUD operations (WAL, thread-safe) |
| `learning.py` | Correction tracking, auto-learning logic |
| `prompt_builder.py` | Generate Whisper initial_prompt from vocabulary |
| `correction_ui.py` | Floating correction window (tkinter, dark theme) |
| `sounds.py` | Audio feedback tones (start/stop/error, generated in-memory) |
| `autostart.py` | Windows auto-start via Registry Run key |
| `vocab.py` | CLI tool for vocabulary management |

## Documentation
- `docs/feature-lists/` — active feature lists and execution plans.
- `docs/feature-lists/FEATURE_LIST_TRANSCRIBER.md` — master plan (5 phases).
- `docs/braindumps/` — user intent source (if any).

## Lane Authority (Critical)
Folder location is the source of truth for active vs historical state:
- `docs/feature-lists/` = active feature lists.
- `docs/feature-lists/archive/` = historical feature lists.
- `docs/braindumps/` = active user intent (unprocessed ideas, feature requests).
- `docs/braindumps/archive/` = processed braindumps (implemented or tracked in a feature list).

In-file status text and checkboxes are secondary metadata and must never override folder location.

## Workflows
Canonical definitions: `.claude/commands/*.md`. Local wrappers must not override.

### Combined workflows (recommended default)
- `/plan`: full planning — intake, discovery, harden audit, sustainable option selection, critique, and execution-ready handoff. Produces a feature list artifact with resume pack. No execution.
- `/run`: full execution — execute approved plan, `/simplify`, update docs, commit, and push.
- `/wrap`: mid-session pause only — save progress, commit/push what's done, prepare handoff. Not needed after `/run`.

### Granular workflows (available for targeted use)
- `/list`: intake and structure broad ideas.
- `/3h`: execution-ready phased plan.
- `/critique`: stress-test a plan; no execution.
- `/diag`: investigate root cause; no execution.
- `/go`: execute approved scope only.
- `/done`: verify, commit, and push.
- `/harden`: production-readiness audit; no execution.
- `/next`: session wrap-up and handoff for next chat.
- `/update`: trim docs and archive resolved work; backlog only with explicit user direction or confirmation.

Active planning/execution artifacts must be in `docs/feature-lists/`.

Default state for unfinished work is active, not backlog.
- Do not move active work into `docs/feature-lists/backlog/` unless the user explicitly asks to defer/postpone it or explicitly approves that move.
- Context pressure, session pauses, or partial progress are not by themselves reasons to backlog work.
- When pausing unfinished work, keep the artifact active and use `/next` or a concise in-place handoff.

## Stack Discipline (Tool / Library / Service Selection)

When a workflow introduces a new tool, library, service, or framework, follow the Stack Discipline Protocol at `~/.claude/commands/__base-stack-discipline.md`.

The protocol fires on its trigger categories (auth, payments, observability, hosting, ORM/DB, real-time, caching, email, file storage, forms, styling, state mgmt, background jobs, data fetching, feature flags). If uncertain whether a task touches a trigger category, run the protocol — skipping requires confidence the task is outside all categories.

Established preferences in `C:\Users\metsc\.claude\projects\C--Users-metsc-Cloned-Repositories-second-brain\memory\MEMORY.md` are defaults, not absolutes — verify use-case fit before applying. Reference: Paddle MOR is the sub-payments default, but Mollie was chosen for tips on `pro-social-tools` because the use case differs.

## Risk Tiers
| Tier | Scope | Required Controls |
|------|-------|-------------------|
| R0 | docs/copy/cosmetic | targeted verification |
| R1 | localized code, low blast radius | + manual smoke test |
| R2 | shared logic/data/config | + `python -m py_compile` on changed files |
| R3 | vocabulary DB structure/destructive/irreversible | + mandatory `/critique`, user go/no-go, rollback plan |

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
- Issue files: `docs/known_issues/current/`. Template and lifecycle: see `/diag`.
- Only mark RESOLVED after explicit user confirmation, then move to `solved/`.
- For AWAITING VERIFICATION, check in with user before moving.

## Scope Discipline
- Execute the approved plan directly; avoid workflow overhead.
- Do not create extra planning artifacts unless blocked.
- Do not perform broad context reloads when scope is already clear.
- Keep progress updates short and action-oriented.
