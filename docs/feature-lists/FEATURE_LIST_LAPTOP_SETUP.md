# Feature List: Laptop Setup — Remote LLM via Tailscale

Date: 2026-04-15
Status: Planned
Scope: Run the transcriber on the laptop, connected to the desktop PC's Ollama via Tailscale
Owner: Freek

---

## Problem Framing

The transcriber codebase is complete through Phase 3.5 (vocabulary brain + UX polish). It has been developed on the desktop PC (NVIDIA GPU, 16GB VRAM, Ollama running locally). Now the user wants to also run it on their laptop.

The laptop doesn't need its own Ollama — the desktop PC's Ollama is already accessible over Tailscale (the same VPN mesh used by the `second-brain` Telegram bot). The laptop just needs to:
1. Run Whisper locally for transcription (CPU mode with a smaller model)
2. Connect to the desktop's Ollama at `100.103.79.95:11434` via Tailscale for post-processing
3. Share the same vocabulary brain (via the committed `brain_export.json`)

**No desktop-side setup needed** — Ollama is already listening on `0.0.0.0:11434`, firewall rules are in place, and Tailscale is running.

---

## Architecture

```
┌─────────────────────────────┐       Tailscale        ┌─────────────────────────┐
│     LAPTOP (laptopfreek)    │  ───HTTP POST─────────► │  DESKTOP (desktop-4ej)  │
│     100.69.232.50           │  100.103.79.95:11434    │  100.103.79.95          │
│                             │                         │                         │
│  Whisper (CPU, medium/small)│                         │  Ollama (qwen2.5:3b)    │
│  Vocabulary brain (SQLite)  │  ◄──JSON response────── │  NVIDIA GPU, 16GB VRAM  │
│  Correction UI              │                         │                         │
└─────────────────────────────┘                         └─────────────────────────┘
```

**Same pattern as the `second-brain` bot** (`100.84.198.95`) which already reaches this Ollama instance over Tailscale.

---

## Prerequisites (verify before starting)

- [ ] Laptop connected to Tailscale (`tailscale status` shows `laptopfreek`)
- [ ] Desktop PC on and running Ollama (`curl http://100.103.79.95:11434/api/tags` works)
- [ ] Python 3.12+ installed on the laptop
- [ ] Physical microphone (USB, headset, or built-in laptop mic)

---

## Phase L1: Laptop — Environment Setup

**Goal**: Python venv with all dependencies, Whisper working on CPU.
**Risk tier**: R0
**Estimated effort**: S (~15 min, mostly waiting for downloads)

### Steps

- [ ] **Clone or pull the repo**
  ```bash
  cd C:\Users\metsc\Repositories\transcriber
  git pull
  ```

- [ ] **Create Python venv and install dependencies**
  ```bash
  python -m venv venv
  venv\Scripts\activate
  pip install -r requirements.txt
  pip install pytest
  ```

- [ ] **Check if CUDA is available** (likely not on the laptop)
  ```bash
  python -c "import ctranslate2; print('CUDA devices:', ctranslate2.get_cuda_device_count())"
  ```

- [ ] **Run test suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: 59/59 passing.

### Verification
- All tests pass

---

## Phase L2: Laptop — Create Local Config

**Goal**: Configure Whisper for CPU and Ollama for the desktop's Tailscale IP.
**Risk tier**: R0
**Estimated effort**: S (~2 min)

The codebase supports `config.local.yaml` — a gitignored file that overrides `config.yaml` with machine-specific settings. This avoids git conflicts between desktop and laptop.

### Steps

- [ ] **Create `config.local.yaml` on the laptop**
  ```yaml
  # Laptop overrides — Whisper on CPU, Ollama on desktop via Tailscale
  whisper:
    model_size: medium
    device: cpu
    compute_type: int8

  postprocessing:
    base_url: http://100.103.79.95:11434
    timeout: 15
  ```

- [ ] **Verify Ollama connectivity**
  ```bash
  python -c "from postprocessor import ollama_health_check; print('OK' if ollama_health_check('http://100.103.79.95:11434') else 'FAIL')"
  ```

### Model Size Guide (CPU mode)

| Model | RAM Usage | Relative Speed (CPU) | Accuracy |
|---|---|---|---|
| `small` | ~500MB | Fast (~3-5s per utterance) | Good for short phrases |
| `medium` | ~1.5GB | Moderate (~5-10s per utterance) | Good balance — **recommended** |
| `large-v3` | ~3GB | Slow (~15-30s per utterance) | Best accuracy, but painful on CPU |

Start with `medium`. Drop to `small` if latency is too high.

### Verification
- Health check returns "OK"

---

## Phase L3: Laptop — Vocabulary Import

**Goal**: Import the seeded vocabulary from the desktop.
**Risk tier**: R0
**Estimated effort**: S (~2 min)

### Steps

- [ ] **Import the vocabulary export** (committed to repo)
  ```bash
  python vocab.py import brain_export.json
  python vocab.py list
  python vocab.py stats
  ```
  Expected: 7 terms (Freek, Claude Code, Anthropic, HeliBoard, Syncthing, Ollama, whisper).

### Verification
- `python vocab.py stats` shows imported terms

---

## Phase L4: First Run and Smoke Test

**Goal**: End-to-end dictation working, with post-processing on the desktop via Tailscale.
**Risk tier**: R1
**Estimated effort**: S (~15 min, includes first Whisper model download)

### Steps

- [ ] **Verify microphone is detected**
  ```bash
  python -c "import sounddevice as sd; print([d['name'] for d in sd.query_devices() if d['max_input_channels'] > 0])"
  ```

- [ ] **First run** (Whisper `medium` downloads automatically, ~1.5GB, one-time)
  ```bash
  python app.py
  ```
  Watch the console for:
  - "Loading Whisper model 'medium' on cpu..."
  - "Model loaded"
  - "Ollama reachable at http://100.103.79.95:11434"
  - "Transcriber ready. Hold ctrl+shift+space to dictate."

- [ ] **Test 1: English dictation**
  - Open Notepad, hold Ctrl+Shift+Space, say "Hello, my name is Freek"
  - Verify: text appears, "Freek" correct, correction window auto-shows

- [ ] **Test 2: Dutch dictation**
  - Say "Dit is een test van de transcriber"
  - Verify: Dutch preserved, not translated

- [ ] **Test 3: Mixed Dutch+English**
  - Say "Ik gebruik Claude Code voor mijn project"
  - Verify: both languages preserved

- [ ] **Test 4: Formatting commands**
  - Say "Hello comma this is a test period new line next sentence"

- [ ] **Test 5: Correction flow**
  - Press Ctrl+Shift+C, edit text, press Enter

- [ ] **Test 6: Desktop offline fallback**
  - Disable Tailscale or turn off desktop
  - Dictate — should still work with raw Whisper text (no post-processing)
  - Reconnect — post-processing resumes automatically

### Verification
- All tests pass
- Post-processing is visibly happening (formatted output, not raw)
- Fallback works when desktop is unreachable

---

## Phase L5: Config Tuning (if needed)

### If Whisper latency is too high on CPU
- Try `model_size: small` in `config.local.yaml`
- Set `OMP_NUM_THREADS` to match your CPU core count:
  ```bash
  set OMP_NUM_THREADS=8
  python app.py
  ```

### If microphone is the wrong device
- Set `audio.device` in `config.local.yaml` to the device index from `sounddevice.query_devices()`

### If correction window is annoying
- Add `brain.correction_mode: hotkey` to `config.local.yaml`

---

## Known Issues from Desktop Testing

1. **"new line" command sometimes sent to LLM literally** — may not be processed before post-processing.
2. **LLM sometimes translates Dutch to English** — qwen2.5:3b occasionally ignores the "do NOT translate" instruction.
3. **"Claude Code" sometimes becomes "Claude Coat"** — phonetic hint may need a stronger prompt.

These are prompt-tuning issues, not setup blockers.

---

## Resume Pack

**Goal**: Run the transcriber on the laptop, using the desktop's Ollama via Tailscale for post-processing.

**Current state**: Codebase ready. `config.local.yaml` support added and gitignored. Desktop Ollama verified reachable at `100.103.79.95:11434` via Tailscale.

**Desktop-side setup needed**: None. Ollama already on `0.0.0.0:11434`, firewall rules in place, Tailscale running.

**What to do on the laptop** (Phases L1–L4):
1. `git pull` → create venv → install deps → run tests
2. Create `config.local.yaml` with CPU whisper + `base_url: http://100.103.79.95:11434`
3. `python vocab.py import brain_export.json`
4. `python app.py` → smoke test

**Estimated total time**: ~25 min (mostly Whisper model download).
