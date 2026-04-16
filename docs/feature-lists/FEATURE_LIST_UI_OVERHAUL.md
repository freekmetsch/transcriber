# Feature List: UI Overhaul — From Developer Tool to Daily-Driver Dictation App

Date: 2026-04-15
Status: Draft — decisions needed
Scope: All user-facing UI across overlay, tray, correction, settings, and new surfaces
Owner: Freek

---

## Problem Framing

The transcriber works well as a pipeline but its UI is still a developer prototype:

1. **No audio feedback** — pressing the hotkey gives no sound confirmation. In noisy environments or when the overlay is off-screen, the user has no idea if recording started.
2. **No settings UI** — every config change requires editing YAML and restarting. This is fine for a developer but unacceptable for daily use.
3. **No transcription history** — once text is pasted, it's gone. No way to review, copy, or re-paste recent transcriptions.
4. **Undiscoverable features** — Ctrl+Shift+A (vocab add), Ctrl+Shift+C (correction), vocab manager — all hidden behind hotkeys or tray menus with no visual hints.
5. **Static overlay** — fixed position, fixed size, no interactivity. Can't drag, can't click, can't dismiss.
6. **No mic level visibility** — user can't tell if the mic is picking up audio until after transcription fails.
7. **No onboarding** — first launch dumps the user into a tray icon with no guidance.
8. **Hardcoded appearance** — dark theme only, font sizes fixed, no user control.

**Root insight**: The gap isn't missing features — it's missing *surfaces*. The pipeline is solid. The UI needs to match.

---

## Feature Inventory

Features are grouped by theme. Each has a **tier** indicating ambition level:

| Tier | Meaning | Typical effort |
|------|---------|---------------|
| **B** (Basic) | Low-risk, small scope, immediate UX win | 1 ticket |
| **M** (Moderate) | New UI surface or meaningful interaction change | 2-4 tickets |
| **R** (Radical) | Architectural shift or complex new system | 5+ tickets, may need prototype |

---

### Theme 1: Audio & Haptic Feedback

> *"I should know dictation started without looking at the screen."*
> — Every dictation app (WisprFlow, Gboard, Voice Access) uses audio cues.

#### F1: Start/stop sounds [B]

Play a short audio cue when recording starts and stops. Two distinct tones so the user knows which transition happened. WisprFlow's "ping" on activation is cited by users as critical.

**Implementation**: `winsound.PlaySound()` with embedded WAV resources (or `winsound.Beep(freq, duration)` for zero-dependency). Async playback so it doesn't block the hotkey.

**Config**: `ui.sounds: true | false` (default: true)

**Decision needed**: Embedded beep tones (zero dependencies, robotic) vs. short WAV files (nicer, ~10KB each, bundled)?

#### F2: Distinct error sound [B]

Different sound when something goes wrong (no mic, Whisper error, empty transcription). Prevents silent failures where the user speaks for 30 seconds into a dead mic.

---

### Theme 2: Overlay Upgrade

> *The overlay is the primary UI surface during dictation. It needs to carry more weight.*

#### F3: Mic input level meter [M]

Show a small real-time volume bar in the overlay, next to the recording dot. Gives immediate feedback that the mic is picking up audio. macOS Dictation does this with a fluctuating microphone icon; Dragon has a full volume meter in the DragonBar.

**Implementation**: Sample RMS from the audio callback (already computed for VAD), send to overlay via thread-safe method, render as a small horizontal bar or series of dots.

**Decision needed**: Horizontal bar (like Dragon) vs. dot-size animation (like macOS) vs. waveform snippet?

#### F4: Draggable overlay [B]

Let the user click-and-drag the overlay to reposition it. Remember position between sessions. Currently fixed at top-center, which may conflict with browser tabs or other toolbars.

**Implementation**: Bind `<Button-1>` and `<B1-Motion>` on the canvas. Save position to `config.local.yaml` on drag-end.

#### F5: Session timer in overlay [B]

Show elapsed recording time (e.g., "0:42") in the overlay. Helps the user gauge how long they've been dictating. Also serves as a "is it still recording?" signal.

#### F6: Segment counter in overlay [B]

Show "3 segments" or similar count during streaming. Gives feedback that the VAD is working and phrases are being detected, even before text appears.

#### F7: Click-to-stop on overlay [B]

Clicking the overlay itself stops recording. Provides a mouse-based alternative to the hotkey. Win+H has a clickable mic button in its toolbar.

#### F8: Overlay auto-hide on idle [M]

After recording stops and the last text fades, the overlay could shrink to a tiny dot or hide entirely rather than staying at full width. Reappears on next recording. Reduces screen clutter.

**Decision needed**: Auto-hide completely vs. shrink to minimal dot vs. keep current behavior (hide on stop)?

---

### Theme 3: Transcription History

> *"What did I just dictate 5 minutes ago?"*
> — Otter.ai and Dragon both maintain a session transcript. Even Win+H has implicit history through the text field.

#### F9: Session history panel [M]

A new window (accessible from tray menu + hotkey) showing all transcriptions from the current session. Each entry shows: timestamp, raw text, processed text, segment count.

**Key interactions**:
- Click entry to copy to clipboard
- Double-click to re-paste into active window
- Right-click for "Correct this" (opens correction UI with that entry)
- Searchable/filterable

**Implementation**: In-memory list of transcription results, new Tk Toplevel window with a Treeview or Text widget. No persistence across app restarts (session only).

**Decision needed**: Session-only (in-memory) vs. persistent history (SQLite, queryable across sessions)?

#### F10: "Copy last" tray menu item [B]

Add "Copy last transcription" to the tray menu. One-click access to the most recent result without opening a history panel.

#### F11: "Re-paste last" hotkey [B]

A new hotkey (e.g., Ctrl+Shift+V) that re-pastes the last transcription. Useful when the paste went to the wrong window or the user wants to paste the same text elsewhere.

---

### Theme 4: Settings UI

> *"I shouldn't need to edit YAML to change the silence threshold."*
> — No consumer app requires config file editing. Even developer tools like VS Code have a settings UI.

#### F12: Settings window [M]

A tabbed settings window accessible from the tray menu. Tabs:

1. **General**: Hotkey, language preferences, startup behavior
2. **Audio**: Device selection (dropdown of available mics), sample rate, VAD tuning (threshold slider with live preview)
3. **Whisper**: Model size, device (CUDA/CPU), compute type
4. **Post-processing**: Ollama URL, model, timeout, enable/disable
5. **Streaming**: Enable/disable, silence threshold (with live RMS readout), silence duration, min/max segment
6. **Appearance**: Theme (dark/light), overlay position, sounds on/off, notification preferences

**Implementation**: Tk Toplevel with ttk.Notebook tabs. Reads current config, writes changes to `config.local.yaml` (preserves user overrides). Some settings apply immediately (appearance), others require restart (Whisper model).

**Decision needed**: Full settings UI now (M effort) vs. minimal "quick settings" in overlay first (B effort)?

#### F13: VAD threshold tuner with live preview [M]

Inside the settings window or as a standalone calibration tool: show the live mic RMS level alongside the current threshold line. User drags the threshold until it sits above the noise floor but below their speech level. Dragon and professional audio tools all have this.

**This solves the #1 VAD tuning problem** — users currently have to guess the threshold value.

#### F14: Quick settings in overlay [M]

A small gear icon in the overlay that opens a compact floating panel with the 3 most-changed settings: mic device, silence threshold, and sounds toggle. Avoids opening a full settings window for common tweaks.

---

### Theme 5: Onboarding & Discoverability

> *"I installed it. Now what?"*

#### F15: First-run wizard [M]

On first launch (no `config.local.yaml` exists), show a 3-step setup:

1. **Mic check** — select audio device, show live input level, confirm it works
2. **Model loading** — show progress while Whisper model downloads/loads, explain CUDA vs CPU
3. **Test dictation** — guided test: "Say something and see it appear below." Paste into a built-in text area (not the clipboard).

After setup, show a cheat sheet of hotkeys.

**Decision needed**: Full wizard vs. simpler "welcome" tooltip on the tray icon?

#### F16: Hotkey cheat sheet overlay [B]

Pressing a help hotkey (e.g., Ctrl+Shift+?) shows a small floating panel listing all active hotkeys and what they do. Fades after 5 seconds or on keypress. Solves discoverability without requiring a manual.

#### F17: Tray tooltip with hotkey hint [B]

Change the tray tooltip from "Transcriber" to "Transcriber — Ctrl+Shift+Space to dictate". Costs nothing, helps every new user.

---

### Theme 6: Language & Confidence

> *Bilingual code-switching is a core use case. The UI should acknowledge it.*

#### F18: Language indicator in overlay [M]

Show the detected language (or language pair) in the overlay after each segment. Whisper already returns `info.language` and `info.language_probability`. Display as a small flag icon or "EN" / "NL" label.

Helps the user know if Whisper is detecting the right language, especially during code-switching.

#### F19: Low-confidence warning [M]

When Whisper's language probability is below a threshold (e.g., 0.7), show the text in a different color (e.g., orange instead of grey) in the overlay. Signals "this might be wrong, check it." Otter.ai and macOS Dictation both highlight uncertain words.

**Implementation**: `info.language_probability` is already available from `transcriber.transcribe()`. Pass it through the pipeline to the overlay.

**Decision needed**: Per-segment confidence (easy, already available) vs. per-word confidence (harder, requires segment-level access)?

---

### Theme 7: Appearance & Personalization

> *Dark theme is great. But only dark theme is limiting.*

#### F20: Light theme option [B]

Add a light theme variant for the overlay, correction window, and vocab manager. Many users work in bright environments where a dark overlay stands out uncomfortably.

**Implementation**: Define two color palettes (dark/light), pick based on `ui.theme: dark | light | system` config. "system" reads Windows dark/light mode preference.

#### F21: Configurable overlay size [B]

Let the user pick compact (current), wide (more text), or minimal (dot only) overlay modes. Different screen sizes and workflows need different overlay footprints.

#### F22: Font size scaling [B]

Global font size multiplier for all UI elements. Helps on high-DPI displays or for accessibility.

---

### Theme 8: Tray Menu & System Integration

#### F23: Richer tray menu [B]

Expand the tray menu with:
- "Copy last transcription" (F10)
- "Session history..." (F9)
- "Settings..." (F12)
- Current mode indicator ("Streaming" or "Batch")
- Recording duration when active
- Separator between actions and info

#### F24: Auto-start on login [B]

Add a "Start with Windows" toggle in settings. Creates/removes a startup shortcut in the Windows Startup folder or registry.

**Decision needed**: Startup folder shortcut (simple, visible) vs. registry Run key (hidden, standard) vs. Task Scheduler (most robust)?

#### F25: Minimize to tray on close [B]

If the app ever gets a main window (settings, history), closing it should minimize to tray rather than exit. Only "Quit" from tray menu actually exits.

---

### Theme 9: Radical Ideas

> *These are high-effort, high-impact features that would fundamentally change the app's character.*

#### F26: App-aware dictation profiles [R]

Detect the active application (via `win32gui.GetForegroundWindow()`) and automatically adjust behavior:
- **Email/Slack**: More formal post-processing, auto-punctuation aggressive
- **Code editor**: Disable post-processing, raw text mode, add code formatting commands ("new line", "indent")
- **Browser text field**: Standard dictation mode

WisprFlow does this and users call it "really smart." Dragon has per-app profiles.

**Implementation**: `win32gui` to get window title/process, configurable profile mappings, per-profile postprocessor settings.

#### F27: Floating dictation box [R]

For apps that don't support clipboard paste well (some Electron apps, remote desktops), offer a floating text box that captures dictation. User can then manually copy/drag the text. Dragon auto-detects when Dictation Box is needed.

**Implementation**: New Tk Toplevel with a Text widget. Auto-detect paste failures and offer the dictation box.

#### F28: Clipboard-free text insertion [R]

Use Windows UI Automation (`comtypes` + `UIAutomationCore`) or `SendInput` to type text character-by-character into the focused field, without touching the clipboard. This is the professional standard (Dragon, Win+H both do this).

**Tradeoffs**: Much slower for long text, fragile across different UI frameworks, but preserves clipboard. Could be an option alongside clipboard paste.

**Decision needed**: Worth the complexity? Clipboard save/restore already works. Main benefit is speed (no clipboard delay) and reliability (some apps block clipboard paste).

#### F29: Voice commands during dictation [R]

Recognize spoken commands during dictation: "select all", "undo that", "new paragraph", "stop listening". Win+H and Dragon both support this. Requires a command recognition layer on top of the transcription pipeline.

#### F30: Inline correction by voice [R]

"Correct <word> to <replacement>" spoken during dictation. Dragon's signature feature. Requires tracking cursor position and editing previously pasted text.

---

## Decision Matrix

These are the choices that shape the plan. Each decision unlocks or blocks downstream features.

### D1: What's the next UI priority?

| Option | Features unlocked | Effort | User impact |
|--------|-------------------|--------|-------------|
| **A) Audio feedback first** | F1, F2 | S (1-2 tickets) | Immediate daily-use improvement. Solves the #1 complaint: "did it start?" |
| **B) Settings UI first** | F12, F13 | L (4-6 tickets) | Unblocks non-developer users. Makes VAD tuning accessible. |
| **C) History + polish first** | F9, F10, F11, F3 | M (3-4 tickets) | Power-user features. Makes streaming mode more useful. |
| **D) Full overlay upgrade** | F3-F8 | M (4-5 tickets) | Makes the overlay the app's command center. |

**Recommendation**: A then D then C then B. Audio feedback is nearly free and the highest-impact-per-effort feature. Overlay upgrades build on the streaming work just completed. History comes next as streaming produces more transcriptions to track. Settings UI is important but can wait since you're comfortable with YAML.

### D2: Session history — ephemeral or persistent?

| Option | Pros | Cons |
|--------|------|------|
| **Ephemeral** (in-memory, session only) | Simple, no schema, no storage growth | Lost on restart |
| **Persistent** (SQLite) | Searchable across sessions, analytics | Schema maintenance, storage, privacy implications |

**Recommendation**: Start ephemeral. Upgrade to persistent later only if you find yourself wanting cross-session search.

### D3: Settings UI scope

| Option | Description | Effort |
|--------|-------------|--------|
| **Minimal** | Quick-settings panel in overlay (3 knobs: mic, threshold, sounds) | S |
| **Medium** | Standalone settings window with 3 tabs (General, Audio, Appearance) | M |
| **Full** | Tabbed window covering every config.yaml option | L |

**Recommendation**: Start with minimal quick-settings (F14). Build the full window when you're tired of YAML editing.

### D4: Sound implementation

| Option | Description | Effort |
|--------|-------------|--------|
| **winsound.Beep()** | Built-in, no files, robotic tone | Trivial |
| **Bundled WAV files** | Pleasant sounds, ~10KB each, `winsound.PlaySound()` | Small |
| **User-configurable sounds** | Let user pick their own WAV files | Moderate |

**Recommendation**: Bundled WAV. `winsound.Beep()` sounds terrible. User-configurable is overkill.

### D5: Radical features — any now?

| Option | Description |
|--------|-------------|
| **None** | Focus on polish. Ship a solid daily-driver first. |
| **F26 (app profiles)** | High impact for bilingual use. Could auto-detect Slack vs. Obsidian and adjust formality. |
| **F28 (clipboard-free)** | Solves a real pain point but fragile. |

**Recommendation**: None now. The radical features need the basic UI to be solid first. F26 is the most interesting for later — app-aware behavior would genuinely differentiate this from Win+H.

---

## Proposed Phasing

### Phase U3: Audio Feedback + Overlay Polish
**Scope**: F1, F2, F4, F5, F6, F7, F17
**Effort**: S-M (5-6 tickets)
**Goal**: Recording feels responsive and professional. Overlay is interactive.

### Phase U4: History + Re-paste
**Scope**: F9, F10, F11
**Effort**: M (3-4 tickets)
**Goal**: Transcriptions are reviewable and re-usable.

### Phase U5: Mic Level + Language Feedback
**Scope**: F3, F18, F19
**Effort**: M (3-4 tickets)
**Goal**: User can see what the app hears and whether it's detecting the right language.

### Phase U6: Settings UI + Onboarding
**Scope**: F12, F13, F15, F16, F24
**Effort**: L (6-8 tickets)
**Goal**: Non-developer-friendly. Can be configured and understood without documentation.

### Phase U7: Appearance + Personalization
**Scope**: F20, F21, F22, F25
**Effort**: M (3-4 tickets)
**Goal**: Looks and feels like a personal tool, not a prototype.

### Phase U8: App-Aware Profiles (Radical)
**Scope**: F26, F27
**Effort**: L (5-6 tickets)
**Goal**: Dictation adapts to context. The "wow" feature.

---

## Open Questions

**Q1**: Do you use multi-monitor? If so, which monitor should the overlay appear on — always primary, or follow the active window?

**Q2**: Do you dictate into any apps where clipboard paste doesn't work? (This would bump F28 priority.)

**Q3**: How important is auto-start on login? If this is a daily-driver, it should probably start automatically.

**Q4**: Do you want the correction UI to survive into the streaming world at all, or should the overlay + history fully replace it?

**Q5**: Any apps where you'd want different dictation behavior? (e.g., formal for email, casual for chat — this gauges F26 priority.)
