# Feature List: Laptop Setup — First Run on NVIDIA Desktop

Date: 2026-04-15
Status: Planned
Scope: Set up the transcriber on the Windows laptop with NVIDIA GPU for daily use
Owner: Freek

---

## Problem Framing

The transcriber codebase is complete through Phase 3.5 (vocabulary brain + UX polish). It has never been run end-to-end on real hardware with a real microphone. The laptop has an NVIDIA GPU with CUDA support — the primary target platform.

This feature list covers everything needed to go from `git pull` to a working voice-to-text system on the laptop.

---

## Prerequisites (verify before starting)

- [ ] Windows laptop with NVIDIA GPU (CUDA-capable)
- [ ] Physical microphone (USB, headset, or built-in laptop mic)
- [ ] Python 3.12+ installed
- [ ] Internet connection (for model downloads on first run)

---

## Phase L1: Environment Setup

**Goal**: Python venv with all dependencies, CUDA working.
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
  pip install pytest  # for running tests
  ```

- [ ] **Verify CUDA is available to CTranslate2**
  ```bash
  python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"
  ```
  Expected: `1` (or more). If `0`, CUDA toolkit needs installing.

- [ ] **Install CUDA Toolkit if needed**
  - Download from https://developer.nvidia.com/cuda-toolkit
  - Only needed if the above check returns 0
  - Restart after install

- [ ] **Run test suite**
  ```bash
  python -m pytest tests/ -v
  ```
  Expected: 59/59 passing.

### Verification
- `ctranslate2.get_cuda_device_count()` returns >= 1
- All tests pass

---

## Phase L2: Ollama Setup

**Goal**: Local LLM post-processing ready.
**Risk tier**: R0
**Estimated effort**: S (~10 min)

### Steps

- [ ] **Install Ollama** (if not already installed)
  - Download from https://ollama.com/download
  - Or via winget: `winget install Ollama.Ollama`

- [ ] **Start Ollama and pull the post-processing model**
  ```bash
  ollama serve          # if not already running
  ollama pull qwen2.5:3b
  ```

- [ ] **Verify Ollama is reachable**
  ```bash
  python -c "from postprocessor import ollama_health_check; print('OK' if ollama_health_check('http://localhost:11434') else 'FAIL')"
  ```

### Verification
- `ollama list` shows `qwen2.5:3b`
- Health check passes

---

## Phase L3: Vocabulary Import

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

- [ ] **Add any laptop-specific terms** (optional)
  ```bash
  python vocab.py add "YourLaptopName" --hint "misheard" --priority normal
  ```

### Verification
- `python vocab.py stats` shows imported terms

---

## Phase L4: First Run and Smoke Test

**Goal**: End-to-end dictation working.
**Risk tier**: R1
**Estimated effort**: S (~15 min, includes first model download)

### Steps

- [ ] **Verify microphone is detected**
  ```bash
  python -c "import sounddevice as sd; print([d['name'] for d in sd.query_devices() if d['max_input_channels'] > 0])"
  ```
  Should list at least one input device.

- [ ] **First run** (Whisper large-v3 downloads automatically, ~3GB, one-time)
  ```bash
  python app.py
  ```
  Watch the console for:
  - "Loading Whisper model 'large-v3' on cuda..."
  - "Model loaded" (may take a few minutes on first run due to download)
  - "Ollama reachable at ..."
  - "Correction UI ready (mode: auto)"
  - "Transcriber ready. Hold ctrl+shift+space to dictate."

- [ ] **Test 1: English dictation**
  - Open Notepad
  - Hold Ctrl+Shift+Space, say "Hello, my name is Freek"
  - Release hotkey
  - Verify: text appears in Notepad, "Freek" spelled correctly
  - Verify: correction window auto-shows near tray (8s timeout)

- [ ] **Test 2: Dutch dictation**
  - Hold hotkey, say "Dit is een test van de transcriber"
  - Verify: Dutch text appears correctly, not translated to English

- [ ] **Test 3: Mixed Dutch+English**
  - Hold hotkey, say "Ik gebruik Claude Code voor mijn project"
  - Verify: both languages preserved, "Claude Code" recognized

- [ ] **Test 4: Formatting commands**
  - Hold hotkey, say "Hello comma this is a test period new line next sentence"
  - Verify: "Hello, this is a test.\nNext sentence" (or close)

- [ ] **Test 5: Correction flow**
  - If any transcription was wrong, press Ctrl+Shift+C
  - Edit the text, press Enter
  - Check console for "Correction accepted"
  - Use quick-add vocab (Ctrl+Shift+A in correction window) for any new terms

- [ ] **Test 6: Vocabulary manager**
  - Right-click tray icon → "Manage vocabulary..."
  - Verify window opens, shows imported terms
  - Try add/remove/toggle priority

- [ ] **Test 7: Toast notifications** (if winotify installed)
  - Make 3 identical corrections → auto-learn should trigger → toast appears

- [ ] **Test 8: Test in different apps**
  - Browser text field
  - VS Code
  - Terminal
  - Chat app (if available)

### Verification
- All 8 tests pass
- Latency feels acceptable (target: <3s from hotkey release to text appearing)
- Correction window doesn't steal focus from target app

---

## Phase L5: Config Tuning (if needed)

**Goal**: Optimize for this specific laptop.
**Risk tier**: R1

### If latency is too high
- Try `model_size: medium` in config.yaml (faster, slightly less accurate)
- Try `model_size: small` for very fast results

### If microphone is wrong device
- Set `audio.device` in config.yaml to the device index from `sounddevice.query_devices()`

### If Ollama post-processing is slow
- Increase `postprocessing.timeout` in config.yaml
- Or try a smaller model: `ollama pull phi3:mini` then update config

### If correction window is annoying
- Set `brain.correction_mode: hotkey` (only shows on Ctrl+Shift+C)
- Or `brain.correction_mode: off` (disable entirely)

---

## Known Issues from Desktop Testing

1. **"new line" command sent to LLM instead of handled by commands.py** — formatting commands may not be processed before post-processing in some cases. If this happens, the LLM may translate the command literally. Needs investigation if it reproduces on laptop.

2. **LLM sometimes translates Dutch to English** — the system prompt says "do NOT translate" but qwen2.5:3b occasionally does anyway. May need prompt tuning or a different model.

3. **"Claude Code" sometimes becomes "Claude Coat"** — the vocabulary hint is "claud coat" which is the phonetic form. The LLM should correct it but doesn't always. May need a stronger prompt or explicit correction rule.

These are prompt-tuning issues, not setup blockers. The system is fully functional — just needs polish.

---

## Resume Pack

**Goal**: Get the transcriber running on the NVIDIA laptop for daily use.

**Current state**: Planned. Codebase complete through Phase 3.5. Never run on real hardware.

**What was done on desktop**:
- Python venv created, all deps verified
- Ollama qwen2.5:3b pulled and tested
- Vocabulary seeded: 7 terms (Freek, Claude Code, Anthropic, HeliBoard, Syncthing, Ollama, whisper)
- Post-processing tested end-to-end with real Ollama model
- 59/59 tests passing
- brain_export.json committed to repo for laptop import

**First command on laptop**: `git pull` then follow Phase L1-L4 sequentially.

**Estimated total time**: ~30-45 min (mostly waiting for model downloads).
