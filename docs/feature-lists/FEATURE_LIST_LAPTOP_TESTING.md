# Feature List: Laptop Testing & Validation

Date: 2026-04-15
Status: Planned
Scope: Validate transcriber on laptop — toggle hotkey, paste output, Ollama fallback, circuit breaker
Owner: Freek

---

## Problem Framing

The transcriber is now running on the laptop with:
- Whisper on CPU (`medium` model, `int8`) — CUDA blocked by missing `cublas64_12.dll`
- Remote Ollama (desktop via Tailscale) with local Ollama fallback
- Toggle hotkey (Ctrl+Shift+Space) with 500ms debounce
- `config.local.yaml` in place (gitignored)

First test run revealed:
1. Toggle hotkey rapid-fired without debounce — **fixed** (commit `88b40fd`)
2. Transcription succeeded but text didn't paste into Notepad — needs investigation
3. CUDA not available on laptop — needs `cublas64_12.dll` (CUDA Toolkit 12.x)

This feature list is a structured test plan to validate everything works end-to-end.

---

## Current Laptop Config

`config.local.yaml` (gitignored):
```yaml
whisper:
  model_size: medium
  device: cpu
  compute_type: int8

postprocessing:
  base_url: http://100.103.79.95:11434
  fallback_url: http://localhost:11434
  timeout: 10
```

---

## Phase T1: Basic Recording & Paste

**Goal**: Verify toggle hotkey works cleanly and text pastes into the active window.
**Risk tier**: R1
**Estimated effort**: S (~10 min)

### Steps

- [ ] **Start the app**
  ```bash
  cd C:\Users\metsc\Cloned_Repositories\transcriber
  python app.py
  ```
  Confirm in console:
  - `Ollama primary: http://100.103.79.95:11434` (checkmark or X)
  - `Ollama fallback: http://localhost:11434` (checkmark)
  - `Hotkey registered: ctrl+shift+space (toggle)`
  - `Transcriber ready.`

- [ ] **Test 1: Toggle starts/stops cleanly**
  - Open Notepad, click in it
  - Press Ctrl+Shift+Space once — console shows "Recording started (toggle)" (only once, no rapid-fire)
  - Speak a sentence
  - Press Ctrl+Shift+Space again — console shows "Recording stopped (toggle)" (only once)
  - Expected: one clean start, one clean stop

- [ ] **Test 2: Text pastes into Notepad**
  - After Test 1's recording stops, watch for "Output: ..." in console
  - Expected: text appears in Notepad via Ctrl+V paste
  - **If paste fails**: check if Notepad still has focus when paste fires. Try with a longer pause between stop and paste.

- [ ] **Test 3: Post-processing is active**
  - Dictate: "hello comma this is a test period"
  - Expected output: "Hello, this is a test." (punctuation added, commands converted)
  - If output matches raw text exactly (no punctuation), Ollama connection failed

### Troubleshooting: Paste Not Working

If transcription appears in console but not in Notepad:

1. **Focus issue**: The Ctrl+Shift+Space hotkey might steal focus from Notepad. Try: dictate, wait for "Output:" in console, then manually Ctrl+V in Notepad — if the text is there, the clipboard copy works but the paste timing is off.

2. **pyautogui blocked**: Some Windows security settings block `pyautogui.hotkey("ctrl", "v")`. Run in elevated terminal (Run as Administrator).

3. **Clipboard race**: The 50ms delay before paste might not be enough. If needed, increase `time.sleep(0.05)` to `time.sleep(0.15)` in `output.py` line 33.

---

## Phase T2: Ollama Fallback

**Goal**: Verify fallback from remote to local Ollama works seamlessly.
**Risk tier**: R1
**Estimated effort**: S (~10 min)
**Prerequisite**: Phase T1 passing (paste works)

### Steps

- [ ] **Test 4: Remote Ollama working**
  - Desktop PC on, Tailscale connected
  - Dictate something, check console log
  - Expected: no "using fallback" message — primary endpoint used

- [ ] **Test 5: Fallback to local**
  - Disconnect Tailscale on laptop (or turn off desktop)
  - Dictate something
  - Expected: console shows "Primary Ollama unavailable, using fallback at http://localhost:11434"
  - Expected: text is still formatted (not raw Whisper output)

- [ ] **Test 6: Circuit breaker skips remote**
  - With desktop still off, dictate a second time within 60s
  - Expected: no 1s delay — goes straight to local fallback
  - Console should NOT show a new "Ollama not reachable" warning for primary

- [ ] **Test 7: Auto-recovery**
  - Reconnect Tailscale (or turn desktop back on)
  - Wait ~60s (circuit breaker cooldown)
  - Dictate again
  - Expected: console shows "Circuit breaker closed — remote recovered"
  - Primary endpoint used again

- [ ] **Test 8: Both endpoints down**
  - Stop local Ollama (`taskkill /F /IM ollama.exe`) AND disconnect Tailscale
  - Dictate something
  - Expected: raw Whisper text (no punctuation), notification fires: "All Ollama endpoints unreachable"
  - Restart Ollama: `ollama serve` (in separate terminal)

---

## Phase T3: Edge Cases

**Goal**: Validate correction UI, vocabulary, and known quirks.
**Risk tier**: R0
**Estimated effort**: S (~10 min)
**Prerequisite**: Phase T1 passing

### Steps

- [ ] **Test 9: Correction window auto-shows**
  - After a dictation, correction window should appear (auto mode, 8s timeout)
  - Edit text, press Enter — correction logged

- [ ] **Test 10: Vocabulary terms recognized**
  - Say "I'm using Claude Code by Anthropic"
  - Expected: "Claude Code" and "Anthropic" spelled correctly (from vocab brain)

- [ ] **Test 11: Dutch dictation**
  - Say "Dit is een test van de transcriber"
  - Expected: Dutch preserved, not translated to English

- [ ] **Test 12: Mixed Dutch+English**
  - Say "Ik gebruik Claude Code voor mijn project"
  - Expected: both languages preserved in single output

---

## Phase T4: CUDA Setup (Optional — Performance Upgrade)

**Goal**: Get faster-whisper running on GPU instead of CPU.
**Risk tier**: R1
**Estimated effort**: M (~30 min, mostly downloads)

The laptop has an RTX 5060 (8GB VRAM) but faster-whisper needs `cublas64_12.dll` from the CUDA Toolkit.

### Steps

- [ ] **Check current CUDA status**
  ```bash
  python -c "import ctranslate2; print('CUDA devices:', ctranslate2.get_cuda_device_count())"
  nvidia-smi
  ```

- [ ] **Install CUDA Toolkit 12.x** (if not present)
  - Download from: NVIDIA CUDA Toolkit (match the version ctranslate2 expects)
  - Or install via pip: `pip install nvidia-cublas-cu12` (lighter alternative)

- [ ] **Verify CUDA works**
  ```bash
  python -c "import ctranslate2; print('CUDA devices:', ctranslate2.get_cuda_device_count())"
  ```
  Expected: `CUDA devices: 1`

- [ ] **Update config.local.yaml**
  ```yaml
  whisper:
    model_size: large-v3
    device: cuda
    compute_type: float16
  ```

- [ ] **Test GPU transcription**
  - Restart app, dictate — should be noticeably faster than CPU
  - VRAM budget: ~3GB Whisper + 2GB Ollama (when loaded) = 5GB of 8GB

---

## Resume Pack

**Goal**: Validate transcriber on laptop — toggle hotkey, paste, Ollama fallback, circuit breaker.

**Current state**: App runs, toggle and fallback code are committed. First test showed rapid-fire toggle (fixed) and paste not reaching Notepad (needs investigation).

**What's ready**:
- `config.local.yaml` on laptop with CPU whisper + remote/local Ollama
- Toggle hotkey with 500ms debounce (commit `88b40fd`)
- Ollama fallback with circuit breaker (commit `592852a`)
- Local Ollama running with `qwen2.5:3b`

**Start command**: `python app.py`

**First focus**: Phase T1 — get paste working in Notepad. If paste fails, check troubleshooting section.

**Open items after testing**:
- CUDA setup (Phase T4) for faster transcription
- Better launch UX (separate feature — shortcut/startup/exe wrapper)
