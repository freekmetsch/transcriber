---
description: Full planning workflow — intake, discovery, harden audit, sustainable option selection, critique, and execution-ready handoff
---

> See `.claude/commands/__common.md` for shared context.

Orchestrates `/list` → `/3h` → `/harden` → `/critique` → resume pack into one uninterrupted flow.

Goal: produce an execution-ready feature list artifact with a resume pack. The next context window runs `/run`.

**Do not implement code. Do not present intermediate work and ask "is this what you want?" Run to completion, then present the finished plan.**

## 0. Communication Mode

Default `No Decision Needed`. Switch to `Decision Required` **only** at optional gates (§5).

## 1. Intake

Execute `/list` §1-2: detect input mode, read raw input without restructuring, preserve user intent.

## 2. Intent Brief + Discovery

Execute `/3h` §2-3 silently (do not present as a checkpoint):
- Build intent brief: objective, constraints, success criteria, scope boundaries.
- Map touched files, reusable patterns, and true gaps.
- Use Context7 for all external framework/library behaviors.

## 3. Harden Audit

Execute `/harden` §2-3 on the scope.

Skip only when scope is pure docs/copy (R0) with zero code change. State the reason if skipping.

Run inline — findings feed directly into §4 and §5.

## 4. Option Selection — Sustainability First

Execute `/3h` §4-6, but **auto-select the best option — do not present options neutrally and wait.**

Tiebreaker (in order):
1. Sustainability — least technical debt, most maintainable long-term
2. Idiomatic Python — modern patterns for the stack (async, Pydantic, PTB v20+)
3. Architectural fit — works with what exists
4. Scope efficiency — no unnecessary bloat

If a refactor is more sustainable than a patch, **recommend the refactor**. Quick-fix approaches must be listed as rejected alternatives with explicit debt reasoning.

Include in plan: chosen approach + why, rejected alternatives + why rejected (1-2 lines each).

## 5. Critique

Execute `/critique` §1-2 on the selected approach. Build the failure-mode table. Integrate mitigations directly into the plan.

### Gates — Zero Mandatory Stops

This workflow runs to completion. Pause with `Decision Required` **only** for:
- **Interpretation conflict**: two plausible readings leading to fundamentally different architectures.
- **NO-GO condition**: critique surfaces an unresolved blocker that cannot be safely defaulted.

Do not pause for routine scope confirmation, option selection, or risk acknowledgment.

## 6. Plan Artifact

Execute `/3h` §9 to create or update `docs/feature-lists/FEATURE_LIST_[NAME].md`.

Required sections: problem framing, scope, chosen approach + rejected alternatives, phase plan with context-window strategy, execution tickets (full schema per `/3h` §8), risk tier and verification matrix, failure modes and mitigations.

Execute `/next` §2-3 to bake a resume pack into the artifact end:
- Goal, current state, first command (`/run`), first files, pending verification, open questions.

## 7. Open Questions

End the artifact with `## Open Questions`. Each question must include a recommended default so `/run` can proceed without waiting:
> **Q: [question]** — Default: [action if unanswered]. Reason: [why this matters].

## 8. Output in Chat

Concise summary only — the plan lives in the artifact:
1. What the plan covers (1-2 lines)
2. Chosen approach and why (2-3 lines)
3. Key risks and mitigations (2-3 lines)
4. Harden findings summary (if audit ran)
5. Open questions (if any)
6. **Bottom line**: "Plan ready at `[artifact path]`. Start a new context and run `/run`."

**Related:** `/run` (execute) | `/3h` (standalone planning) | `/critique` (standalone stress-test) | `/list` (standalone intake)
