---
description: Full execution workflow — execute approved plan, simplify, update docs, commit, and push
---

> See `.claude/commands/__common.md` for shared context.

Orchestrates `/go` → `/simplify` → `/update` → `/done` (commit + push) into one flow.

Expects an execution-ready feature list artifact from `/plan`.

## 0. Communication Mode

Default `No Decision Needed`. Use `Decision Required` only at pause conditions in §2.

## 1. Preflight

Execute `/go` §1-2:
1. Locate the active artifact. Read the resume pack and `## Open Questions` section.
2. If the user provided answers to open questions, incorporate them. Accept recommended defaults for anything unanswered. If critical open questions have no safe default, ask them **in one batch** now.
3. Confirm artifact, scope, risk tier. Set status to `in progress`.
4. Publish execution header: artifact path, risk tier, target files, verification commands.
5. Budget check (S/M/L/XL per `__common.md` Context Budget).

## 2. Execute

Execute `/go` §3-6 in full — all pause conditions, the plan deviation gate, and verification policy apply as defined there.

Do not re-summarize those rules here. `/go` is the authority.

### Gate: Verification Pass

- **All verification passes**: proceed to §3 automatically.
- **Any verification failure**: attempt one focused remediation per `/go` on-failure policy. If remediation succeeds, proceed. If not, HARD STOP and report.

## 3. Simplify

After execution completes and verification passes, invoke the `/simplify` system skill on all changed code.

Fix every issue it surfaces. Re-run targeted verification to confirm nothing broke.

This step is **not optional**.

## 4. Update Docs

Execute `/update` §1-4 on the active artifact and core docs. This includes the auto-archive scan (§3) and braindump review (§4).

## 5. Commit and Push

Execute `/done` §2-6. All `/done` verification, commit, and push behaviors apply as written. Auto-push proceeds without additional confirmation per `/done` policy.

## 6. Handoff

1. What was implemented
2. What was verified
3. What `/simplify` changed (or "no changes")
4. Commit hash and message
5. Suggested next focus — top open item from the artifact, if any
6. **Bottom line**: "Pipeline complete. Committed and pushed."

**Starter Prompt Block (Required — Always the Final Output)**

After the handoff summary, emit this as the absolute last element of the response:

**PASTE TO START NEXT SESSION:**
```
[If remaining work in artifact]: Continue: [remaining goal]. Load [exact artifact path], then /run.
[If fully complete, no remaining items]: Session complete. Run /plan for the next item.
State: [one-sentence status — what shipped, what (if anything) remains].
```

Rules:
- This fenced code block is the very last thing in your response. Nothing after it.
- Maximum 3 lines inside the block. Pick the correct opening line (remaining work vs. complete).
- Include the artifact path verbatim when work remains so the next agent loads it cold.

## 7. Depth Checkpoint

If a DEPTH CHECK fires: finish the current subtask, then run §3-5 on whatever is complete. Leave remaining work active in the artifact with a resume pack. State what's done, what remains, exact `/run` restart point.

**Related:** `/plan` (create the plan) | `/wrap` (session wrap-up) | `/go` (standalone execution) | `/done` (standalone commit/push)
