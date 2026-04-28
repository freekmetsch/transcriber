---
description: Session wrap-up for next-chat resume - update active docs with progress, insights, and the exact restart point
---

> See `.claude/commands/__common.md` for shared context.

Use `/next` when pausing work in this chat but intending to continue in the next chat.
Primary goal: leave the active artifact updated so the next agent can restart with minimal rediscovery.
Prefer this over `/update` when the pause is caused by time/context pressure rather than an actual defer/archive decision.

Constraint: do not implement new app code in this workflow. Only make the minimum documentation and status updates needed for a clean handoff.

## 0. Communication Mode

Default `No Decision Needed`. Use `Decision Required` only when next step depends on unresolved user choice.

## 1. Select the Active Artifact

Update exactly one active artifact for this paused work:
- Feature work: the specific `docs/feature-lists/FEATURE_LIST_*.md`
- Issue work: the specific `docs/known_issues/current/*.md`

If no active artifact exists yet, create the lightest valid one in the correct active lane before handoff.

## 2. Update the Handoff State (Required)

Record only what the next session needs:
- What was completed this session.
- Current status and exact stopping point.
- Files touched or closely inspected.
- Key findings, decisions, and constraints learned.
- Verification run, skipped, or still needed.
- Open risks, blockers, or unanswered questions.
- Exact next recommended step.

Trim stale notes or duplicate history that no longer helps the next session.

## 3. Resume Pack (Required)

Leave a concise resume pack in the artifact and echo it in chat:
- Goal to continue.
- Current state in 2-4 lines.
- First file to add to the next context window (i.e., feature_list_x.md) + the workflow or command to run next (`/go`, `/diag`, `/3h`, `/update`, or direct file review).
- Pending verification or validation.
- User input still needed, if any.
- NEVER tell user to run a CLI command if ai agent can and should do it instead.

If the next chat can execute immediately, say so explicitly.
If the next chat should diagnose, plan, or wait for a user choice first, say that explicitly.

## 4. Scope Guardrail

Do not start new implementation or broad new research in this workflow.
Run only lightweight truth-checks needed to keep the handoff accurate.
Do not commit or ask for push approval; that belongs to `/done`.
Do not move unfinished active work to backlog solely because the session is pausing.

## 5. Output in Chat

Deliver a short handoff that includes:
1. Artifact updated.
2. What changed.
3. Resume from here.
4. What to watch.
5. `Bottom Line` with the exact next-chat start instruction or reply needed.

When invoked after a DEPTH CHECK, optimize for speed and truth over polish.

## 6. Starter Prompt Block (Required — Always the Final Output)

After the handoff, emit this as the absolute last element of the response.

**PASTE TO START NEXT SESSION:**
```
Continue: [goal in one sentence]. Load [exact artifact path], then [exact first command or action].
State: [current status in 1–2 sentences].
[Only if a blocking question exists] Needs: [exact question].
```

Rules:
- This fenced code block is the very last thing in your response. Nothing after it.
- Maximum 4 lines inside the block.
- Include the artifact path verbatim — next agent loads it cold with no prior context.
- If no artifact exists, reference the relevant wiki page or `index.md` instead.
- If the next action is a slash command, write it as `/command` (e.g. `/run`, `/plan`).

**Related commands:** `/update` (broader doc maintenance) | `/done` (completion + commit and push handoff) | `/go` (resume execution)
