# Feature List: Dictation Audio Overhaul — VAD, GPU, Timeouts, Preprocessing

Date: 2026-04-17
Status: Implemented 2026-04-17 — T1–T6, T8 landed in code. T7 smoke matrix pending on user's machine.
Scope: Fix the audio pickup/latency/fragmentation issues at their roots. No UI, overlay, brain, or Android work.
Owner: Freek
Linked issue: `docs/known_issues/current/ISSUE_DICTATION_BACKEND_SPOTTY_20260417-1430.md`

---

## Implementation Summary (2026-04-17)

- **T1 ✓** `config.local.yaml` → CUDA + `distil-large-v3` + `float16`. Stale DLL comment removed.
- **T2 ✓** Residential-WiFi timeouts: `_CONNECT_TIMEOUT=1.5s`; Groq `stt_timeout`/`polish_timeout`=3.0s in both `groq_dictator.py` defaults and `config.yaml`.
- **T3 ✓** `silero-vad>=5.1` + `onnxruntime>=1.18` + `scipy>=1.11` in `requirements.txt`. New `vad.py` with `SileroStreamingVAD`, `EnergyVAD`, and `make_vad()` factory with graceful Silero→Energy fallback. Installed successfully (silero-vad 6.2.1, torch 2.11).
- **T4 ✓** `StreamingRecorder` refactored: mic-native capture via `sd.query_devices`, scipy polyphase resample, 300 ms pre-roll deque of chunks, 512-sample VAD frames, Silero VADIterator state transitions. New `streaming.vad` config block; legacy keys honored under `vad.engine: energy`.
- **T5 ✓** `Transcriber.transcribe(vad_filter=...)` parameter; `CascadeDictator` passes `vad_filter=False` on `mode == "streaming"`. Double-VAD eliminated on streaming path; batch path keeps `vad_filter=True`.
- **T6 ✓** `StreamingRecorder._condition()` helper: DC removal + peak-normalize to 0.3 when peak ∈ [0.01, 0.3). Applied on both flush and stop paths.
- **T8 ✓** Per-event DEBUG logs: `vad: speech start p=... pre_roll_ms=...` and `vad: speech end duration=... pad_ms=...`.
- **T7 ⏳ pending** — manual smoke matrix (8 tests) must be run on the user's Windows machine. Latency numbers go in the issue file Investigation Log.

Verification executed: `python -m py_compile` on all touched files; `SileroStreamingVAD.probe` returned True; synthetic-burst unit test drove `EnergyVAD` path end-to-end and produced a correctly conditioned segment (30720 samples, float32, peak=0.604). Simplify pass removed 2 redundant `probe()` methods, extracted `_condition()` helper, switched pre-roll deque from boxed floats to ndarray chunks, and trimmed WHAT-only comments.

---

## Problem Framing

User reports: "The actual dictation part is only partly working. It's not picking up my voice consistently and when it does it's quite slow and spotty. [...] The actual audio component needs serious work maybe on top of having the right model and infra."

`/diag` evidence (see linked issue for full forensics):

1. **Model runs on CPU despite CUDA being available.** `config.local.yaml` pins `distil-small.en` on CPU/int8 with a stale comment claiming CUDA needs DLL install. Verified: `ctranslate2.get_cuda_device_count() == 1`, RTX 5060 Laptop GPU with 8151 MiB, `WhisperModel('distil-small.en', device='cuda', compute_type='float16')` loads end-to-end in 1.33s. CUDA has been working the whole time; the config is wrong.
2. **`StreamingRecorder` VAD is pure-RMS energy threshold.** No Silero, no adaptive noise floor, no hysteresis, no pre-roll buffer. Fixed `silence_threshold: 0.01` drops soft speech entirely and fragments phrases at natural breath pauses. Log: 5 of 25 segments under 1 second, outputs like `"Does not seem to"`, `"Just need"`, `"I'm curious to see if"` — all mid-phrase cuts.
3. **Double-VAD strips word edges.** `StreamingRecorder` slices by energy → `faster-whisper.transcribe(..., vad_filter=True)` runs Silero again on the already-sliced chunk. Log: `VAD filter removed 00:01.148 of audio` from a 3.1s chunk (37% cut). Silero running twice on sliced audio trims onsets/offsets twice.
4. **Groq timeouts set for a LAN.** `stt_timeout=1.0s`, `polish_timeout=1.2s`, `_CONNECT_TIMEOUT=0.8s`. >60% of segments in the logged session fell back to local path (35 local vs 18 cloud); 4 hard timeout/SSL-EOF events.
5. **No audio conditioning.** Mic is Realtek Array at 44.1kHz stereo native, PortAudio auto-resamples to 16kHz mono. No DC removal, no gain normalization, no noise floor calibration. A fixed energy threshold cannot work across mic/gain/room changes.

**Success criteria:**
- Speech captured reliably down to normal-room soft voice (≈-45 dBFS peak).
- No fragmentation on natural breath pauses up to ~800ms mid-phrase.
- End-to-end latency (end-of-phrase → text visible): **p50 < 1.0s cloud**, **p50 < 0.6s local/CUDA** for 2–3s utterances.
- Cloud fall-through rate < 10% on home WiFi (currently > 60%).
- Degrades gracefully when CUDA unavailable, when Silero VAD fails to load, and when cloud is unreachable.

---

## Scope

### In scope
- **A.** Flip device + model to CUDA + `distil-large-v3` + `float16` (local override).
- **B.** Replace RMS VAD in `StreamingRecorder` with **Silero VAD via `silero-vad` pypi + onnxruntime CPU** (already installed). Add pre-roll ring buffer + hysteresis + min/max segment guards.
- **C.** Disable `vad_filter=True` on the *streaming* transcribe path (keep it for batch to protect against noisy batch recordings). Eliminates double-VAD.
- **D.** Raise Groq + `_CONNECT_TIMEOUT` timeouts to realistic residential WiFi values (connect 1.5s, stt 3.0s, polish 3.0s).
- **E.** Record at mic-native rate, resample via `scipy.signal.resample_poly` for quality-controlled downsample. Normalize DC offset and peak-normalize gain on each segment before inference.
- **F.** Graceful-fallback wrapper: if Silero fails to load/import, log warning + toast + fall back to current RMS path (keep the old code as `_EnergyVAD` class).

### Out of scope
- UI/overlay changes, mode-cycle polish, brain/vocabulary work, Android.
- Streaming STT (Deepgram/AssemblyAI) — explicit rejected alternative below.
- Replacing local Whisper with a different ASR backend.
- Warmup / pre-emphasis filters — can be added later if still needed after A–F.

---

## Chosen Approach — Sustainability First

### Why Option A (fundamentals) over the alternatives

Rejected alternatives:

| Rejected option | Why rejected |
|-----------------|--------------|
| Config tuning only (raise threshold, lengthen silence window, bump timeouts) | Band-aid. Pure-RMS VAD is the architectural root cause of fragmentation and soft-voice drops — no tuning fixes it. Technical debt grows each time the user changes mic/room. |
| Streaming STT API (Deepgram Nova-3, AssemblyAI Realtime, OpenAI Realtime) | Kills offline, introduces vendor lock-in, ongoing cost (~$0.005/min), rewrites `recorder.py` pipeline. Disproportionate for a bug that's fixable upstream. Revisit if A still feels slow after landing. |
| Re-use faster-whisper's bundled Silero internals directly | Imports from undocumented `faster_whisper.vad` module paths that are not in the stable API. Brittle across faster-whisper upgrades. The 2.3 MB `silero-vad` package is negligible cost for a clean public API. |
| Swap model to `large-v3-turbo` (multilingual) | User dropped Dutch 2026-04-16 (see memory). English-only `distil-large-v3` is faster and slightly more accurate on English than turbo. |

### Architecture

```
Mic (Realtek 44.1 kHz stereo)
  │
  ▼
sounddevice InputStream
  (samplerate=mic_native, channels=1, blocksize=tuned_to_512_at_16k)
  │  downmix stereo→mono in callback (cheap)
  ▼
callback → ring buffer (last 300 ms pre-roll)
  │      → resampler (mic_native → 16 kHz via resample_poly)
  │      → chunker (feeds exact 512-sample frames to Silero)
  ▼
SileroStreamingVAD
  (VADIterator, threshold=0.5, min_silence_ms=600, speech_pad_ms=120)
  │  emits: on_speech_start(pre_roll_audio) / on_speech_end(segment_audio)
  ▼
Queue<np.ndarray>   ──→   worker thread
                               │
                               ▼  (if cloud enabled)
                            Groq STT (3.0s timeout) ── fail → Whisper CUDA
                               │  │
                               ▼  ▼
                            Groq polish ── soft-fail → raw STT / formatting commands
                               │
                               ▼
                            output.paste_or_type
```

Key properties:
- **Single authoritative VAD** (Silero). Whisper's `vad_filter` stays ON for batch mode only.
- **Pre-roll buffer** reconstructs the 100–300 ms before speech onset that Silero's threshold crossing discards. Eliminates clipped word beginnings.
- **Hysteresis** via Silero's native `min_silence_duration_ms=600`. Pauses shorter than 600 ms do not flush.
- **Graceful VAD fallback**: Silero import/load failure → log + toast + old `_EnergyVAD` class resumes old behavior.
- **Audio preprocessing** (DC + gain) applied once per flushed segment, not per audio callback — cheap and keeps the callback fast-path clean.

### Key library pattern (verified via Context7 /snakers4/silero-vad)

```python
from silero_vad import load_silero_vad, VADIterator

model = load_silero_vad(onnx=True, opset_version=16)   # 2.3 MB, CPU-only fine
vad = VADIterator(model, threshold=0.5, sampling_rate=16000,
                  min_silence_duration_ms=600, speech_pad_ms=120)

# feed exactly 512-sample float32 chunks at 16 kHz:
event = vad(chunk_512)   # → {'start': t} | {'end': t} | None
# reset between sessions:
vad.reset_states()
```

---

## Phase Plan — Context-Window Strategy

One fresh chat per phase unless noted. Each phase commits independently. `/run` picks up at Phase 1 first.

### Phase 1 — CUDA flip + timeout raise (quick wins, ~45 min, R1)
Smallest possible change, biggest single-session quality win. Must land first because Phase 2 verification depends on the local-fallback path being fast.

### Phase 2 — Silero VAD in `StreamingRecorder` (~3 h, R2)
Core refactor. Adds `silero-vad` dep, introduces `SileroStreamingVAD` class alongside the existing `_EnergyVAD` fallback, wires config. Single smoke test at the end of the phase.

### Phase 3 — Audio conditioning + double-VAD removal (~1.5 h, R2)
Native-rate capture + `resample_poly`, DC/gain normalization per segment, disable `vad_filter` on streaming path. Requires Phase 2 landed (otherwise the old RMS VAD still runs and the resample layer is moot).

### Phase 4 — Verification & metrics (~45 min, R1)
Per-segment timing (VAD detect → dictate → paste), Silero probability log at speech start (for threshold tuning), smoke-test matrix. This is the go/no-go phase.

---

## Execution Tickets

### T1 — Flip local config to CUDA + `distil-large-v3`
**Files:** `config.local.yaml`
**Risk:** R1. **Verification:** manual smoke test + `python -m py_compile` (no Python touched — YAML only).

**Do:**
- Replace the `whisper:` block:
  ```yaml
  whisper:
    model_size: distil-large-v3
    device: cuda
    compute_type: float16
    cloud:
      provider: groq
      api_key: "<existing>"
  ```
- Remove the stale `# CUDA needs cublas64_12.dll setup` comment.

**Don't:** touch `config.yaml` defaults — keep CUDA/`distil-large-v3` there too.

**Verify:** `python app.py`, check log for `Model loaded successfully` without CUDA fallback, then ctrl+shift+space a 3-second phrase and confirm `dictate=0.1–0.2s (local)` range.

---

### T2 — Raise Groq + connect timeouts
**Files:** `groq_dictator.py`, `cloud_dictator.py`, `config.yaml`
**Risk:** R1. **Verification:** `python -m py_compile` both files + smoke test.

**Do:**
- `cloud_dictator.py:21` → `_CONNECT_TIMEOUT = 1.5`.
- `groq_dictator.py` defaults → `stt_timeout=3.0`, `polish_timeout=3.0`.
- `config.yaml` cloud block → `stt_timeout: 3.0`, `polish_timeout: 3.0`.
- Document in the cloud block comment: "Set for residential WiFi; drop to 1.0/1.2 on LAN if you want faster fallback."

**Don't:** change `failure_threshold` (3) or `cooldown_s` (60) — still want fast circuit-break on a true outage.

**Verify:** log should stop showing `stt timed out after 1.0s` on normal WiFi; cloud fall-through rate should drop visibly in a 10-segment test.

---

### T3 — Add `silero-vad` dependency + capability probe
**Files:** `requirements.txt`, new `vad.py`
**Risk:** R2. **Verification:** `pip install -r requirements.txt` clean + `python -c "from vad import SileroStreamingVAD; SileroStreamingVAD.probe()"` returns True.

**Do:**
- Append to `requirements.txt`:
  ```
  silero-vad>=5.1
  onnxruntime>=1.18
  scipy>=1.11   # already an indirect dep; pin for resample_poly
  ```
- Create `vad.py` with:
  - `class SileroStreamingVAD` — thin wrapper around `VADIterator`, exposes:
    - `__init__(threshold=0.5, min_silence_ms=600, speech_pad_ms=120)` — loads ONNX model.
    - `feed(chunk_512_float32)` → returns `"start" | "end" | None` + optional probability.
    - `reset()` — called at session start.
  - `class EnergyVAD` — the current algorithm, extracted verbatim from `StreamingRecorder` so Silero can fall back to it.
  - Module-level `make_vad(config) -> VAD protocol` — tries Silero, falls back to Energy on ImportError/onnxruntime failure, logs which one was chosen.

**Don't:** import silero-vad at module top-level in `app.py` — keep startup clean when the dep isn't installed.

**Verify:** unit-level: feed a 3-second WAV file to `SileroStreamingVAD` and confirm it emits exactly one `"start"` and one `"end"` bracketing the speech.

---

### T4 — Refactor `StreamingRecorder` to use the VAD protocol
**Files:** `recorder.py`, `app.py`, `config.yaml`, `config.py`
**Risk:** R2. **Verification:** `python -m py_compile` both + manual smoke matrix (T7).

**Do:**
- `StreamingRecorder` takes a `vad` object conforming to the protocol instead of a float threshold.
- In the audio callback:
  1. Downmix to mono if multichannel (`chunk[:, 0]` or `chunk.mean(axis=1)`).
  2. Resample to 16 kHz if mic native ≠ 16 kHz (scipy.signal.resample_poly; precompute up/down ratios at construction).
  3. Push to a 300 ms pre-roll ring buffer (deque with maxlen in frames).
  4. Chunk into 512-sample frames and feed Silero VAD.
  5. On `"start"` event: concatenate current pre-roll into `_speech_buffer` and begin appending.
  6. On `"end"` event: flush segment to queue, reset pre-roll.
  7. Honor `max_segment_s` with force-flush as before.
- New config block:
  ```yaml
  streaming:
    enabled: true
    vad:
      engine: silero        # silero | energy (auto-falls-back on silero load fail)
      threshold: 0.5
      min_silence_ms: 600
      speech_pad_ms: 120
      preroll_ms: 300
    min_segment_ms: 500
    max_segment_s: 30
  ```
- Keep the old top-level `silence_threshold`/`silence_duration_ms` keys as an opt-in Energy override: if `vad.engine: energy`, use them; otherwise ignored.
- `app.py`: `make_vad(scfg['vad'])` is called once; constructs `StreamingRecorder` with it.

**Don't:** block the PortAudio callback with Silero inference. Silero takes ~0.3 ms per 32 ms chunk on CPU, so inline is fine *for now*, but guard by only running VAD on the resampled 16 kHz path, never on the raw 44.1 kHz path.

**Verify:** a 10-second test with a mid-phrase 500 ms pause should land as ONE segment. Soft speech at `-45 dBFS` peak should fire a `"start"` event (watch the probability log from T8).

---

### T5 — Disable `vad_filter` on streaming transcribe path
**Files:** `transcriber.py`, `cascade_dictator.py`
**Risk:** R2. **Verification:** `python -m py_compile` + T7 smoke.

**Do:**
- Add `vad_filter: bool = True` parameter to `Transcriber.transcribe(...)`.
- In `CascadeDictator.dictate(..., mode=...)`, pass `vad_filter=False` when `mode == "streaming"`.
- Batch mode (`mode == "batch"`) keeps `vad_filter=True` — protects against long pauses in one-shot recordings.

**Don't:** remove VAD entirely from `transcribe` — batch path still needs it.

**Verify:** log line `VAD filter removed 00:00.000` (or no VAD-filter log at all) for every streaming segment.

---

### T6 — Per-segment audio conditioning
**Files:** `recorder.py` (extends T4)
**Risk:** R2. **Verification:** T7 smoke.

**Do:** in `_flush_segment`, after concatenation, before enqueueing:
- DC removal: `audio -= audio.mean()`.
- Peak normalization: if `peak < 0.3`, scale so peak = 0.3 (leaves 10 dB headroom; avoid clipping).
- Skip normalization for segments with peak < 0.01 — that's noise, don't amplify it.

**Don't:** add noise reduction (spectral gate, Wiener filter) — risk of cutting speech.

**Verify:** soft-voice test reliably reaches text; compare dictate times before/after (expect <5% slowdown).

---

### T7 — Smoke-test matrix (manual, required before marking complete)
**Files:** none (test-only)
**Risk:** R0.

Run in order; each must pass:
1. Loud clear speech, 3 sec → cloud path, full text, latency < 1.0 s.
2. Soft speech at normal conversational volume with laptop mic at arm's length → captured, not dropped.
3. Phrase with a 500 ms mid-sentence breath pause → one segment, not two.
4. Phrase with a 1500 ms deliberate pause → two segments (confirms hysteresis works, not over-merged).
5. Airplane WiFi / disable network → local CUDA path, latency < 0.6 s, no hang.
6. Back online → cloud path recovers within one segment (circuit breaker closes).
7. Talk over HVAC / background fan noise → no false speech triggers during silence.
8. Whisper mode (very quiet) → may drop, but app stays responsive.

Record latency numbers into the issue file's Investigation Log.

---

### T8 — Diagnostic logging for threshold tuning
**Files:** `vad.py`, `recorder.py`
**Risk:** R0.

**Do:**
- Log once per speech `"start"` event: `log.debug("vad: speech start p=%.2f pre_roll_ms=%d", prob, preroll_ms)`.
- Log once per `"end"` event: `log.debug("vad: speech end duration=%.2fs pad_ms=%d", dur, pad_ms)`.
- Keep at DEBUG level — INFO is for segment output.

Useful for post-hoc tuning without touching production logs.

---

## Risk & Verification Matrix

| Ticket | Risk | Verification |
|--------|------|--------------|
| T1 | R1 | `python app.py`; confirm CUDA load; 1 utterance |
| T2 | R1 | `py_compile`; 10-utterance cloud test |
| T3 | R2 | `py_compile`; unit test on 3 s WAV |
| T4 | R2 | `py_compile`; full T7 matrix |
| T5 | R2 | `py_compile`; log inspection |
| T6 | R2 | T7 tests 2 and 4 |
| T7 | R0 | Human-in-the-loop |
| T8 | R0 | Log-format inspection |

Shared rule: Python 3.12, Windows cp1252 default → always `python -m py_compile`, never raw `open()`.

---

## Failure Modes & Mitigations (from /critique pass)

| Failure mode | Likelihood | Mitigation |
|--------------|------------|------------|
| `silero-vad` install fails (e.g. offline) | Low | Graceful fallback to `EnergyVAD` with loud warning + toast. `make_vad()` catches ImportError. |
| Silero VAD over-triggers in noisy rooms | Med | `threshold` in config (default 0.5, can raise to 0.6). T8 logs probabilities for tuning. |
| CUDA OOM if browser/game also on GPU | Low-Med | `Transcriber.load_model` already has CPU fallback; keep it. Document VRAM cost in feature list. |
| Pre-roll buffer swamps memory | Very low | 300 ms × 16 kHz × 4 bytes = 19 KB. Fixed-size deque. |
| Resample_poly adds latency in callback | Low | Benchmark: ~0.1 ms per 20 ms chunk for 44.1→16 on this CPU. Well inside callback budget. |
| VADIterator state stale between sessions | Med | `reset_states()` is called in `StreamingRecorder.start()`. Add to `stop()` too for safety. |
| Disabling `vad_filter` lets a noise burst reach Whisper → hallucination | Low | Silero pre-filters; `min_segment_ms=500` still discards bursts. Keep `vad_filter=True` for batch. |
| New config keys break existing users | Low | `config.py` deep-merges defaults; old keys still honored when `vad.engine: energy`. |
| `silero-vad` chunk size mismatch (sounddevice blocksize ≠ 512) | High if naive | Re-chunk in Python between callback and VAD. Trivial, documented in T4. |
| Groq timeouts raised to 3 s → slower failure on true outage | Low | Circuit breaker still opens after 3 fails (`failure_threshold=3`); worst case 9 s of slow before 60 s cooldown. Acceptable. |

---

## Resume Pack (for next context window)

**Goal:** Land Phases 1–4 (T1–T8) so dictation reliably captures soft speech, doesn't fragment at breath pauses, runs on CUDA, and falls back gracefully.

**Current state:**
- Diagnosis complete; all 5 root causes verified.
- No code changes yet. Issue tracked at `docs/known_issues/current/ISSUE_DICTATION_BACKEND_SPOTTY_20260417-1430.md`.
- Dependencies present: `onnxruntime 1.24.4`, `faster-whisper 1.2.1`, `ctranslate2 4.7.1`, `sounddevice 0.5.5`. Missing: `silero-vad` (add in T3).
- CUDA hardware confirmed: RTX 5060 Laptop GPU, 8151 MiB, driver 592.01, `ctranslate2.get_cuda_device_count() == 1`.
- Mic: Realtek Array, native 44.1 kHz stereo.

**First command next session:** `/run`

**First files to open:**
1. `config.local.yaml` (T1 — tiny)
2. `cloud_dictator.py`, `groq_dictator.py`, `config.yaml` (T2)
3. New file `vad.py` (T3)
4. `recorder.py`, `app.py`, `config.py` (T4)
5. `transcriber.py`, `cascade_dictator.py` (T5)

**Pending verification:** T7 smoke matrix must run end-to-end on the user's actual Windows machine before the feature list moves to archived. Latency numbers go into the issue file Investigation Log.

**Commit strategy:** one commit per ticket with message pattern `overhaul(audio): T<n> <summary>`. Do not squash — each phase is independently revertable.

---

## Open Questions

- **Q: Keep OpenRouter audio-chat path available, or delete it?** — Default: **keep** as-is (it's already relegated to an opt-in provider; out of scope for this overhaul). Reason: removing it is an unrelated simplification; bundle into a future `/simplify` pass. Do not touch in this overhaul.
- **Q: Pin `silero-vad` to an exact version or use `>=5.1`?** — Default: **`>=5.1`** with a floor. Reason: it's a leaf dep, API stable since v5; floor protects against a v4 regression without locking upgrades. Re-evaluate if we hit churn.
- **Q: Should batch mode also get Silero VAD pre-filtering?** — Default: **no** (leave `vad_filter=True` in batch unchanged). Reason: batch is a single user-triggered utterance; Whisper's built-in VAD is sufficient and the streaming refactor is already big enough. Revisit if batch quality issues appear.
- **Q: Auto-calibrate noise floor on session start (500 ms listen before going live)?** — Default: **skip for this overhaul**. Reason: Silero's learned threshold is already adaptive in the sense that it's trained on diverse audio; adding a calibration phase adds 500 ms of felt latency. File as follow-up if T7 tests 7 (HVAC noise) fail.
- **Q: Swap `keyboard` library (archived Feb 2026) as part of this?** — Default: **no**. Reason: unrelated to audio root causes; separate ticket. Hotkey delivery is not in the failure surface.
