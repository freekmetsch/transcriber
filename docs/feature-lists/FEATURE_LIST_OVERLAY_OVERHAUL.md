# Feature List: Overlay Overhaul — Win+H Parity + Visual Modernization

Date: 2026-04-17
Status: P1 implemented (awaiting smoke test); P2 + P3 pending
Scope: Recording overlay (always-visible), Win+H QoL parity, modes system, optional PySide6 visual port
Owner: Freek

## Implementation Log

**2026-04-17 — Phase P1 complete (Win+H behavior parity on Tk)**
Committed: (pending). Files changed: `recording_indicator.py` (major refactor),
`recorder.py` (+`cancel()` on both recorders), `app.py` (tray state, Esc cancel,
overlay toggle hotkey, gear menu wiring), `config.py` + `config.yaml`
(`ui.overlay_visible_on_start`, `ui.toggle_overlay_hotkey`).

Shipped in P1:
- P1-1: Always-visible state machine — added `idle` state, renamed
  `show/hide` → `begin_session/end_session`, added `dismiss/restore`.
- P1-2: Click-mic-to-toggle — zone-based hit test on Canvas, `WS_EX_NOACTIVATE`
  preserves target focus (verified at import-time; manual smoke pending).
- P1-3: Gear glyph (left) opens dynamic popup menu; close × (right) dismisses;
  first-close toast points user at `Ctrl+Shift+H` / tray "Show overlay".
- P1-4: Cancel-on-Esc — statically registered `keyboard` Esc hotkey with
  `suppress=False`, handler no-ops unless `self._recording`. Added
  `Recorder.cancel()` and `StreamingRecorder.cancel()` (drains queue, signals
  worker, joins outside lock to avoid latent deadlock).
- P1-5: Four-state tray icons (`idle`/`listening`/`transcribing`/`blocked`)
  via `_ICON_STATES` dict and `_set_tray_state()`; blocked state draws red X
  overlay on the mic.
- P1-6: Config keys + tray "Show/Hide overlay" (dynamic label via
  `is_dismissed()`) + all wiring.

Post-simplify cleanup: removed 4 `_*_noarg` adapter methods (gave underlying
methods `icon=None, item=None` defaults instead); hoisted `_TRAY_STATE_TITLES`
to module scope; added `_set_state()`/`_return_to_idle()` helpers to collapse
6× `end_session + _set_tray_state("idle")` and 3× `set_state + _set_tray_state`
duplication; moved `worker.join()` outside the lock in
`StreamingRecorder.cancel()`; swapped `update_level` lambda for `after(0, fn, arg)`
positional form on the audio hot path.

**Pending (user)**: run the 10-step smoke plan in §P1-6 before declaring done.
**Next**: start a fresh `/run` on this artifact to execute P2.

---

## Problem Framing

The current `recording_indicator.py` is a 567-line tkinter Canvas pill that **only appears while recording or transcribing**. Win+H — the OS-native dictation overlay the user models against — works the opposite way: it stays visible from the moment it's invoked until explicitly dismissed, and the central mic button toggles capture on click.

Three concrete gaps:

1. **Visibility model mismatch.** Our pill flashes in for the recording session and disappears the rest of the time. Win+H's overlay is a persistent "I'm here, click me or hotkey me" surface. The user explicitly likes the persistent model and wants it ported.
2. **UI looks like a debug panel.** Tkinter `Canvas` with overlapping ovals to fake a pill, color-key transparency that fringes magenta at AA edges, no Mica/blur, no per-pixel alpha, no real drop shadow, no animated waveform, jagged primitives. Compared to Win+H, PowerToys Command Palette Dock, Raycast for Windows, Wispr Flow, Superwhisper — all of which are GPU-rendered with Mica/Acrylic — our pill reads as developer-art.
3. **Missing Win+H QoL.** No click-mic-to-toggle, no settings gear, no close button → minimize-to-tray, no cancel-on-Esc, no voice control commands during dictation ("stop listening", "delete that", "new line"), no foreground-app awareness.

**Root insight.** The pill is the brand. It's the only surface the user looks at during dictation. Closing the gap to Win+H requires both a behavior change (always-visible state machine) **and** a rendering layer with true rounded windows, system backdrops, and 60 fps animation — which Tk on Windows cannot deliver without compromise.

**Goal.** Reach Win+H feature parity, then exceed it on the dimensions Win+H is weak (streaming display, history, vocab/brain, offline, modes), inside a visual shell that looks native to Windows 11.

---

## Scope

### In Scope
- Always-visible overlay state machine (idle → listening → transcribing → idle, never auto-hidden)
- Click-mic-to-toggle parity with Win+H, with focus_guard handled correctly
- Settings gear (left), close X (right) — close minimizes to tray, restored from tray menu
- Cancel-on-Esc while recording → discard segment, no paste
- Persistent overlay show/hide toggle hotkey (Ctrl+Shift+H)
- Core voice control commands: "stop listening", "delete that", "scratch that", "new line", "new paragraph"
- State-keyed tray icon (4 distinct glyphs: idle / listening / transcribing / blocked)
- Modes system foundation (Default / Email / Code) with cycle hotkey
- Visual port to PySide6 + qframelesswindow (Mica backdrop, true rounded corners, drop shadow, 60 fps waveform)
- Hover-expand: hovering the pill reveals last 3 transcriptions with one-click re-paste
- Win10 fallback: opaque dark rounded background when Mica unavailable
- Position persistence (already works, preserved through port)

### Out of Scope (deferred to later feature lists)
- Full per-app Power Mode (auto-switch profile by foreground app) — foundation only
- CLI remote flags (--toggle, --cancel)
- First-run wizard
- Standalone settings window (gear opens a popover, not a tabbed window)
- Migrating correction_ui.py / vocab_ui.py to PySide6 (they're modal, not always-visible — Tk stays)
- Whisper Mode (gain boost + stricter VAD profile)
- Per-word confidence highlighting
- Voice command for selection ("select this word") — needs cursor inspection, not feasible without UIAutomation work

---

## Chosen Approach — and Why

### Decision 1: Always-visible state machine (Phase 1, Tk)

Extend the existing tkinter `RecordingIndicator` to **never withdraw the window unless the user explicitly hides it**. Add an `idle` visual state (dim mic, no waveform, no timer) that's the default at app start and after each session ends. The pill becomes the persistent home base; recording is a state of the pill, not its reason for existing.

**Why this over a full PySide6 rewrite first**: Tk extensions can ship the persistent-pill behavior in 1-2 days. The visual port is a separate concern that benefits from validating the always-visible UX first against real daily use. If the persistent model turns out to feel cluttered, the lighter Tk iteration is cheaper to revert than a Qt port.

### Decision 2: Visual port to PySide6 (Phase 3, after behavior is validated)

Migrate **only** `recording_indicator.py` to PySide6 with [`qframelesswindow`](https://github.com/zhiyiYo/PyQt-Frameless-Window/tree/PySide6). Keep all other UI (correction_ui, vocab_ui, tray icon via pystray) on tkinter / pystray as-is.

**Why PySide6 over alternatives**:

| Option | Why rejected |
|---|---|
| **Stay on tkinter + DwmSetWindowAttribute hacks** | Win11 rounded corners + Mica via DWM API "work" but Tk's color-key transparency leaks magenta at anti-aliased edges, and Canvas primitives have no AA. Result: 60% of the way to "modern", with hacks that fight the framework. Sustainability cost: every tweak compounds against the color-key trick. |
| **customtkinter** | Same Tk under the hood. Rounded widgets are still drawn with the color-key trick. CustomTkinter Discussion #684 confirms the main window remains OS-controlled. Solves nothing the rendering layer cares about. |
| **pywebview + HTML/CSS** | Three open Win11-blocking bugs: #1611 (transparency shows theme color, not desktop), #1271 (mouse click-through when transparent=True), #834 (no rounded corners frameless). The exact features we need are broken. |
| **DearPyGui** | Per-window `always_on_top` (#1270) and viewport transparency (#1142, #2528) are open feature requests as of 2025. Unsuitable today. |
| **Flet (Flutter)** | Visually capable but reaching into the Win32 hwnd for `WS_EX_NOACTIVATE` is awkward — the Flutter window owns the hwnd and Flet doesn't expose it cleanly. Critical for our focus-safe overlay invariant. |
| **PySide6 + qframelesswindow** ✅ | True per-pixel alpha (`Qt.WA_TranslucentBackground`), native Mica via `setMicaEffect(True)`, GPU-accelerated 60 fps animations via `QPropertyAnimation`, `Qt.WA_ShowWithoutActivating` for focus safety, hwnd reachable for our existing `WS_EX_NOACTIVATE` ctypes hook. ~40 MB extra in PyInstaller bundle. ~1 day of port for the bar itself. Closes >90% of the visual gap. |

LGPL is fine for personal use; bundle size is the only meaningful cost.

### Decision 3: Coexist Tk + PySide6 in one process

Run `pystray` on its own thread (already does), `tkinter` for correction/vocab on its own thread (already does), `PySide6` on its own thread for the overlay. Three event loops, three threads, no shared widgets. The `RecordingIndicator` class becomes a `QObject`-based wrapper exposing the same public API (`show`/`set_state`/`update_level`/`show_text`/`hide`) so `app.py` is unchanged.

**Why this over migrating everything**: The overlay is the only always-visible surface and the only one the user judges aesthetically. Correction/vocab windows are modal, opened on demand — Tk's look is acceptable there. Wholesale migration is 2-3× the work for marginal value.

### Decision 4: Modes as the headline post-Phase-1 feature

Superwhisper's modes are the most-cited "killer feature" in every dictation app review. A mode bundles `{name, hotkey, polish_prompt, output_format, vocab_filter}`. We already have most of the parts (cloud polish prompt, vocab brain, output formatter); modes are the integration that turns them into a user-visible product feature. Cycle via a hotkey, current mode shown in the pill.

### Rejected alternatives

| Alternative | Why rejected |
|---|---|
| **Full first-run wizard** | Out of scope. The pill being always visible IS the discoverability fix — no wizard needed for the primary surface. |
| **Per-word confidence colors** | Requires faster-whisper segment-level access we don't currently route. Defer. |
| **Voice "select this word"** | Needs UIAutomation cursor inspection. Architecturally large and fragile across apps. Defer. |
| **Auto-launch on text-field focus (like Win+H launcher toggle)** | We already block recording when no text field is focused via `focus_guard.py`. Auto-popping the overlay on every text-field focus is noisy for our use case (already always-visible). |

---

## Harden Audit Findings

| # | Finding | Severity | Mitigation in Plan |
|---|---|---|---|
| 1 | **Click-mic-to-toggle conflicts with focus_guard**: clicking the overlay's mic moves foreground focus to the overlay window itself. `focus_guard.check_text_field()` then sees the overlay class and blocks recording. | High | The mic-button click handler must NOT call `check_text_field()`. Instead, capture the previously-focused HWND before the click via low-level mouse hook or by relying on `WS_EX_NOACTIVATE` to prevent focus stealing in the first place. Use the saved `_target_hwnd` from before the click. |
| 2 | **WS_EX_NOACTIVATE + click handlers**: a non-activating window that still receives `<Button-1>` is the goal. Tk supports this; PySide6 supports via `Qt.WA_ShowWithoutActivating` + the same ctypes hook. Verify on target Win11 build before committing. | High | Phase 1 ticket P1-1 includes a smoke-test step: click the mic icon while a Notepad window has focus, verify Notepad keeps the caret AND the mic click toggles recording. |
| 3 | **Mica unavailable on Win10 / pre-22H2 Win11**: `DwmSetWindowAttribute(DWMWA_SYSTEMBACKDROP_TYPE)` returns `E_INVALIDARG` on builds <22621. | Medium | qframelesswindow's `setMicaEffect()` already handles this and falls back. We add an explicit fallback path: detect build, render opaque rounded dark background without Mica. Both paths look acceptable. |
| 4 | **PySide6 + Tk + pystray three-eventloop coordination**: `pystray.Icon.run()` blocks; Tk has its own mainloop; PySide6 has `QApplication.exec()`. All three currently run on different threads. Adding a third (PySide6 on its own thread) risks COM apartment issues since `pystray` uses COM (Windows tray) and Qt also touches COM. | Medium | Run PySide6 on its own thread with `QApplication` instantiated inside that thread. COM is already STA-per-thread, so no shared state. Verify by running for 30 minutes during smoke test, watching for crashes. Alternative if it fails: launch the overlay in a subprocess and IPC via stdin/stdout JSON. |
| 5 | **Always-visible overlay = constant Tk timer ticks** even at idle. Today the timer only runs while recording. | Low | Idle state has no timer, no level updates, no animation — just a static QPixmap of the dim mic. Idle CPU should round to 0%. Verify with Process Explorer. |
| 6 | **Voice commands collide with literal user speech**: user dictates "delete that text" → command interpreter eats the prefix and types only "text"? | Medium | Commands only fire when they are the **entire** transcript of a segment (after stripping punctuation). "delete that text" has trailing words → treated as literal text. Existing `apply_formatting_commands` in `output.py` follows this pattern; extend it. |
| 7 | **Cancel-on-Esc clashes with Esc in target app** (e.g., closing dialogs). | Medium | Only suppress Esc while we are in `listening` or `transcribing` state. In `idle`, Esc passes through to the target app. Use `keyboard.add_hotkey('esc', ..., suppress=True)` with dynamic register/unregister around recording. |
| 8 | **Hover-expand of last 3 transcriptions: privacy** — anything you dictated is one mouse hover away. | Low | Only show in expanded state if the pill is hovered for >300 ms (intentional dwell). Truncate each entry to 60 chars. Provide a tray menu toggle to disable hover-expand. |
| 9 | **Modes system + per-mode polish prompt: prompt injection from vocab terms**. A vocabulary entry could contain prompt-like text that bleeds into the polish prompt template. | Low | Vocab terms are already sanitized in `prompt_builder.py`. Mode prompts use the same sanitization path. No new vector. |
| 10 | **Restoring overlay after "close X" minimizes to tray**: user clicks X, then can't find the overlay. | Medium | Tray menu gains an explicit "Show overlay" item and the Ctrl+Shift+H hotkey toggles visibility. Toast notification on first close: "Overlay hidden — click tray icon or press Ctrl+Shift+H to show again." |
| 11 | **PyInstaller bundle bloat**: PySide6 adds ~40 MB to a packaged bundle. Currently the app runs from venv, not packaged. | Low | We are not packaging today. When we do, use `--exclude-module` for unused PySide6 components (QtWebEngine, QtMultimedia, QtNetwork). Likely ~25 MB net cost. |

---

## Phase Plan

Three phases, each its own `/run` context. Phase 1 ships Win+H behavior parity on the existing Tk overlay (fast). Phase 2 ships modes + voice commands. Phase 3 is the visual port to PySide6.

**Risk tier overall**: R2 (cross-cutting code, multiple files, behavior change to a daily-driver surface). Phase 3 jumps to R2-borderline-R3 because of the framework swap; mitigated by scoping it to one file and keeping the public API stable.

| Phase | Goal | Files touched | Tickets | Effort |
|---|---|---|---|---|
| **P1** — Win+H behavior parity (Tk) | Always-visible pill, click-mic toggle, gear, close-to-tray, cancel-on-Esc, state-keyed tray, hide hotkey | `recording_indicator.py`, `app.py`, `config.py`, `config.yaml` | 6 | M |
| **P2** — Modes + voice commands | Modes config, mode pill in overlay, cycle hotkey, core voice commands during dictation | `modes.py` (new), `output.py`, `cascade_dictator.py`, `app.py`, `recording_indicator.py`, `config.yaml` | 5 | M |
| **P3** — PySide6 visual port | Replace `recording_indicator.py` with PySide6 implementation behind same public API; Mica + rounded + shadow + 60fps waveform + hover-expand | `recording_indicator.py` (rewrite), `requirements.txt`, optional `recording_indicator_tk.py` (kept for fallback) | 4 | L |

---

## Phase P1 — Win+H Behavior Parity (Tk)

### P1-1: Always-visible state machine

**File**: `recording_indicator.py`
**Action**: Add `idle` state. Remove `withdraw()` from `_do_hide` — instead transition to `idle` and keep the window visible. Show on `start()` instead of waiting for `show()`.
**Risk tier**: R2

**Design**:
- New state `"idle"`: dim grey mic (`#666666`), no level bar, no timer, no waveform.
- `_STATE_COLORS` gains `"idle": "#666666"`.
- `start()` calls `_do_show()` so the pill appears at app startup.
- `show()` is renamed `begin_session()` — sets state to `listening`, starts timer, starts level meter.
- `hide()` is renamed `end_session()` — stops timer, stops level meter, transitions to `idle`. Window stays visible.
- New method `dismiss()` — actually withdraws the window (called from close-X click and Ctrl+Shift+H toggle).
- New method `restore()` — deiconifies after a `dismiss()`.
- `app.py` callsites updated: `_do_show`/`_do_hide` calls in `_toggle_recording` become `begin_session`/`end_session`.
- `_recording_indicator.start()` already runs at app init (line 169). Now the pill is visible from then on.

**Verification**: `python -m py_compile recording_indicator.py app.py` then manual run — pill should appear at app launch and never disappear unless tray "Hide overlay" is clicked.

### P1-2: Click-mic-to-toggle with focus-safe target capture

**File**: `recording_indicator.py`, `app.py`
**Action**: Make the central mic icon click-region trigger recording toggle. Since the overlay has `WS_EX_NOACTIVATE`, the previously-focused window keeps focus when we click — `focus_guard.check_text_field()` will then correctly see the target text field, not our overlay.
**Risk tier**: R2

**Design**:
- Define mic click zone: `40 ≤ event.x ≤ 120` (center of pill, excluding drag handles on left and menu/timer on right).
- Bind in `_on_press`: if click is in mic zone AND not in menu zone AND not the drag-handle zone → call `self._on_mic_click` (new callback passed in `__init__`).
- `app.py` passes `on_mic_click=self._toggle_recording` to `RecordingIndicator`.
- Verify WS_EX_NOACTIVATE behavior: smoke test by clicking mic with Notepad focused. Notepad caret must remain. `focus_guard.check_text_field()` must see Notepad's `Edit` class.
- If WS_EX_NOACTIVATE turns out to lose focus on this Tk version: fall back to capturing `GetForegroundWindow()` 50 ms before each mouse-down via a `pyHook`-style low-level hook. (Document but don't implement unless smoke test fails.)

**Verification**: Manual smoke test: 1) Open Notepad. 2) Click overlay mic. 3) Speak. 4) Verify text appears in Notepad and Notepad never lost caret.

### P1-3: Gear icon (left) + close X (right) + tray restore

**File**: `recording_indicator.py`, `app.py`
**Action**: Replace the 3 grey vertical drag-handle lines with a gear glyph (left). Replace the menu dots with a small × (right). Drag region becomes the empty space between gear and timer.
**Risk tier**: R1

**Design**:
- Gear icon: Unicode `⚙` in `("Segoe UI Symbol", 12)` at `x=18`. Click opens a popup menu with: Hide overlay, Manage vocabulary, Export vocab, Import vocab, Start with Windows, Quit. (Same menu as tray, surfaced from the overlay.)
- Close glyph: Unicode `✕` in `("Segoe UI", 11)` at `x=_WIN_W - 16`. Click → `dismiss()` + show one-time toast.
- Drag region: any click between gear (x≤30) and timer (x≥130) that isn't on the mic icon. Update `_on_press` zone logic.
- `app.py`: tray menu gains "Show overlay" item that calls `_recording_indicator.restore()`. Set `Ctrl+Shift+H` hotkey to toggle `restore()` / `dismiss()`.

**Verification**: `py_compile`. Smoke test all click zones.

### P1-4: Cancel-on-Esc

**File**: `app.py`, `recorder.py`
**Action**: While recording, Esc cancels the current segment without paste.
**Risk tier**: R2

**Design**:
- New method `Recorder.cancel()` — stop the stream, discard buffer, return None.
- In `_toggle_recording`, when starting recording, dynamically register `keyboard.add_hotkey('esc', self._cancel_recording, suppress=False)`. Use `suppress=False` so Esc still passes to target apps that need it (we just observe).
- On stop or cancel, `keyboard.remove_hotkey('esc', ...)`.
- `_cancel_recording` flips `self._recording = False`, calls `recorder.cancel()` or `streaming_recorder.cancel()`, plays error tone, sets state to idle, no paste. Logs "cancelled".

**Verification**: `py_compile`. Smoke test: start recording, press Esc within 2 s, verify nothing is pasted and overlay returns to idle.

### P1-5: State-keyed tray icon

**File**: `app.py`
**Action**: Tray icon glyph reflects current state (idle / listening / transcribing / blocked).
**Risk tier**: R1

**Design**:
- Pre-build 4 PIL Images at import: `_ICON_IDLE` (blue, current default), `_ICON_LISTENING` (red, current "recording"), `_ICON_TRANSCRIBING` (orange), `_ICON_BLOCKED` (grey with × overlay).
- New method `_set_tray_state(state)` — updates `self._icon.icon` and tooltip. Called from the same code paths that call `_recording_indicator.set_state()`.

**Verification**: `py_compile`. Smoke test: watch tray during dictation cycle, see 4 distinct icons.

### P1-6: Config + integration smoke test

**Files**: `config.yaml`, `config.py`, integration check
**Action**: Add `ui.overlay_visible_on_start: true`, `ui.cancel_hotkey: esc`, `ui.toggle_overlay_hotkey: ctrl+shift+h`. Wire all P1 changes into `app.py`.
**Risk tier**: R2

**Verification**: Full smoke test plan:
1. Launch app → pill appears in idle state at saved position.
2. Click mic → recording starts, pill turns red, level bar moves, timer counts.
3. Speak short phrase → text pastes, pill returns to idle.
4. Press Ctrl+Shift+Space → starts recording (hotkey path still works).
5. Press Esc mid-recording → discards, no paste.
6. Click gear → menu shows.
7. Click × → pill hides; toast shows "Press Ctrl+Shift+H to restore".
8. Press Ctrl+Shift+H → pill returns.
9. Right-click tray → "Show overlay" present and works.
10. Tray icon changes through 4 states during one dictation cycle.

---

## Phase P2 — Modes + Voice Commands

### P2-1: Modes module

**File**: New file `modes.py`
**Action**: Mode definitions, current-mode state, cycle.
**Risk tier**: R1

**Design**:
```python
@dataclass
class Mode:
    name: str
    polish_prompt_addendum: str
    vocab_priority_filter: str | None  # None = all; or "high" / "medium"
    output_format: str  # "default" | "raw" | "code"

DEFAULT_MODES = [
    Mode("Default", "", None, "default"),
    Mode("Email", "Format as a polite professional email body. Preserve user's tone.", None, "default"),
    Mode("Code", "", None, "raw"),  # No polish, no formatting commands
]
```

Loaded from `config.yaml` `modes:` section (defaults if missing). Current mode persisted to `mode_state.json`. Cycle: `current = (current + 1) % len(modes)`.

### P2-2: Mode pill in overlay

**File**: `recording_indicator.py`
**Action**: Tiny mode-name pill on right side of bar (between timer and × close).
**Risk tier**: R1

**Design**: Small text item showing current mode name (e.g., "Default", "Email", "Code") in a 1-px-bordered chip. Click → cycle to next mode. Background color shifts subtly per mode.

### P2-3: Cycle hotkey

**File**: `app.py`, `config.yaml`
**Action**: `Ctrl+Shift+M` cycles modes. Toast shows new mode name.
**Risk tier**: R1

### P2-4: Mode-aware dictation

**File**: `cascade_dictator.py`, `app.py`
**Action**: `dictate()` accepts a `mode` parameter that affects polish prompt and output format. `app.py` passes `modes.current()` on each call.
**Risk tier**: R2

**Design**:
- `cascade_dictator.dictate(audio, ..., mode: Mode | None = None)`.
- In cloud polish path, append `mode.polish_prompt_addendum` to the polish prompt.
- If `mode.output_format == "raw"`, skip both polish AND `apply_formatting_commands`.
- If `mode.vocab_priority_filter`, narrow the vocab passed for prompt conditioning.

### P2-5: Core voice commands

**File**: `output.py`, `app.py`
**Action**: Recognize 5 voice commands when they are the **entire** segment transcript: "stop listening", "stop dictating", "delete that", "scratch that", "new line", "new paragraph".
**Risk tier**: R2

**Design**:
- New function `output.detect_command(text: str) -> str | None`. Strip punctuation, lowercase, exact-match against command list. Return command id or None.
- In `app.py._on_speech_segment`, before output: if `detect_command(result)`, dispatch instead of pasting.
  - `stop_listening` / `stop_dictating` → `_toggle_recording()` to stop.
  - `delete_that` / `scratch_that` → backspace the previous segment's character count via `keyboard.send('backspace')` × N. Track segment lengths in a small ring buffer.
  - `new_line` → `keyboard.send('enter')`.
  - `new_paragraph` → `keyboard.send('enter, enter')`.
- The existing `apply_formatting_commands` in `output.py` already handles in-stream commands like "comma" / "period". This new layer handles full-segment control commands and is checked first.

**Verification**: `py_compile`. Smoke test: dictate "this is a test new line second line". Expect "this is a test\nsecond line".

---

## Phase P3 — PySide6 Visual Port

### P3-1: Add PySide6 + qframelesswindow to requirements

**File**: `requirements.txt`
**Action**: Add `PySide6==6.8.*` and `PySide6-Frameless-Window>=0.4`.
**Risk tier**: R1

**Verification**: `pip install -r requirements.txt` cleanly. `python -c "from PySide6.QtWidgets import QApplication; from qframelesswindow import FramelessWindow; print('ok')"`.

### P3-2: PySide6 RecordingIndicator (parallel implementation)

**File**: New file `recording_indicator_qt.py`. Existing `recording_indicator.py` renamed `recording_indicator_tk.py` and kept as fallback.
**Action**: Reimplement `RecordingIndicator` class with PySide6 + qframelesswindow. Same public API: `start()`, `begin_session()`, `end_session()`, `set_state(state)`, `update_level(rms)`, `show_text(text, language, confidence)`, `show_feedback(type)`, `dismiss()`, `restore()`, `destroy()`, `__init__(on_stop, on_mic_click)`.
**Risk tier**: R2-R3 (framework swap on the daily-driver surface)

**Design**:
- `class RecordingIndicator(QObject)` — owns a `FramelessWindow` subclass.
- Init sequence on its own thread:
  1. `QApplication([])` (per-thread).
  2. `FramelessWindow` with `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool`.
  3. `setAttribute(Qt.WA_TranslucentBackground)`, `setAttribute(Qt.WA_ShowWithoutActivating)`.
  4. `setMicaEffect(True)` (qframelesswindow API). Falls back gracefully on Win10.
  5. Apply `WS_EX_NOACTIVATE` via existing ctypes hook on `winId()`.
  6. Layout: HBox — `QLabel(gear)` | drag-area `QFrame` | `MicButton` (custom QPushButton with custom paint) | `WaveformWidget` | `QLabel(timer)` | `ModeChip` | `QLabel(close)`.
  7. `MicButton.paintEvent`: draw circle in current state color, optional pulsing halo via `QPropertyAnimation` on `pen.width`.
  8. `WaveformWidget.paintEvent`: draw 32 bars from a rolling RMS buffer; refresh at 30 Hz via `QTimer`.
- Public API methods marshal to the GUI thread via `QMetaObject.invokeMethod(..., Qt.QueuedConnection)`.
- Position persistence: same `indicator_pos.json` format. Read in init, write on `moveEvent`.
- Hover-expand: `enterEvent` + 300 ms `QTimer` → expand to 360x120 px, render last 3 transcriptions in a vertical `QListWidget` below the bar. `leaveEvent` collapses after 200 ms grace.
- Drop shadow: `QGraphicsDropShadowEffect` (`blurRadius=24, offset=(0,4), color=QColor(0,0,0,160)`).

**Toggle**: `config.yaml` gains `ui.overlay_backend: qt | tk` (default `qt`, fallback `tk`). `app.py` imports the selected module.

**Verification**: `py_compile recording_indicator_qt.py`. Manual smoke: launch with `ui.overlay_backend: qt`, run full P1 smoke plan again. Watch for COM/threading errors over 30 minutes.

### P3-3: Mica + rounded fallback for pre-22H2

**File**: `recording_indicator_qt.py`
**Action**: Detect Win build via `sys.getwindowsversion().build`. If <22621, skip `setMicaEffect` and use a solid `#1e1e1e` background with manual rounded mask via `QPainterPath`.
**Risk tier**: R1

**Verification**: Test on a Win10 VM if available, otherwise force `setMicaEffect = lambda *a: None` and verify fallback look.

### P3-4: Hover-expand transcription history

**File**: `recording_indicator_qt.py`, `app.py`
**Action**: On 300 ms hover dwell, expand pill downward to show last 3 transcriptions. Click an entry → re-paste. Right-click → discard from history. Privacy toggle in gear menu.
**Risk tier**: R1

**Design**:
- `app.py` already keeps `self._last_transcription`. Extend to a deque of last 10.
- New method `RecordingIndicator.set_history(items: list[str])` called whenever a new transcription completes.
- Expand animation: `QPropertyAnimation` on `geometry`, 200 ms ease-out.

**Verification**: Manual hover test, click-to-repaste smoke.

---

## Failure Modes and Mitigations

| # | Failure | Trigger | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Mic click steals focus | `WS_EX_NOACTIVATE` not honored on Tk overlay | Recording blocked because focus_guard sees the overlay, not target | P1-2 smoke test catches this. Fallback: low-level mouse hook to capture target hwnd before click event reaches Tk. |
| 2 | Esc cancel suppresses Esc in target app | Keyboard library suppress flag | Target app dialogs can't be closed during recording | Use `suppress=False` — we observe but don't block. Esc reaches both us and the app. Document that Esc may still trigger the app's own Esc handler. |
| 3 | Voice command false-fires on dictated text | Single-word match too eager | "delete that file from the folder" triggers `delete_that` and erases prior text | Match only when command is the **complete** transcript after stripping punctuation. "delete that file" → not a command. |
| 4 | PySide6 + Tk + pystray COM conflict | Three event loops on three threads | App crashes or tray stops responding | Each event loop in its own thread (already pattern). PySide6 uses STA per thread. If unstable, last-resort fallback: launch overlay as subprocess, IPC via JSON over stdin/stdout. |
| 5 | Mica unavailable on user's Windows | Win10 or pre-22H2 Win11 | Backdrop renders incorrectly | qframelesswindow handles silently. We add explicit fallback path for confidence. |
| 6 | Always-visible overlay distracts during non-dictation work | UX preference variation | User dismisses overlay frequently, defeats the purpose | Ctrl+Shift+H toggle is fast. If user persistently hides it, add a `ui.overlay_visible_on_start: false` opt-out. |
| 7 | Mode cycling hits a hotkey conflict | Ctrl+Shift+M used by another app | Cycle silently fails | Log a warning at startup if `keyboard.add_hotkey` raises. Make hotkey configurable. |
| 8 | Hover-expand shows sensitive transcriptions to bystander | Pill is on screen during a screen-share | Privacy leak | Default OFF for hover-expand on first install; gear menu opt-in. Add "Clear history" button. |
| 9 | PySide6 install bloats venv / breaks existing import path | `pip install` order issues | Existing `python app.py` fails | Pin `PySide6==6.8.*`. Smoke test in a clean venv before merging. Document in README. |
| 10 | "Stop listening" voice command fires before user finishes | Eager command matching during streaming | Recording stops mid-sentence | Only check commands at segment boundaries (already the case in `_on_speech_segment`). And require the command to be the entire segment text — incidental "stop listening" inside a sentence won't match. |

---

## Risk Tier and Verification Matrix

| Phase | Ticket | Risk | Verification |
|---|---|---|---|
| P1 | P1-1 always-visible state | R2 | py_compile + manual: pill visible at startup, never hidden by recording cycle |
| P1 | P1-2 click-mic-toggle | R2 | py_compile + Notepad smoke: caret stays in Notepad after mic click |
| P1 | P1-3 gear + close + restore | R1 | py_compile + click all 3 zones |
| P1 | P1-4 cancel-on-Esc | R2 | py_compile + Esc-during-recording yields no paste |
| P1 | P1-5 state-keyed tray | R1 | py_compile + visual: tray cycles 4 icons during one dictation |
| P1 | P1-6 config + smoke | R2 | py_compile + full P1 smoke plan |
| P2 | P2-1 modes module | R1 | py_compile + unit-style import test |
| P2 | P2-2 mode pill UI | R1 | py_compile + click-to-cycle visual test |
| P2 | P2-3 cycle hotkey | R1 | manual: Ctrl+Shift+M cycles, toast shows |
| P2 | P2-4 mode-aware dictation | R2 | py_compile + dictate same phrase in Default vs Code mode, verify Code skips polish |
| P2 | P2-5 voice commands | R2 | dictate "test new line line two", expect newline in output |
| P3 | P3-1 deps | R1 | clean venv install + import smoke |
| P3 | P3-2 PySide6 port | R3 | py_compile + 30-min smoke test + side-by-side visual comparison vs Tk fallback |
| P3 | P3-3 fallback for pre-22H2 | R1 | force fallback path, verify rounded opaque dark renders |
| P3 | P3-4 hover-expand | R1 | manual hover + click-to-repaste smoke |

---

## Resume Pack

**Goal**: Reach Win+H feature parity on visibility model + click-mic + close behavior + voice commands, then exceed Win+H on visual polish via a PySide6 port with Mica/rounded/shadow/animated waveform. Three phases: P1 behavior parity on Tk (**done, awaiting smoke**), P2 modes + voice commands (1 session), P3 PySide6 visual port (2-3 sessions).

**Current state**: P1 implemented in code. `recording_indicator.py` exposes the always-visible API (`begin_session`/`end_session`/`dismiss`/`restore`/`toggle_visibility`/`is_dismissed`). `Recorder.cancel()` and `StreamingRecorder.cancel()` added (worker join is outside the lock). Tray has 4-state icons (`idle`/`listening`/`transcribing`/`blocked`) with a dynamic "Show/Hide overlay" entry. Config keys `ui.overlay_visible_on_start` and `ui.toggle_overlay_hotkey` live. Simplify pass cleaned up 4 `_noarg` wrappers, hoisted `_TRAY_STATE_TITLES`, added `_set_state`/`_return_to_idle` helpers, and swapped the audio-hot-path lambda for positional `after()` args.

**Pending for P1 (user-side)**: run the 10-step smoke plan in §P1-6. Key watchpoints:
- `WS_EX_NOACTIVATE`: click overlay mic while Notepad has focus — Notepad caret must stay, dictation must land in Notepad.
- Esc passthrough: while idle, Esc must still reach target apps (we register `suppress=False`).
- First-close toast: `notify_info` should fire exactly once per session when the user clicks the overlay's X.

**What's ready for P2 (decided, not coded)**:
- Voice commands: full-transcript match for 5 control commands in `output.py` + dispatch in `app._on_speech_segment`.
- Modes: dataclass + JSON state file + cycle hotkey (Ctrl+Shift+M) + per-mode polish addendum.

**What's ready for P3 (decided, not coded)**:
- PySide6 port: parallel `recording_indicator_qt.py` preserving the public API shipped in P1, `ui.overlay_backend` config flag.

**Next start command**: `/run docs/feature-lists/FEATURE_LIST_OVERLAY_OVERHAUL.md` (to execute P2).

**Remaining execution order**: P2-1 → P2-2 → P2-3 → P2-4 → P2-5 (one /run context). Then a new /run for P3.

**First files to touch in P2**: create `modes.py`; then extend `output.py` for full-segment command detection; then wire `app.py` and `recording_indicator.py` (mode chip).

---

## Open Questions

**Q1: Do you actually want voice commands ("stop listening", "delete that") in P2, or are they a distraction from the always-visible-pill goal?** — Default: include them. They're cheap (extend existing `apply_formatting_commands`) and Win+H has them. If you don't use them after a week, remove. Reason: feature parity with Win+H is the stated goal, and voice control is the most-cited missing piece in OSS dictation apps.

**Q2: PySide6 in P3 — accept the ~40 MB future PyInstaller bundle cost?** — Default: yes. Bundle is irrelevant today (you run from venv). When packaging matters, PyInstaller exclusions trim to ~25 MB net. Reason: every other modern Windows overlay (Win+H, PowerToys, Raycast, ChatGPT) uses GPU-accelerated rendering. Tk's color-key trick caps us at "good enough" forever.

**Q3: Modes — start with 3 built-in (Default, Email, Code) or wait for you to specify your own?** — Default: ship 3 built-ins, document how to add more in `config.yaml`. Reason: examples teach the schema. If Default+Email+Code don't fit your workflow, you can replace them in config.

**Q4: Hover-expand history — opt-in or opt-out?** — Default: opt-in. Disabled on first install, enable from gear menu. Reason: privacy concern (hover reveals last 3 transcriptions to anyone shoulder-surfing or screen-sharing). Lower friction to enable than to recover from accidental disclosure.

**Q5: Tk fallback for the overlay (P3) — keep `recording_indicator_tk.py` indefinitely, or remove after PySide6 stabilizes?** — Default: keep for one minor version (e.g., until v0.5), then remove. Reason: insurance against PySide6 issues we discover only in long-running daily use. Removal is a 1-line config + file delete.

**Q6: Mode cycle hotkey — Ctrl+Shift+M? Or per-mode direct hotkeys (Ctrl+Alt+1/2/3)?** — Default: cycle (Ctrl+Shift+M). Reason: scales with adding modes. Per-mode hotkeys add cognitive load and run out of free chord space fast. Can add per-mode hotkeys later as opt-in config entries per mode.
