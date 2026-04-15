---
description: Executing a task
---

> See `.claude/commands/__common.md` for shared context.

Lean execution. Use when a plan is approved or the task is straightforward. If risk or uncertainty is high, use `/critique` first.

## 0. Communication Mode

Default `No Decision Needed`. Use `Decision Required` only at pause/deviation gates.

## 1. Start from the Approved Artifact

If the user says `/go` on an approved plan, execute that plan directly.

Use the existing active artifact:
- Feature work: `docs/feature-lists/FEATURE_LIST_*.md`
- Issue work: `docs/known_issues/current/*.md`

Do not pull scope from:
- `docs/feature-lists/archive/`
- `docs/known_issues/solved/`

unless the user explicitly requests historical review or reopening.

Do not create a new feature list when one already exists for the same work.

## 2. Minimal Preflight (Hard Cap)

Before coding, do only:
1. Confirm target artifact and scope.
2. Set artifact status to `in progress` (if not already).
3. Identify changed files and risk level.
4. Publish an execution header in 2-4 lines:
   - Artifact path
   - Risk tier
   - Exact files intended for change
   - Verification commands to run

5. Budget check: estimate task cost (S/M/L/XL per Context Budget in `__common.md`), compare against remaining context budget.

## 2b. Risk Tier Gate (Mandatory)

Determine task risk tier from the active artifact (or set a provisional tier if missing).
Apply risk tier controls per `__common.md`.

## 3. Execute the Approved Scope

Implement the planned changes directly.

Do not start side quests, extra audits, or new planning tracks unless blocked.

## 4. Targeted Reference Verification

Use `#context7` when implementation depends on external framework/library behavior or version-specific APIs.

If the approved change is internal-only and no external behavior assumptions are introduced, skip fresh Context7 lookup and state:
- `Context7 exception: internal-only change; no external API behavior change.`

Before finalizing implementation summary, include:
- Which external behaviors were verified (if any).
- How verification affected implementation choices (or why exception applied).

## 5. Pause Conditions (Only These)

Pause and ask the user when changes involve:
- `R3` risk-tier work.
- Vocabulary DB structure changes.
- Config model changes.
- Major dependency upgrades.
- Destructive operations (data loss, DB rewrites).
- Cross-cutting architecture changes.

### Plan Deviation Gate
If execution reveals the approved plan won't work as written (missing dependency, wrong assumption, unexpected state), do NOT silently adjust, but instead STOP execution and PRESENT to user:
1. Explain why the plan needs adjustment.
2. Present & Explain the tradeoffs of each alternative path with recommendations.
3. Include instructions if users needs to do something manually.
4. Finish with /critique of plan.
5. Synthesize the plan and ask user to confirm before continuing.
6. Use `Decision Required` mode for the plan-deviation prompt.

- **Depth checkpoint**: pause per `__common.md` Context Budget when a DEPTH CHECK appears. Prefer `/next` or a concise active-artifact handoff; do not backlog/archive work solely because of context pressure.

Do not pause just because 3+ files are touched.

## 6. Verification Policy

Default: targeted verification for changed area.

Run verification commands from `__common.md`:
- `python -m py_compile <file>` for any changed Python file.
- `mypy <file> --ignore-missing-imports` when type contracts change.

Run manual smoke test when:
- Functional behavior changed (hotkey, recording, transcription, output).
- Risk is `R1` or higher.
- User asks.

## 7. Minimal Artifact Update (Required)

Update only the active artifact for this execution scope.

Issue workflow default:
- Change status only (`FIX IN PROGRESS` -> `AWAITING VERIFICATION` as appropriate).
- Append one investigation-log row for this run.
- Update touched files list if needed.

Do not rewrite entire issue files or perform broad format rewrites unless the user explicitly requests it.
Do not edit unrelated feature lists/issues.

## 8. Mark for Review

Set artifact status to `reviewing` and summarize in a concise handoff (max 6 lines):
- What changed.
- What was verified.
- Manual test steps.
- Use `No Decision Needed` mode unless a gate requires explicit user choice.

Do not commit during `/go`.
Local commit authority belongs in `/done`; push approval still belongs there as well.

## On Failure

Attempt one focused remediation within approved scope, then rerun relevant verification.
If root cause is unclear or scope starts expanding, stop and switch to `/diag`.
