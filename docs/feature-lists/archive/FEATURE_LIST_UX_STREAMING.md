# Feature List: UX Streaming Upgrade — Win+H-Like Live Dictation

Date: 2026-04-15
Status: Implemented
Scope: Streaming transcription pipeline, VAD auto-chunking, overlay text feedback, disable correction popup
Owner: Freek

---

## Problem Framing

The transcriber works but has a UX gap compared to Windows Win+H voice typing:

1. **No live text**: User records, waits for full transcription + post-processing, then gets all text at once. Win+H shows text appearing phrase-by-phrase as you speak.
2. **Correction popup disrupts workflow**: The auto-showing correction window steals attention and interrupts the flow. The user wants non-disruptive feedback.
3. **No state visibility**: Between pressing the hotkey and text appearing, the user has no feedback on what's happening (transcribing? processing? stuck?).
4. **Window switching friction**: The current batch approach ties the user to one window for the entire recording session.

**Root cause**: The pipeline is fully sequential — record ALL audio → transcribe entire buffer → post-process → paste. There are no intermediate results.

**Goal**: Transform the transcriber into a streaming dictation tool where text appears phrase-by-phrase as the user speaks, matching the Win+H experience.

---

## Scope

### In Scope
- VAD-based streaming recorder that auto-segments speech on silence gaps
- Per-segment transcription and paste (text appears phrase-by-phrase)
- Upgraded overlay showing state transitions and last transcribed text
- Disable correction auto-popup (overlay replaces it as feedback)
- Per-segment post-processing via Ollama
- Whisper context chaining between segments (pass previous text as context)
- Session-based clipboard management (save once at start, restore at end)
- Streaming config section in `config.yaml`

### Out of Scope
- Silero VAD (energy-based is sufficient for now, zero new dependencies)
- Real-time partial word display (faster-whisper is batch; we simulate streaming at phrase level)
- Auto-stop on extended silence (Phase U2)
- Sound feedback on start/stop (Phase U2)
- Cancel-recording gesture (Phase U2)

---

## Chosen Approach: VAD-Chunked Streaming with Energy-Based Voice Detection

### How it works

```
[Mic] → [InputStream callback] → [Energy VAD monitor]
                                        ↓ (silence gap detected)
                                  [Extract speech segment]
                                        ↓
                                  [Transcribe segment (Whisper)]
                                        ↓
                                  [Post-process (Ollama)]
                                        ↓
                                  [Paste to active window]
                                  [Show text in overlay]
                                        ↓
                                  [Continue listening...]
```

1. User presses Ctrl+Shift+Space → streaming recording starts
2. Audio flows in continuously via sounddevice callback
3. Energy-based VAD monitors RMS levels in real time
4. When speech followed by silence gap (600ms default) is detected → that speech segment is extracted
5. Segment is transcribed by Whisper (fast — only a few seconds of audio)
6. Result is post-processed by Ollama (fast — short text)
7. Text is pasted into whatever window currently has focus
8. Overlay briefly shows the transcribed phrase
9. Continue listening for next phrase...
10. User presses hotkey again → stop, flush remaining audio, restore clipboard

### Why this approach

- **Natural sentence boundaries**: Speech has natural pauses between phrases. VAD detects these automatically, giving Whisper clean inputs that align with sentence structure.
- **Zero new dependencies**: Energy-based VAD is a simple RMS threshold check on the audio buffer. No Silero, no ONNX runtime, no torch.
- **Focus-friendly**: Each segment pastes independently into whatever window has focus. User can switch windows mid-dictation — the next phrase pastes into the new window.
- **Context chaining**: Each segment's transcription is passed as `initial_prompt` to the next segment, giving Whisper continuity across phrase boundaries.

### Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| **Periodic re-transcription** (transcribe every N seconds of accumulated audio) | Arbitrary cut points confuse Whisper's decoder. Re-transcribing overlapping audio wastes CPU. Requires complex deduplication of partial results. More resource-intensive with worse quality than VAD-chunked. |
| **Hybrid periodic + VAD** (show tentative text periodically, finalize on silence) | Triple the complexity: tentative/final text state management, UI for grey→black text transitions, result reconciliation. Marginal UX gain over pure VAD does not justify the debt. |
| **whisper_streaming library** (external streaming wrapper) | Adds a dependency with its own architecture assumptions. Our pipeline needs tight integration with Ollama post-processing and the overlay UI. Building the simple VAD ourselves is cleaner and more maintainable. |
| **Silero VAD** (ML-based voice activity detection) | More accurate in noisy environments but adds ONNX runtime dependency. Energy-based VAD is sufficient for a quiet home/office. Can upgrade later if needed — the VAD interface is the same. |

---

## Harden Audit Findings

| # | Finding | Severity | Mitigation in Plan |
|---|---------|----------|--------------------|
| 1 | **Clipboard restoration race**: With rapid streaming pastes, each segment saving/restoring clipboard creates races | Medium | Session-based clipboard: save once at recording start, restore once at stop. New `paste_text_streaming()` in output.py skips per-call save/restore |
| 2 | **Paste timing overhead**: Current 400ms total delay per paste (150+50+200ms) makes rapid segments visibly laggy | Medium | Streaming paste uses shorter delays (100ms pre-paste, 30ms post-paste). No restore delay in streaming mode |
| 3 | **Whisper context loss between segments**: Independent transcription per segment loses continuity | Medium | Pass previous segment's output as `initial_prompt` to next segment. Maintains vocabulary bias AND provides conversational context |
| 4 | **Thread proliferation**: Adding a VAD-aware streaming recorder adds threading complexity | Low | VAD logic runs inside sounddevice's existing audio callback — no new thread needed. Segment callback fires on a worker thread (one at a time via queue) |
| 5 | **Multiple Tk roots**: Recording indicator and correction UI each have their own Tk() | Low | Acceptable — separate daemon threads, no cross-root interaction. Tested pattern already working in production |
| 6 | **Overlay must not steal focus**: Showing text in the overlay could accidentally steal focus from the target window | Low | `overrideredirect(True)` + no `focus_force()`. Text updates via `canvas.itemconfig()` which does not affect focus |

---

## Phase Plan

### Phase U1: Streaming Pipeline + Overlay Upgrade
**Goal**: Text appears phrase-by-phrase as the user speaks. Overlay shows state and recent text.
**Risk tier**: R2 (shared logic across multiple files)
**Estimated effort**: L (cross-cutting, single /run context)
**Context strategy**: Single /run window, 6 tickets sequential

### Phase U2: Polish & Tuning (future)
**Goal**: Auto-stop, sound feedback, VAD tuning, cancel gesture.
**Risk tier**: R1
**Estimated effort**: M
**Deferred**: Not part of this plan. Tracked in master feature list.

---

## Phase U1 — Execution Tickets

### U1-1: Streaming recorder with energy-based VAD

**File**: `recorder.py`
**Action**: Add `StreamingRecorder` class alongside existing `Recorder` (keep for backward compat)
**Risk tier**: R2

**Design**:
```python
class StreamingRecorder:
    """Records audio with VAD-based auto-chunking. Calls on_segment for each speech phrase."""
    
    def __init__(self, sample_rate, channels, device,
                 silence_threshold=0.01,    # RMS energy threshold
                 silence_duration_ms=600,   # Silence before segment boundary
                 min_segment_ms=500,        # Ignore segments shorter than this
                 max_segment_s=30):         # Force-cut segments longer than this
    
    def start(self, on_segment: Callable[[np.ndarray], None]):
        """Start streaming. on_segment(audio) called per speech segment."""
    
    def stop(self) -> np.ndarray | None:
        """Stop streaming. Returns any remaining buffered audio."""
```

**VAD logic** (runs inside sounddevice audio callback):
- Calculate RMS energy per chunk: `rms = np.sqrt(np.mean(chunk ** 2))`
- Track state: `in_speech` (bool), `silence_count` (frames), `speech_buffer` (list of chunks)
- Speech starts: RMS > threshold → start buffering
- Speech ends: RMS < threshold for `silence_duration_ms` → flush buffer as segment
- Safety: force-flush at `max_segment_s` to prevent unbounded buffers
- Minimum segment length: ignore segments shorter than `min_segment_ms` (coughs, clicks)

**Segment delivery**: `on_segment` callback is called from a worker thread (not the audio callback thread) to avoid blocking audio capture. Use a `queue.Queue` — audio callback enqueues segments, a single worker thread dequeues and calls `on_segment`.

**Verification**: `python -m py_compile recorder.py`

---

### U1-2: Upgrade recording indicator with text display and states

**File**: `recording_indicator.py`
**Action**: Rewrite to wider overlay with state transitions and text feedback
**Risk tier**: R1

**New design**:
- Window: 420x52px, top-center, dark background (#1e1e1e), 90% opacity
- Layout (Canvas):
  - Left: pulsing red dot (existing)
  - Center: state text — "Listening...", "Transcribing...", "Processing..."
  - Below or second line: last transcribed phrase (grey, smaller font, fades after 3s)
- `overrideredirect(True)`, `topmost=True`, no focus stealing

**New API**:
```python
def show(self):           # Show overlay (recording started)
def hide(self):           # Hide overlay (recording stopped)
def set_state(self, s):   # "listening" | "transcribing" | "processing" — thread-safe
def show_text(self, t):   # Show transcribed text briefly — thread-safe, auto-fades
def destroy(self):        # Cleanup
```

**State → display mapping**:
| State | Dot | Text | Color |
|-------|-----|------|-------|
| listening | pulsing red | "Listening..." | #e0e0e0 |
| transcribing | solid orange | "Transcribing..." | #F39C12 |
| processing | solid blue | "Processing..." | #4A90D9 |

**Text fade**: After `show_text(t)`, text appears in grey (#888888) below the state line. After 3 seconds, text fades (set to empty). Uses `_root.after()` timer.

**Verification**: `python -m py_compile recording_indicator.py`

---

### U1-3: Streaming pipeline in app.py

**File**: `app.py`
**Action**: Add streaming pipeline methods, rewire `_toggle_recording`
**Risk tier**: R2

**Changes**:
1. Import `StreamingRecorder` from `recorder.py`
2. Create `StreamingRecorder` instance in `__init__` alongside existing `Recorder`
3. Rewrite `_toggle_recording()` to use streaming mode
4. Add new methods:

```python
def _start_streaming(self):
    """Begin streaming recording with VAD."""
    self._update_icon(True)
    self._recording_indicator.show()
    self._segment_context = ""  # For Whisper context chaining
    # Save clipboard once for the session
    self._clipboard_original = _save_clipboard()
    self.streaming_recorder.start(on_segment=self._on_speech_segment)

def _on_speech_segment(self, audio: np.ndarray):
    """Called per speech segment. Runs on worker thread."""
    self._recording_indicator.set_state("transcribing")
    
    # Transcribe with context from previous segment
    prompt = self._segment_context or self._initial_prompt or None
    text = self.transcriber.transcribe(audio, initial_prompt=prompt)
    text = text.strip()
    if not text:
        self._recording_indicator.set_state("listening")
        return
    
    # Post-process
    self._recording_indicator.set_state("processing")
    result = postprocess_text(text, self.config["postprocessing"],
                              vocabulary_text=self._vocabulary_text)
    
    # Paste (streaming mode — no clipboard save/restore per call)
    paste_text_streaming(result)
    
    # Update state
    self._segment_context = result
    self._last_transcription = result
    self._recording_indicator.show_text(result)
    self._recording_indicator.set_state("listening")

def _stop_streaming(self):
    """Stop streaming, flush remaining audio, restore clipboard."""
    remaining = self.streaming_recorder.stop()
    self._update_icon(False)
    
    if remaining is not None and len(remaining) > 0:
        # Process final segment synchronously before hiding overlay
        self._on_speech_segment(remaining)
    
    self._recording_indicator.hide()
    
    # Restore clipboard after brief delay
    _restore_clipboard(self._clipboard_original)
```

5. Remove `_show_correction_auto()` call from the pipeline (correction popup disabled)

**Verification**: `python -m py_compile app.py`

---

### U1-4: Streaming paste mode in output.py

**File**: `output.py`
**Action**: Add `paste_text_streaming()` and clipboard session helpers
**Risk tier**: R1

**New functions**:
```python
def paste_text_streaming(text: str):
    """Paste without clipboard save/restore (for streaming mode).
    Clipboard is managed at session level by the caller."""
    with _paste_lock:
        pyperclip.copy(text)
        time.sleep(0.1)   # Shorter delay for streaming responsiveness
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.03)

def save_clipboard() -> str | None:
    """Save current clipboard contents. Call once at session start."""
    try:
        return pyperclip.paste()
    except Exception:
        return None

def restore_clipboard(original: str | None):
    """Restore clipboard contents. Call once at session end."""
    if original is not None:
        time.sleep(0.2)
        try:
            pyperclip.copy(original)
        except Exception:
            log.warning("Failed to restore clipboard")
```

Keep existing `paste_text()` for any non-streaming use.

**Verification**: `python -m py_compile output.py`

---

### U1-5: Config changes

**Files**: `config.yaml`, `config.py`
**Action**: Add streaming section, change correction default
**Risk tier**: R1

**config.yaml additions**:
```yaml
# Streaming mode settings
streaming:
  enabled: true
  silence_threshold: 0.01   # RMS energy threshold for speech detection
  silence_duration_ms: 600  # Silence gap before segment boundary
  min_segment_ms: 500       # Minimum speech segment to transcribe
  max_segment_s: 30         # Force-cut very long segments
```

**config.yaml change**:
```yaml
brain:
  correction_mode: off       # Was: auto. Overlay now provides feedback.
```

**config.py**: Add `streaming` defaults to the default config dict.

**Verification**: `python -m py_compile config.py`

---

### U1-6: Integration smoke test

**Action**: Manual end-to-end test
**Risk tier**: R1

**Test plan**:
1. Start app (`python app.py`) — verify streaming config loaded
2. Press Ctrl+Shift+Space — overlay appears with "Listening..."
3. Speak a phrase, pause briefly — overlay shows "Transcribing..." then "Processing..."
4. Text appears in active window — overlay shows the transcribed phrase
5. Speak another phrase — new text appends in active window
6. Switch to a different window mid-dictation — next phrase pastes into new window
7. Press Ctrl+Shift+Space to stop — overlay hides
8. Verify clipboard was restored
9. Verify correction popup did NOT auto-show

---

## Failure Modes and Mitigations

| # | Failure Mode | Trigger | Impact | Mitigation |
|---|---|---|---|---|
| 1 | VAD threshold too sensitive | Background noise above threshold | Noise segments transcribed as garbage text | Configurable threshold. Default 0.01 is conservative. User can increase in config. Future: auto-calibration on startup. |
| 2 | VAD threshold too high | Quiet speaker below threshold | Speech not detected, nothing transcribed | Overlay stays on "Listening..." with no transitions → user knows VAD isn't triggering. Lower threshold in config. |
| 3 | Segment too short for Whisper | Brief word followed by pause | Whisper hallucinates or returns empty | `min_segment_ms: 500` filters out sub-500ms segments. Whisper handles 0.5-1s audio reasonably. |
| 4 | Paste into wrong window | User switches windows during paste operation | Text goes to unintended window | Each segment paste is atomic (copy+paste in <150ms). Window switch between copy and paste is extremely unlikely. |
| 5 | Ollama adds latency per segment | Slow model or remote endpoint | Visible delay between speech and text | Overlay shows "Processing..." so user knows it's working. Timeout already configured. Raw text fallback if Ollama fails. |
| 6 | CPU transcription too slow for streaming | Laptop CPU mode, medium model | Previous segment still transcribing when next segment arrives | Segments queue up — worker thread processes sequentially. User sees delayed text but nothing is lost. On CPU, 3s of audio takes ~2-3s to transcribe — usable but not instant. |

---

## Risk Tier and Verification Matrix

| Ticket | Risk | Verification |
|--------|------|-------------|
| U1-1: StreamingRecorder | R2 | `py_compile recorder.py` + manual test |
| U1-2: Overlay upgrade | R1 | `py_compile recording_indicator.py` + visual check |
| U1-3: App pipeline | R2 | `py_compile app.py` + integration smoke test |
| U1-4: Streaming paste | R1 | `py_compile output.py` |
| U1-5: Config | R1 | `py_compile config.py` |
| U1-6: Integration test | R1 | Full manual smoke test (see ticket) |

---

## Resume Pack

**Goal**: Transform the transcriber from batch-mode to streaming phrase-by-phrase dictation, matching Win+H UX.

**Current state**: All source files read and analyzed. Architecture designed. No code changes made yet.

**What's ready**:
- Existing `Recorder` class in `recorder.py` — `StreamingRecorder` adds alongside it
- Existing `RecordingIndicator` in `recording_indicator.py` — rewrite with text display
- Existing `paste_text()` in `output.py` — add `paste_text_streaming()` alongside
- Existing pipeline in `app.py` — add streaming pipeline methods

**Start command**: `/run docs/feature-lists/FEATURE_LIST_UX_STREAMING.md`

**First files**: `recorder.py` (U1-1), then `recording_indicator.py` (U1-2), then `app.py` (U1-3)

**Execution order**: U1-1 → U1-2 → U1-4 → U1-5 → U1-3 → U1-6
(Build dependencies bottom-up: recorder and output first, then app wires them together)

**Pending verification**: Full integration smoke test after all tickets complete.

---

## Open Questions

**Q1: VAD silence threshold default?** — Default: `0.01` RMS. Reason: Conservative value that works in quiet environments. User can tune in `config.yaml`. If too many false triggers in practice, increase to 0.02-0.03.

**Q2: Should post-processing run per segment or batch at end?** — Default: Per segment. Reason: The whole point is live text. Batching at end defeats streaming UX. Per-segment Ollama calls are fast for short phrases (~200ms for qwen2.5:3b on a short input).

**Q3: Keep old batch mode as fallback?** — Default: Yes, keep `Recorder` class and existing `_stop_and_transcribe()`. Streaming is the new default but `streaming.enabled: false` in config falls back to batch mode. Reason: Safety net if streaming doesn't work well on a specific setup.

**Q4: Correction UI completely removed or just auto-popup disabled?** — Default: Auto-popup disabled (`correction_mode: off`). Correction hotkey (Ctrl+Shift+C) still works. Reason: User said "get rid of the correction menu" for workflow. Hotkey access preserved for occasional use. Brain/learning system unaffected.
