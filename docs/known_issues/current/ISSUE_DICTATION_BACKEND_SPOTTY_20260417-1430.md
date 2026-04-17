---
status: FIX_LANDED_PENDING_SMOKE
severity: HIGH
---

# Issue: Dictation backend — inconsistent pickup, slow, spotty output
Created: 2026-04-17 14:30
Status: FIX_LANDED_PENDING_SMOKE — code fix committed; T7 smoke matrix still to run on user's machine.

## Symptom
- Voice not picked up consistently.
- When picked up, transcription is slow and output is fragmented.
- User describes the audio component as needing "serious work" beyond just the model/infra.

## Expected Behavior
- Every spoken phrase is captured fully without clipping.
- Text appears with low, predictable latency (<1.5s end-to-end for short phrases).
- Segments contain complete thoughts, not partial fragments like `"Just need"`, `"Does not seem to"`.

## Investigation Log
| Date | Action | Result | Next Step |
|------|--------|--------|-----------|
| 2026-04-17 14:30 | Read `recorder.py`, `transcriber.py`, `config.yaml`, `config.local.yaml`, recent `transcriber.log` | Identified 5 concrete root causes (model, VAD, timeouts, double-VAD, no audio conditioning) | Present diagnosis and fix options; await `/go` |
| 2026-04-17 | Implemented T1–T6 + T8 per FEATURE_LIST_DICTATION_AUDIO_OVERHAUL: CUDA flip, cloud timeouts 3.0s, Silero VAD via `vad.py`, 300 ms pre-roll, disabled `vad_filter` on streaming path, DC/peak normalization, diagnostic logs. Unit-verified Silero load + end-to-end EnergyVAD pipeline on synthetic audio. | Code compiles; VAD probe True; segment conditioning verified. | Run T7 smoke matrix on user machine; log latency numbers below. |

## Ranked Hypotheses
- [x] H1 (HIGH): Local fallback runs `distil-small.en` on CPU — weak model + slow inference
- [x] H2 (HIGH): Pure-RMS VAD in `StreamingRecorder` misses soft speech and cuts mid-phrase
- [x] H3 (MED):  Double-VAD (energy VAD + Silero via `vad_filter=True`) over-clips segment edges
- [x] H4 (MED):  Groq timeouts (1.0s / 1.2s) too tight for typical residential WiFi → frequent local fallback
- [x] H5 (LOW-MED): No audio preprocessing (no DC removal, no AGC, no noise gate), fixed threshold assumes clean input

## Approaches Tried
(None yet — awaiting user approval of fix plan)

## Related Files
- `recorder.py` — `StreamingRecorder` (energy-based VAD)
- `transcriber.py` — `vad_filter=True, min_silence_duration_ms=500` (second VAD pass)
- `config.yaml` — `streaming.silence_threshold=0.01, silence_duration_ms=700`
- `config.local.yaml` — forces CPU + `distil-small.en` (CUDA not installed)
- `groq_dictator.py` — `stt_timeout=1.0, polish_timeout=1.2`
- `cloud_dictator.py` — `_CONNECT_TIMEOUT = 0.8`

## Evidence
- Log counts (full session): 35 `local`-path calls vs 18 `cloud`-path calls → cloud fails >60% of the time.
- 5 of 25 speech segments under 1 second → ~20% are mid-phrase cuts.
- `config.local.yaml` pins `distil-small.en` on CPU with int8; `distil-large-v3` on CUDA (YAML default) never loads.
- Single-character/word outputs ("Oh.", "off.", "(laughter)") indicate either VAD cutting too aggressively or cloud hallucinating on silent fragments.
