# Feature List: Seamless Ollama Fallback

Date: 2026-04-15
Status: Reviewing
Scope: Add primary→fallback Ollama routing so post-processing never silently degrades to raw Whisper text
Owner: Freek

---

## Problem Framing

The transcriber uses Ollama to post-process raw Whisper output — adding punctuation, formatting commands, and vocabulary corrections. Currently, if Ollama is unreachable, the system silently falls back to raw Whisper text: no punctuation, no formatting, no vocabulary corrections. The user has said this is unacceptable.

With the laptop using the desktop's Ollama over Tailscale (`100.103.79.95:11434`), there are realistic scenarios where the remote endpoint is unavailable:
- Desktop PC is off or sleeping
- Tailscale is disconnected
- Desktop's Ollama process crashed or is restarting
- Network hiccup during a dictation

The laptop also has a local Ollama with `qwen2.5:3b` already pulled. This should serve as an automatic fallback so the user **always** gets formatted, post-processed text.

**Non-goal**: This is not about load balancing or choosing the "best" endpoint. It's a simple primary→fallback chain for reliability.

---

## Architecture

```
dictation audio
     │
     ▼
  Whisper (local GPU, large-v3)
     │
     ▼ raw text
  postprocess_text()
     │
     ├──► Try PRIMARY (remote desktop: 100.103.79.95:11434)
     │         │
     │    success? ──► return formatted text ✓
     │         │
     │    fail (timeout/error/unreachable)
     │         │
     │         ▼
     ├──► Try FALLBACK (local laptop: localhost:11434)
     │         │
     │    success? ──► return formatted text ✓
     │         │
     │    fail
     │         │
     │         ▼
     └──► return raw text (both endpoints down — extremely rare)
```

### Circuit Breaker (latency optimization)

Without optimization, every dictation when the desktop is off pays a ~1s connect-timeout penalty before trying local. A lightweight circuit breaker eliminates this:

```
Remote succeeds  →  mark healthy
Remote fails     →  mark failed, record timestamp
Next dictation:
  - If remote failed < 60s ago  →  skip remote, go straight to local
  - If remote failed > 60s ago  →  probe remote again (maybe it recovered)
```

This means: desktop goes off → first dictation has ~1s extra delay → all subsequent go straight to local → when desktop comes back, auto-recovers within 60s.

---

## Chosen Approach: Sequential fallback with circuit breaker

**Why this approach:**
- Minimal code change (~50 lines across 3 files)
- Zero VRAM cost on laptop when desktop is available (Ollama only loads model on demand)
- Backward compatible — desktop config unchanged, no `fallback_url` means old behavior
- Same pattern works for future mobile client (primary=remote, no fallback)
- Circuit breaker prevents latency penalty when remote is known-down

### Rejected Alternatives

1. **Parallel requests (fire both, take first)** — Rejected: doubles GPU load on laptop for every dictation, complex cancellation, wastes resources when remote is working fine.

2. **Background health-check polling thread** — Rejected: adds thread management complexity, polling is wasteful when the circuit breaker achieves the same result with zero overhead.

3. **Local-only Ollama (no remote)** — Rejected: wastes 2GB of the laptop's 8GB VRAM permanently, gains nothing when desktop is available and Tailscale latency is <10ms.

4. **Raw text fallback with notification (current behavior)** — Rejected: user explicitly said unformatted text is unacceptable. The notification doesn't fix the problem, it just announces it.

---

## Scope

### In scope
- `fallback_url` config option in postprocessing section
- Sequential try-primary-then-fallback in `postprocess_text()`
- Circuit breaker for latency optimization
- Aggressive connect timeout (1s) for fast failure detection
- Updated startup health check logging for both endpoints
- Updated notification: only warn when BOTH endpoints fail
- `config.local.yaml` creation on laptop
- New `tests/test_postprocessor.py` with full coverage
- Update `FEATURE_LIST_LAPTOP_SETUP.md` Phase L2 to reflect new config

### Out of scope
- Load balancing / endpoint selection based on latency
- Auto-discovery of Ollama instances
- Mobile client setup (future feature list)
- Changing the Ollama model or prompt (separate concern)

---

## Phase 1: Postprocessor Fallback Logic

**Goal**: `postprocess_text()` tries primary, falls back to local, only returns raw text if both fail.
**Risk tier**: R1 (changes the core post-processing path)
**Estimated effort**: S (~30 min)
**Context window**: Single — all changes are small and interdependent.

### Ticket 1.1: Add `fallback_url` to config defaults

**File**: `config.py`
**Change**: Add `"fallback_url": None` to `DEFAULT_CONFIG["postprocessing"]`.

No other config.py changes needed — `_deep_merge` already handles new keys from `config.local.yaml`.

### Ticket 1.2: Implement fallback logic in postprocessor

**File**: `postprocessor.py`
**Changes**:

1. **Split timeout into connect + read**: Change `_call_ollama` to use `timeout=(connect_timeout, read_timeout)` instead of a single `timeout` value. Hardcode connect timeout at 1s (fast failure detection). Use the config `timeout` value as read timeout.

2. **Add circuit breaker state** (module-level):
   ```
   _remote_healthy: bool = True
   _last_remote_failure: float = 0.0
   _CIRCUIT_COOLDOWN: int = 60  # seconds
   ```

3. **Add `_is_remote_available()` helper**: Returns `True` if remote hasn't failed recently (within cooldown).

4. **Update `postprocess_text()`** logic:
   ```
   if not enabled: return raw_text

   fallback_url = pp_config.get("fallback_url")

   # Try primary (skip if circuit breaker is open AND fallback exists)
   if fallback_url is None or _is_remote_available():
       result = _call_ollama(..., base_url=primary_url)
       if result is not None:
           _mark_remote_healthy()
           return result
       if fallback_url is not None:
           _mark_remote_failed()

   # Try fallback
   if fallback_url:
       result = _call_ollama(..., base_url=fallback_url)
       if result is not None:
           return result

   # Both failed
   log.warning("All Ollama endpoints failed")
   return raw_text
   ```

5. **Key behaviors**:
   - No `fallback_url` configured → identical to current behavior (backward compatible)
   - `fallback_url` configured, primary up → uses primary, zero overhead
   - `fallback_url` configured, primary down → 1s delay on first failure, then instant fallback
   - Both down → raw text (should be extremely rare — local Ollama is always available)

### Ticket 1.3: Update startup health check in app.py

**File**: `app.py`, method `TranscriberApp.run()`
**Change**: Check and log status of both primary and fallback URLs at startup.

```
Current:
  "Ollama reachable at http://..."
  or "Ollama not reachable at http://... — post-processing will fall back to raw text"

New:
  "Ollama primary: http://100.103.79.95:11434 ✓"
  "Ollama fallback: http://localhost:11434 ✓"
  or "Ollama primary: http://100.103.79.95:11434 ✗ (will use fallback)"
  or "Ollama: no endpoints reachable — post-processing will use raw text" (only if both down)
```

### Ticket 1.4: Update notification for both-down case

**File**: `notifications.py`
**Change**: Update `notify_ollama_fallback()` message. This function is only called in `app.py` when postprocessing returned raw text. With fallback in place, this means BOTH endpoints failed — update the message accordingly:

```
Current: "Ollama not reachable — using raw transcription text"
New:     "All Ollama endpoints unreachable — using raw transcription text"
```

No change to the once-per-session guard — still only fires once.

### Ticket 1.5: Create laptop `config.local.yaml`

**File**: `config.local.yaml` (gitignored, laptop only)
**Content**:
```yaml
# Laptop overrides — GPU Whisper, remote Ollama with local fallback
whisper:
  model_size: large-v3
  device: cuda
  compute_type: float16

postprocessing:
  base_url: http://100.103.79.95:11434
  fallback_url: http://localhost:11434
  timeout: 10
```

### Ticket 1.6: Write tests

**File**: `tests/test_postprocessor.py` (new)
**Tests**:

1. `test_primary_succeeds` — primary returns result, fallback not called
2. `test_primary_fails_fallback_succeeds` — primary returns None, fallback returns result
3. `test_both_fail_returns_raw` — both return None, raw text returned
4. `test_no_fallback_configured` — fallback_url is None, primary fails → raw text (backward compat)
5. `test_disabled_returns_raw` — enabled=False → raw text, nothing called
6. `test_circuit_breaker_skips_remote` — after primary failure, next call skips primary within cooldown
7. `test_circuit_breaker_resets_on_success` — successful primary call resets circuit breaker
8. `test_circuit_breaker_probes_after_cooldown` — after cooldown expires, primary is tried again

All tests mock `_call_ollama` via `unittest.mock.patch` — no real HTTP calls.

### Ticket 1.7: Update laptop setup feature list

**File**: `docs/feature-lists/FEATURE_LIST_LAPTOP_SETUP.md`
**Change**: Update Phase L2 config example to include `fallback_url`. Update Phase L4 Test 6 (desktop offline fallback) to reflect that local Ollama takes over instead of raw text.

---

## Verification Matrix

| Scenario | Expected Result | How to Verify |
|---|---|---|
| Desktop on, Tailscale connected | Uses remote Ollama, formatted text | Normal dictation, check log for primary URL |
| Desktop off, local Ollama running | Falls back to local, formatted text | Turn off desktop, dictate, check log for "fallback" |
| Desktop off, second dictation | Skips remote (circuit breaker), instant local | Dictate twice with desktop off, no 1s delay on second |
| Desktop comes back after being off | Auto-recovers within 60s | Turn desktop back on, wait ~60s, dictate |
| Both endpoints down | Raw text returned, notification fires | Stop local Ollama + disconnect Tailscale |
| Desktop-only (no fallback configured) | Current behavior unchanged | Run on desktop with default config.yaml |
| All 59 existing tests | Still pass | `python -m pytest tests/ -v` |
| New postprocessor tests | All pass | `python -m pytest tests/test_postprocessor.py -v` |

---

## Failure Modes and Mitigations

| Failure Mode | Impact | Mitigation |
|---|---|---|
| Connect timeout too aggressive (1s) | Slow networks time out falsely, causing unnecessary fallback | 1s is generous for LAN/Tailscale (<10ms RTT). If needed, make configurable later |
| Circuit breaker cooldown too long (60s) | User waits up to 60s to use desktop after it comes back | 60s is a reasonable balance. User can restart app for immediate reset |
| Circuit breaker cooldown too short | Keeps probing a dead endpoint, adding 1s latency | 60s avoids this. At worst, one probe every 60s |
| Local Ollama not running on laptop | Fallback also fails, raw text | Startup health check warns clearly. User starts Ollama |
| Both endpoints serve different model versions | Inconsistent formatting quality | Both use same model (qwen2.5:3b) and same prompt. Non-issue |
| Module-level circuit breaker state and thread safety | Race condition on `_remote_healthy` flag | Python GIL protects simple bool/float writes. Single writer (dictation thread). Safe |
| `config.local.yaml` missing `fallback_url` | No fallback, current behavior | This IS the backward-compatible default. Not a failure |

---

## Harden Audit

### Checked, no issues:
- **Thread safety**: `_call_ollama` runs in daemon thread via `_stop_and_transcribe`. `requests.Session` is thread-safe. Circuit breaker state is single-writer (GIL-protected). Safe.
- **Backward compatibility**: No `fallback_url` in config → `pp_config.get("fallback_url")` returns `None` → old code path. Zero risk to desktop setup.
- **Error surface**: `_call_ollama` already catches `ConnectionError`, `Timeout`, `HTTPError`, and generic `Exception`. Fallback logic wraps around this — no new exception paths.
- **Config merge**: `_deep_merge` in config.py handles the new `fallback_url` key automatically.
- **VRAM impact**: Local Ollama loads model on demand, unloads after 5min idle. When desktop is available, local Ollama uses zero VRAM.

### Findings to address:
1. **Connect timeout is currently bundled with read timeout**: `_call_ollama` passes `timeout=10` to requests, which applies to both connect and read. Must split to `timeout=(1, 10)` for fast failure detection. *Addressed in Ticket 1.2.*
2. **`notify_ollama_fallback()` message is misleading with fallback**: Says "using raw transcription text" but with fallback, raw text only happens when BOTH fail. *Addressed in Ticket 1.4.*

---

## Resume Pack

**Goal**: Add primary→fallback Ollama routing so the user always gets post-processed text, regardless of which machine is available.

**Current state**: Implementation complete. All code changes made and verified.

**What was changed**:
- `config.py` — added `fallback_url: None` default
- `postprocessor.py` — circuit breaker + primary→fallback chain (~40 lines added)
- `app.py` — dual endpoint health check at startup
- `notifications.py` — updated message for both-down case
- `config.local.yaml` — created with GPU whisper + remote primary + local fallback (gitignored)
- `tests/test_postprocessor.py` — 8 new tests (fallback chain + circuit breaker)
- `docs/feature-lists/FEATURE_LIST_LAPTOP_SETUP.md` — updated Phase L2 config + L4 Test 6

**Verification**: 67/67 tests passing (59 existing + 8 new). `py_compile` clean on all changed files.

**Pending**: Manual smoke test on laptop with desktop on/off scenarios.

---

## Open Questions (all resolved)

**Q: Should the circuit breaker cooldown (60s) be configurable?**
Resolved: No — hardcoded at 60s. Can revisit if needed.

**Q: Should the app log when it falls back from remote to local?**
Resolved: Yes, at INFO level. Implemented.

**Q: Should there be a tray menu indicator showing which Ollama endpoint is active?**
Deferred: Out of scope for this feature list — separate UI enhancement.

**Q: With laptop having RTX 5060 + CUDA, should we use large-v3 or medium for Whisper?**
Resolved: `large-v3` on CUDA. Config reflects this.
