---
description: Production-readiness audit — analyze code for safety, cleanup, and industry-standard hardening
---

> See `.claude/commands/__common.md` for shared context.

Production-readiness audit on the bot or a targeted area.

Output: ranked findings table, severity-grouped hardening plan, feature list artifact.
Do not implement code changes in this workflow.

## 0. Communication Mode

Default `No Decision Needed` for evidence. Use `Decision Required` for hardening sequence recommendation.

## 1. Scope Selection

Determine audit scope from user input:
- **Full app**: no target specified — audit top-down from `bot.py` entry point. Use `docs/FLOW.md` as the pipeline map to ensure all stages are covered (input → auth → transcription → classification → action dispatch → vault write → confirmation → memory).
- **Area**: subsystem (e.g., "processor", "vault", "config", "transcription").
- **File**: one or more specific files.

Confirm scope and classify size per `__common.md` Context Budget before proceeding.

## 2. Audit Dimensions

| Dimension | Focus |
|-----------|-------|
| **Security & Secrets** | Env var handling, no hardcoded secrets, Telegram user ID validation, input sanitization, file path traversal prevention |
| **Error Handling** | Graceful degradation on API failures (Groq, Telegram), network timeouts, malformed input, missing vault dirs |
| **Code Quality** | Dead code, unsafe patterns, debug artifacts (`print`/`breakpoint`), duplication, Python anti-patterns |
| **Reliability** | Async correctness, signal handling, graceful shutdown, Docker health, restart behavior |
| **Data Safety** | Vault write atomicity, no silent data loss, Git sync safety, concurrent write handling |
| **Configuration** | All env vars validated at startup, sensible defaults, clear error messages for missing config |
| **Testing** | Test coverage gaps, missing edge-case tests, test isolation |
| **Deployment** | Dockerfile best practices, compose config, systemd service, log rotation |

## 3. Evidence Gathering

- **Grep sweeps**: `print(`, `breakpoint()`, `# TODO`, hardcoded API keys/tokens, `os.system(`.
- **Syntax check**: `python -m py_compile` on all `.py` files.
- **Test run**: `pytest tests/ -v`.
- **Docker build**: `docker compose build` (if Dockerfile in scope).
- **Context7**: verify API usage only for findings that depend on external API behavior.

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
Use `/3h` conventions for phasing, ticket schema, and context-window strategy.

Output artifact: `docs/feature-lists/FEATURE_LIST_HARDEN_[AREA].md`
Use `PRODUCTION_READINESS` as area for full-app audits.

Include decision brief: plain-language readiness assessment, recommended sequence, total effort estimate (S/M/L/XL).
Deliver this decision brief in `Decision Required` mode with explicit option tradeoffs.

## 6. Hard Stop

Do not execute. Wait for `/go`.

**Related:** `/critique` (stress-test plan) | `/go` (execute) | `/diag` (investigate specific finding)
