---
description: Production-readiness audit — analyze code for safety, cleanup, and industry-standard hardening
---

> See `.claude/commands/__common.md` for shared context.

Production-readiness audit on the transcriber app or a targeted area.

Output: ranked findings table, severity-grouped hardening plan, feature list artifact.
Do not implement code changes in this workflow.

## 0. Communication Mode

Default `No Decision Needed` for evidence. Use `Decision Required` for hardening sequence recommendation.

## 1. Scope Selection

Determine audit scope from user input:
- **Full app**: no target specified — audit top-down from the `app.py` entry point across the pipeline: hotkey trigger → audio capture (`recorder.py`) → VAD (`vad.py`) → transcription (`transcriber.py` local / `groq_dictator.py` / `cloud_dictator.py` / `cascade_dictator.py` per mode) → post-processing (`postprocessor.py`) → output (`output.py`) → vocabulary learning (`brain.py`).
- **Area**: subsystem (e.g., "recorder", "transcriber", "dictators", "output", "config", "brain").
- **File**: one or more specific files.

Confirm scope and classify size per `__common.md` Context Budget before proceeding.

## 2. Audit Dimensions

| Dimension | Focus |
|-----------|-------|
| **Security & Secrets** | Provider API key handling (Groq/cloud) via config, no hardcoded secrets, no secrets leaked into `transcriber.log`, config-file permissions |
| **Error Handling** | Graceful degradation on provider failures (Groq/cloud timeouts), model-load failure, mic/audio-device disconnect, clipboard write failure, empty/silent audio |
| **Code Quality** | Dead code, unsafe patterns, debug artifacts (`print`/`breakpoint`), duplication, Python anti-patterns |
| **Reliability** | Threading correctness (capture loop + hotkey listener), graceful shutdown, recovery after a failed transcription, CUDA/GPU OOM handling, fallback between modes |
| **Data Safety** | `brain.db` vocabulary write integrity, no silent loss of learned corrections, atomic config writes |
| **Configuration** | `config.yaml` / `config.local.yaml` validated at startup, sensible defaults, clear error messages for a missing/invalid mode or provider |
| **Testing** | Test coverage gaps, missing edge-case tests, test isolation |
| **Packaging & Startup** | Autostart behavior, system-tray + recording-indicator init, icon/resource files present, pinned `requirements.txt` |

## 3. Evidence Gathering

- **Grep sweeps**: `print(`, `breakpoint()`, `# TODO`, hardcoded API keys/tokens, `os.system(`.
- **Syntax check**: `python -m py_compile` on all scoped `.py` files.
- **Test run**: `pytest tests/ -v`.
- **Smoke**: `python app.py` boots, hotkey registers, tray icon + recording indicator appear (if startup is in scope).
- **Context7**: verify API usage only for findings that depend on external API behavior (faster-whisper, Groq/cloud SDKs).

Every finding must reference a specific `file:line`.

## 4. Findings Report (Required Output)

### Severity Levels
| Level | Meaning | Action |
|-------|---------|--------|
| **P0** | Security vulnerability or data loss risk | Must fix before production |
| **P1** | Correctness bug or reliability gap | Should fix before production |
| **P2** | Code quality / robustness issue | Fix in hardening phase |
| **P3** | Best practice gap / polish | Optional but recommmended |

### Findings Table
| # | Severity | Dimension | Finding | File(s) | Effort | Risk Tier |
|---|----------|-----------|---------|---------|--------|-----------|

Include summary: totals by severity, by dimension, and highest-risk areas.

## 5. Hardening Plan

Group findings into phases by severity: P0 → P1 → P2 → P3 (optional, but recommended for large audits).
Use `~/.claude/commands/__base-planning.md` conventions for phasing, ticket schema, and context-window strategy.

Output artifact: `docs/feature-lists/FEATURE_LIST_HARDEN_[AREA].md`
Use `PRODUCTION_READINESS` as area for full-app audits.

Include decision brief: plain-language readiness assessment, recommended sequence, total effort estimate (S/M/L/XL).
Deliver this decision brief in `Decision Required` mode with explicit option tradeoffs.

## 6. Hard Stop

Do not execute. Wait for `/run`.

**Related:** `/critique` (stress-test plan) | `/run` (execute) | `/plan` (fix-mode for specific finding, sources `__base-diag.md` library)
