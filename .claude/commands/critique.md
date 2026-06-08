---
description: Critique and refine a plan before execution
---

> See `.claude/commands/__common.md` for repo context.
> Base: `C:\Users\metsc\.claude\commands\__base-critique.md` — read and apply first.

## Repo Overrides

### §1 Critique Phase — items 3–5

3. Standards: idiomatic Python, clean threading for the capture/hotkey loop, proper error handling.
4. Edge cases: mic disconnect mid-capture, CUDA/GPU OOM on model load, clipboard write race, global-hotkey conflict with another app, Groq/cloud provider timeout or downtime, empty/silent audio, missing or malformed config.
5. Failure modes: enumerate realistic break paths and their blast radius. Trace each against the real pipeline — `app.py` → `recorder.py` → `transcriber.py` (or `groq_dictator.py`/`cloud_dictator.py`/`cascade_dictator.py` per mode) → `postprocessor.py` → `output.py`, with `brain.py` vocabulary lookups — to verify all failure paths are covered.
