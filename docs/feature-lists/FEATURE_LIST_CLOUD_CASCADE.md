# Feature List: Cloud Dictation via OpenRouter Audio-Chat + Local Fallback + Live Audio Feedback

Date: 2026-04-16
Status: Implementation complete — pending manual verification (T_C6)
Scope: OpenRouter audio-chat primary (transcription + formatting + vocabulary in one call), local faster-whisper + Ollama fallback, live audio-level indicator (delegated)
Owner: Freek

---

## Problem Framing

Three daily-driver gaps surfaced this session:

1. **No live confirmation the mic is hearing sound.** The pill bar shows the "listening" state (white mic icon) but doesn't react to audio. Unlike Win+H, WisprFlow, Dragon — all of which show a live level — this app gives zero feedback between hotkey press and segment completion. User can speak into a dead mic for 30s before discovering it.

2. **Streaming mode has no post-processing — personal diction is weak.** The real user-value gap is *formatting and personal diction* (kids' names, local town, teacher context, contacts, proper nouns). Streaming mode (default) runs `apply_formatting_commands` (regex) and skips Ollama entirely. Vocabulary reaches Whisper only via `initial_prompt` (500-char cap), which is a weak bias — not a reliable fix for unusual names.

3. **No cloud option for faster/better dictation.** Architecture supports only one local `Transcriber`. An OpenRouter chat model with audio input can do transcription + formatting + vocabulary in a single call — directly upgrading what the user cares about most. Cloud enabled by default; local stays as fallback.

**Success criteria:**
- Live level bar moves during recording, stops moving in silence.
- Elapsed timer visible during recording; language badge visible after each segment.
- Per-segment log reads `dictate=X.XXs (cloud|local), total=Y.YYs`.
- With the API key present and online, an OpenRouter audio-chat model returns polished text in <1.5s end-to-end per segment.
- Personal vocabulary (brain terms, proper nouns) is respected in cloud output with no further manual correction.
- When offline or errored, cloud path is skipped (first segment tolerates a short timeout), and local Whisper + local post-processing handles it transparently.
- When rate-limited or erroring, circuit breaker opens and next segments go local immediately.
- No regression in streaming / batch / vocabulary-brain / post-processing flows.
- API key never reaches a tracked file.

---

## Scope

### In Scope

**A. Live audio feedback.** Execute tickets T1–T6 from `FEATURE_LIST_UI_EXPERIENCE.md` Phase 1 verbatim (RMS `on_level` callback, level bar, elapsed timer, language attributes, badge, app wiring). No re-specification — that plan is complete.

**B. Timing instrumentation.** Ensure `_on_speech_segment` and `_stop_and_transcribe` log `dictate=X.XXs (cloud|local), total=Y.YYs`. Extends the UI_EXPERIENCE wiring by one label.

**C. Cloud dictation via OpenRouter audio-chat.** New `CloudDictator` class posting audio + system prompt to OpenRouter `chat/completions` with `input_audio` content; returns polished text in one round-trip. New `CascadeDictator` orchestrating cloud-primary → local-fallback where local = existing Whisper + (streaming: formatting commands | batch: Ollama). Circuit breaker copied from `postprocessor.py`. Config keys for provider, model, credentials, timeout, breaker thresholds. **Default on** once the key is configured in `config.local.yaml`.

**D. Supersede stale planning doc.** Mark `FEATURE_LIST_SPEED_AND_UI.md` as superseded (one-line header change) so `/docs/feature-lists/` stays honest.

### Out of Scope

- **Local model swaps / Parakeet migration.** Measurement first. Only revisit local model choice if cascade + post-processing is still insufficient.
- **Session history / re-paste / tray enrichment.** `FEATURE_LIST_UI_EXPERIENCE.md` Phase 2 — separate plan.
- **Waveform / VU-meter visualization.** Bar is sufficient.
- **Streaming cloud transcription** (WebSocket realtime). Segment-level batch latency (<1.5s) is already acceptable.
- **Multiple cloud providers concurrently.** One cloud provider (OpenRouter). Model is swappable via config.
- **Audio compression (Opus/FLAC).** 16 kHz mono WAV ≈ 1 MB for 30s; upload cost is already a few hundred ms on fiber.
- **Settings UI for cloud toggle.** Config-file + `config.local.yaml` suffices.

---

## Chosen Approach — Sustainability First

### A. Live audio indicator — execute existing plan unchanged

Delegate to `FEATURE_LIST_UI_EXPERIENCE.md` Phase 1 (T1–T6). That plan is well-designed: thread-safe via `root.after()`, natural update rate from sounddevice block cadence (~10–15 Hz), R1/R2 risk profile, zero new dependencies.

Reproducing the design here would be busywork and introduce drift risk. The only extension this plan adds is the `(cloud|local)` label on the timing log (T_C4 below).

**Why this over re-designing:** sustainability tiebreaker — a solved problem stays solved.

### B. Measure before touching local model

Current local config is `distil-large-v3` on `cuda/float16` — the best English-only distilled Whisper variant available. Post-Dutch-drop (2026-04-16), there is no longer a reason to downgrade to `small`. The older `FEATURE_LIST_SPEED_AND_UI.md` recommends `medium → small` to keep Dutch; that rationale is dead.

**Action:** keep the local model as-is. Ensure per-segment timing logs are present (via UI_EXPERIENCE T5 + T_C4's label). If local-path latency dominates when cloud is off, revisit then.

### C. Cloud dictation — unified audio-chat call, no interface break on local path

**Two new modules, existing `Transcriber` and `postprocessor.py` untouched.**

```
transcriber.py          — unchanged
postprocessor.py        — unchanged
cloud_dictator.py       — new: OpenRouter HTTP client, WAV serialization, circuit breaker
cascade_dictator.py     — new: cloud-first → local-fallback orchestrator
```

The cascade exposes a `dictate(audio, *, mode, vocabulary_text, previous_segment, initial_prompt) -> str` method that returns **ready-to-output polished text** (not raw transcription). `app.py` calls this instead of `transcriber.transcribe(...)` + formatting/postprocessing.

**Cloud provider: OpenRouter — `openai/gpt-audio` (default, cheapest)**

- REST endpoint (OpenAI-compatible): `POST https://openrouter.ai/api/v1/chat/completions`
- Auth: `Authorization: Bearer <api_key>` + `HTTP-Referer: https://github.com/freekmetsch/transcriber` + `X-Title: Transcriber`.
- Request body:
  ```json
  {
    "model": "openai/gpt-audio",
    "modalities": ["text"],
    "messages": [
      {"role": "system", "content": "<system prompt: transcription + formatting rules + vocabulary>"},
      {"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": "<base64 wav>", "format": "wav"}}
      ]}
    ],
    "temperature": 0.1
  }
  ```
- Response: `choices[0].message.content` is the polished text.
- Pricing: `openai/gpt-audio` is $32/M audio input tokens + $64/M audio output tokens (but we ask for text-only output so no audio-output tokens). Estimated cost at 30 min/day speech: **~$1.50–$2.50/month**.
- Alternatives configurable via `cloud.model`: `openai/gpt-4o-audio-preview` (~$2–4/month, older), others as OpenRouter adds them.
- Typical latency: ~1–2s for <30s audio. Slightly slower than dedicated STT but acceptable — value comes from combined transcription+formatting+vocab.

**Unified system prompt** (reuse `postprocessor._build_system_prompt()` — same semantics):

```
You are a dictation post-processor. The user dictates in English.

Rules:
1. Transcribe the audio accurately.
2. Add correct punctuation and capitalization.
3. Convert formatting commands to symbols:
   - "comma"/"period" → "," / "." etc.
4. Output ONLY the corrected text. No explanations, no commentary.
5. Apply the following personal vocabulary (prefer these exact spellings):
   <vocabulary_text>

[In streaming mode only:]
6. Previous segment for context (do NOT repeat in output): "<previous_segment>"
```

**Why OpenRouter audio-chat over alternatives:**
- **Matches user preference.** User has an OpenRouter key; one provider to manage.
- **One call does transcription + formatting + vocabulary.** Current streaming mode has no post-processing at all; this is the biggest UX upgrade for the user's stated value driver (names, teacher context, local town).
- **Groq Whisper-turbo (pure STT):** cheaper ($0.60/mo) and faster, but would ONLY speed up transcription. Streaming mode still wouldn't apply diction post-processing. A later two-call design (Groq STT + OpenRouter text) remains a viable future optimization if latency becomes a problem.
- **Free-tier-only alternatives (Deepgram, AssemblyAI):** credit-limited, not sustainable.

**Why local fallback stays mandatory:**
1. **Offline** — laptop anywhere without internet.
2. **Rate limiting / auth errors** — breaker opens, local serves.
3. **Privacy opt-out** — `cloud.enabled: false` disables cloud entirely.
4. **Latency spikes** — 2s timeout triggers fallback rather than hang.

**Local fallback — branches per mode:**
- **Streaming mode** (default): local Whisper → `apply_formatting_commands` (regex). This is exactly the current path — falls back to today's behavior.
- **Batch mode**: local Whisper → `postprocess_text` (Ollama). Exactly today's batch path.

The cascade's local fallback is a thin wrapper over the existing pipeline; no logic moves.

**Circuit breaker** (copy pattern from `postprocessor.py:25-45`):
- Track consecutive failures. After 3 failures, open breaker for 60s cooldown (or `Retry-After` seconds if 429 supplied that header).
- In open state, skip cloud entirely — go straight to local.
- On any success, close breaker.
- On HTTP 401 (invalid key), open indefinitely until next restart; log once.

**Vocabulary in cloud path:** include the full `self._vocabulary_text` in the system prompt (not `initial_prompt`, which is a Whisper-specific bias). `vocabulary_text` is already built by `get_vocabulary_for_llm(self._brain)` and used by `postprocessor.py`. Reuse.

**Language badge (cloud path):** the audio-chat model doesn't return a language field. Since the user's project requirements are English-only as of 2026-04-16, default `last_language = "en"` and `last_language_probability = 1.0` on cloud success. The badge still renders consistently across paths.

### Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| Swap local Whisper model without measuring | Sustainability violation — `distil-large-v3` on GPU is already near-optimal post-Dutch-drop. |
| Groq Whisper (dedicated STT, cheapest) | Doesn't address streaming mode's missing post-processing — the user's main value gap. Future optimization: reconsider Groq STT + OpenRouter chat (two calls) if single-call latency becomes a problem. |
| OpenAI Whisper API direct | Paid ($0.006/min), no perpetual free tier, no advantage over Groq. Not what user asked for. |
| Streaming cloud via WebSocket | Larger scope (connection lifecycle, partial-result reconciliation). Segment batch <1.5s is already fine. |
| Replace `Transcriber` with cascade inline | Fork risk — cleaner to compose via a new class. |
| Run cloud + local in parallel, first-wins | Wastes GPU on the 99% of segments where cloud wins. Sequential with tight timeout is cheaper. |
| Audio compression (Opus/FLAC) | 1 MB WAV for 30s uploads in ~200ms on fiber. Premature optimization. |
| Keep and execute `SPEED_AND_UI` plan | Stale — pre-Dutch-drop rationale would regress accuracy. |
| Add tray-menu toggle for cloud on/off | Config-file toggle is sufficient for v1. One-line future addition. |
| Default cloud off | User explicitly requested cloud-by-default. Startup gracefully handles missing key (logs once, cloud=None). |

---

## Harden Audit

| # | Finding | Severity | Mitigation |
|---|---|---|---|
| 1 | **API key leakage via git** | High | Store only in `config.local.yaml` (`.gitignore`d). Startup sanity check logs a red warning if `api_key` is non-empty in tracked `config.yaml`. |
| 2 | **Cloud timeout blocks segment worker** | Medium | Blocking is contained to one segment's worker thread. 2s timeout + circuit breaker prevents repeat. |
| 3 | **Circuit breaker state shared across threads** | Medium | Protect with `threading.Lock`. Pattern proven in `postprocessor.py`. |
| 4 | **Audio bytes serialization correctness** | Low | Use `soundfile.write(io.BytesIO(), audio, 16000, subtype='PCM_16')` — correct WAV headers, handles float32 → PCM_16 conversion. New dep `soundfile>=0.12.0`, small and well-maintained. |
| 5 | **Vocabulary text exceeds model context** | Low | LLM chat models accept many thousands of tokens. Existing `vocabulary_text` from `get_vocabulary_for_llm` has no hard cap but is small in practice (hundreds of terms max). |
| 6 | **Rate limit (429) mid-session** | Medium | On 429, open breaker for `Retry-After` seconds (default 60s). Segments go local transparently. |
| 7 | **No network / captive portal** | Medium | `requests` connect timeout 0.8s. On connection/DNS failure, breaker opens instantly; first segment takes `timeout + local`, rest are pure local. Cooldown retry every 60s. |
| 8 | **Cloud returns empty or garbage text** | Low | Treat empty response as failure; fall back to local. Log once per occurrence. |
| 9 | **API key accidentally logged** | High | Never log the key. Log `"cloud: key set"` vs `"cloud: key missing"`. Never log request headers. |
| 10 | **Cloud adds user audio to third-party training** | Low | OpenRouter routes to OpenAI — document the privacy posture in config comments. User has explicitly opted in by setting the key. `cloud.enabled: false` provides a zero-data egress mode. |
| 11 | **Local model loaded even when cloud always wins** | Low | Construct both at startup. Lazy-loading local on first cascade miss would introduce a latency spike on the error path. Accept VRAM cost. |
| 12 | **Level bar path interferes with dictation path** | Low | Bar is driven by pre-dictation audio callback; independent of cascade. Non-issue. |
| 13 | **Timing log confusion across paths** | Low | T_C4 labels every line `(cloud\|local)`. Unambiguous. |
| 14 | **Cloud model pricing change** | Low | Model name is configurable (`cloud.model`). User swaps to a cheaper model in one config line. |
| 15 | **Segment context drift between paths** | Low | Cloud: `previous_segment` in system prompt. Local: `initial_prompt=segment_context` to Whisper. Same semantics; cascade passes both. |

---

## Phase Plan

### Phase A: Live feedback (1 context window, ~40 min)

**Goal:** level bar + elapsed timer + language badge + baseline timing logs.
**Risk tier:** R2.
**Files modified:** `recorder.py`, `transcriber.py`, `recording_indicator.py`, `app.py`, `config.py`, `config.yaml`.
**Execution:** tickets T1–T6 from `FEATURE_LIST_UI_EXPERIENCE.md` Phase 1 (see that document).

### Phase B: Cloud dictation cascade (1 context window, ~60 min)

**Goal:** OpenRouter audio-chat cloud-primary + local fallback with circuit breaker.
**Risk tier:** R2.
**Files created:** `cloud_dictator.py`, `cascade_dictator.py`.
**Files modified:** `app.py` (instantiation + `_on_speech_segment` + `_stop_and_transcribe` rewires), `config.py`, `config.yaml`, `requirements.txt`, `FEATURE_LIST_SPEED_AND_UI.md` (supersede header).

---

## Phase A — Execution Tickets

Delegated to `FEATURE_LIST_UI_EXPERIENCE.md` Phase 1 tickets T1–T6. No re-specification. Execute tickets in order. The only addition here is the `(cloud|local)` label on the timing line — deferred to T_C4 in Phase B.

---

## Phase B — Execution Tickets

### T_C1: `cloud_dictator.py`

**File:** new `cloud_dictator.py`
**Action:** OpenRouter chat/completions HTTP client with WAV serialization + base64, timeout, circuit breaker.
**Risk tier:** R2.

**Interface:**
```python
class CloudUnavailable(Exception):
    pass

class CloudDictator:
    def __init__(self, api_key: str, *,
                 model: str = "openai/gpt-audio",
                 base_url: str = "https://openrouter.ai/api/v1",
                 referer: str = "https://github.com/freekmetsch/transcriber",
                 title: str = "Transcriber",
                 timeout: float = 2.0,
                 failure_threshold: int = 3,
                 cooldown_s: float = 60.0):
        ...

    def dictate(self, audio: np.ndarray, *,
                system_prompt: str) -> str:
        """Return polished text from audio. Raises CloudUnavailable if breaker open
        or call fails."""
```

**Notes:**
- Serialize audio via `soundfile.write(io.BytesIO(), audio, 16000, subtype='PCM_16')`; base64-encode the resulting WAV bytes.
- Build one `user` message with a single `input_audio` content block (`format: "wav"`). `modalities: ["text"]`. `temperature: 0.1`.
- Headers: `Authorization: Bearer <key>`, `HTTP-Referer`, `X-Title`, `Content-Type: application/json`.
- Extract text from `choices[0].message.content`. If empty or missing → raise `CloudUnavailable`.
- Breaker state protected by `threading.Lock`. Pattern copied from `postprocessor.py:25-45`.
- On HTTP 401: open breaker indefinitely; log `"cloud: invalid API key — cascade disabled until restart"` once.
- On HTTP 429: parse `Retry-After` (int seconds) and open breaker for that duration, default 60s.
- On connection/timeout/5xx: increment failure count; open breaker after `failure_threshold`.
- Never log the API key. Log `"cloud: key set"` / `"cloud: key missing"` at startup only.
- Connect timeout 0.8s, read timeout = `timeout` from config.

**Verification:** `python -m py_compile cloud_dictator.py`.

---

### T_C2: `cascade_dictator.py`

**File:** new `cascade_dictator.py`
**Action:** Orchestrate cloud → local fallback. Locally branches on mode (streaming vs batch).
**Risk tier:** R1.

**Interface:**
```python
class CascadeDictator:
    def __init__(self, *,
                 cloud: CloudDictator | None,
                 transcriber: Transcriber,
                 pp_config: dict,
                 build_system_prompt):
        """
        build_system_prompt: callable(vocabulary_text, previous_segment) -> str
            — builds the cloud system prompt. Reuses postprocessor helpers.
        """
        self._cloud = cloud
        self._transcriber = transcriber
        self._pp_config = pp_config
        self._build_system_prompt = build_system_prompt
        self.last_language: str = ""
        self.last_language_probability: float = 0.0
        self.last_path: str = "local"

    def dictate(self, audio, *,
                mode: str,                 # "streaming" | "batch"
                vocabulary_text: str,
                previous_segment: str,
                initial_prompt: str | None) -> str:
        if self._cloud is not None:
            try:
                prompt = self._build_system_prompt(vocabulary_text, previous_segment, mode)
                text = self._cloud.dictate(audio, system_prompt=prompt)
                self.last_language = "en"
                self.last_language_probability = 1.0
                self.last_path = "cloud"
                return text
            except CloudUnavailable:
                pass

        # Local fallback
        raw = self._transcriber.transcribe(audio, initial_prompt=initial_prompt)
        self.last_language = self._transcriber.last_language
        self.last_language_probability = self._transcriber.last_language_probability
        self.last_path = "local"
        raw = raw.strip()
        if not raw:
            return ""
        if mode == "streaming":
            from commands import apply_formatting_commands
            return apply_formatting_commands(raw)
        else:  # batch
            from postprocessor import postprocess_text
            return postprocess_text(raw, self._pp_config, vocabulary_text=vocabulary_text)
```

**Notes:**
- If `cloud is None` (disabled or missing key), identical behavior to today's pipeline.
- Exposes `last_path` for the timing log label (T_C4).
- No threading primitives — `dictate()` runs on the existing segment worker thread (single-threaded per session).
- `build_system_prompt` is injected so `postprocessor.py` isn't imported here — composition over coupling.

**Verification:** `python -m py_compile cascade_dictator.py`.

---

### T_C3: System-prompt helper extension

**File:** `postprocessor.py`
**Action:** Add a small helper `build_cloud_system_prompt(vocabulary_text, previous_segment, mode) -> str` that returns the same system prompt used for Ollama, plus a transcription directive for the audio-chat model and an optional "previous segment" context line.
**Risk tier:** R1.

**Additions (do not touch existing `_build_system_prompt`):**
```python
_CLOUD_PROMPT_TEMPLATE = """\
You are a dictation post-processor. The user dictates in English.

Rules:
1. Transcribe the user's audio accurately.
2. Add correct punctuation and capitalization.
3. Convert formatting commands to symbols:
{commands_block}
4. Output ONLY the corrected text. No explanations, no commentary.
{vocabulary_block}{context_block}"""


def build_cloud_system_prompt(vocabulary_text: str = "",
                              previous_segment: str = "",
                              mode: str = "streaming") -> str:
    if vocabulary_text:
        vocab_block = (
            "\n5. The user has these custom vocabulary terms. "
            "Prefer these exact spellings when the audio is ambiguous:\n"
            + vocabulary_text
        )
    else:
        vocab_block = ""
    if mode == "streaming" and previous_segment:
        context_block = (
            f"\n\nPrevious segment (for context, do NOT repeat in output): "
            f"\"{previous_segment}\""
        )
    else:
        context_block = ""
    return _CLOUD_PROMPT_TEMPLATE.format(
        commands_block=_COMMANDS_BLOCK,
        vocabulary_block=vocab_block,
        context_block=context_block,
    )
```

**Verification:** `python -m py_compile postprocessor.py`.

---

### T_C4: App wiring + config + timing label

**Files:** `app.py`, `config.py`, `config.yaml`, `requirements.txt`.
**Action:** Instantiate cascade at startup; rewire segment/batch paths through it; add config keys; add dependency.
**Risk tier:** R2.

**config.py — add under `DEFAULT_CONFIG["whisper"]`:**
```python
"cloud": {
    "enabled": True,
    "provider": "openrouter",
    "model": "openai/gpt-audio",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key": "",
    "referer": "https://github.com/freekmetsch/transcriber",
    "title": "Transcriber",
    "timeout": 2.0,
    "failure_threshold": 3,
    "cooldown_s": 60.0,
},
```

**config.yaml — add under `whisper:`:**
```yaml
  cloud:
    enabled: true
    provider: openrouter
    model: openai/gpt-audio
    # api_key: SET IN config.local.yaml — never commit here
    timeout: 2.0
```

**`config.yaml` startup sanity check:** if `whisper.cloud.api_key` is non-empty in the **tracked** `config.yaml`, log a red warning. Simple detection: re-parse `config.yaml` alone and check the raw value.

**User-side `config.local.yaml` (documented in comments, gitignored):**
```yaml
whisper:
  cloud:
    api_key: "sk-or-v1-..."
```

**app.py — in `TranscriberApp.__init__`** (replace the bare `Transcriber(...)` assignment):
```python
from cloud_dictator import CloudDictator
from cascade_dictator import CascadeDictator
from postprocessor import build_cloud_system_prompt

local_transcriber = Transcriber(
    model_size=self.config["whisper"]["model_size"],
    device=self.config["whisper"]["device"],
    compute_type=self.config["whisper"]["compute_type"],
)

cc = self.config["whisper"]["cloud"]
cloud = None
if cc["enabled"] and cc["api_key"]:
    cloud = CloudDictator(
        api_key=cc["api_key"],
        model=cc["model"],
        base_url=cc["base_url"],
        referer=cc["referer"],
        title=cc["title"],
        timeout=cc["timeout"],
        failure_threshold=cc["failure_threshold"],
        cooldown_s=cc["cooldown_s"],
    )
    log.info("cloud dictation: enabled (provider=%s model=%s)",
             cc["provider"], cc["model"])
elif cc["enabled"]:
    log.info("cloud dictation: enabled in config but api_key missing — using local only")
else:
    log.info("cloud dictation: disabled (local only)")

self.transcriber = local_transcriber  # kept for language badge + UI_EXPERIENCE Phase 1 wiring
self.dictator = CascadeDictator(
    cloud=cloud,
    transcriber=local_transcriber,
    pp_config=self.config["postprocessing"],
    build_system_prompt=build_cloud_system_prompt,
)
```

**app.py — rewire `_on_speech_segment`:** replace the `self.transcriber.transcribe(...)` + `apply_formatting_commands(...)` block with one cascade call:
```python
t_start = time.monotonic()
try:
    t_dictate = time.monotonic()
    result = self.dictator.dictate(
        audio,
        mode="streaming",
        vocabulary_text=self._vocabulary_text,
        previous_segment=self._segment_context,
        initial_prompt=self._segment_context or self._initial_prompt or None,
    )
    result = result.strip()
    t_dictate = time.monotonic() - t_dictate
except Exception:
    log.exception("Segment dictation failed")
    sounds.play_error()
    self._recording_indicator.set_state("listening")
    return

if not result:
    self._recording_indicator.set_state("listening")
    return

log.info("Segment output: %s", result)
t_total = time.monotonic() - t_start
log.info("Segment timing: dictate=%.2fs (%s), total=%.2fs",
         t_dictate, self.dictator.last_path, t_total)
```
Keep segment-context concatenation (`" " + result` when prior context), target-window output, indicator updates, and `_last_transcription` wiring unchanged.

**app.py — rewire `_stop_and_transcribe` (batch):** replace the `Whisper + postprocess_text` block with one cascade call:
```python
t_start = time.monotonic()
t_dictate = time.monotonic()
result = self.dictator.dictate(
    audio,
    mode="batch",
    vocabulary_text=self._vocabulary_text,
    previous_segment="",
    initial_prompt=self._initial_prompt or None,
)
result = result.strip()
t_dictate = time.monotonic() - t_dictate
t_total = time.monotonic() - t_start
log.info("Batch timing: dictate=%.2fs (%s), total=%.2fs",
         t_dictate, self.dictator.last_path, t_total)
# Existing: output_text_to_target, _last_transcription, _show_correction_auto, indicator.
```
Note: the `notify_ollama_fallback` branch (line 416-417) becomes obsolete on the cloud path. Keep it only inside the local-batch branch of `CascadeDictator` if `postprocess_text` returned raw (by comparing before/after in the cascade), or drop it for simplicity. **Default: drop it** — fallback is now less user-relevant with cloud as primary, and the log already records `(local)` path usage. If dropped, remove the call site and the helper in `notifications.py` may still be used by other features; leave the helper alone, just remove the call.

**requirements.txt — add:** `soundfile>=0.12.0`

**Verification:** `python -m py_compile app.py config.py cascade_dictator.py cloud_dictator.py postprocessor.py`; restart with `cloud.enabled: false` (confirm no regression); set key + enable; dictate; confirm OpenRouter call in log.

---

### T_C5: Supersede stale planning doc

**File:** `docs/feature-lists/FEATURE_LIST_SPEED_AND_UI.md`
**Action:** Insert a single status header near the top.
**Risk tier:** R0.

Insert after the existing `Status: Planned` line:
```markdown
Status: Superseded by FEATURE_LIST_CLOUD_CASCADE.md (2026-04-16)
Reason: Model-swap rationale (downgrade `medium → small` to preserve Dutch) is stale after the Dutch-drop decision on 2026-04-16. UI redesign portion is already implemented in `recording_indicator.py`. Per-step timing logs are preserved in FEATURE_LIST_CLOUD_CASCADE.md T_C4.
```
Remove or strike the original `Status: Planned` line.

**Verification:** open the file and confirm the header is present and clear.

---

### T_C6: Phase B integration tests

**Action:** Manual smoke tests across cloud states.
**Risk tier:** R1.

- [ ] `cloud.enabled: false` — dictate (streaming); log shows `dictate=X (local)`. Baseline preserved (Whisper + formatting commands only, no diction upgrade).
- [ ] `cloud.enabled: true` + valid API key — dictate a sentence containing a brain-vocab proper noun; log shows `dictate=X (cloud)`; output has correct formatting AND correct proper-noun spelling with no manual correction needed.
- [ ] Batch mode + cloud — hotkey-trigger without VAD; same cloud upgrade applies.
- [ ] Unplug network — dictate; first segment shows `dictate ≈ 0.8s + local` (connect timeout + local). Next segments (within 60s) show `(local)` without cloud attempt.
- [ ] Reconnect, wait 60s, dictate — breaker closes, cloud is tried again.
- [ ] Set `api_key: "invalid"` — dictate; logs show `"invalid API key"` once, subsequent segments are `(local)` with no retry.
- [ ] Fake-commit `config.yaml` with populated `api_key` → startup warning fires. Empty `api_key` → no warning.
- [ ] Language badge still shows (EN) on cloud path.
- [ ] End-to-end latency stays below 1.5s on cloud path for a ~3s utterance.

---

## Risk Tier and Verification Matrix

| Ticket | Risk | Verification |
|---|---|---|
| Phase A (UI_EXPERIENCE T1–T6) | R2 | That plan's manual test checklist |
| T_C1: CloudDictator | R2 | py_compile + mocked-HTTP unit test if time allows |
| T_C2: CascadeDictator | R1 | py_compile + stubbed unit test |
| T_C3: Cloud system-prompt helper | R1 | py_compile |
| T_C4: Wiring + config + timing label | R2 | py_compile + smoke test (cloud off) + smoke test (cloud on) |
| T_C5: Supersede doc | R0 | Doc review |
| T_C6: Integration | R1 | Full manual test plan |

---

## Failure Modes and Mitigations

| Failure | Impact | Mitigation |
|---|---|---|
| API key committed to `config.yaml` | Key leaked | Startup sanity check logs red warning. `config.local.yaml` is gitignored. |
| Cloud timeout on every segment when offline | Sluggish UX offline | 2.0s read timeout + 0.8s connect timeout + circuit breaker — first segment only. |
| OpenRouter 429 rate limit | Cloud rejects | Parse `Retry-After`, open breaker for that duration. Segments go local transparently. |
| `soundfile` serialization fails | Cloud path always fails | Fall back to local (same code path as any cloud error). Log once per startup. |
| Cloud returns hallucinated formatting or extra commentary | Noisy output | Temperature 0.1 + explicit "Output ONLY the corrected text" rule. Regression tracked in T_C6. |
| User sets `cloud.enabled: true` with empty key | Every segment goes local (no cloud attempt) | `CascadeDictator` checks truthy `api_key` at init; cloud is `None` if missing. One log line at startup. |
| Circuit breaker persists across network recovery | Stale fallback | 60s cooldown — breaker tries again. Worst case: one stale segment on recovery. |
| Cost overrun at heavy usage | Unexpected bill | Default model `openai/gpt-audio` at ~$32/M audio tokens gives ~$2/month for daily-driver use. User-swappable via `cloud.model`. |
| Unified system prompt drifts from `postprocessor._build_system_prompt` | Diction quality regresses when falling back to local | Both helpers share `_COMMANDS_BLOCK` module-level constant. Keep vocabulary block wording identical. |

---

## Open Questions

**Q: Should cloud be enabled by default in `config.yaml`?** **Yes** (user explicit preference). Cloud only activates when `api_key` is also set — empty key falls through to local gracefully, no user-visible error.

**Q: One-call audio-chat vs two-call (STT + LLM)?** **One call.** Reason: directly addresses the streaming-mode diction gap, matches user's OpenRouter choice, cost is acceptable. A future optimization is two-call (Groq STT + OpenRouter chat) if single-call latency is too high — low-risk to add as a third path later.

**Q: Supersede `FEATURE_LIST_SPEED_AND_UI.md` explicitly?** **Yes** (T_C5 — one-line header change).

**Q: Skip Phase A and only do the cloud cascade?** **No — do both**. Cascade doesn't solve "is my mic hearing me?" — orthogonal problems.

**Q: Add tray toggle for cloud on/off?** **No for v1.** Config-file toggle is sufficient.

**Q: What if OpenRouter removes or reprices `openai/gpt-audio`?** `cloud.model` is configurable. Breaker handles transient failures. Doc the fallback options (`openai/gpt-4o-audio-preview`, Gemini audio models, etc.) in `config.yaml` comments.

**Q: Drop or keep the `notify_ollama_fallback` call?** **Drop the call in `_stop_and_transcribe`.** With cloud as primary, Ollama-specific fallback notification is misleading. Leave the helper in `notifications.py` untouched (may be reused).

---

## Cost Estimate

- Typical daily-driver usage: ~30 min of actual speech per day across many short segments.
- Audio tokens at ~25 tokens/sec ≈ 45,000 audio input tokens/day.
- `openai/gpt-audio`: $32/M audio input + $64/M audio output. We request text-only output → text-output tokens priced at standard text rates (~$10/M). Text output is a few hundred tokens/day.
- Daily estimate: `45,000 × $32/1M + ~5,000 × $10/1M ≈ $0.0014 + $0.00005 ≈ $0.05/day`.
- **Monthly: ~$1.50–$2.50** at the default model.
- Alternative `openai/gpt-4o-audio-preview`: ~$2–4/month.

---

## Resume Pack

- **Goal**: live audio indicator + OpenRouter audio-chat cloud dictation with local fallback, cloud-by-default, single-call transcription+formatting+vocab in one round-trip.
- **Current state**: implementation complete, all `py_compile` checks pass. Pending user-side steps: `pip install soundfile`, add OpenRouter API key to `config.local.yaml`, then run the app and execute the T_C6 manual test plan.
- **What's done**:
  - Phase A (T1–T6): level bar + elapsed timer + language badge + RMS callbacks + `last_language` attrs.
  - Phase B (T_C1–T_C5): `cloud_dictator.py`, `cascade_dictator.py`, `postprocessor.build_cloud_system_prompt`, full `app.py` rewire, config schema + YAML, `requirements.txt`, `FEATURE_LIST_SPEED_AND_UI.md` superseded.
- **Next manual steps for user**:
  1. `pip install soundfile` (requirements.txt already lists it).
  2. Create or edit `config.local.yaml` and add:
     ```yaml
     whisper:
       cloud:
         api_key: "sk-or-v1-..."
     ```
  3. Launch app and run through T_C6 checklist.
- **Dependencies**: `soundfile>=0.12.0` (new, WAV serialization). OpenRouter API key (user action, `config.local.yaml`).

---

## Superseded / Related Documents

- `FEATURE_LIST_SPEED_AND_UI.md` — **Supersede** (T_C5 applies). UI redesign portion already implemented in `recording_indicator.py`; model-swap rationale stale post-Dutch-drop.
- `FEATURE_LIST_UI_EXPERIENCE.md` — **Depend**. Phase 1 (T1–T6) is Phase A of this plan.
- `FEATURE_LIST_OLLAMA_FALLBACK.md` — **Pattern source**. Circuit breaker in `postprocessor.py` is the model for T_C1.
