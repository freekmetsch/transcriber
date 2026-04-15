# Feature List: Phase 3.5 — UX Polish for Vocabulary Brain

Date: 2026-04-15
Status: Complete
Scope: Desktop UX improvements to make the vocabulary brain usable day-to-day
Owner: Freek

---

## Problem Framing

Phase 3 built the vocabulary brain — SQLite database, Whisper prompt conditioning, correction tracking, auto-learning. All the machinery works (59/59 tests passing). But the **user interface to that machinery** has three problems:

1. **Invisible correction flow**: The correction window only appears when the user presses Ctrl+Shift+C. If they forget (they will), no corrections get logged, no auto-learning happens, and the brain stays empty forever. The brain's value proposition depends on corrections flowing in.

2. **No feedback**: Auto-learning events, Ollama failures, vocabulary changes — all go to terminal logs. The user has no idea the brain is working unless they watch the console. This makes the whole system feel broken even when it's working.

3. **Vocabulary management requires a terminal**: `python vocab.py add "Freek" --hint "freak" --priority high` is fine for development, but not for daily use. The user should be able to manage vocabulary from the tray icon — the thing that's always visible.

**Core insight**: The brain is only as good as the corrections that feed it. The single most important UX change is making corrections effortless and automatic.

---

## Scope

### In Scope
- Auto-show correction window after each transcription (configurable mode)
- "Add to vocabulary" button in correction window for immediate term addition
- Windows toast notifications for key events (auto-learned, errors)
- Vocabulary manager window accessible from system tray menu
- Dynamic tray menu updates (live vocabulary count)
- Non-aggressive focus behavior (don't steal keystrokes from target app)

### Out of Scope
- Full settings GUI (config.yaml is fine for settings)
- Redesign of system tray icon or menu structure
- New keyboard shortcuts beyond existing ones
- Web-based or Electron-based UI
- Cross-platform UI (Windows-only is fine)

---

## Chosen Approach: Auto-Show Correction + Toast Notifications + Tray Vocab Manager

### Why This Approach

1. **Auto-show correction window** is the highest-impact change. The brain can't learn if corrections don't flow in. Making the correction window appear automatically (with a tasteful UX) removes the biggest friction point.

2. **Toast notifications via `winotify`** are the lightest way to give feedback. Native Windows 10/11 notifications — no custom UI needed, no focus stealing, just a brief popup in the notification area. Zero new visual design work.

3. **Vocabulary manager as a Tkinter Toplevel** reuses the existing Tk thread from the correction window. No new dependency, no second mainloop, no thread conflicts. Simple list+buttons UI is all that's needed.

4. **Everything is optional/configurable**: correction mode (always/hotkey/never), notifications (on/off). The system stays functional with all UX features disabled — just less discoverable.

### Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| **Keep correction on hotkey only, add only toast notifications** | Doesn't solve the core problem — if the user forgets Ctrl+Shift+C, no corrections flow in. The brain stays empty. Toast notifications alone can't fix an invisible feature. |
| **Full standalone settings/manager Tkinter app** | Over-engineered for a tray-resident utility. Would need its own window management, wouldn't feel integrated. The tray menu is the natural home for vocabulary management. |
| **Electron or web-based UI** | Massive dependency for a simple list window. Would increase app startup time and memory usage for no real benefit over Tkinter. |
| **Auto-show AND auto-focus correction window** | Dangerous — steals keystrokes from the target app. If the user dictates "Hello world" and immediately starts typing more, the correction window eats those keystrokes. Auto-show without auto-focus is the safe middle ground. |

---

## Phase Plan

### Phase 3.5: UX Polish
**Goal**: Make the vocabulary brain feel responsive and effortless to use.
**Context strategy**: single-window
**Risk tier**: R1 (localized UI changes, existing backend unchanged)
**Estimated effort**: S-M (~1 session)

---

#### 3.5A: Auto-Show Correction Window

**What changes:**
- After each transcription completes and text is pasted, the correction window auto-shows with the transcribed text.
- Window appears near the system tray (bottom-right) as a non-modal popup.
- **Does NOT steal focus** — the target app keeps focus. User can ignore the correction window and it auto-hides after a configurable timeout (default: 8 seconds). Or they can click it to edit.
- If user clicks the window or presses the correction hotkey, the window gains focus and the auto-hide timer stops.
- Enter saves correction + hides. Escape dismisses without saving. Auto-hide after timeout also dismisses without saving.

**New config option:**
```yaml
brain:
  correction_mode: auto    # auto | hotkey | off
  correction_timeout: 8    # seconds before auto-hiding (0 = no auto-hide)
```

**Files modified:**
- `correction_ui.py` — Add auto-hide timer, no-focus show mode, position near tray
- `app.py` — Call `show()` after paste based on `correction_mode` setting
- `config.py` — Add `correction_mode` and `correction_timeout` defaults
- `config.yaml` — Add new settings

**Why non-aggressive focus:**
The dictation workflow is: hold hotkey → speak → release → text pastes into Notepad/browser/etc. The user's cursor is in their target app. If the correction window steals focus, the very next keystrokes go to the correction window instead of their document. This would be maddening. Instead: show the window, let the user glance at it, and only focus it if they click or press the correction hotkey.

---

#### 3.5B: Quick-Add Vocabulary from Correction Window

**What changes:**
- Correction window gets an "Add to vocab" button (or Ctrl+Shift+A shortcut while window is focused).
- When clicked: opens a small inline panel at the bottom of the correction window with fields for: term (pre-filled with the corrected text), phonetic hint (pre-filled with the original text), priority (normal/high toggle).
- One-click add — term immediately appears in vocabulary, prompts rebuild.
- This lets users teach the brain without waiting for the 3-correction auto-learn threshold.

**Files modified:**
- `correction_ui.py` — Add "Add to vocab" button and inline panel
- `app.py` — Wire vocab-add callback to brain

---

#### 3.5C: Windows Toast Notifications

**What changes:**
- Add `winotify` as an optional dependency for native Windows 10/11 toast notifications.
- Notifications for:
  - **Auto-learned term**: "Brain learned: Freek (was: Freak) — after 3 corrections"
  - **Ollama fallback**: "Post-processing unavailable — using raw text" (once per session, not every transcription)
  - **Vocabulary imported**: "Imported 12 terms from brain_export.json"
- Notifications are silent (no sound) and brief (5 seconds).
- If `winotify` is not installed, notifications are silently skipped (log-only fallback).
- Configurable on/off.

**New config option:**
```yaml
brain:
  notifications: true    # Windows toast notifications for brain events
```

**New file:**
- `notifications.py` — Thin wrapper around `winotify` with graceful fallback

**Files modified:**
- `app.py` — Send notifications on auto-learn, Ollama fallback, import
- `config.py` — Add `notifications` default
- `config.yaml` — Add setting
- `requirements.txt` — Add `winotify>=1.1.0` (optional, app works without it)

---

#### 3.5D: Vocabulary Manager Window

**What changes:**
- New Tkinter `Toplevel` window (runs on the same Tk thread as correction window) accessible from the tray menu: "Manage vocabulary..."
- Shows a scrollable list of all vocabulary terms with columns: Term, Hint, Priority, Frequency, Source.
- Buttons: Add, Remove, Edit Priority, Export JSON, Import JSON.
- Add opens a small dialog with fields: term, phonetic hint, priority.
- Remove deletes the selected term after confirmation.
- Edit Priority toggles between normal/high.
- Export/Import use a native Windows file dialog (`tkinter.filedialog`) instead of hardcoded paths.
- Rebuilds Whisper prompt and LLM vocabulary text after any change.
- Dark theme matching the correction window.

**Files modified:**
- New file: `vocab_ui.py` — Vocabulary manager Toplevel window
- `correction_ui.py` — Refactor Tk thread management so it can host multiple Toplevel windows
- `app.py` — Add "Manage vocabulary..." to tray menu, wire callbacks

---

#### 3.5E: Dynamic Tray Menu

**What changes:**
- Tray menu vocabulary count updates after each change (correction, auto-learn, manual add/remove).
- Current behavior: count is set once at startup and never changes.
- Approach: rebuild the tray menu on vocabulary change events using `pystray`'s `update_menu()` or by toggling menu item visibility.

**Files modified:**
- `app.py` — Add method to refresh tray menu, call it after brain mutations

**Note**: `pystray` doesn't natively support dynamic menu updates on all backends. If the Windows backend doesn't support it, we fall back to showing the count in the tray icon tooltip instead (which does update dynamically).

---

## Failure Modes and Mitigations

| # | Failure Mode | Trigger | Impact | Mitigation | Residual Risk |
|---|---|---|---|---|---|
| 1 | Auto-show steals focus from target app | User types immediately after dictation ends | Keystrokes go to correction window instead of their document | Show without focus (`root.focus_force()` removed). Only focus on click or correction hotkey. | Edge case: some Windows apps may still lose focus when a new window appears. Test with Notepad, browser, VS Code. |
| 2 | Two Toplevel windows conflict | Correction window and vocab manager both visible | Tk event loop stalls or crashes | Both are `Toplevel` on the same `Tk()` root, sharing one mainloop. Tested pattern — works reliably. | If vocab manager is open during rapid corrections, UI may feel sluggish. Acceptable. |
| 3 | `winotify` not installed | User doesn't install optional dependency | No toast notifications shown | Import wrapped in try/except. If missing, all notification calls become no-ops. Log once at startup. | User misses auto-learn feedback. Terminal log still has the info. |
| 4 | Correction window annoying | User doesn't want to see it after every dictation | User disables brain entirely out of frustration | `correction_mode: hotkey` disables auto-show. `correction_mode: off` hides it completely. Default `auto` with 8s timeout is a mild nudge, not aggressive. | Some users will set it to `hotkey` and forget it exists. That's their choice. |
| 5 | Auto-hide races with user click | User clicks correction window just as timeout fires | Window hides mid-edit | Cancel auto-hide timer on any user interaction (click, keypress). Re-arm only if user hasn't touched the window. | Sub-second race still possible. Timer cancel on `<FocusIn>` event handles this. |
| 6 | Tray menu can't dynamically update | `pystray` Windows backend limitation | Vocabulary count stays stale | Fall back to updating tray icon tooltip text (always works). Tooltip shows "Transcriber — 12 terms". | Minor visual inconsistency. Non-blocking. |
| 7 | File dialog blocks Tk thread | `tkinter.filedialog` is modal | Correction window can't receive events during file dialog | File dialog is inherently modal — this is expected. Correction auto-hide timer should pause while dialog is open. | Non-issue in practice — file dialogs are brief. |

---

## Risk Tier and Verification Matrix

| Sub-phase | Risk Tier | Verification |
|---|---|---|
| 3.5A: Auto-show correction | R1 | Manual test: dictate → window appears → doesn't steal focus. Test timeout auto-hide. Test click-to-focus. Test all 3 modes (auto/hotkey/off). |
| 3.5B: Quick-add vocab | R1 | Manual test: correct text → click "Add to vocab" → term appears in `python vocab.py list`. Verify prompt rebuilds. |
| 3.5C: Toast notifications | R1 | Manual test: trigger auto-learn → toast appears. Test without `winotify` installed → no crash. |
| 3.5D: Vocabulary manager | R1 | Manual test: open from tray → add/remove/edit terms. Export/import via file dialog. Verify brain DB updated. |
| 3.5E: Dynamic tray menu | R1 | Manual test: add term → tray menu count updates (or tooltip updates). |

---

## Files Summary

**New files (2):**
```
transcriber/
├── notifications.py    # Toast notification wrapper (winotify, graceful fallback)
└── vocab_ui.py         # Vocabulary manager Toplevel window
```

**Modified files (5):**
```
transcriber/
├── correction_ui.py    # Auto-show/hide, no-focus mode, quick-add panel, position near tray
├── app.py              # Wire auto-show, notifications, vocab manager, dynamic tray
├── config.py           # New defaults: correction_mode, correction_timeout, notifications
├── config.yaml         # New settings section
└── requirements.txt    # Add winotify>=1.1.0 (optional)
```

**Unchanged (8):**
```
brain.py, learning.py, prompt_builder.py, postprocessor.py,
transcriber.py, recorder.py, output.py, commands.py, vocab.py
```

---

## User Guide: Testing Phase 3 Today

### What you can test right now (on this laptop, no GPU needed)

**1. Vocabulary CLI tool:**
```bash
cd C:\Users\metsc\Cloned_Repositories\transcriber
python -m venv venv && venv\Scripts\activate
pip install pyyaml

# Add your name and commonly misrecognized terms
python vocab.py add "Freek" --hint "freak" --priority high
python vocab.py add "Claude Code" --hint "claud coat"
python vocab.py add "Anthropic" --hint "anthropik"
python vocab.py add "HeliBoard" --hint "heli board"

# See what's in the brain
python vocab.py list
python vocab.py stats

# Export for backup / sync to phone later
python vocab.py export brain_export.json

# Test import round-trip
python vocab.py import brain_export.json
```

**2. Run the test suite:**
```bash
pip install pytest
python -m pytest tests/ -v
# Should see: 59 passed
```

**3. Test the correction UI standalone:**
```python
# Quick test script — run from transcriber/ dir
python -c "
from correction_ui import CorrectionWindow
import time
def on_corr(orig, corr):
    print(f'Correction: {orig!r} -> {corr!r}')
w = CorrectionWindow(on_correction=on_corr)
w.start()
w.show('Hello Freak, how are you today?')
time.sleep(30)  # gives you 30 seconds to test the window
"
# → A dark correction window appears. Edit text, press Enter.
# → Terminal shows the correction callback.
```

### What you test on the desktop PC (GPU required)

**4. Full pipeline end-to-end:**
```bash
# On your desktop PC:
cd C:\Users\metsc\Cloned_Repositories\transcriber
git pull                           # get latest
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt

# Start Ollama (if not running)
ollama serve
ollama pull qwen2.5:3b

# Seed vocabulary before first run
python vocab.py add "Freek" --hint "freak" --priority high
python vocab.py add "Claude Code" --hint "claud coat"
python vocab.py stats              # verify terms are loaded

# Run the app
python app.py
```

**5. Test the transcription + brain pipeline:**
1. Hold **Ctrl+Shift+Space** → say "Hello, my name is Freek" → release
2. Text pastes into active window. Check if "Freek" is spelled correctly (brain should help).
3. Press **Ctrl+Shift+C** → correction window opens with the transcribed text
4. If "Freek" was wrong, fix it and press Enter → correction logged
5. Repeat 3 times with the same error → auto-learn triggers (check terminal logs)
6. Run `python vocab.py stats` → should show the auto-learned term
7. Run `python vocab.py corrections` → should show correction history

**6. Test formatting commands:**
- Hold hotkey → say "Hello comma this is a test period new line next sentence" → release
- Should output: `Hello, this is a test.\nNext sentence`
- Try Dutch: "Hallo komma dit is een test punt nieuwe regel"

**7. Test brain export/import (Syncthing path for phone sync):**
```bash
python vocab.py export brain_export.json
# Copy brain_export.json to your Syncthing folder for future Android sync
```

---

## Open Questions

**Q8: Should the correction window auto-show by default?**
Default: Yes (`correction_mode: auto` with 8-second timeout). Reason: The brain can't learn without corrections. Auto-show is the highest-impact UX change. Users who find it annoying can switch to `hotkey` mode.

**Q9: Should toast notifications make a sound?**
Default: No (silent notifications). Reason: Dictation already produces output — adding a notification sound on top would be jarring. Visual-only is sufficient.

**Q10: Should the vocabulary manager support bulk add (paste a list of terms)?**
Default: No — single add for now. Reason: `python vocab.py import terms.json` handles bulk import. The GUI should be simple. Bulk add is a future nice-to-have.

---

## Resume Pack

**Goal**: Polish the vocabulary brain UX so corrections flow naturally and the brain actually learns.

**Current state**: Complete. All 5 sub-phases implemented and syntax-checked.

**What was built (Phase 3.5)**:
- `correction_ui.py` — Rewritten: auto-show/hide with configurable timeout, no-focus passive mode (doesn't steal keystrokes from target app), quick-add vocabulary panel (Ctrl+Shift+A), position near system tray, auto-hide cancels on user interaction
- `notifications.py` — New: winotify wrapper for native Windows 10/11 toast notifications (auto-learned terms, Ollama fallback once-per-session, vocabulary import). Graceful no-op if winotify not installed.
- `vocab_ui.py` — New: Tkinter Toplevel vocabulary manager (dark theme, scrollable Treeview, add/remove/toggle-priority/export/import via native file dialogs). Shares Tk root with correction window.
- `app.py` — Rewired: auto-show correction after transcription (respects correction_mode setting), notifications on auto-learn/Ollama fallback/import, "Manage vocabulary..." in tray menu, dynamic tray menu rebuilds on vocabulary changes, tooltip shows live term count
- `config.py` — Added defaults: correction_mode (auto), correction_timeout (8), notifications (true)
- `config.yaml` — Added settings: correction_mode, correction_timeout, notifications
- `requirements.txt` — Added winotify>=1.1.0

**Resolved open questions**: Q8 (auto-show: yes, default), Q9 (silent notifications: yes), Q10 (no bulk add in GUI).

**Dependencies**: `winotify>=1.1.0` (optional, for toast notifications).

**Next step**: Phase 4 (Android Voice Input Service) or manual smoke test on desktop PC.

**Next command**: `/run` (Phase 4)
