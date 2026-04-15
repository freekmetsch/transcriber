---
description: Unified diagnosis workflow - deep evidence, ranked hypotheses, and fix options
---

> See `.claude/commands/__common.md` for shared context.

This is the single diagnosis command for this repository.

Output of this workflow:
- Deep evidence-backed diagnosis.
- Ranked hypotheses.
- Logging strategy when evidence is missing.
- 2-3 fix options with one recommendation.

Do not implement code changes in this workflow.

## 0. Communication Mode

Default `No Decision Needed` for evidence. Use `Decision Required` for fix options and final recommendation.

## 1. Define Symptom and Scope

Capture clearly:
- What happened.
- What was expected.
- Where it occurs.
- Current repro path.

Mandatory issue artifact:
1. Locate matching issue file in `docs/known_issues/current/`.
2. If none exists, create `docs/known_issues/current/ISSUE_[SLUG]_[YYYYMMDD-HHMM].md`.
3. Add an investigation-log entry for this diagnosis session before proceeding.

Issue template (`docs/known_issues/current/ISSUE_[SLUG]_[YYYYMMDD-HHMM].md`):
```markdown
# Issue: [Brief description]
Created: [Date/Time]
Status: INVESTIGATING

## Symptom
[What user reported]

## Expected Behavior
[What should happen]

## Investigation Log
| Date | Action | Result | Next Step |
|------|--------|--------|-----------|

## Hypotheses
- [ ] ...

## Approaches Tried
(None yet)

## Related Files
- ...
```

Issue lifecycle:
- **INVESTIGATING** -> **FIX IN PROGRESS** -> **AWAITING VERIFICATION** -> **RESOLVED** (move to `solved/`)
- **REOPENED**: confirm with user, move back to `current/`, append new investigation-log entry, run `/diag` before `/go`.
- Only mark RESOLVED after explicit user confirmation.
- For AWAITING VERIFICATION, check in with user before moving between folders.

Treat `docs/known_issues/solved/` as historical unless user explicitly asks to reopen.

## 2. Deterministic Repro Pass (Mandatory First)

Run deterministic-first diagnosis before broad exploration.

Required first-pass outputs:
- Exact failing command/path/interaction.
- Exact failing file/line when available.
- Minimal failing case and expected vs actual behavior.
- Deterministic classification:
  - `deterministic`: reproducible with stable steps.
  - `non-deterministic`: intermittent, timing/state/environment dependent.

If deterministic (for example import error, config validation failure, test failure), prioritize:
- Contract/path mismatch checks.
- Minimal root-cause fix options.
- Verification command sequence to confirm resolution.

Only escalate to broad forensic exploration when deterministic pass is inconclusive.

## 3. Build Ranked Hypotheses

Create 2-4 concrete hypotheses.
Each must include:
- Suspected root cause.
- Why it fits the symptom.
- What evidence would confirm/refute it.
- Initial confidence (High/Med/Low).

## 4. Deep Evidence Pass (Forensic Mode, Conditional)

Investigate with a structured evidence matrix:
- Config state: env vars present/missing, provider selection.
- Data state: vault empty/populated, malformed markdown, missing folders.
- Environment: local/Docker, Windows/Linux, Python version.
- Timeline/regression window: what changed and when.

Trace (`docs/FLOW.md` is the pipeline map; if its `Last verified` date is >7 days old, spot-check function names first):
- Lineage: caller -> callee path (e.g., bot.py -> processor.py -> vault.py).
- Lateral: similar working code paths vs failing path.
- Pertinent negatives: where this is not failing and why.

Use `#context7` to verify all framework/library behaviors and APIs referenced in the diagnosis.

Use this section only when deterministic pass is inconclusive.

## 5. User-in-the-Loop Evidence

Actively involve the user in evidence gathering.
Define targeted checks such as:
- What Telegram shows vs what the bot logs.
- Docker logs vs local run behavior.
- Specific message types that trigger vs don't trigger the issue.
- Edge cases (voice vs text, Dutch vs English, very long input, empty input).

Treat user observations as first-class evidence in ranking hypotheses.

## 6. Logging Strategy (When Needed)

If evidence is insufficient, produce a hypothesis-linked logging matrix.

For each hypothesis define:
- Probe location (file/function).
- Signal to capture.
- What confirms/refutes it.

Use targeted probes only. Prefix logs with `[DIAG-LOG]`.

Example:
`logging.debug('[DIAG-LOG] processor: classification result', extra={'input': text, 'result': result})`

Then provide exact repro steps for user log collection.

## 7. Diagnostic Report

Provide:
1. Findings summary.
2. Deterministic classification (`deterministic` or `non-deterministic`) and why.
3. Ranked hypotheses table:
   - Hypothesis
   - Evidence for
   - Evidence against
   - Confidence
4. Fix options (2-3):
   - Strategy
   - Root-cause alignment
   - Sustainability
   - Tradeoffs
5. Recommendation.
6. Recommendation and options must be delivered in `Decision Required` mode with explicit reply choices.
7. Repro Pack (required):
   - Exact repro steps
   - Environment assumptions
   - Data/setup assumptions
   - Expected vs actual result
   - Issue file path updated during diagnosis

## 8. Hard Stop

Wait for explicit instruction to execute (`/go`).

**Related commands:** `/go` (execute chosen fix) | `/critique` (review implementation plan first) | `/3h` (broader planning)
