# Feature List: Cloud Dictation V2 — Groq Two-Call + Latency + Level-Bar Clarity

Date: 2026-04-17
Status: Reviewing — all 8 tickets landed in code (T_V1-T_V8). Pending manual verification per Resume Pack (20-segment daily-driver run, hallucination count, felt-latency timing).
Scope: Replace OpenRouter audio-chat with Groq Whisper STT + Groq text polisher (two calls); cut VAD silence gap; fix level-bar/state mental model; keep local + OpenRouter as fallbacks.
Owner: Freek

---

## Problem Framing

Three symptoms after one daily-driver session on `openai/gpt-audio`:

### 1. Cloud model hallucinates chat replies — not a prompt problem, a model-choice problem

Ground truth from `transcriber.log`:

```
2026-04-17 07:08:33,807 Speech segment: 2.8s
2026-04-17 07:08:35,409 Segment timing: dictate=1.59s (cloud)
2026-04-17 07:08:35,491 Segment output: Sure, please go ahead and start dictating.
                                         I'll transcribe it for you.
```

2.8s of speech went in — a conversational reply came out. The system prompt explicitly says *"Output ONLY the corrected text. No explanations, no commentary."* and the model ignored it.

`openai/gpt-audio` (the OpenAI `gpt-4o-audio-preview` family under the OpenRouter brand) is a **conversational multimodal LLM**, not a transcription model. Its training objective is to *respond to* audio, not *transcribe* it. System-prompt guards reduce but do not reliably eliminate this — it's an architectural mismatch, not a prompt bug. No amount of prompt tuning will make a chat-trained model stop occasionally replying.

### 2. Cloud is slower than it feels necessary, and the felt delay is dominated by VAD

Observed per-segment timings:

| Segment | Duration | Cloud dictate | Perceived delay* |
|---|---|---|---|
| 1.5s speech | 1.17s (cloud) | 1.17s | ~2.67s |
| 1.5s speech | 1.61s (cloud) | 1.61s | ~3.11s |
| 2.8s speech | 1.59s (cloud) | 1.59s | ~3.09s |
| 1.9s speech | 2.0s timeout + 3.27s local | 3.27s (local) | ~4.77s |

\* = `silence_duration_ms (1.5s) + dictate time`. User stops speaking → 1.5s of silence must elapse before VAD flushes the segment → then the round-trip starts.

**The dominant contributor to felt latency is the 1500ms VAD gap, not the cloud.** Cloud itself is 1.2-1.6s, which is inherent to audio-chat models doing ASR + LLM synthesis + LLM token output all in one pass. A pure STT endpoint does the same transcription in ~300ms.

### 3. Level bar confusion — orange bar that doesn't match speech

Evidence in `recording_indicator.py`:
- `_STATE_COLORS`: listening=white, **transcribing=orange (#F39C12)**, processing=blue.
- `_do_update_level()` (line 478-484) sets the bar's fill color to `_STATE_COLORS[current_state]` on every RMS update. Width is `min(rms/0.05, 1) * 50` pixels.
- `set_state("transcribing")` fires at the *start* of `_on_speech_segment` (app.py:364) — the moment a segment is dequeued for the cloud call.
- `StreamingRecorder` keeps capturing during that call (the audio stream never stops mid-session).

So what you actually see:
- **Bar width** = live RMS of the mic, continuously updated by `_on_audio_level` from the audio callback thread. Regardless of state.
- **Bar color** = current processing phase. White when between segments, orange during cloud/local dictation, blue during batch post-processing.
- **During a 1.5s cloud call, the bar can be orange AND pulsing** — because the recorder is already capturing your *next* utterance while the previous one is being transcribed.

**The sound/transcription mismatch is real but explainable.** Sound picked up without transcription happens when:
  - RMS spikes but stays under `silence_threshold: 0.01` in aggregate (bar flickers, VAD never opens a segment).
  - Segment is under `min_segment_ms: 500ms` (dropped silently — debug log only).
  - Whisper's VAD filter strips it (log line: `VAD filter removed 00:01.148 of audio`).
  - Cloud returned an empty response or was discarded as a hallucination.

Transcription without visible bar movement happens when:
  - The segment finished flushing before the bar drew a wide frame (VAD chunks are ~2048-4096 frames; bar updates at audio-callback cadence ~10-15 Hz).
  - The bar stays orange across rapid consecutive segments, so it looks like "processing" not "new audio," even when width pulses with new RMS.

**Success criteria:**
- A 3s utterance lands as typed text in <1.5s after the user stops speaking.
- Zero conversational hallucinations over a full day's use (replace with a model that can't hallucinate chat — purpose-built STT).
- Level bar communicates one thing at a time: either "we're hearing you" (width + listening color) or "we're working" (state color, width frozen).
- Offline, rate-limited, and 401 paths unchanged (local fallback still wins).

---

## Scope

### In Scope
- **A. Swap cloud primary to a two-call Groq pipeline** (Whisper-large-v3-turbo + Llama for text polish). One Groq API key, one SDK surface (OpenAI-compatible REST).
- **B. Cut perceived latency.** Reduce `silence_duration_ms` default from 1500 → 700ms.
- **C. Clarify the indicator.** Freeze the level bar when state ≠ "listening" so bar motion always means "we're hearing you right now."
- **D. Keep OpenRouter audio-chat as a configurable alternative** (`provider: openrouter|groq`) — still useful for users without a Groq key, not the default.
- **E. Keep `postprocessor.build_cloud_system_prompt` semantics** — same commands block + vocabulary, now consumed by a *text* polisher instead of an audio-chat model.

### Out of Scope
- Streaming / WebSocket STT (larger scope; batch <1s is already fine).
- Replacing the local Whisper path. It's the offline floor, not a speed problem.
- Re-plumbing the brain / vocabulary pipeline — unchanged.
- Session history, tray enrichment, waveform visualization.
- Swapping `keyboard`/`pyautogui` — see existing tickets.

---

## Chosen Approach — Sustainability First

### A. Two-call cloud via Groq

**Flow:** `audio → Groq Whisper-large-v3-turbo → raw text → Groq Llama-3.3-70B (via chat/completions) → polished text`.

**Why two calls instead of one:**

| | One-call (gpt-audio) | Two-call (Groq STT + Groq text) |
|---|---|---|
| ASR quality | Good | Excellent (Whisper-large-v3-turbo) |
| Hallucinates chat replies | **Yes** (observed) | **No** — STT endpoint only returns transcription; text step operates on text, not audio |
| Typical latency | 1.2-1.6s | ~0.3-0.5s STT + ~0.3-0.5s text = **0.6-1.0s** |
| Handles vocabulary | In one prompt | Text step handles vocab + commands with full LLM power |
| Handles empty audio | Model sometimes replies conversationally | STT returns empty string → cascade skips polish, outputs nothing |
| Pricing (daily driver) | ~$1.50-$2.50/month | Groq free-tier covers typical daily use; paid is ~$0.04/hr audio + cents for text |
| Provider lock-in | Yes (OpenRouter → OpenAI) | Can swap text model independently |

The two-call design eliminates the observed hallucination *by construction* — the STT endpoint is architecturally unable to reply conversationally because its output schema is `{text: str}`, not a chat completion.

**Groq endpoints:**
- `POST https://api.groq.com/openai/v1/audio/transcriptions` — multipart form, `model=whisper-large-v3-turbo`, returns `{text}`.
- `POST https://api.groq.com/openai/v1/chat/completions` — OpenAI-compatible, `model=llama-3.3-70b-versatile` (or `llama-3.1-8b-instant` for maximum speed).

**Cascade becomes:** Groq STT → Groq polish → (on failure) OpenRouter audio-chat if configured → (on failure) local Whisper + local polish. Each stage has the same circuit-breaker pattern already in `CloudDictator`.

### B. Reduce VAD silence gap

`streaming.silence_duration_ms`: 1500 → 700ms. Expected felt-latency drop: ~800ms per segment. 700ms is large enough to separate natural pauses (commas, breaths) from end-of-thought, based on Gboard/WisprFlow defaults. Config-adjustable.

### C. Level-bar clarity

In `_do_update_level`, short-circuit when `self._current_state != "listening"`: keep the bar at whatever width it last rendered, but **stop feeding it new RMS**. The state-color change already communicates "we're processing." Bar motion now always means "mic is live and hearing you."

Alternative considered and rejected: show two stacked indicators (state above, RMS below). More pixels, same information. Freezing is cleaner.

### D. Provider selector

`whisper.cloud.provider: groq` (new default) | `openrouter` (existing). The `CloudDictator` becomes a thin factory; each provider has its own concrete class (`GroqDictator`, `OpenRouterDictator`), both implementing `dictate(audio, *, system_prompt) -> str`. `CascadeDictator` is untouched — it only calls `dictate()`.

### Rejected Alternatives

| Alternative | Why rejected |
|---|---|
| Keep `openai/gpt-audio`, harden system prompt (temperature=0, "output empty string on ambiguous audio", prefix tricks) | Band-aid for a model-choice problem. Conversational training surfaces are not reliably suppressible by prompt alone; next session's first ambiguous audio triggers it again. |
| Swap to `openai/gpt-4o-audio-preview` on OpenRouter | Same model family, same conversational training, same hallucination risk. No architectural fix. |
| Groq STT only + regex formatting (no LLM polish) | Regresses diction on proper nouns (kids, teachers, local town) — the main UX win the cascade was built to deliver. Regex can't do vocabulary bias. |
| Groq STT + OpenRouter text LLM | Two providers, two API keys, two circuit breakers. Groq for both is simpler and faster (both calls to one endpoint family). |
| Streaming cloud STT over WebSocket | Connection lifecycle, partial-result reconciliation, reconnect logic. Latency is already <1s with batch two-call — not worth the complexity. |
| Drop OpenRouter entirely | Throwing away working code that's a legitimate fallback/alternative. Keep as provider option. |
| Run cloud + local in parallel, first-wins | Wastes GPU on the 99% of segments where cloud wins. Sequential with tight timeout is cheaper and simpler. |
| Add a "transcribing" pulse to the bar too | User's complaint is the bar is confusing. Adding animation makes it busier, not clearer. |
| Set `silence_duration_ms` to 500ms (even lower) | Too aggressive — natural pauses mid-sentence flush early, breaking "new paragraph" / comma commands. 700ms is the stable floor. |

---

## Harden Audit

| # | Finding | Severity | Mitigation |
|---|---|---|---|
| 1 | **Groq API key leakage via git** | High | Reuse existing pattern: key only in `config.local.yaml` (gitignored). Startup sanity-check warns if tracked `config.yaml` has a non-empty `api_key` for any provider. |
| 2 | **Two calls = two timeout points** | Medium | Budget: 1.2s total (0.6s STT connect+read, 0.6s polish read). If STT succeeds but polish times out, return raw STT text (graceful degradation) — partial value beats blank. |
| 3 | **Groq rate limits (free tier 30 rpm)** | Medium | Existing circuit-breaker + `Retry-After` parsing in `CloudDictator` applies verbatim. Breaker open → local fallback. |
| 4 | **STT returns empty → polish call wastes latency** | Low | `GroqDictator.dictate()` checks for empty STT before calling polish. No empty-audio round-trip. |
| 5 | **Level-bar freeze races with state change** | Low | `_do_update_level` reads `self._current_state` on the Tk thread (via `root.after(0, ...)`). Same thread as `_do_set_state`. No race. |
| 6 | **Silence reduction 1500→700ms breaks "new paragraph" commands** | Low | 700ms is above typical inter-word pauses (~300ms) but below end-of-thought. Configurable — user can tune per session. |
| 7 | **Provider selector typo bricks startup** | Low | Unknown provider → log error + disable cloud (same path as missing key). App starts with local-only. |
| 8 | **Backwards compat with existing `openai/gpt-audio` users** | Low | `provider: openrouter` path preserved verbatim. Default flip to `groq` is behind config — existing `config.local.yaml` continues to work. |
| 9 | **Text polish LLM hallucinates / over-corrects** | Medium | `temperature: 0.1`, explicit "Output ONLY the corrected text" rule (existing). Polish is text-in-text-out — no audio-triggered chat collapse path. |
| 10 | **Two-call cost at heavy use** | Low | Groq pricing: Whisper-turbo $0.04/hr audio, Llama-3.3-70B ~$0.59/M input + $0.79/M output. Daily driver: well within free tier; paid ceiling ~$1-3/month. |
| 11 | **Vocabulary pipeline change** | None | Reuses `get_vocabulary_for_llm` and `build_cloud_system_prompt` unchanged — text polish step consumes same prompt format. |
| 12 | **Hallucination regression during rollout** | High | Side-by-side test: with Groq enabled, expect zero chat-reply outputs over a 20-segment smoke test. Keep OpenRouter code so it's one config line to compare. |

---

## Phase Plan

Two small context windows, each ~45-60 min in `/run`.

### Phase A: Groq provider + provider selector (1 context window)

**Goal:** `provider: groq` is default and works end-to-end with hallucination-free output in <1.5s felt latency.
**Risk tier:** R2.
**Files created:** `groq_dictator.py`.
**Files modified:** `cloud_dictator.py` (rename class to `OpenRouterDictator`, extract common base), `cascade_dictator.py` (no change to interface — still calls `.dictate()`), `app.py` (provider selector), `config.py`, `config.yaml`, `config.local.yaml` (add Groq key).
**Execution tickets:** T_V1–T_V5.

### Phase B: Latency + indicator clarity (1 context window)

**Goal:** perceived end-of-speech-to-text latency under 1.5s; level bar unambiguous.
**Risk tier:** R1.
**Files modified:** `config.yaml` (silence_duration default), `recording_indicator.py` (freeze bar outside listening state).
**Execution tickets:** T_V6–T_V8.

---

## Phase A — Execution Tickets

### T_V1: Extract `CloudProvider` base + rename existing class

**File:** `cloud_dictator.py`
**Action:** Rename `CloudDictator` → `OpenRouterDictator`. Extract a thin abstract base `CloudProvider` with one method: `dictate(audio, *, system_prompt) -> str` and a shared circuit-breaker mixin.
**Risk:** R2.

**Interface:**
```python
class CloudUnavailable(Exception): ...

class CloudProvider:
    def dictate(self, audio: np.ndarray, *, system_prompt: str) -> str:
        raise NotImplementedError

class _CircuitBreaker:
    # Existing code: _failures, _breaker_open_until, _key_invalid, _lock,
    # _breaker_allows, _trip_breaker, _reset_breaker, _parse_retry_after.

class OpenRouterDictator(_CircuitBreaker, CloudProvider):
    # Existing body, unchanged semantics. Rename only.
```

**Notes:**
- No behavior change. Pure rename + hoist. This keeps the existing manual-test matrix green.
- Keep `_wav_bytes` on the base — Groq also needs WAV serialization.

**Verification:** `python -m py_compile cloud_dictator.py`. `CascadeDictator` still imports `CloudUnavailable` unchanged.

---

### T_V2: `GroqDictator` — two-call STT + text polish

**File:** new `groq_dictator.py`
**Action:** Two sequential HTTP calls. STT via multipart upload, text polish via OpenAI-compatible chat/completions. Shares `_CircuitBreaker` from `cloud_dictator`.
**Risk:** R2.

**Interface:**
```python
class GroqDictator(_CircuitBreaker, CloudProvider):
    def __init__(
        self,
        api_key: str,
        *,
        stt_model: str = "whisper-large-v3-turbo",
        polish_model: str = "llama-3.3-70b-versatile",
        base_url: str = "https://api.groq.com/openai/v1",
        stt_timeout: float = 1.0,
        polish_timeout: float = 1.2,
        failure_threshold: int = 3,
        cooldown_s: float = 60.0,
    ): ...

    def dictate(self, audio, *, system_prompt: str) -> str:
        # 1. Breaker check (same pattern as OpenRouter).
        # 2. WAV-encode audio (reuse base _wav_bytes).
        # 3. STT call:
        #       POST /audio/transcriptions
        #       multipart: file=audio.wav, model=stt_model, response_format=text
        #    On timeout/5xx/401/429: trip breaker, raise CloudUnavailable.
        # 4. If STT text empty/whitespace → return "" (no polish call needed).
        # 5. Polish call:
        #       POST /chat/completions
        #       messages = [{role:"system", content:system_prompt},
        #                   {role:"user", content:raw_stt_text}]
        #       temperature=0.1
        #    On timeout/5xx: log warning, return raw STT text (graceful).
        #    On 401/429: trip breaker, raise CloudUnavailable.
        # 6. Reset breaker on success. Return polished text.
```

**Notes:**
- STT response is plain text when `response_format=text`. No JSON parsing.
- Polish failure returning raw STT is a deliberate partial-success path. Log at INFO.
- Auth error on either call treats the full key as invalid — opens breaker indefinitely, same as existing 401 handler.
- `Retry-After` parsing is shared with OpenRouter via `_CircuitBreaker._parse_retry_after`.
- Audio field name is `file`, not `audio` (Groq OpenAI-compat convention).

**Verification:** `python -m py_compile groq_dictator.py`. Unit test: stub `requests.post` for both endpoints; verify STT-empty short-circuit; verify polish-failure returns raw STT.

---

### T_V3: App wiring — provider selector

**Files:** `app.py`, `config.py`, `config.yaml`, `config.local.yaml` (user edit).
**Action:** Factory-style selection in `TranscriberApp.__init__`.
**Risk:** R2.

**config.py — under `DEFAULT_CONFIG["whisper"]["cloud"]`:**
```python
"cloud": {
    "enabled": True,
    "provider": "groq",                      # NEW DEFAULT. Was: openrouter.
    # Groq
    "stt_model": "whisper-large-v3-turbo",   # NEW
    "polish_model": "llama-3.3-70b-versatile", # NEW
    "stt_timeout": 1.0,                      # NEW
    "polish_timeout": 1.2,                   # NEW
    # OpenRouter (alternative)
    "model": "openai/gpt-audio",
    "base_url": "https://openrouter.ai/api/v1",  # Used only for openrouter provider.
    # Common
    "api_key": "",
    "referer": "https://github.com/freekmetsch/transcriber",
    "title": "Transcriber",
    "timeout": 2.0,
    "failure_threshold": 3,
    "cooldown_s": 60.0,
},
```

**config.yaml — update the cloud block:**
```yaml
whisper:
  cloud:
    enabled: true
    provider: groq                         # groq | openrouter
    stt_model: whisper-large-v3-turbo
    polish_model: llama-3.3-70b-versatile
    stt_timeout: 1.0
    polish_timeout: 1.2
    # OpenRouter alternative (set provider: openrouter to use):
    #   model: openai/gpt-audio
    #   timeout: 2.0
    # api_key: SET IN config.local.yaml — never commit here.
```

**app.py — replace the `CloudDictator` instantiation (around line 81-97):**
```python
cc = self.config["whisper"]["cloud"]
cloud = None
if cc["enabled"] and cc["api_key"]:
    provider = cc["provider"]
    if provider == "groq":
        from groq_dictator import GroqDictator
        cloud = GroqDictator(
            api_key=cc["api_key"],
            stt_model=cc["stt_model"],
            polish_model=cc["polish_model"],
            stt_timeout=cc["stt_timeout"],
            polish_timeout=cc["polish_timeout"],
            failure_threshold=cc["failure_threshold"],
            cooldown_s=cc["cooldown_s"],
        )
        log.info("cloud dictation: enabled (provider=groq stt=%s polish=%s)",
                 cc["stt_model"], cc["polish_model"])
    elif provider == "openrouter":
        cloud = OpenRouterDictator(
            api_key=cc["api_key"],
            model=cc["model"],
            base_url=cc["base_url"],
            referer=cc["referer"],
            title=cc["title"],
            timeout=cc["timeout"],
            failure_threshold=cc["failure_threshold"],
            cooldown_s=cc["cooldown_s"],
        )
        log.info("cloud dictation: enabled (provider=openrouter model=%s)", cc["model"])
    else:
        log.error("cloud dictation: unknown provider %r — disabling cloud", provider)
elif cc["enabled"]:
    log.info("cloud dictation: enabled in config but api_key missing — local only")
else:
    log.info("cloud dictation: disabled (local only)")
```

**config.local.yaml (user-side, gitignored — user action after merge):**
Existing OpenRouter key stays in place as a fallback. New Groq key added:
```yaml
whisper:
  cloud:
    provider: groq
    api_key: "gsk_..."          # Groq key (free tier: console.groq.com/keys)
```

**Verification:** `python -m py_compile app.py`. Start with `provider: groq` and valid key → log shows `(provider=groq)`. Start with `provider: openrouter` → behavior matches today exactly.

---

### T_V4: Smoke-test script — hallucination regression guard

**File:** new `tests/test_groq_smoke.py`
**Action:** Record a WAV clip of 2-3s ambiguous speech ("uh, hello, I'm testing"), feed it through `GroqDictator.dictate` with the cloud system prompt, and assert the response doesn't contain known chat-hallucination markers.
**Risk:** R1.

**Interface:** Pytest test gated by `@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"))`. One clip fixture in `tests/fixtures/ambiguous_speech.wav`.

**Assertions:**
- Response is non-empty (Groq doesn't silently drop).
- Response does NOT contain any of: `"please go ahead"`, `"start dictating"`, `"i'll transcribe"`, `"how can i help"`.
- Response length is proportionate to input (<200 chars for 2-3s speech).

**Notes:** This is the codified version of the manual assertion from the log-evidence case. Runs in CI as a guardrail.

**Verification:** `pytest tests/test_groq_smoke.py -v` passes locally with a valid key.

---

### T_V5: Supersede OpenRouter-as-default in `FEATURE_LIST_CLOUD_CASCADE.md`

**File:** `docs/feature-lists/FEATURE_LIST_CLOUD_CASCADE.md`
**Action:** Insert a one-line `Status: Superseded` header at top pointing here.
**Risk:** R0.

**Content to add (after date/status line):**
```
Status: Superseded by FEATURE_LIST_CLOUD_SPEED_V2.md (2026-04-17) — provider flipped to Groq two-call STT+polish after observed hallucination regression on openai/gpt-audio. OpenRouter path preserved as alternative.
```

---

## Phase B — Execution Tickets

### T_V6: Reduce VAD silence default

**File:** `config.yaml`
**Action:** `streaming.silence_duration_ms: 1500 → 700`. Update the comment to clarify felt-latency tradeoff.
**Risk:** R1.

**Notes:**
- `DEFAULT_CONFIG` in `config.py` already has `600` (from an earlier edit). The live `config.yaml` currently overrides it to `1500`. Flipping `config.yaml` to `700` is a one-line diff.
- Keep 700, not 600 — the test above showed 600 occasionally cuts mid-sentence pauses.

**Verification:** Dictate a 2-sentence utterance with a natural pause between sentences. Two segments should emerge, not one merged segment. If sentences merge, bump to 900 and re-test.

---

### T_V7: Freeze level bar outside listening state

**File:** `recording_indicator.py`
**Action:** In `_do_update_level`, early-return when `self._current_state != "listening"`. Also reset bar to zero width on state transition *into* listening (so no stale width lingers).
**Risk:** R1.

**Diff:**
```python
def _do_update_level(self, rms: float):
    if self._level_bar is None or self._canvas is None:
        return
    if self._current_state != "listening":
        return                                 # NEW: freeze during transcribing/processing.
    width = min(max(rms, 0.0) / 0.05, 1.0) * 50.0
    cx = _WIN_W // 2
    half = width / 2.0
    self._canvas.coords(self._level_bar, cx - half, 42, cx + half, 45)
    color = _STATE_COLORS.get(self._current_state, "#e0e0e0")
    self._canvas.itemconfig(self._level_bar, fill=color)
```

And in `_do_set_state`, when transitioning to listening, reset the bar:
```python
def _do_set_state(self, state: str):
    prev = self._current_state
    self._current_state = state
    self._stop_pulse()
    self._recolor_mic(_STATE_COLORS[state])
    if state == "transcribing":
        self._start_pulse()
    elif state == "listening" and prev != "listening":
        self._reset_level_bar()                # NEW: clear stale width.
```

**Verification:** Dictate a full session. Bar should visibly drop to zero the moment cloud call begins; reappear when we return to listening. Mic color pulsing orange during transcribe is unchanged.

---

### T_V8: Document the indicator mental model

**File:** `docs/feature-lists/FEATURE_LIST_CLOUD_SPEED_V2.md` (this file)
**Action:** This plan already documents the mental model in "Problem Framing" section 3. No additional ticket — covered inline.
**Risk:** R0.

---

## Risk Tier and Verification Matrix

| Ticket | Risk | Verification |
|---|---|---|
| T_V1: rename + base class | R2 | py_compile + existing OpenRouter smoke still passes |
| T_V2: GroqDictator | R2 | py_compile + unit test for empty-STT + polish-timeout paths |
| T_V3: provider selector | R2 | Start with `groq`, `openrouter`, unknown → all three log paths correct |
| T_V4: smoke test | R1 | pytest green with key, skipped without |
| T_V5: supersede doc | R0 | doc review |
| T_V6: silence 1500→700 | R1 | 2-sentence dictation yields 2 segments |
| T_V7: freeze bar | R1 | Bar drops to 0 on state change; resumes cleanly |
| T_V8: doc inline | R0 | covered in this file |

---

## Failure Modes and Mitigations

| Failure | Impact | Mitigation |
|---|---|---|
| Groq STT times out (>1.0s) | Segment falls back to local | Circuit breaker opens after 3 failures. `stt_timeout` is adjustable in config. |
| Groq polish times out but STT succeeded | Raw unpolished text output | Graceful degradation — partial value beats blank. Log at INFO. |
| Groq free-tier 30 rpm exceeded during heavy session | 429 rate limit | Circuit breaker parses `Retry-After`, opens for that duration. Local fallback for the interval. |
| Provider=groq set but api_key missing | Every segment goes local | Same as today: startup log line, no cloud attempt. |
| OpenRouter users flip to Groq and their key is wrong provider | 401 on first call, breaker opens indefinitely | Startup log `"invalid API key — cascade disabled until restart"` points user to config. |
| Polish model refuses to transcribe-as-text ("I can't do that") | Malformed polish output | System prompt says "Output ONLY the corrected text." Temperature 0.1. Regression caught by T_V4 smoke test. |
| Silence 700ms cuts mid-sentence for slow speakers | Broken flow | User-tunable in config.yaml. Recommend 900ms if affected. |
| Bar freeze feels "dead" during long cloud call | Perceived unresponsiveness | Mic icon pulses orange during transcribe (existing). Elapsed timer keeps ticking. State color is still visible feedback. |

---

## Open Questions

**Q: Should we keep OpenRouter as the default for users without a Groq key?** — **Default: flip to Groq.** Reason: hallucination regression is a correctness bug, not a preference. Users without a Groq key can keep their existing `config.local.yaml` pointing at OpenRouter by setting `provider: openrouter` explicitly. This is a one-line user-side change, documented in config comments.

**Q: Should we default `silence_duration_ms` even lower (500ms) for speed?** — **Default: 700ms.** Reason: 500ms in testing cut natural comma/breath pauses, breaking "new paragraph" commands. 700ms is the stable floor for this user's cadence based on existing sessions. Config-adjustable.

**Q: Should the text-polish model be `llama-3.3-70b-versatile` or `llama-3.1-8b-instant`?** — **Default: 70B.** Reason: polish quality matters for proper-noun / vocabulary bias; 8B occasionally mangles unusual names. 70B at Groq is fast enough (<500ms). User can flip to 8B for maximum speed via `polish_model` config.

**Q: Should we stream the STT result into the polish call as it arrives?** — **No, defer.** Reason: Groq STT is already <500ms; streaming across two calls adds complexity for marginal gain. Revisit only if polish becomes the bottleneck.

**Q: Do we keep the `openai/gpt-audio` code path at all?** — **Yes.** Reason: sustainability — working code, legitimate alternative for users with OpenRouter already set up, cheap insurance against Groq outages. One config line toggles.

**Q: Should the level bar still show RMS during cloud call, just in gray?** — **No — freeze entirely.** Reason: the user's complaint is "the orange bar doesn't match speech." The fix is to make bar motion mean exactly one thing. Greyed motion is still motion; ambiguity returns.

---

## Resume Pack

- **Goal**: Replace OpenRouter audio-chat with Groq two-call (STT + text polish) as default; cut VAD silence 1500→700ms; freeze level bar when not listening; preserve OpenRouter as alternative provider.
- **Current state**: Plan ready. No code changes yet. Log evidence archived in Problem Framing section.
- **First command**: `/run` in a new context, reading this file.
- **First files to open (Phase A start)**: `cloud_dictator.py` (T_V1 rename + base), then create `groq_dictator.py` (T_V2).
- **Pending user action before `/run` finishes**: Obtain a Groq API key at `console.groq.com/keys` and add to `config.local.yaml` under `whisper.cloud.api_key` with `provider: groq`. Existing OpenRouter key can stay as a second block or be kept by setting `provider: openrouter` explicitly.
- **Verification after `/run`**: Restart app, dictate 20 segments over 5 minutes. Expect zero conversational hallucinations, per-segment dictate time <1.0s, felt latency <1.5s from end-of-speech to typed text.
- **If Groq account not yet created**: `/run` still runs Phase A scaffolding (code + config) — only T_V4 smoke test and the manual 20-segment verification are blocked on the key.
