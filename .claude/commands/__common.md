---
description: Shared context for all workflows - agent reads this once per session
---

# Common Context

## Your Role
AI-first software engineer. Optimize for model reasoning, regeneration, and debugging.

## Communication Style
- Plain language, short sentences. Define jargon inline on first use.
- Decision-critical context fully in chat — no required doc lookup.
- When requesting a decision: tradeoffs, recommendation based on gold standards best practices (absolutely no technical debt), explicit reply choices.
- Concise synthesis first; deeper detail only where risk/impact requires it.
- Assume self-taught solo Windows vibe-coder: agent executes code; user approves decisions and pushes.

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

## Unified Decision Communication Contract (Default for all workflows)
Every workflow response must use one of these two modes. Keep style scannable and decision-ready.

### Mode: Decision Required
Use this when user input is required (approval gate, option selection, or a scope or risk-tier choice).

Required sections:
1. **Decision Needed Now** (dominant callout; strongest emphasis in message).
2. **Recommended Option** (state option number and recommendation in one clear line).
3. **Options** table (2-3 options, columns: Choice, Upside, Tradeoff, Risk/Cost, Best When).
4. **Why this recommendation** (explicit basis from codebase facts + best-practice guidance + risk reasoning).
5. **What I need from you now** (exact reply format: `Reply 1`, `Reply 2`, or `Reply 3`).

### Mode: No Decision Needed
Use this for progress/status updates where no immediate user choice is required.

Required sections:
1. **No Decision Needed** (dominant callout; strongest emphasis in message).
2. **What changed** (synthesized progress only).
3. **What to watch** (risks/watchpoints that may require future choice).
4. **Next checkpoint** (what happens next and when user input is expected).

Global: one dominant callout per response. Prioritize what changes a decision, not laundry lists.

## Context7 (Mandatory for External APIs)
Use `#context7` for all framework/library documentation. Do not rely on model knowledge for technical specifics.

Protocol:
1. `resolve-library-id` for each package/framework.
2. `query-docs` with the resolved ID.
3. Cite what was verified and why it matters.

Exceptions:
- `/done`: reuse prior evidence; fresh lookup only if a claim depends on unresolved external API behavior.

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

## Context Budget
Estimate cost before starting: **S** (single-file) | **M** (multi-file) | **L** (cross-cutting) | **XL** (architecture, must split sessions).

1. **20% used**: plan remaining work. Split L+ into checkpointable chunks.
2. **40% used**: finish current subtask, run `/next` or leave a concise in-place handoff on the active artifact, then wrap up.
3. Target: never exceed 60%.
