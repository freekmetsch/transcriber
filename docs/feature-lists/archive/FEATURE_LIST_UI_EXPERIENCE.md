# Feature List: UI Experience Polish — Live Feedback & Session Recall

Date: 2026-04-16
Status: Planned
Scope: Mic level meter, elapsed timer, language indicator, session history, re-paste, tray enrichment
Owner: Freek

---

## Problem Framing

The transcription pipeline is solid and the overlay works, but the UI has three feedback gaps that prevent a daily-driver feel:

1. **No mic-level feedback during recording.** The user presses the hotkey, the pill bar shows "listening" (white mic icon), but there is zero visual confirmation that the microphone is actually picking up sound. Every professional dictation app (WisprFlow, Dragon, macOS Dictation, Win+H) shows a live audio level. Without it, the user speaks into a potentially dead mic for 30 seconds before discovering the problem.

2. **No language awareness.** The user code-switches Dutch and English mid-session. Whisper detects the language per segment (`info.language` and `info.language_probability` are already computed in `transcriber.py:68-74`) but the information is discarded — only logged, never shown. The user has no idea whether Whisper detected "en" or "nl" until the output text looks wrong. For a bilingual daily-driver, this is critical missing feedback.

3. **No session recall.** Once text is pasted into the target window, it's gone. If the paste went to the wrong window, the user has no way to recover it. If they want to re-use a transcription from 5 minutes ago, there's nothing. The only trace is `self._last_transcription` which holds exactly one result. Professional dictation tools (Dragon, Otter.ai) all maintain session history.

**Secondary gap:** The tray menu is sparse — vocabulary management, shortcut creation, auto-start, quit. No status awareness, no quick actions for the most common post-dictation need (re-paste, copy last).

**Success criteria:**
- During recording, a live level bar shows the mic is picking up audio
- An elapsed timer confirms the app is still recording
- After each segment, the detected language is visible (EN/NL badge)
- All recent transcriptions are recallable from a history panel or tray menu
- A re-paste hotkey outputs the last transcription into the current window
- The tray menu shows current mode, last dictation preview, and quick actions

---

## Scope

### In Scope
- Real-time mic level bar in the pill bar (using RMS already computed for VAD)
- Elapsed recording timer in the pill bar
- Language + confidence badge in the text popup after each segment
- In-memory session history (capped deque, not persistent)
- History panel window (Tk Toplevel, dark theme, click-to-copy, double-click-to-repaste)
- Re-paste hotkey (configurable, default Ctrl+Shift+V)
- "Copy last transcription" tray menu item
- "Session history..." tray menu item
- Mode indicator in tray menu (Streaming/Batch)
- Config additions for all new features

### Out of Scope
- Persistent history across app restarts (future — requires SQLite schema)
- Settings UI (separate feature list per FEATURE_LIST_UI_OVERHAUL.md)
- Mic level meter calibration / VAD threshold tuner (future)
- Per-word confidence highlighting (requires segment-level Whisper data)
- Light theme / font scaling (cosmetic, separate scope)
- First-run wizard / onboarding (separate scope)

---

## Chosen Approach

### Mic Level Meter: RMS callback + canvas bar in pill

**How it works:**
1. Both `Recorder` and `StreamingRecorder` already receive audio in their `_audio_callback`. StreamingRecorder already computes `rms = np.sqrt(np.mean(chunk ** 2))` for VAD. Batch Recorder does not — add the same computation.
2. Both recorders expose a new `on_level` callback parameter. In `_audio_callback`, after computing RMS, call `on_level(rms)` if set.
3. `RecordingIndicator` gets a new canvas rectangle below the mic icon (y=39 to y=43, centered at x=100, max width 50px). A new `update_level(rms: float)` method resizes this bar proportionally. Thread-safe via `root.after()`.
4. The audio callback fires per sounddevice block (~64-128ms at 16kHz), giving a natural ~8-15 Hz update rate — perfect for a level meter without explicit throttling.

**Bar design:** Thin horizontal bar (4px tall, max 50px wide) below the mic icon base line. Color matches the current state color (white when listening, orange when transcribing). Width = `min(rms / 0.05, 1.0) * 50px` where 0.05 is a reasonable max-scale RMS for speech.

**Why this over alternatives:**
- **Animated mic icon (macOS-style)**: Scaling canvas items in Tk is complex and flickers. A bar is simpler, universally readable, and matches the pill bar's horizontal orientation.
- **Vertical bar in drag handle zone**: Conflicts with drag functionality. The drag area already has interaction bindings.
- **Separate level window**: Unnecessary new surface. The level bar belongs inside the existing pill bar, right where the user is looking.

### Elapsed Timer: Canvas text in pill bar

A small timer text ("1:23") displayed between the mic icon and the menu dots. Updated every second via `root.after(1000, ...)`. Starts at "0:00" when recording begins, resets on hide.

**Position:** x=145, y=24 (right of mic center at x=100, left of menu dots at x=176). Muted color (#666666) so it doesn't compete with the mic icon.

**Why not in the text popup:** The text popup is ephemeral (shows segment text, fades after 3s). The timer needs to be always visible during recording. Putting it in the pill bar itself is the right surface.

### Language Indicator: Attributes on Transcriber + badge in text popup

**Data flow:**
1. `transcriber.py` already calls `self._model.transcribe()` which returns `(segments, info)` where `info.language` and `info.language_probability` are available (line 68-74). Currently only logged. Add `self.last_language: str` and `self.last_language_probability: float` instance attributes, set them before returning.
2. `app.py` reads `self.transcriber.last_language` after each `transcribe()` call and passes it to the recording indicator.
3. `RecordingIndicator.show_text()` gains an optional `language` parameter. The text popup prepends a small "EN" or "NL" badge with confidence-based coloring: green (>0.8), yellow (0.5-0.8), orange (<0.5).

**Why attributes instead of changing the return type:** Zero API breakage. Both call sites in `app.py` (`_on_speech_segment` and `_stop_and_transcribe`) continue to assign `text = self.transcriber.transcribe(...)` unchanged. Language info is accessed separately.

### Session History: In-memory deque + Toplevel panel

**Storage:** New `history.py` module with a `SessionHistory` class. Internally a `collections.deque(maxlen=N)` (default N=50, configurable via `ui.history_max`). Each entry is a dataclass: `timestamp`, `raw_text`, `processed_text`, `language`, `language_probability`. Thread-safe via `threading.Lock`.

**Panel:** A `HistoryPanel` class (Tk Toplevel on the correction UI's Tk root, same pattern as `VocabularyManager`). Dark theme. Scrollable list showing timestamp, text preview, and language badge per entry. Interactions:
- Click: select entry
- Button "Copy": copy selected entry's text to clipboard
- Button "Re-paste": output selected entry's text to current foreground window
- Button "Correct": open correction UI with selected entry's text
- Search/filter: text entry at the top filters the list in real-time

**Re-paste hotkey:** A new global hotkey (default Ctrl+Shift+V, configurable via `ui.repaste_hotkey`) that outputs the most recent transcription to the current foreground window via `output_text()`. If history is empty, plays error sound.

**Tray menu additions:**
- "Copy last transcription" — copies `history.get_last().processed_text` to clipboard
- "Session history... (Ctrl+Shift+H)" — opens the history panel
- "Mode: Streaming" or "Mode: Batch" — informational, not clickable
- Last dictation preview — "Last: Hello this is a te..." (truncated, informational)

### Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| **Persistent SQLite history** | Adds schema maintenance, storage growth, privacy implications. In-memory is sufficient for v1 — the user can review within the current session. Upgrade path is clear if cross-session search is wanted later. |
| **Waveform visualization (oscilloscope style)** | Complex to render in Tk canvas at adequate frame rate. A simple bar conveys the essential information (mic is hearing you) with zero complexity. |
| **Per-word confidence highlighting** | Requires iterating Whisper segments and aligning words with the final post-processed text. High complexity, moderate value. Per-segment language/confidence is sufficient for v1. |
| **History as a tray-menu submenu** | pystray on Windows doesn't support dynamic submenus well. A dedicated Toplevel window is more functional and follows the VocabularyManager pattern. |
| **Re-paste via Ctrl+Shift+V** | Minor conflict: Ctrl+Shift+V is "paste as plain text" in some apps (Chrome, VS Code). However, `keyboard.add_hotkey(..., suppress=True)` consumes the hotkey before it reaches the foreground app, so no actual conflict occurs. Still, making it configurable is wise. |

---

## Harden Audit

| # | Finding | Severity | Mitigation |
|---|---------|----------|------------|
| 1 | **RMS callback on audio thread could block if Tk dispatch is slow** | Low | `root.after()` is a non-blocking enqueue (~microseconds). The audio callback returns immediately after calling `on_level()`. No blocking risk. |
| 2 | **Level bar update rate could cause Tk event loop pressure** | Low | Audio callback fires at ~10-15 Hz naturally (sounddevice block size). Tk canvas `coords()` call is <0.1ms. Well within budget. No throttling needed. |
| 3 | **Thread safety of `Transcriber.last_language` attribute** | Low | Written on transcription thread, read on Tk thread. Python's GIL makes simple attribute assignment atomic. Stale read is harmless (shows previous segment's language briefly). |
| 4 | **Session history deque contention** | Low | Lock held only during append (~microseconds) and list copy for panel refresh (~microseconds for 50 items). No contention with audio hot path. |
| 5 | **Re-paste hotkey Ctrl+Shift+V suppressed from foreground app** | Medium | `suppress=True` means Chrome/VS Code never sees it. Document this clearly. Make hotkey configurable in config so users can pick a non-conflicting key if needed. |
| 6 | **History panel Toplevel on correction_ui Tk root** | Low | Same pattern as VocabularyManager — proven to work. The Tk root is long-lived (daemon thread). Multiple Toplevel windows on one root is standard Tk. |
| 7 | **Elapsed timer drift over long sessions** | Low | Timer reads `time.monotonic()` on each tick and computes elapsed from start. No drift — each display update is independently computed, not accumulated. |
| 8 | **Level bar flicker on rapid show/hide** | Low | `update_level()` checks if the indicator is visible before updating. If hidden, the update is a no-op. The bar resets to zero width on `show()`. |

---

## Phase Plan

### Phase 1: Live Recording Feedback (1 context window)

**Goal:** During recording, the user sees mic level, elapsed time, and detected language.
**Risk tier:** R2 (cross-cutting: recorder, transcriber, indicator, app)
**Files modified:** `recorder.py`, `transcriber.py`, `recording_indicator.py`, `app.py`, `config.py`, `config.yaml`
**Files created:** None

### Phase 2: Session Recall & Tray Polish (1 context window)

**Goal:** After dictation, the user can recall, copy, or re-paste any recent transcription.
**Risk tier:** R2 (new module + cross-cutting wiring)
**Files modified:** `app.py`, `config.py`, `config.yaml`
**Files created:** `history.py`

---

## Phase 1 — Execution Tickets

### T1: Expose RMS from both recorders

**Files:** `recorder.py`
**Action:** Add `on_level` callback to Recorder and StreamingRecorder
**Risk tier:** R1

**Recorder changes:**
- Add `on_level: callable | None = None` parameter to `__init__`
- In `_audio_callback`, compute `rms = np.sqrt(np.mean(indata ** 2))` and call `self.on_level(rms)` if set

**StreamingRecorder changes:**
- Add `on_level: callable | None = None` parameter to `__init__`
- In `_audio_callback`, after existing `rms = np.sqrt(np.mean(chunk ** 2))` (line 120), call `self.on_level(rms)` if set

**Verification:** `python -m py_compile recorder.py`

---

### T2: Add level bar and elapsed timer to recording indicator

**File:** `recording_indicator.py`
**Action:** Add horizontal level bar below mic icon and elapsed timer text
**Risk tier:** R2

**Level bar:**
- In `_run_tk`, after mic drawing, create a thin rectangle at (cx-25, 39, cx-25, 43) with fill matching state color. Store item ID as `self._level_bar`.
- Initial width: 0px (invisible).
- New `update_level(rms: float)` method (thread-safe via `root.after()`):
  - Compute bar width: `min(rms / 0.05, 1.0) * 50`
  - Update bar coords: `self._canvas.coords(self._level_bar, cx-25, 39, cx-25+width, 43)`
  - Update bar color to match current state color
- In `_do_show()`: reset bar to zero width, start timer.
- In `_do_hide()`: cancel timer.

**Elapsed timer:**
- In `_run_tk`, create timer text at (145, 24), fill="#666666", font=("Segoe UI", 9), anchor="center". Store as `self._timer_item`.
- `_start_timer()`: record `self._timer_start = time.monotonic()`, schedule `_update_timer` every 1s.
- `_update_timer()`: compute elapsed = `int(time.monotonic() - self._timer_start)`, format as "M:SS", update text.
- `_cancel_timer()`: cancel the `after` ID, clear text.

**Verification:** `python -m py_compile recording_indicator.py` + visual inspection

---

### T3: Expose language info from Transcriber

**File:** `transcriber.py`
**Action:** Save detected language and probability as instance attributes
**Risk tier:** R1

**Changes:**
- Add to `__init__`: `self.last_language: str = ""` and `self.last_language_probability: float = 0.0`
- In `transcribe()`, after `segments, info = self._model.transcribe(...)` (line 68), add:
  ```python
  self.last_language = info.language
  self.last_language_probability = info.language_probability
  ```
- No return type change. Existing call sites unaffected.

**Verification:** `python -m py_compile transcriber.py`

---

### T4: Language badge in text popup

**File:** `recording_indicator.py`
**Action:** Modify `show_text()` to display a language badge
**Risk tier:** R1

**Changes:**
- `show_text(text: str, language: str = "", confidence: float = 1.0)` — new optional params.
- In `_do_show_text`: if language is provided, prepend a colored badge to the display text.
  - Badge text: language code uppercased ("EN", "NL")
  - Badge color: green (#2ECC71) if confidence > 0.8, yellow (#F1C40F) if > 0.5, orange (#E67E22) otherwise
  - Implementation: add a second text item in the text popup canvas at x=20, showing the badge. Main text shifts right to x=(tp_w//2)+10.
- Configurable: only show badge if `language` parameter is non-empty. App.py controls whether to pass it based on `ui.show_language` config.

**Verification:** `python -m py_compile recording_indicator.py`

---

### T5: Wire live feedback into app.py + config additions

**Files:** `app.py`, `config.py`, `config.yaml`
**Action:** Connect RMS callbacks, language info, timer to the existing pipeline
**Risk tier:** R2

**app.py changes:**

1. **RMS callback wiring in `__init__`:**
   ```python
   def _on_audio_level(self, rms: float):
       self._recording_indicator.update_level(rms)
   ```
   - Pass `on_level=self._on_audio_level` to both `Recorder()` and `StreamingRecorder()` constructors.

2. **Language info in `_on_speech_segment` (streaming):**
   - After `text = self.transcriber.transcribe(...)`, read `self.transcriber.last_language` and `self.transcriber.last_language_probability`.
   - Pass to `self._recording_indicator.show_text(result.strip(), language=lang, confidence=prob)` if `self.config["ui"]["show_language"]` is True.

3. **Language info in `_stop_and_transcribe` (batch):**
   - Same pattern: read language after transcribe, pass to text popup.

**config.py changes:**
- Add to `DEFAULT_CONFIG["ui"]`: `"show_language": True`, `"show_level_meter": True`

**config.yaml changes:**
- Add under `ui:`: `show_language: true` and `show_level_meter: true` with comments.

**Verification:** `python -m py_compile app.py config.py` + manual smoke test

---

### T6: Phase 1 compile check and smoke test

**Action:** Compile all modified files, run existing tests, define manual test plan
**Risk tier:** R1

**Compile check:**
```bash
python -m py_compile recorder.py
python -m py_compile transcriber.py
python -m py_compile recording_indicator.py
python -m py_compile app.py
python -m py_compile config.py
```

**Manual test plan:**
- [ ] Start app, press Ctrl+Shift+Space
- [ ] Pill bar shows: mic icon + level bar + timer "0:00"
- [ ] Speak — level bar dances in response to voice
- [ ] Silence — level bar drops to near-zero
- [ ] Timer increments: 0:01, 0:02, ...
- [ ] Speak a segment (streaming mode) — text popup shows with "EN" or "NL" badge
- [ ] Badge color is green for high-confidence detection
- [ ] Stop recording — pill bar fades out, level bar resets
- [ ] Batch mode: same level bar + timer behavior, language badge after transcription
- [ ] No visible lag or stutter in the level bar animation
- [ ] `transcriber.log` shows "Detected language: en (probability 0.98)" as before

---

## Phase 2 — Execution Tickets

### T7: Session history module

**File:** New file `history.py`
**Action:** Create in-memory session history with thread-safe storage
**Risk tier:** R1

**Design:**
```python
@dataclass
class HistoryEntry:
    timestamp: float          # time.time()
    raw_text: str
    processed_text: str
    language: str
    language_probability: float

class SessionHistory:
    def __init__(self, max_entries: int = 50):
        self._entries: deque[HistoryEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def add(self, raw_text, processed_text, language="", probability=0.0) -> None
    def get_last(self) -> HistoryEntry | None
    def get_all(self) -> list[HistoryEntry]
    def search(self, query: str) -> list[HistoryEntry]
    def clear(self) -> None
    def __len__(self) -> int
```

**Verification:** `python -m py_compile history.py`

---

### T8: History panel window

**File:** `history.py` (same file, below SessionHistory)
**Action:** Add HistoryPanel Tkinter Toplevel window
**Risk tier:** R2

**Design:**
- `HistoryPanel(root: tk.Tk, history: SessionHistory, on_repaste: callable, on_correct: callable)` — follows VocabularyManager pattern.
- Dark theme (#2b2b2b bg, #e0e0e0 fg), 650x400, centered on screen.
- Top: search entry with filter-as-you-type.
- Middle: ttk.Treeview with columns (Time, Text, Language). Style matches VocabularyManager's "Dark.Treeview".
- Bottom: button row — Copy, Re-paste, Correct, Clear All. Status bar with entry count.
- `schedule_show()` for thread-safe display from tray menu callback.
- `refresh()` reloads from history deque.
- Time column shows "HH:MM" format. Text column shows first 80 chars with ellipsis.
- Language column shows "EN 98%" or "NL 85%".

**Verification:** `python -m py_compile history.py` + visual inspection

---

### T9: Re-paste hotkey + "Copy last" logic

**Files:** `app.py`
**Action:** Register re-paste hotkey, implement copy-last and re-paste actions
**Risk tier:** R1

**Re-paste hotkey:**
- In `_register_hotkey()`, add: `keyboard.add_hotkey(self.config["ui"]["repaste_hotkey"], self._repaste_last, suppress=True)`
- `_repaste_last()`: if `self._history` has entries, call `output_text(history.get_last().processed_text, method=self.config["ui"]["output_method"])`. If empty, `sounds.play_error()`.

**Copy last:**
- `_copy_last_transcription()`: if history has entries, `pyperclip.copy(history.get_last().processed_text)` + log. If empty, no-op.

**Verification:** `python -m py_compile app.py`

---

### T10: Enriched tray menu

**File:** `app.py` (`_build_tray_menu`)
**Action:** Add history items, mode indicator, last dictation preview to tray menu
**Risk tier:** R1

**New menu items (inserted before the existing vocabulary section):**
```python
# Quick actions
pystray.MenuItem(
    lambda item: f"Last: {self._history.get_last().processed_text[:35]}..."
                 if len(self._history) > 0 else "No dictations yet",
    None, enabled=False,
),
pystray.MenuItem("Copy last transcription", self._copy_last_transcription),
pystray.MenuItem("Session history...", self._open_history_panel),
pystray.Menu.SEPARATOR,
# Mode indicator
pystray.MenuItem(
    lambda item: "Mode: Streaming" if self._streaming_enabled else "Mode: Batch",
    None, enabled=False,
),
pystray.Menu.SEPARATOR,
```

**Verification:** `python -m py_compile app.py` + visual inspection of tray menu

---

### T11: Wire session history into app + config + integration test

**Files:** `app.py`, `config.py`, `config.yaml`
**Action:** Initialize SessionHistory, HistoryPanel, wire into pipeline, add config
**Risk tier:** R2

**app.py changes:**

1. **Init:** Create `self._history = SessionHistory(max_entries=self.config["ui"]["history_max"])`.
2. **History panel:** Create `HistoryPanel` on the correction UI's Tk root (same as VocabularyManager):
   ```python
   if self._correction_ui and self._correction_ui._root:
       self._history_panel = HistoryPanel(
           self._correction_ui._root, self._history,
           on_repaste=self._repaste_entry,
           on_correct=self._open_correction_window_with,
       )
   ```
3. **Record to history:** In both `_on_speech_segment` and `_stop_and_transcribe`, after successful output, call:
   ```python
   self._history.add(
       raw_text=text, processed_text=result,
       language=self.transcriber.last_language,
       probability=self.transcriber.last_language_probability,
   )
   ```
4. **History hotkey:** Register `self.config["ui"]["history_hotkey"]` to open the history panel.
5. **Tray menu:** Wire `_open_history_panel` and `_copy_last_transcription` as described in T10.

**config.py changes:**
- Add to `DEFAULT_CONFIG["ui"]`:
  ```python
  "history_max": 50,
  "repaste_hotkey": "ctrl+shift+v",
  "history_hotkey": "ctrl+shift+h",
  ```

**config.yaml changes:**
```yaml
ui:
  history_max: 50            # Max transcriptions to keep in session history
  repaste_hotkey: ctrl+shift+v  # Re-paste last transcription
  history_hotkey: ctrl+shift+h  # Open session history panel
```

**Compile check:**
```bash
python -m py_compile history.py
python -m py_compile app.py
python -m py_compile config.py
```

**Manual test plan:**
- [ ] Dictate 3 phrases — all appear in target window
- [ ] Right-click tray — "Last: [first 35 chars of last dictation]..." visible
- [ ] Click "Copy last transcription" — clipboard now has last dictation text
- [ ] Press Ctrl+Shift+V — last dictation text is output to current window
- [ ] Press Ctrl+Shift+H — history panel opens with all 3 entries
- [ ] Click entry + "Copy" — text copied to clipboard
- [ ] Double-click entry or "Re-paste" — text output to current window
- [ ] Type in search bar — list filters in real-time
- [ ] Each entry shows timestamp, text preview, and language badge
- [ ] Close history panel — re-open from tray menu, entries still there
- [ ] Tray menu shows "Mode: Streaming" (or Batch based on config)
- [ ] With no dictations: "Copy last" is greyed or no-ops, re-paste plays error sound
- [ ] History panel "Clear All" empties the list
- [ ] After 50+ dictations, oldest entries are automatically dropped

---

## Risk Tier and Verification Matrix

| Ticket | Risk | Verification |
|--------|------|-------------|
| T1: RMS callback | R1 | `py_compile recorder.py` |
| T2: Level bar + timer | R2 | `py_compile recording_indicator.py` + visual |
| T3: Language attributes | R1 | `py_compile transcriber.py` |
| T4: Language badge | R1 | `py_compile recording_indicator.py` + visual |
| T5: App wiring (Phase 1) | R2 | `py_compile app.py config.py` + smoke test |
| T6: Phase 1 integration | R1 | All compiles + full manual test |
| T7: History module | R1 | `py_compile history.py` |
| T8: History panel | R2 | `py_compile history.py` + visual |
| T9: Re-paste + copy last | R1 | `py_compile app.py` |
| T10: Tray menu | R1 | `py_compile app.py` + visual |
| T11: Phase 2 integration | R2 | All compiles + full manual test |

---

## Failure Modes and Mitigations

| # | Failure | Likelihood | Impact | Mitigation |
|---|---------|------------|--------|------------|
| 1 | Level bar update blocks audio callback | Very Low | Audio glitches | `root.after()` is non-blocking enqueue. RMS computation is <0.01ms for 512 samples. No blocking path. |
| 2 | Level bar flickers or looks jerky | Low | Cosmetic annoyance | Natural update rate (~10-15 Hz) matches standard VU meters. Tk canvas `coords()` is atomic — no partial draws. |
| 3 | Timer text overlaps mic icon on narrow screens | Very Low | Visual glitch | Fixed at x=145, well clear of mic at x=100. Pill bar is always 200px — no responsive resize. |
| 4 | `last_language` read before first transcription | Low | Shows empty string | Badge display is conditional on non-empty language string. Shows nothing on first call — correct behavior. |
| 5 | Re-paste hotkey triggers in wrong context | Low | Unexpected text insertion | `suppress=True` prevents passthrough. Re-paste only fires if history is non-empty. Output uses `output_text()` with all existing safeguards (modifier release, lock). |
| 6 | History deque grows beyond expected memory | Very Low | Marginal memory use | `deque(maxlen=50)` auto-evicts. 50 entries at ~500 bytes each = ~25KB. Negligible. |
| 7 | History panel Toplevel conflicts with correction UI Toplevel | Low | One window hidden behind another | Both are `-topmost`. User can bring either to front. Standard Tk window management. |
| 8 | Tray menu rebuild frequency increases with dynamic items | Low | Slight delay on right-click | Menu rebuild is already triggered by `_refresh_tray_menu()`. Adding 4 items is negligible. pystray caches the menu structure. |
| 9 | Ctrl+Shift+V hotkey conflicts with user's paste-as-plain-text habit | Medium | Frustration | Hotkey is configurable in config.yaml. Document the default in the tray tooltip or help. User can change to Ctrl+Shift+R or any other combo. |

---

## Open Questions

**Q: Should the re-paste hotkey default to Ctrl+Shift+V?**
Default: Yes. Reason: Intuitive mnemonic (V for paste, Shift for "again"). `suppress=True` prevents conflict with "paste as plain text" in browsers. Configurable in `ui.repaste_hotkey` for users who want a different key.

**Q: Should the level bar color change at the silence threshold?**
Default: No, keep it single-color (matches state color). Reason: Adding threshold-based color changes (green→yellow→red) adds visual complexity. The primary feedback is "bar moves = mic works." A simple bar is cleaner. If users request threshold visualization later, it's a one-line change.

**Q: Should the history panel be persistent across sessions?**
Default: No, in-memory only. Reason: Persistent history requires SQLite schema, storage management, and privacy considerations. In-memory covers the most common use case: "what did I just say?" Cross-session history is a clear upgrade path if needed.

**Q: Should the language badge show in batch mode too?**
Default: Yes. Reason: The batch pipeline also runs through Whisper, which detects language. The text popup shows briefly after batch output (green flash + text), and the language badge provides the same value there.

**Q: Maximum history entries?**
Default: 50 (configurable via `ui.history_max`). Reason: At typical dictation patterns (1-2 segments per minute), 50 entries covers ~30 minutes of active dictation. Memory cost is trivial (~25KB). Users who dictate more can increase it.

---

## Resume Pack

- **Goal**: Polish the UI experience with live mic feedback, language awareness, session history, and tray enrichment
- **Current state**: Plan complete, no code changes yet
- **First command**: `/run`
- **Phase 1 first files**: `recorder.py` (RMS callback), `recording_indicator.py` (level bar + timer + language badge), `transcriber.py` (language attributes)
- **Phase 2 first files**: `history.py` (new module), `app.py` (wiring + tray menu)
- **Pending verification**: Full manual test per Phase 1 and Phase 2 checklists
- **Open questions**: All have defaults, safe to proceed
- **Dependencies**: None — all changes use existing libraries (numpy, tkinter, pystray, collections)
- **Risk tier**: R2 (cross-cutting changes across 6-7 files, 1 new file)
- **Context strategy**: 2 context windows (Phase 1 + Phase 2), or 1 window if context budget allows
