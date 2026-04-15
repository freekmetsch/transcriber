---
description: Update and trim feature-list and related docs; backlog only with explicit user confirmation or defer intent
---

> See `.claude/commands/__common.md` for shared context.

## 0. Communication Mode

Default `No Decision Needed`. Switch to `Decision Required` for unresolved archive/split/backlog choices.

## Phase 1: Update
Update progress and integrate new insights based on work done.

## Phase 2: Trim
Remove anything that no longer earns its space. Use careful judgement informed by best practices and tech debt avoidance to decide what's valuable. Never keep any plan information in MEMORY.md. Always trim this.

## Phase 3: Archive, split, backlog, or restore
Use the lightest lane change that matches the user's intent and the actual state of the work.

- Default for unfinished work: keep it active in `docs/feature-lists/`.
- Move to `docs/feature-lists/backlog/` only when the user explicitly says later/defer/backlog, or explicitly confirms a backlog option in chat.
- If the session is pausing but the work is still intended to continue, prefer `/next` or an in-place active-artifact handoff instead of backlogging it.
- **Archive rule**: Archive a feature list to `docs/feature-lists/archive/` when its implementation tasks are complete in code. Do not hold archiving for pending smoke tests, manual verification, or other post-implementation checks. When the user runs `/update`, treat that as confirmation that the work is done or that they accept the current state. If something is broken, the user will say so — do not second-guess by keeping completed work active.
- **Auto-archive scan**: When running `/update`, scan ALL feature lists in `docs/feature-lists/` (not just the active artifact). Cross-reference with `git log` to identify any feature list whose work has been committed and pushed but whose file was never archived. Move these to `archive/` automatically — do not accumulate stale completed feature lists.

## Phase 4: Braindump review and archiving
Scan `docs/braindumps/` for any ideas or feature requests related to the current work or the preliminary wishlist. If a braindump contains intent that is not yet tracked in any active feature list, flag it in the output.

### Braindump archiving
After review, archive braindumps that have been fully addressed:
- A braindump is **archivable** when its intent is either (a) implemented in code and committed, or (b) tracked in an active feature list with a concrete plan item.
- Move archivable braindumps to `docs/braindumps/archive/`. Create the directory if it doesn't exist.
- Braindumps that are **pure exploration** (infrastructure musings, "what if" ideas with no actionable ask) and older than 7 days can also be archived — they've served their purpose as captured thought.
- Braindumps that contain **untracked actionable intent** must NOT be archived — flag them for inclusion in a feature list first.
- When archiving, do not modify the file content. Just move it.

## Depth Checkpoint Mode
When invoked after a DEPTH CHECK (soft or hard), include in the feature list update:
- What was completed this session
- What remains (with S/M/L/XL cost estimate per Context Budget)
- Recommended next chunk (which phase/step to start from)
- Do not backlog work solely because a DEPTH CHECK fired.

## Output in chat
The skill was likely called at the end of a work session, so output relevant information that a user has to act on (decisions, test results in clear non-jargon language, tradeoffs, recommended next steps)
