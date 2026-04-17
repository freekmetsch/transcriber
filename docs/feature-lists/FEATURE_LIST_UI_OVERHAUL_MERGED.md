# Feature List: UI + Overlay — Merged Remaining Work

Date: 2026-04-17
Status: In progress — Q1-1 (re-done after package-name fix), Q1-2, Q1-3, Q2-1 / Q2-2 / Q2-3 shipped 2026-04-17
Open phases: Q1-4 (hover-expand), Q2-4 (hover-expand wiring, gated on Q1-4), Q2-5 (tray Session history, gated on Q2-4), Q3, Q4
Scope: All not-yet-shipped features from `FEATURE_LIST_UI_OVERHAUL.md` (2026-04-15)
  and `FEATURE_LIST_OVERLAY_OVERHAUL.md` (2026-04-17)
Owner: Freek
Sources merged: `FEATURE_LIST_UI_OVERHAUL.md`, `FEATURE_LIST_OVERLAY_OVERHAUL.md`

---

## Problem Framing

Two prior feature lists overlap substantially:

- `FEATURE_LIST_UI_OVERHAUL.md` catalogued 30 UX gaps (F1–F30) across audio
  feedback, overlay polish, history, settings, onboarding, appearance,
  tray integration, and radical ideas.
- `FEATURE_LIST_OVERLAY_OVERHAUL.md` focused on Win+H parity and a visual
  port, in three phases (P1 behavior parity → P2 modes + voice commands
  → P3 PySide6 visual port).

Both authored a mixture of already-shipped and still-pending work. This
document verifies each feature against the current code tree and defines
a single execution plan for what genuinely remains.

---

## Implementation Status — verified in code on 2026-04-17

### Shipped (in-tree, smoke pending where noted)

| Source | Feature | Evidence |
|---|---|---|
| UI F1, F2 | Start/stop/error sounds | `sounds.py` — `_SOUND_START`, `_SOUND_STOP`, `_SOUND_ERROR`, `play_*` |
| UI F3 | Mic input level meter in overlay | `recording_indicator.py` `update_level`, `_do_update_level`; fed from `app.py:_on_audio_level` |
| UI F4 | Draggable overlay + position persistence | `recording_indicator.py` `_on_drag`, `_save_position` |
| UI F5 | Session timer in overlay | `_start_timer`, `_update_timer` |
| UI F7 | Click-to-stop on overlay (mic zone) | `_on_press` mic-zone branch → `on_mic_click` |
| UI F17 | Tray tooltip with hotkey hint | `_tray_tooltip()` |
| UI F18 | Language indicator in overlay | `_do_show_text` language badge |
| UI F19 | Low-confidence warning (color tiers) | badge color tiers in `_do_show_text` (0.8 / 0.5 thresholds) |
| UI F24 | Auto-start on login | `autostart.py` (Registry Run key) |
| UI F28 | Clipboard-free text insertion | `output.py` `type_text` via SendInput is the default for streaming and short text |
| UI F29 (partial) | Voice commands during dictation | `commands.py` `CONTROL_COMMANDS` — "stop listening", "stop dictating", "delete that", "scratch that" |
| Overlay P1 | Always-visible pill, gear ⚙, close ✕, Ctrl+Shift+H toggle, cancel-on-Esc, 4-state tray | `recording_indicator.py`, `app.py:_cancel_recording`, `_set_tray_state`, `_build_overlay_menu_items` |
| Overlay P2 | Modes system, mode chip, Ctrl+Shift+M cycle | `modes.py`, `app.py:_cycle_mode`, `refresh_mode`, mode chip in `recording_indicator.py` |

### Not shipped — candidate scope for this merged plan

| Source | Feature | Note |
|---|---|---|
| Overlay P3 | PySide6 visual port (Mica, rounded, shadow, 60 fps waveform, hover-expand) | Full design lives in source plan §Phase P3 |
| UI F6 | Segment counter in overlay | Trivial — easiest to add during Q1 layout |
| UI F9 | Session history panel | Ephemeral deque (per D2 decision) |
| UI F10 | "Copy last" tray menu item | Trivial |
| UI F11 | "Re-paste last" hotkey | Needs focus_guard integration |
| UI F12 | Full settings window | **Rejected** — see Chosen Approach |
| UI F13 | VAD threshold tuner with live preview | Build inside gear popover, not a full window |
| UI F14 | Quick settings in overlay | Gear popover already covers actions — extend with toggles |
| UI F15 | First-run wizard | **Rejected** — always-visible pill IS the discoverability fix |
| UI F16 | Hotkey cheat sheet overlay | Cheap polish |
| UI F20 | Light theme | Cheap once Qt shell exists |
| UI F21 | Configurable overlay size | Cheap once Qt shell exists |
| UI F22 | Font size scaling | Cheap once Qt shell exists |
| UI F23 | Richer tray menu | Partially done (mode, overlay toggle, autostart, shortcut, vocab); still missing Copy last + Session history |
| UI F25 | Minimize-to-tray on close | N/A until a main window exists; revisit only if F12 ever ships |
| UI F26 | App-aware dictation profiles | Radical; defer — separate feature list after parity |
| UI F27 | Floating dictation box | Radical; defer — no concrete failing app reported |
| UI F29 (ext.) | "select all" / "undo that" voice commands | Defer — cost > value today |
| UI F30 | Inline correction by voice | Fragile across apps; defer |

---

## Scope

### In scope
- Overlay P3 visual port (Q1)
- Transcription history surface: F9 + F10 + F11 + tray completion from F23 (Q2)
- Appearance + F6 segment counter after the Qt shell lands (Q3)
- Discoverability + live VAD tuner + quick-settings toggles (Q4)

### Out of scope (deferred / rejected)
- F12 full tabbed settings window — gear popover + F13 + F14 cover the pain
- F15 first-run wizard — redundant once the pill is always-visible
- F25 minimize-to-tray-on-close — gated on a main window existing
- F26, F27, F29-extensions, F30 — radical; separate later plans
- Migrating `correction_ui.py` / `vocab_ui.py` to Qt — they're modal, Tk stays

---

## Chosen Approach — and Why

### Order: Visual port first, then features that sit on it

Q1 replaces the rendering layer. Doing it before Q3 avoids building F6,
F20, F21, F22 twice (once in Tk color-key hack, once in Qt). Same public
API means `app.py` is untouched. Sustainability tiebreaker: least
technical debt.

### Q1 scope discipline

- **Only** `recording_indicator.py` becomes PySide6. `correction_ui.py`,
  `vocab_ui.py`, tray (`pystray`) stay as-is.
- Keep `recording_indicator_tk.py` as fallback behind
  `ui.overlay_backend: qt | tk` for one minor version; remove once
  stable.
- Absorbs tickets P3-1…P3-4 from `FEATURE_LIST_OVERLAY_OVERHAUL.md`
  §Phase P3 verbatim. No redesign — that plan's decisions (PySide6 +
  qframelesswindow, Mica fallback, per-thread QApplication, hover-expand
  privacy default OFF) stand as written.

### Q2: history lives in app.py as an in-memory deque

- `deque(maxlen=ui.history_length)` (default 10) of `HistoryEntry(text,
  lang, timestamp)`.
- No persistence (matches D2 ephemeral decision). Privacy > cross-session
  convenience.
- Re-paste hotkey **default `ctrl+alt+v`**, not `ctrl+shift+v` — the
  latter is "paste plain text" in browsers/Office. Fully configurable via
  `ui.repaste_hotkey`.
- Re-paste routes through the existing `focus_guard.check_text_field()`
  gate; refuses on empty history (error tone).
- Hover-expand (Q1-4) reads the same deque.

### Q3: appearance is QSS/palette, not Tk hacks

- `ui.theme: dark | light | system`. `system` reads Windows registry
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize\AppsUseLightTheme`.
- `ui.overlay_size: compact | normal | wide` — drives pill width + font
  sizes.
- `ui.font_scale: float` — multiplier on pill text.
- Tray icon set rebuilt per theme so the PIL image doesn't clash on light
  Windows taskbars.
- F6 segment counter is a numeric chip next to the timer; resets on
  `end_session`.

### Q4: discoverability and live tuning inside the gear popover

- F16 cheat-sheet: small QWidget opened by `Ctrl+Shift+?`, auto-dismiss
  on keypress or 5 s.
- F13 VAD tuner: `QDialog` launched from gear menu. Live RMS plot with
  threshold slider writes to `config.local.yaml` (both Silero and energy
  thresholds, separately). **Gated**: refuses to open while
  `self._recording` is true; reuses `Recorder`'s `on_level` callback
  rather than opening a second PortAudio stream.
- F14 quick-settings toggles (sounds on/off, level meter on/off, language
  badge on/off) added to the existing gear popup structure.

### Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Do history first, port later | Two history implementations (Tk + Qt). Visible debt. |
| Light theme on Tk first | Color-key transparency + ovals fight theming. Dead-end. |
| Full tabbed settings window (F12) | Gear popover already reaches every live-editable value. F13 live-preview is the genuine missing piece; bake into the popover instead of spinning up a new window. |
| Ship more Tk polish, skip P3 | Every further polish ticket compounds the color-key debt. |
| Ctrl+Shift+V for re-paste | Collides with "paste plain text" in browsers/Office. |

---

## Harden Audit — new findings for the merge

| # | Finding | Severity | Mitigation |
|---|---|---|---|
| H1 | PySide6 + Tk + pystray three-event-loop COM risk | High | Inherited from source plan Finding 4. Per-thread `QApplication`. 30-min soak in Q1 smoke. Subprocess IPC fallback is documented if unstable. |
| H2 | Deque of recent transcriptions could leak via swap / crash dump | Low | In-memory only, `maxlen=10`. No persistence. Privacy toggle on hover-expand (default OFF). |
| H3 | Re-paste fires while a different window is focused | Medium | Route through `focus_guard.check_text_field()` before paste; on block, play error and show toast. |
| H4 | Tray icons pre-built for dark taskbars clash on light Windows | Low | Rebuild `_ICON_STATES` dict when `ui.theme` changes. |
| H5 | F13 VAD tuner opens a mic stream while recording active | Medium | Gate on `self._recording`; reuse existing `Recorder.on_level` callback, do not open a second PortAudio stream. |
| H6 | `delete that` empties history → re-paste errors | Low | Re-paste plays error sound on empty deque. Document: `delete that` only removes the most recent entry. |
| H7 | PyInstaller bundle bloat from PySide6 | Low | Not packaging today. When packaged: `--exclude-module` QtWebEngine/QtMultimedia/QtNetwork → ~25 MB net. |
| H8 | Theme switch at runtime needs to reach tray + overlay + correction UI | Low | Only overlay and tray recolor live. Correction UI keeps its dark theme (out of scope for this merge). |
| H9 | Light theme overlay over bright content reduces mic-state contrast | Low | Light palette uses darker mic glyph (`#1a1a1a`) and a soft shadow for separation. |

Source plan's 10 pre-existing failure modes (FEATURE_LIST_OVERLAY_OVERHAUL.md §Failure Modes and Mitigations) still apply to Q1 verbatim.

---

## Phase Plan

Four phases, each its own `/run` context. Q1 is the largest and blocks
the rest.

| Phase | Goal | Files | Tickets | Effort | Tier |
|---|---|---|---|---|---|
| Q1 | PySide6 visual port (overlay P3) | `requirements.txt`, `recording_indicator_qt.py` (new), `recording_indicator_tk.py` (rename of current), `app.py` (import switch), `config.yaml` | 4 | L | R3 |
| Q2 | History deque + Copy last + Re-paste + tray completion | `app.py`, `recording_indicator_qt.py`, `config.yaml` | 5 | M | R2 |
| Q3 | Light theme + size/font scaling + F6 segment counter | `recording_indicator_qt.py`, `app.py`, `config.yaml` | 4 | M | R1 |
| Q4 | Cheat sheet + live VAD tuner + quick-settings toggles | `recording_indicator_qt.py`, `app.py`, `config.yaml` | 3 | M | R2 |

---

### Phase Q1 — PySide6 Visual Port

Absorbs tickets P3-1, P3-2, P3-3, P3-4 from
`FEATURE_LIST_OVERLAY_OVERHAUL.md` §Phase P3 **verbatim**. Do not
redesign. That plan's decisions stand.

- **Q1-1** = P3-1: add `PySide6==6.8.*` and `PySide6-Frameless-Window>=0.4`
  to `requirements.txt`; clean-venv install smoke.
- **Q1-2** = P3-2: implement `recording_indicator_qt.py` with the public
  API currently in `recording_indicator.py`: `start`, `begin_session`,
  `end_session`, `dismiss`, `restore`, `toggle_visibility`,
  `is_dismissed`, `refresh_mode`, `set_state`, `show_text`,
  `update_level`, `show_feedback`, `destroy`. Rename current file to
  `recording_indicator_tk.py`. Add `ui.overlay_backend: qt | tk` flag;
  `app.py` imports the selected module.
- **Q1-3** = P3-3: Mica fallback for pre-22H2. Detect
  `sys.getwindowsversion().build < 22621` → skip
  `WindowEffect().setMicaEffect(hwnd, isDarkMode=True, isAlt=False)`.
  Fallback path paints a solid `#1e1e1e` rounded pill via `QPainterPath`
  in `paintEvent`; Mica layers on top when available.
- **Q1-4** = P3-4: hover-expand showing the last 3 history entries from
  the deque built in Q2-1. Click = re-paste. Right-click = discard.
  Privacy toggle (default OFF) in gear popover.

**Verification**: full P1+P2 smoke plans from source plan (must pass
first), then P3 smoke plan + 30-minute soak watching for COM /
threading issues.

---

### Phase Q2 — History + Re-paste + Tray Completion

- **Q2-1 History deque** — `app.py`:
  ```python
  from collections import deque
  from dataclasses import dataclass

  @dataclass
  class HistoryEntry:
      text: str
      language: str
      timestamp: float
  ```
  Replace `self._last_transcription: str = ""` bookkeeping with:
  - `self._history: deque[HistoryEntry]`
  - Property `self._last_transcription` → `history[-1].text if history else ""`
  Append on every completed paste in `_on_speech_segment` and
  `_stop_and_transcribe`. `delete that` pops the most recent entry.

- **Q2-2 Copy last** — extend `_build_tray_menu` with
  `MenuItem("Copy last transcription", self._copy_last)`. Disabled when
  history is empty. Uses `save_clipboard()` + write, no restore.

- **Q2-3 Re-paste hotkey** — register
  `keyboard.add_hotkey(self.config["ui"]["repaste_hotkey"],
  self._repaste_last, suppress=True)`. Default
  `ui.repaste_hotkey: ctrl+alt+v`. Handler:
  1. If `history` empty → `sounds.play_error()`, toast, return.
  2. `focus_guard.check_text_field()` → if blocked, error tone + toast.
  3. `output_text_to_target(history[-1].text, target_hwnd, method=...)`.

- **Q2-4 Hover-expand history panel** — wires into Q1-4. Show up to 3
  most recent entries, 60-char truncation, timestamps. Click re-pastes.
  Right-click discards that entry. Gear popover gains a "Show history on
  hover" toggle; default OFF.

- **Q2-5 Tray completion for F23** — add "Session history…" item that
  restores the overlay (if dismissed) and briefly opens the hover-expand
  panel. When backend is `tk`, hide this item (no hover-expand).

**Verification**: py_compile + manual: one segment → re-paste → text
lands in target; re-paste after `delete that` plays error; tray Copy
last → clipboard has it; hover-expand shows last 3 after 300 ms dwell.

---

### Phase Q3 — Light Theme + Size/Font + Segment Counter

- **Q3-1 Light theme** — `ui.theme: dark | light | system`. Qt palette
  + QSS per theme. Tray `_ICON_STATES` rebuilt on theme change; mic
  glyph switches to `#1a1a1a` for light theme. `system` reads the
  `AppsUseLightTheme` registry value at startup and on theme-change
  signal (`QGuiApplication.styleHints().colorSchemeChanged`).
- **Q3-2 Configurable overlay size** — `ui.overlay_size: compact |
  normal | wide`. Pill width + font sizes scale. Mode chip + segment
  counter auto-hide in `compact`.
- **Q3-3 Font size scaling** — `ui.font_scale: 1.0` multiplier on all
  pill text.
- **Q3-4 Segment counter (F6)** — tiny numeric chip next to the timer,
  increments per completed segment, resets on `end_session`.

**Verification**: py_compile + toggle each setting live; confirm tray
icon repaints on theme switch; confirm segment counter resets between
sessions.

---

### Phase Q4 — Cheat Sheet + VAD Tuner + Quick Settings

- **Q4-1 Hotkey cheat sheet (F16)** — `Ctrl+Shift+?` opens a
  frameless `QWidget` listing all active hotkeys and their actions
  (record toggle, cycle mode, toggle overlay, re-paste, Esc cancel).
  Auto-dismiss on keypress or after 5 s.
- **Q4-2 Live VAD tuner (F13)** — `QDialog` launched from gear menu
  item "Tune VAD…". Live RMS plot against the current threshold line;
  slider writes `streaming.vad.threshold` (Silero) or
  `streaming.silence_threshold` (energy) to `config.local.yaml`.
  **Gated**: refuses to open while `self._recording`. Reuses the
  existing `Recorder.on_level` callback; does not open a second stream.
- **Q4-3 Quick-settings toggles (F14)** — gear popover gains three
  toggle items: `ui.sounds`, `ui.show_level_meter`, `ui.show_language`.
  Writes to `config.local.yaml` and applies live.

**Verification**: py_compile + open VAD tuner during idle; confirm it
refuses during active recording; confirm toggles persist across restart.

---

## Risk Tier and Verification Matrix

| Phase | Ticket | Tier | Verify |
|---|---|---|---|
| Q1 | Q1-1 deps | R1 | clean-venv pip install + import smoke |
| Q1 | Q1-2 Qt port | R3 | P1+P2 smoke first → full P3 smoke + 30-min soak |
| Q1 | Q1-3 Mica fallback | R1 | force fallback path; verify rounded opaque dark |
| Q1 | Q1-4 hover-expand | R1 | manual hover + click-to-repaste |
| Q2 | Q2-1 history deque | R2 | py_compile + unit-style: dictate N, verify `len(history)==min(N,10)` |
| Q2 | Q2-2 Copy last | R1 | tray click → clipboard has text |
| Q2 | Q2-3 re-paste hotkey | R2 | press hotkey with/without text field focus |
| Q2 | Q2-4 hover-expand wiring | R1 | manual hover on overlay |
| Q2 | Q2-5 tray completion | R1 | tray shows Session history when backend=qt |
| Q3 | Q3-1 theme | R1 | toggle dark / light / system live |
| Q3 | Q3-2 size | R1 | switch sizes; pill re-layouts |
| Q3 | Q3-3 font scale | R1 | slider-style config, text scales |
| Q3 | Q3-4 segment counter | R1 | stream 3 segments → counter shows 3 |
| Q4 | Q4-1 cheat sheet | R1 | press Ctrl+Shift+? → panel appears |
| Q4 | Q4-2 VAD tuner | R2 | open idle → works; open while recording → refuses |
| Q4 | Q4-3 quick settings | R1 | toggle each, restart, confirm persisted |

---

## Resume Pack

**Goal**: Finish the remaining UI + overlay work across four phases —
Q1 PySide6 port, Q2 history + re-paste, Q3 appearance + segment
counter, Q4 discoverability + VAD tuner. Sustainable order: port first
to avoid building theming / segment counter twice.

**Current state (updated 2026-04-17 end-of-day)**:
- Q1-1 redone — prior commit pinned a non-existent package
  (`PySide6-Frameless-Window>=0.4`). Corrected to
  `PySideSix-Frameless-Window>=0.8.1` (zhiyiyo's PySide6 branch on PyPI;
  import name `qframelesswindow`, class `AcrylicWindow` / helper
  `WindowEffect`). Clean-venv install + import smoke now pass.
- Q1-2 — `recording_indicator_qt.py` implements the full pill body on a
  dedicated Qt worker thread (mirrors Tk threading model so
  `pystray.Icon.run()` keeps the main thread). Custom `paintEvent` draws
  pill + gear + mic + level bar + elapsed timer + mode chip + close X;
  hit zones match the Tk `x`-coordinate ranges. Thread-safe public API
  via Qt signals. Drag + position persistence reuse `indicator_pos.json`.
  `ui.overlay_backend: qt | tk` added to `config.yaml` (default `qt`);
  `app.py` imports the selected module inside `__init__`.
- Q1-3 — Mica applied in `showEvent` when
  `sys.getwindowsversion().build >= 22621`; silent fallback to the solid
  `#1e1e1e` rounded paint otherwise. `WS_EX_NOACTIVATE` still applied
  via `ctypes` post-show to preserve no-focus-steal behavior.
- Q2-1 history deque (`HistoryEntry`, `deque(maxlen=ui.history_length)`,
  `_last_transcription` now a property, streaming + batch + `delete that`
  rewired to `_append_history` / `deque.pop`) — shipped.
- Q2-2 tray "Copy last transcription" item (disabled when history empty)
  — shipped.
- Q2-3 re-paste hotkey (`ui.repaste_hotkey`, default `ctrl+alt+v`, routes
  through `focus_guard.check_text_field` + `output_text_to_target`) —
  shipped.
- `config.yaml` gained `ui.repaste_hotkey`, `ui.history_length`.
- `FEATURE_LIST_OVERLAY_OVERHAUL.md` P1 + P2 in code, smoke still
  pending.
- `FEATURE_LIST_UI_OVERHAUL.md`: F1, F2, F3, F4, F5, F7, F17, F18, F19,
  F24, F28, F29 (partial), F10, F11 already shipped; F23 partially
  shipped (Copy last added; Session history still pending hover-expand).
- No hover-expand panel. No theming beyond dark palette. No cheat
  sheet. No VAD tuner.

**Pending verification before `/run` of Q1**:
- P1 smoke plan (10 steps) from
  `FEATURE_LIST_OVERLAY_OVERHAUL.md` §P1-6.
- P2 smoke plan (mode cycle via chip / Ctrl+Shift+M / gear / tray;
  "stop listening", "delete that", Code mode = `local-raw`).

**First command (next window)**: `/run docs/feature-lists/FEATURE_LIST_UI_OVERHAUL_MERGED.md`
— resume at Q1-4 (hover-expand history panel).

**Manual smoke still pending (do before further Q1 work)**:
- P1 + P2 smoke on the Tk backend first: flip
  `ui.overlay_backend: tk` in `config.local.yaml`, restart, run the
  original P1 (10-step) and P2 (mode cycle / voice control) plans.
  Establishes a regression-free baseline.
- Q1-2 + Q1-3 smoke on the Qt backend: flip back to `qt`, restart,
  repeat the same P1+P2 plans. Any failure unique to `qt` is a Q1-2
  regression. 30-minute soak while dictating to watch for COM / thread
  issues (H1).

**Remaining execution order**: Q1-4 → Q2-4 → Q2-5 → Q3-1…Q3-4 → Q4-1
→ Q4-2 → Q4-3. (Q1-1, Q1-2, Q1-3, Q2-1, Q2-2, Q2-3 done.)

**Smoke still to run (Q2 shipped tickets)**:
1. Dictate a segment → tray "Copy last transcription" enabled → clicking
   puts the text on the clipboard.
2. Dictate a segment → press `Ctrl+Alt+V` in another text field → text
   lands there.
3. Press `Ctrl+Alt+V` with empty history → error tone + "Nothing to
   re-paste" toast.
4. Dictate a streaming segment → say "delete that" → backspace clears
   output AND history pops that entry (confirmed by re-paste falling
   back to prior entry or empty toast).
5. Restart app → `ui.repaste_hotkey` / `ui.history_length` honored from
   `config.yaml`.

---

## Open Questions

**Q1: Run P1 + P2 smoke plans before starting Q1, or fold them into
Q1-2 smoke?** — Default: run them first, in isolation. Reason: Q1-2 is
a framework swap; finding a P2-era bug on the Qt path is much harder
to diagnose than on Tk.

**Q2: Re-paste default hotkey — `ctrl+alt+v` or keep `ctrl+shift+v`
as the source plan implied?** — Default: `ctrl+alt+v`. Reason:
`ctrl+shift+v` is "paste plain text" in Chromium / Firefox / Office —
silent collisions.

**Q3: History deque length — 10 items, configurable?** — Default: 10,
configurable via `ui.history_length`. Reason: hover-expand shows 3, but
power users may want more for tray re-paste. 10 keeps the deque RAM
trivial.

**Q4: F12 full tabbed settings window — confirm deferred?** —
Default: deferred. Reason: gear popover + Q4-2 VAD tuner + Q4-3 quick
toggles cover every realistic live-editable value. Revisit only if
daily use surfaces a concrete missing knob.

**Q5: `recording_indicator_tk.py` fallback — remove after Q1
stabilizes, or keep indefinitely?** — Default: keep for one minor
version post-Q1, then delete. Reason: insurance against Qt issues that
only surface under long-running daily use. Removal is a 1-line config
+ file delete.

**Q6: Archive the two source plans after this merge ships, or keep
them in active?** — Default: keep active until Q1 lands, then move
both to `docs/feature-lists/archive/` with a pointer back to this
merged plan. Reason: they still carry design context (option tables,
rejected alternatives) this merged plan summarizes but does not
replicate.
