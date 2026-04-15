---
description: Task wrap-up - documentation review, verification, local commit, and push
---

> See `.claude/commands/__common.md` for shared context.

## 0. Communication Mode

Default `No Decision Needed`. Use `Decision Required` only when commit scope is ambiguous.

## 1. Finalize Active Artifact (Required)

Update exactly one active artifact for this task:
- Feature work: the specific `docs/feature-lists/FEATURE_LIST_*.md` used during execution.
- Issue work: the specific `docs/known_issues/current/*.md` used during execution.

Do not bulk-edit multiple feature lists with wildcard scope.

## 2. Post-Implementation Check (Context-Dependent, Mandatory)

Build the checklist from changed files and include only applicable rows.

Suggested applicable rows:
- Syntax validity (`python -m py_compile` on changed files)
- Manual smoke test (run `python app.py`, test hotkey, verify transcription)
- Config validation (if config.py or config.yaml changed)
- Type contracts (if type annotations changed — `mypy <file> --ignore-missing-imports`)
- Vocabulary DB safety (if brain.py changed — no data loss paths)

If any check fails, fix before commit.

## 3. Risk-Tier Closure Checks

Confirm closure checks based on task risk tier:
- `R0`: targeted verification evidence captured.
- `R1`: targeted verification + manual smoke validation captured.
- `R2`: `py_compile` syntax check results captured.
- `R3`: explicit rollback plan and explicit user approval log captured.

## 4. Documentation Review

If behavior/architecture changed, update:
- `docs/feature-lists/FEATURE_LIST_TRANSCRIBER.md` (resume pack, phase status)
- Relevant `docs/feature-lists/*.md`

Reference policy for `/done`:
- Do not run fresh Context7 lookups by default.
- Use prior verification evidence unless a wrap-up claim depends on unresolved external API behavior.

## 5. Safe Commit Flow

Treat `/done` as the user's explicit authorization to create one local commit for the most logical completed scope of the task.
Stage only intended files (no `git add .`). Windows: run as separate commands.
Do not ask again before commit unless the scope is ambiguous, verification failed, or there is material risk of bundling unrelated work.
Leave unrelated or in-progress files unstaged when the logical task scope is clear.
After a successful commit, push to origin:
1. Run `git push origin master`.
2. `git push` reporting **"Everything up-to-date"** is a **success** — proceed normally.
3. If rejected with a non-fast-forward error ("fetch first" / "rejected"), automatically run `git pull --rebase` then retry `git push origin master`. No user input needed — this is a single-developer project and the rebase is always safe.
4. If the retry also fails, report the exact error and stop.

If you need user input because commit scope is ambiguous, use `Decision Required` mode with explicit reply choices.

## 6. Confirm and Hand-Off

Summarize completed work and verification results.
Use `No Decision Needed` mode unless push approval or commit-scope clarification is required.
