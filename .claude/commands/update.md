---
description: Update and trim feature-list and related docs; backlog only with explicit user confirmation or defer intent
---

> See `.claude/commands/__common.md` for repo context.
> Base: `C:\Users\metsc\.claude\commands\__base-update.md` — read and apply first.

## Repo Overrides

### Archive rule
This repo's archive rule omits deploy confirmation (desktop app, no deploy step):

- **Archive rule**: Archive a feature list to `docs/feature-lists/archive/` when its implementation tasks are complete in code. Do not hold archiving for pending smoke tests, manual verification, or other post-implementation checks. When the user runs `/update`, treat that as confirmation that the work is done or that they accept the current state. If something is broken, the user will say so — do not second-guess by keeping completed work active.

### Archive mechanics
Replace the base archive-mechanics override with the compact auto-archive scan, run as a bullet inside Phase 3:

- **Auto-archive scan (invoke the scripts — never re-describe the scan inline)**: When running `/update`, (1) for each completed feature list stamp the canonical `_Status:` line directly under its H1 — `_Status: Shipped — <YYYY-MM-DD> (<summary>)_` (or `Superseded` / `Cancelled`); active vocab is `Plan ready | In flight | Deferred`. (2) Run `pwsh -NoProfile -File scripts/archive-scan.ps1` — it git-mv's every active list whose first `_Status:` line is terminal into `docs/feature-lists/archive/` (history preserved). (3) Run `pwsh -NoProfile -File scripts/feature-list-lint.ps1` as the gate — it must exit 0 (enforces the `_Status:` invariant + lane consistency; prescriptive error names the file + line + valid vocab). Author-written `_Status:` replaces the old `git log` heuristic — the marker is explicit, not inferred. Portable lint contract + rationale: truecolours ADR 0032.

### Phase 4: Braindump review and archiving
Scan `docs/braindumps/` for any ideas or feature requests related to the current work or the preliminary wishlist. If a braindump contains intent that is not yet tracked in any active feature list, flag it in the output.

#### Braindump archiving
After review, archive braindumps that have been fully addressed:
- A braindump is **archivable** when its intent is either (a) implemented in code and committed, or (b) tracked in an active feature list with a concrete plan item.
- Move archivable braindumps to `docs/braindumps/archive/`. Create the directory if it doesn't exist.
- Braindumps that are **pure exploration** (infrastructure musings, "what if" ideas with no actionable ask) and older than 7 days can also be archived — they've served their purpose as captured thought.
- Braindumps that contain **untracked actionable intent** must NOT be archived — flag them for inclusion in a feature list first.
- When archiving, do not modify the file content. Just move it.
