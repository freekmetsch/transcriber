# Feature List: Daily Driver UX — Logging, Launch, Text Guard, Active Feedback

Date: 2026-04-16
Status: Implemented
Scope: File logging, desktop launcher, text field detection, target window capture, output reliability, active feedback loop
Owner: Freek

---

## Problem Framing

Four blockers prevent daily-driver use:

1. **No visibility into what's happening.** Running via `pythonw.exe` (windowless) produces zero log output. Running from terminal shows logs but requires keeping a terminal open. When text doesn't appear, there's no way to diagnose why — no error feedback, no pipeline status, no output confirmation. The user reported "no text appearing and no feedback in terminal" after the pill bar redesign.

2. **App launch requires a terminal.** Daily-driver use means dozens of starts per day. Opening a terminal, navigating to the project directory, and running `python app.py` is too much friction. The user needs a desktop icon that starts the app silently.

3. **No text field guard.** The app blindly outputs text to whatever has focus. If the user presses the hotkey on the desktop, in file explorer, or in a non-editable element, text either goes nowhere or causes unintended actions (keystrokes sent to a tree view, menu, etc.). The user explicitly wants recording to only work in viable text fields.

4. **Passive feedback.** The pill bar shows state via mic icon color, but provides no confirmation that text was actually output, no warning when something fails, and no proactive guidance. The user can't tell if the app is "working" without reading terminal logs.

**Success criteria:**
- App starts from a desktop shortcut — zero terminal interaction
- All pipeline events are logged to a rotating file, always, regardless of launch method
- Recording only starts when a text field is detected; warns otherwise
- Text arrives in the original text field even if the user switches windows mid-recording
- User sees confirmation on output and clear feedback on failure

---

## Scope

### In Scope
- Rotating file logger (always on, works with `pythonw.exe`)
- Desktop shortcut creation from tray menu (`.lnk` with custom `.ico`)
- Text field detection module (pure ctypes, no new dependencies)
- Recording guard: block recording if no text field detected
- Target window capture: remember HWND at recording start, refocus on output
- Output confirmation: brief green flash on pill bar after successful output
- Error feedback: toast notifications for transcription/output failures
- Startup toast: "Transcriber ready — Ctrl+Shift+Space to dictate"
- Tray tooltip enhancement: last action status

### Out of Scope
- PyInstaller `.exe` packaging (separate infrastructure task)
- Continuous focus polling during recording (complexity too high for v1; capture-at-start is sufficient)
- Settings UI for preferences (deferred per FEATURE_LIST_UI_OVERHAUL.md)
- Mic level meter in overlay (deferred per FEATURE_LIST_UI_OVERHAUL.md)
- Session history panel (deferred)
- First-run wizard / onboarding (deferred)
- UI Automation (IUIAutomation) for browser-internal text field detection (v2 upgrade path)

---

## Chosen Approach

### Logging: RotatingFileHandler + dual output

Add a `RotatingFileHandler` to the root logger alongside the existing `StreamHandler`. Writes to `transcriber.log` in the app directory. Rotates at 5 MB, keeps 3 backups.

**Why:** Standard Python logging, zero dependencies. Works with both `python app.py` (dual output: console + file) and `pythonw.exe` (file only). Rotating prevents disk fill. Gives full diagnostic visibility for the "no text appearing" issue and all future debugging.

### Desktop Launch: PowerShell .lnk creation from tray menu

Add "Create Desktop Shortcut" to the tray menu. When clicked, generates a `.ico` from the existing PIL mic icon (cached at `icon.ico`), then runs a PowerShell command via `subprocess` to create a `.lnk` file on the desktop. Target: `pythonw.exe` (windowless). Arguments: absolute path to `app.py`. Working directory: app directory.

**Why:** Zero new dependencies — PowerShell's `WScript.Shell` COM is universal on Windows 10/11. User-initiated from tray (discoverable, not a CLI script). Produces a proper Windows shortcut with custom icon. `pythonw.exe` ensures no console window on launch.

**Rejected alternatives:**
1. **PyInstaller** — Most professional (standalone `.exe`), but adds build infrastructure, increases startup time, complicates development. Rejected for this phase: too much scope for what's needed. Recommended as a dedicated future task.
2. **Batch file (`.bat`)** — Simple but briefly flashes a console window. Rejected: poor daily-driver UX.
3. **VBS wrapper** — Can launch silently, but adds a file in an unfamiliar language. Rejected: harder to maintain than a PowerShell one-liner.

### Text Field Detection: ctypes class-name heuristic (no new dependencies)

New `focus_guard.py` module. Pure ctypes strategy:

1. `GetForegroundWindow()` → active window HWND
2. `GetWindowThreadProcessId()` → thread ID
3. `GetGUIThreadInfo()` → focused child control + caret info
4. `GetClassName()` → control class name

Decision logic:
| Signal | Result | Examples |
|--------|--------|----------|
| Known editable class name | **Allow** | `Edit`, `RichEdit20W`, `RICHEDIT50W`, `Scintilla`, `_WwG` (Word), `RichEditD2DPT` |
| Browser/Electron renderer | **Allow** (assume editable) | `Chrome_RenderWidgetHostHWND`, `MozillaWindowClass`, `Internet Explorer_Server` |
| `hwndCaret != 0` (active Win32 caret) | **Allow** | Any native control with blinking cursor |
| Known non-text window | **Block + warn** | `Progman` (desktop), `CabinetWClass` (explorer), `Shell_TrayWnd` (taskbar) |
| Unknown class | **Allow + log** | Permissive default — never block an unknown app |

**Why:** Zero dependencies (pure ctypes). Fast (~1ms per check). Catches the obvious cases: hotkey on desktop, in explorer, in an image viewer. Browser-permissive avoids false negatives in the most common dictation target (web apps). The `hwndCaret` signal strengthens native control detection.

**Known limitation:** Cannot distinguish "user is in a Chrome text field" from "user is reading a webpage." For accurate browser-internal detection, UI Automation (IUIAutomation COM) is needed. This is the recommended v2 upgrade path if the heuristic proves insufficient. For v1, browser-permissive is correct: most browser interactions involve text input, and blocking browser users would be worse than occasionally allowing a non-text-field start.

**Rejected alternatives:**
1. **`uiautomation` package** — Most accurate, sees into browser DOM via UIA. Rejected: external dependency, 50-200ms per call, installation issues on some systems. Recommended for v2.
2. **`comtypes` + IUIAutomation COM** — Accurate without external package but extremely verbose COM interface definitions. Rejected: essentially reimplementing `uiautomation` from scratch.
3. **Strict block-only (no permissive default)** — Safest against misfire but frustrating. Rejected: false negatives in Qt, JavaFX, and unusual frameworks would block legitimate use. Permissive default with logging lets us build the whitelist over time.

### Target Window Capture: HWND save + AttachThreadInput refocus

When recording starts (after text field check passes):
1. Save the foreground window HWND as the "output target"
2. When outputting text, compare current foreground to saved target
3. If different: `AttachThreadInput()` + `SetForegroundWindow()` to bring target back, output text, then return focus to wherever the user was
4. If same: output normally (current behavior — no change)

**Safety guards:**
- `IsWindow(target)` check before every refocus (handles closed windows)
- `AttachThreadInput` return value check (fails for elevated processes)
- Fallback to current-window output if refocus fails (never lose text)
- 50ms delay after refocus for window activation

**Why the user asked for this:** "unless you can keep it focused on that text box while I'm navigating away?" — The user wants to start dictating in Gmail, switch to a reference doc, and have text arrive in Gmail. `AttachThreadInput` + `SetForegroundWindow` is the standard technique used by accessibility tools for this exact pattern.

**Rejected alternatives:**
1. **No refocus (current behavior)** — Text goes wherever cursor is. Rejected: user explicitly asked for text to return to original field.
2. **WM_SETTEXT / EM_REPLACESEL** — Inject text via Win32 messages without needing focus. Rejected: only works for native Win32 Edit controls, not browsers, Electron, WPF.
3. **Keep original window focused** — Not possible. Windows doesn't support split focus. When user clicks another window, the original loses focus.

### Active Feedback: Toasts + pill bar enhancements

| Event | Feedback |
|-------|----------|
| App startup | Toast: "Transcriber ready — Ctrl+Shift+Space to dictate" |
| Recording blocked (no text field) | Toast: "No text field detected — click a text field first" + error sound |
| Text output success | Pill bar: brief green mic flash (200ms) |
| Transcription failure | Toast: "Transcription failed — check microphone" |
| Ollama timeout/fallback | Toast: "Post-processing unavailable — using raw text" |
| Target refocus failed | Log warning (not toast — too noisy) |

---

## Harden Audit

| Finding | Severity | Mitigation |
|---------|----------|------------|
| File logging may fail if app directory is read-only (e.g., Program Files) | Medium | App runs from user's cloned repo directory (always writable). Catch `PermissionError` in logging setup, fall back to console-only with warning. |
| PowerShell execution policy may block shortcut creation | Low | Use `-ExecutionPolicy Bypass` for the single command. Show error toast and log if it fails. |
| `AttachThreadInput` fails for elevated (admin) target windows due to UIPI | Medium | Check return value. Fallback to normal paste if refocus fails. Log warning. Never crash. |
| Stale target HWND if user closes window during recording | Medium | `IsWindow()` guard before every refocus. Clear target if window is gone. Fallback to current-window output. |
| Class-name heuristic misclassifies custom UI frameworks (Qt, JavaFX, GTK) | Low | Permissive default — unknown classes are always allowed, never blocked. Log class name so we can build the whitelist over time from real usage. |
| Toast notifications fail silently if `winotify` is not installed | Low | Already handled: `notifications.py` checks `is_available()`. All critical feedback also appears in pill bar and log file. Toasts are supplementary, not primary. |
| `.ico` generation requires Pillow ICO support | Low | Pillow supports ICO natively since v3.0. Generate once on first shortcut creation, cache at `icon.ico`. |
| Multiple app instances could contend on log file | Low | Only one instance runs (pystray enforces via tray icon singleton). Not a practical concern. |

---

## Phase Plan

### Phase 1: Foundation — Logging, Launch, Output Diagnosis (1 context window)

**T1: Add rotating file logger**
- File: `app.py` (logging setup near line 27)
- Add `logging.handlers.RotatingFileHandler` → `transcriber.log`, 5 MB, 3 backups
- Keep existing `StreamHandler` for console output
- Add `transcriber.log` and `*.log` to `.gitignore`
- Import: `from logging.handlers import RotatingFileHandler`

**T2: Diagnose and fix text output**
- File: `output.py` — add `log.info`/`log.warning` around every paste/type operation
- File: `app.py` — add logging at each pipeline boundary: audio received, transcribe start/end, post-process start/end, output start/end
- Run app → speak → read `transcriber.log` → identify where pipeline stalls
- Fix identified issues (likely focus-related with new pill bar or timing)

**T3: Desktop shortcut mechanism**
- New file: `shortcut.py` (~50 lines)
  - `create_icon() -> Path`: PIL mic image → `icon.ico` (cached, only regenerated if missing)
  - `create_desktop_shortcut() -> bool`: PowerShell `WScript.Shell` COM → `.lnk` on Desktop
  - Target: `pythonw.exe` from `sys.executable` parent
  - Arguments: absolute path to `app.py`
  - Working directory: app directory
  - Icon: `icon.ico`
- File: `app.py` — add "Create Desktop Shortcut" to tray menu (`_build_tray_menu`)
- Add `icon.ico` to `.gitignore`

**T4: Startup and error feedback**
- File: `app.py` (`run()` method, after "Transcriber ready" log)
- Send startup toast: "Transcriber ready — Ctrl+Shift+Space to dictate"
- File: `app.py` (error paths in `_on_speech_segment` and `_stop_and_transcribe`)
- Send toast on transcription failure and Ollama fallback
- Use existing `notifications.py` patterns

### Phase 2: Smart Recording — Text Guard + Target Capture (1 context window)

**T5: Focus guard module**
- New file: `focus_guard.py` (~130 lines)
- ctypes structures: `GUITHREADINFO` (cbSize, flags, hwndActive, hwndFocus, hwndCapture, hwndMenuOwner, hwndMoveSize, hwndCaret, rcCaret)
- Functions:
  - `check_text_field() -> tuple[bool, str, int]`: returns (is_viable, class_name, hwnd)
  - `capture_target() -> int`: save and return foreground HWND
  - `refocus_target(target: int, return_to: int | None) -> bool`: AttachThreadInput + SetForegroundWindow + optional return
  - `is_target_alive(hwnd: int) -> bool`: IsWindow wrapper
- Class whitelists/blocklists as module-level sets
- All win32 calls wrapped in try/except (never crash on API failure)

**T6: Integrate recording guard into hotkey flow**
- File: `app.py` (`_toggle_recording` method)
- On recording start (before `self._recording = True`):
  1. `is_viable, class_name, hwnd = focus_guard.check_text_field()`
  2. If not viable: toast warning + error sound + return (don't start recording)
  3. If viable: `self._target_hwnd = hwnd` + proceed normally
- Log: `"Recording target: %s (hwnd=%d)"` or `"Recording blocked: no text field (%s)"`

**T7: Target window refocus on output**
- File: `output.py` — add `output_text_to_target(text, target_hwnd, method)` function
  - Check if `GetForegroundWindow() == target_hwnd`
  - If different: save current foreground → refocus target → paste/type → return focus
  - If same: call existing `output_text()` directly
  - Fallback: if refocus fails, call `output_text()` to current window
- File: `app.py` — pass `self._target_hwnd` through `_on_speech_segment` and `_stop_and_transcribe`
- Streaming: also pass target to `output_text_streaming`

**T8: Output confirmation in pill bar**
- File: `recording_indicator.py` — add `show_success()` method
  - Briefly recolor mic to green (#2ECC71) for 300ms, then revert to current state color
  - Thread-safe via `root.after()` dispatch (same pattern as other methods)
- File: `app.py` — call `self._recording_indicator.show_success()` after successful output in both streaming and batch paths

**T9: Tray tooltip with status**
- File: `app.py` (`_tray_tooltip` method)
- After successful output: update tooltip to "Last dictation: Xs ago"
- After error: update tooltip to "Last error: [brief description]"
- Idle: "Transcriber — Ctrl+Shift+Space to dictate (N terms)"

---

## Verification

### Phase 1
- [ ] App starts without errors; `transcriber.log` exists and contains startup messages
- [ ] Running via `pythonw.exe` (no console) still produces log file
- [ ] Startup toast appears: "Transcriber ready"
- [ ] Tray menu shows "Create Desktop Shortcut" item
- [ ] Clicking "Create Desktop Shortcut" creates `Transcriber.lnk` on desktop with mic icon
- [ ] Double-clicking desktop shortcut starts app (no console window)
- [ ] Dictate in Notepad — text appears correctly
- [ ] `transcriber.log` shows full pipeline: audio → whisper → ollama → output with timing
- [ ] Error toast appears when transcription fails (e.g., no mic connected)

### Phase 2
- [ ] Ctrl+Shift+Space on desktop → warning toast, recording does NOT start
- [ ] Ctrl+Shift+Space in Notepad → recording starts, text appears
- [ ] Ctrl+Shift+Space in Chrome text field → recording starts (browser-permissive)
- [ ] Start recording in Notepad → switch to browser → speak → text appears in Notepad (refocus)
- [ ] Start recording in Notepad → close Notepad → speak → text goes to current window (stale HWND fallback)
- [ ] After text output → brief green flash on pill bar mic icon
- [ ] Tray tooltip shows "Last dictation: Xs ago" after output
- [ ] `transcriber.log` shows class names and guard decisions for every hotkey press
- [ ] `focus_guard.py` never crashes on any window (fuzz test: try hotkey in various apps)

---

## Failure Modes

| Failure | Likelihood | Impact | Mitigation |
|---------|------------|--------|------------|
| Class-name heuristic blocks a legitimate text field | Low | User can't dictate in that app | Permissive default for unknown classes. Log class name. Add to whitelist config. |
| `AttachThreadInput` refocus fails (elevated target) | Medium | Text goes to current window instead of target | Fallback to normal output. Log warning. Never lose text. |
| Desktop shortcut points to wrong Python (e.g., venv vs system) | Low | App doesn't start from shortcut | Use `sys.executable` resolved to `pythonw.exe`. Validate existence before creating shortcut. |
| Toast notifications not showing (Focus Assist, DND mode) | Medium | User misses warnings | Critical feedback also in pill bar (green flash / state change) and log file. Toasts are supplementary. |
| Log file grows large on high-dictation days | Low | Disk fill | RotatingFileHandler with 5 MB cap and 3 backups = max 20 MB. |
| `GetGUIThreadInfo` fails on UWP/WinUI3 apps | Low | Falls through to "unknown class" → permissive allow | Expected behavior. No crash. Logged for whitelist building. |
| Refocus briefly flashes the target window | Medium | Mild visual disruption when user is in another app | Acceptable trade-off — user asked for text to arrive in original field. Window flash is ~100ms. |

---

## Open Questions

**Q: Should the text field guard be strict (block recording) or permissive (warn but allow)?**
Default: Strict — don't start recording if no text field detected. Reason: the user explicitly said "only be able to record when I'm actually in a viable text box." Configurable via `ui.text_field_guard: strict | warn | off` for users who want permissive mode.

**Q: Should target refocus return focus to where the user navigated?**
Default: Yes — save the foreground window before refocus, paste in target, then `SetForegroundWindow` back to where the user was. Reason: user shouldn't be yanked to the target window against their will. The text just silently appears there.

**Q: Where should the log file live?**
Default: App directory (`transcriber.log`). Reason: simple, visible, near the code. The app runs from a user-writable directory (cloned repo). Alternative if needed: `%APPDATA%/Transcriber/` for a more "installed app" location.

**Q: Should there be a config option to add custom class names to the text field whitelist?**
Default: Not in v1. Log unknown class names so the built-in whitelist can grow over time. If a user reports a false block, add the class name in a code update. Config-based whitelist is a v2 enhancement if needed.

---

## Resume Pack

- **Goal**: Transform transcriber from developer tool to daily-driver — file logging, desktop launch, text field guard, target capture, active feedback
- **Current state**: Implemented and code-verified on 2026-04-16 — all phases complete
- **Files changed**: `app.py` (logging + guard + feedback + tray menu), `output.py` (target refocus), `notifications.py` (app-level toasts + `notify_info`), `autostart.py` (shared pythonw), `recording_indicator.py` (show_feedback), `.gitignore` (*.log, icon.ico)
- **Files created**: `shortcut.py`, `focus_guard.py`
- **Dependencies added**: `winotify` (pip install)
- **Critique fixes applied**: winotify installed, notifications decoupled from brain, batch mode green flash visible (deferred hide), pythonw logic shared, OneDrive desktop path handled
- **Verification findings (2026-04-16)**: All assumptions match code. One bug found and fixed — `_create_shortcut` reused `notify_startup`, which garbled the success toast into "Press Desktop shortcut created! to dictate". Added `notifications.notify_info(title, detail)` and routed shortcut success through it. Syntax checks pass on all touched files.
- **Pending verification**: Manual smoke test per Phase 1/2 checklists (automated syntax checks pass)
