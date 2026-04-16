# Feature List: Speed Fix + Windows+H Recording Bar

Date: 2026-04-16
Status: Superseded by FEATURE_LIST_CLOUD_CASCADE.md (2026-04-16)
Reason: Model-swap rationale (downgrade `medium → small` to preserve Dutch) is stale after the Dutch-drop decision on 2026-04-16. UI redesign portion is already implemented in `recording_indicator.py`. Per-step timing logs are preserved in FEATURE_LIST_CLOUD_CASCADE.md T_C4.
Scope: Whisper model swap, Ollama model swap, recording indicator redesign
Owner: Freek

---

## Problem Framing

Two blockers prevent daily-driver use:

1. **Transcription is too slow for real-time dictation.** Currently running Whisper `medium` (769M params) on CPU int8. Each streaming segment takes 3-8+ seconds to transcribe, plus 1-3 seconds for Ollama post-processing (qwen2.5:3b over LAN). Total latency per phrase: 5-10+ seconds. Unusable for conversational dictation.

2. **Recording indicator doesn't match the Windows+H experience.** The current overlay is a 420x52 text-heavy status bar (dot + "Listening..." + timer + hover-reveal stop). The user wants the compact, icon-centric pill bar that Windows+H uses: drag handle | mic icon | menu button. The current code exists and initializes correctly (`recording_indicator.py`), but the design needs a full rework.

**Success criteria**: Transcription latency under 2 seconds per segment. Recording bar looks and feels like Windows+H.

---

## Scope

### In Scope
- Switch Whisper model for CPU speed (config + validate)
- Switch Ollama post-processing model for speed
- Add per-step timing logs to measure improvements
- Redesign recording indicator to Windows+H pill-bar style
- Keep existing thread-safe API (show/hide/set_state/show_text)

### Out of Scope
- CUDA setup (cublas64_12.dll — separate infrastructure task)
- Parakeet TDT v3 migration (future phase, requires ONNX Runtime)
- Settings UI for model selection
- Mic level meter in overlay (future per FEATURE_LIST_UI_OVERHAUL.md)

---

## Chosen Approach

### Speed: Model downgrades for CPU real-time

**Whisper: `medium` -> `small`** (primary recommendation)

| Model | Params | Relative CPU Speed | Dutch+English | faster-whisper |
|-------|--------|--------------------|---------------|----------------|
| medium (current) | 769M | 1x baseline | Yes | Yes |
| **small** | **244M** | **~3x faster** | **Yes** | **Yes** |
| turbo | 809M | ~1.5x faster | Yes | Yes |
| base | 74M | ~10x faster | Yes (weak) | Yes |

Why `small` over `turbo`: On CPU, the encoder dominates inference time. Turbo has the large-v3 encoder (1280 dim, 32 layers) with a tiny decoder — great on GPU where the decoder bottlenecks, but on CPU the large encoder still costs. `small` (768 dim, 12 encoder layers) is genuinely ~3x faster end-to-end on CPU while maintaining Dutch+English support. Turbo is only ~1.5x faster than medium on CPU despite having fewer total params, because its encoder is *bigger*.

Why not `base`: Accuracy drops too much for non-English speech. Dutch recognition becomes unreliable.

**Fallback plan**: If `small` accuracy is unacceptable for Dutch, try `turbo` (near large-v3 accuracy, ~1.5x speedup). If neither is fast enough on CPU, the real fix is CUDA setup or Parakeet migration.

**Ollama: `qwen2.5:3b` -> `qwen2.5:1.5b`**

The post-processing step adds 1-3 seconds per segment. qwen2.5:1.5b is ~2x faster while still capable of punctuation, capitalization, and formatting command conversion. The task is simple text cleanup — 1.5B is sufficient.

**Combined expected improvement**: ~4-6x total speedup (3x Whisper + 2x Ollama). Target latency: 1-3 seconds per segment.

### Rejected alternatives

1. **Disable post-processing entirely** — Fastest option but loses punctuation, formatting commands, and vocabulary correction. Raw Whisper output is usable but noticeably worse for Dutch mixed text. Rejected: quality regression too visible.

2. **distil-large-v3** — 6x faster than large-v3 and high accuracy, but **English only**. Distillation erased multilingual capability. Rejected: user requires Dutch+English code-switching.

3. **Parakeet TDT 0.6B v3** — The real speed king (~30x real-time on CPU, 25 languages including Dutch, better accuracy). But requires replacing faster-whisper with ONNX Runtime — moderate refactor of transcriber.py. Rejected *for this phase*: too much scope for an immediate fix. Recommended for Phase 3.

4. **Moonshine v2** — Fast edge model but no Dutch support. Rejected: language coverage.

---

### UI: Windows+H-style pill bar

Rewrite `recording_indicator.py` to match the Windows+H voice typing bar:

**Target design** (from user-provided screenshot):
```
+---+--------+-----+
| | |  mic   | ... |
| |||        |     |
+---+--------+-----+
 drag  icon   menu
```

- **Shape**: Pill-shaped (rounded corners), ~200x48 pixels, dark background (#1e1e1e), semi-transparent
- **Left**: Drag handle — 3 thin vertical gray lines. Click+drag to reposition.
- **Center**: Large microphone icon drawn on canvas. Color changes by state:
  - Listening: white mic
  - Transcribing: orange mic (pulsing)
  - Processing: blue mic
- **Right**: "..." menu button — click to show options (Stop, settings hint)
- **Position**: Bottom-center of screen (like Windows+H), 60px from bottom edge. Remembers position after drag.
- **Animations**: Keep existing fade in/out transitions. Simplify pulse to mic color breathing.
- **Text display**: Transcribed text appears as a tooltip-style popup above the bar, auto-fades after 3s (instead of cramming into the bar).

**Why redesign vs. incremental update**: The current layout (dot + text + timer in a 420px bar) is fundamentally text-oriented. The Windows+H design is icon-oriented with a completely different spatial layout. Easier and cleaner to rewrite the `_run_tk` layout method than to try morphing the current one.

**What stays the same**:
- Same class name and public API (show/hide/set_state/show_text/destroy)
- Same thread-safety model (Tk thread + `root.after()` dispatch)
- Same WS_EX_NOACTIVATE focus-steal prevention
- Same fade animation system
- Same daemon thread lifecycle

---

## Harden Audit

| Finding | Severity | Mitigation |
|---------|----------|------------|
| Model switch could silently degrade Dutch accuracy | Medium | Add timing + accuracy logging. User tests both `small` and `turbo` before committing. |
| Drag position persistence needs safe file I/O | Low | Write to config.local.yaml only on drag-end, not continuously. Use existing config merge. |
| Tk canvas drawing differences across Windows versions | Low | Use simple shapes (ovals, rectangles, lines) — universally supported. No custom fonts or images. |
| qwen2.5:1.5b may not be pulled on remote Ollama server | Low | Add pull check or document `ollama pull qwen2.5:1.5b` prerequisite. |

---

## Phase Plan

### Phase 1: Speed (this context window, ~20 min)

**T1: Switch Whisper model to `small`**
- File: `config.local.yaml`
- Change: `model_size: medium` -> `model_size: small`
- Validate: restart app, dictate test phrases in Dutch and English, check logs for timing

**T2: Add per-step timing to streaming pipeline**
- File: `app.py` (`_on_speech_segment` method, lines 291-333)
- Add `time.monotonic()` measurements around: Whisper transcribe, Ollama post-process, text output
- Log format: `"Segment timing: whisper=%.2fs, ollama=%.2fs, total=%.2fs"`

**T3: Switch Ollama model to qwen2.5:1.5b**
- File: `config.local.yaml`
- Add: `model: qwen2.5:1.5b` under postprocessing
- Prerequisite: `ollama pull qwen2.5:1.5b` on the remote server (or use existing model if available)

### Phase 2: Windows+H UI (this context window, ~30 min)

**T4: Redesign recording indicator**
- File: `recording_indicator.py` (full rewrite of layout, keep API)
- Design: pill bar with drag handle, mic icon, menu button
- Position: bottom-center, draggable
- States: listening (white mic), transcribing (orange pulse), processing (blue)
- Text popup: floating tooltip above bar instead of inline text

### Verification

- [ ] App starts without errors
- [ ] Ctrl+Shift+Space shows pill bar at bottom-center
- [ ] Pill bar is draggable
- [ ] Dictate in English — transcription appears in <3 seconds
- [ ] Dictate in Dutch — transcription appears, language detected correctly
- [ ] Timing logs show improvement over baseline
- [ ] Bar state transitions (listening -> transcribing -> processing -> listening) visible
- [ ] Transcribed text appears above bar briefly
- [ ] Stop via "..." menu or Ctrl+Shift+Space hides bar with fade

---

## Failure Modes

| Failure | Likelihood | Impact | Mitigation |
|---------|------------|--------|------------|
| `small` model butchers Dutch transcription | Medium | User gets wrong text | Test immediately; fall back to `turbo` or `medium` |
| qwen2.5:1.5b not available on remote Ollama | Low | Post-processing falls back to raw text (circuit breaker) | Pull model first; fallback URL handles gracefully |
| Tk canvas rounded rectangle rendering issues | Low | Visual glitch on some Windows builds | Use overlapping shapes (rectangles + ovals) for cross-version pill shape |
| Drag handle conflicts with WS_EX_NOACTIVATE | Medium | Can't drag because clicks don't register | Test; may need to handle WM_NCHITTEST for drag area specifically |

---

## Open Questions

**Q: Should we benchmark `small` vs `turbo` vs `medium` side-by-side before committing?**
Default: Switch to `small` immediately, add timing logs, user evaluates during testing. If Dutch accuracy is bad, swap to `turbo` in config.local.yaml (one-line change). Reason: speed is the primary complaint; we can always dial accuracy back up.

**Q: Should the pill bar remember its position between sessions?**
Default: Yes, save to config.local.yaml on drag-end. Reason: matches Windows+H behavior where the bar stays where you put it.

**Q: Should the "..." menu include a "Switch to batch mode" option?**
Default: No, keep it minimal (Stop only). Reason: avoid scope creep; streaming mode is the primary use case.

---

## Resume Pack

- **Goal**: Fix transcription speed + redesign recording indicator to Windows+H style
- **Current state**: Plan complete, no code changes yet
- **First command**: `/run`
- **First files**: `config.local.yaml` (model swap), `app.py` (timing logs), `recording_indicator.py` (UI rewrite)
- **Pending verification**: All items in verification checklist above
- **Open questions**: See above — all have defaults, safe to proceed
