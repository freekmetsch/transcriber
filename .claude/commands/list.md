---
description: Discovery and insight refiner - ingest raw ideas, map context, and clarify intent without premature deferral
---

> See `.claude/commands/__common.md` for repo context.
> Base: `C:\Users\metsc\.claude\commands\__base-list.md` — read and apply first.

## Repo Overrides

### §2 Analysis and Vocalization

For each item, state assumptions explicitly:

- File-path hunting: identify likely affected files (`app.py`, `config.py`, `recorder.py`, `transcriber.py`, `output.py`, `postprocessor.py`, `brain.py`, `modes.py`, the per-mode dictators `groq_dictator.py`/`cloud_dictator.py`/`cascade_dictator.py`, `shortcut.py` hotkey, `vad.py`). Trace which pipeline stage (capture → VAD → transcribe → post-process → output → vocabulary learning) an idea touches.
- Technical logic check: validate against the current stack (Python, faster-whisper local + Groq/cloud backends, global hotkey, system-tray UI).
- Ambiguity detection: flag vague phrases that cannot be executed reliably.
