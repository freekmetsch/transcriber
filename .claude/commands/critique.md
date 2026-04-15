---
description: Critique and refine a plan before execution
---

> See `.claude/commands/__common.md` for shared context.

Critique-first. Use when the plan is complex, risk is high, or confidence is low. Sequence: Critique → Refine → User Confirmation → Execute.

## 0. Communication Mode

Default `No Decision Needed`. Final GO/NO-GO uses `Decision Required` with 2-3 remediation paths if NO-GO.

## 1. Critique Phase

Do not write code yet.
This is planning/review only.

Critique checklist:
1. Complexity: Is there a simpler path?
2. Safety: What can regress? Could vault data be lost or corrupted?
3. Standards: idiomatic Python, clean async patterns, proper error handling.
4. Edge cases: network failure, missing env vars, empty/malformed input, Telegram API errors, LLM provider downtime.
5. Failure modes: enumerate realistic break paths and their blast radius. Cross-reference against the error handling table in `docs/FLOW.md` to verify all failure paths are covered.
6. Reference verification: ensure Context7-backed framework/library assumptions are explicit.
7. Scope sizing: estimate per `__common.md` Context Budget. Identify checkpoint boundaries for large scope.

Output:
- Failure-Mode Table (required):
  - Failure mode
  - Trigger
  - Impact
  - Detectability
  - Mitigation
  - Residual risk
- Risk summary for the active planning artifact.

## 2. Refine the Plan

1. Update the plan artifact.
2. Remove violations of Python/async best practices from the plan.
3. Add mitigations for high-risk failure modes.
4. Confirm readiness to execute.

## 3. Go/No-Go Recommendation

Provide one explicit recommendation:
- `GO`: acceptable residual risk and clear verification.
- `NO-GO`: unresolved blockers or weak rollback.

If `NO-GO`, list exactly what must change before execution.
Explain decisions in clear non-jargon language with recommendations for each item based on best practices that reduce/eliminate tech debt.
Use `Decision Required` mode for this section so the user can approve immediately in chat.

## 4. Hard Stop

**"Critique complete. Awaiting your confirmation to execute with /go."**

## 5. Plan-Readiness Checklist

- [ ] Scope and boundaries are explicit.
- [ ] Failure modes and mitigations are documented.
- [ ] Verification strategy is defined for `/go`.
- [ ] Rollback path documented.
- [ ] Decision gates are explicit and user-confirmable.
