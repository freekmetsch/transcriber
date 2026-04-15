---
description: Session wrap-up pipeline - update docs, commit/push, and prepare next-session handoff
---

> See `.claude/commands/__common.md` for shared context.

Mid-session pause only. Use when you need to save progress, push what's done, and hand off before the session ends — **not needed after `/run`**, which already commits, pushes, and hands off.

Orchestrates `/update` → `/done` → `/next` into one pass. Do not re-invoke sub-commands individually.

## 0. Communication Mode

Each phase uses the mode defined in its source command. Between phases, emit: `--- PHASE [N]: [NAME] ---`

## Phase 1: Update

Execute the full workflow from `.claude/commands/update.md` (all phases, including auto-archive scan and braindump review).

### Gate: Unresolved Decisions

- **No unresolved decisions**: proceed to Phase 2 automatically.
- **Unresolved archive/split/backlog/restore choices**: present using `Decision Required` mode. Wait for user reply, apply the decision, then proceed.

## Phase 2: Done

Execute the full workflow from `.claude/commands/done.md` (all sections).

All `/done` verification, commit, and push behaviors apply as written.
Auto-push proceeds without additional confirmation per `/done` policy.

## Phase 3: Next

Execute the full workflow from `.claude/commands/next.md` (all sections).

If push failed in Phase 2, the resume pack must flag this as the first item to resolve in the next session.

## Final Output

Deliver the `/next` resume pack as the final output. This is the last thing the user sees before closing the session, so it must be self-contained and actionable.
