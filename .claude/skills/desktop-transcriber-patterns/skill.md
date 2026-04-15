---
name: desktop-transcriber-patterns
description: Expert patterns for building a desktop voice-to-text app on Windows with faster-whisper, sounddevice, pystray, keyboard, pyautogui/pyperclip. Covers CUDA setup, VAD tuning, multilingual transcription, real-time audio capture, system tray, global hotkeys, and clipboard paste.
license: MIT
metadata:
  tags: [python, whisper, faster-whisper, sounddevice, pystray, keyboard, pyautogui, windows, voice-to-text, speech-recognition]
  sources:
    - github:SYSTRAN/faster-whisper (official README and issues)
    - openai:whisper-prompting-guide (OpenAI Cookbook)
    - deepwiki:SYSTRAN/faster-whisper/5.2-voice-activity-detection
    - docs:python-sounddevice (spatialaudio official docs)
    - github:boppreh/keyboard (README and source)
    - github:moses-palmer/pystray (docs and issues)
    - pypi:pyperclip (official docs)
    - pypi:pyautogui (official docs)
---

# Desktop Voice-to-Text Patterns (Windows + faster-whisper)

## 1. faster-whisper: Model Loading & CUDA

### Model size selection
| Model | VRAM (fp16) | Speed vs real-time | Best for |
|-------|-------------|-------------------|----------|
| large-v3 | ~10 GB | ~6x | Maximum accuracy, all languages |
| large-v3-turbo | ~6 GB (~2.5 GB peak) | ~36x | Best speed/accuracy tradeoff |
| distil-large-v3 | ~6 GB (~2.4 GB peak) | ~40x | English-dominant, fastest |
| medium | ~5 GB | ~20x | Mid-range GPUs |
| small | ~2 GB | ~50x | Low VRAM / CPU fallback |

For bilingual Dutch/English with code-switching, prefer **large-v3** or **large-v3-turbo**. The turbo model has only 4 decoder layers (vs 32) so it is 6x faster with minimal accuracy loss on well-supported languages.

### CUDA / cuDNN compatibility (critical)
```
ctranslate2 >= 4.5.0 --> requires CUDA >= 12.3 + cuDNN 9
ctranslate2 == 4.4.0 --> requires CUDA 12.x + cuDNN 8
ctranslate2 <= 3.24.0 --> requires CUDA 11.x + cuDNN 8
```

**Windows setup checklist:**
1. Install CUDA Toolkit 12.x from NVIDIA.
2. Download cuDNN 9 for CUDA 12 and copy DLLs to `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin\`.
3. Verify: `python -c "from faster_whisper import WhisperModel; m = WhisperModel('tiny', device='cuda')"`.
4. If you get `ValueError: This CTranslate2 package was not compiled with CUDA support` -- reinstall ctranslate2 with `pip install --force-reinstall ctranslate2`.
5. If you get missing DLL errors like `cublas64_11.dll` -- you have a CUDA version mismatch. Do NOT rename DLLs; fix the actual version.

**Pitfall:** `pip install faster-whisper` may pull a ctranslate2 version mismatched with your CUDA. Pin versions explicitly:
```
faster-whisper>=1.0.0
ctranslate2==4.5.0  # match to your CUDA/cuDNN
```

### Model loading with graceful fallback
```python
from faster_whisper import WhisperModel

def load_model(model_size="large-v3", device="cuda", compute_type="float16"):
    """Load model with automatic CPU fallback."""
    try:
        return WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception:
        if device == "cuda":
            log.warning("CUDA failed, falling back to CPU with int8")
            return WhisperModel(model_size, device="cpu", compute_type="int8")
        raise
```

**Performance tip:** Load the model once at startup and reuse it. WhisperModel is thread-safe for sequential calls. Do NOT create a new model per transcription.

**Compute type guidance:**
- GPU: `float16` (default), or `int8_float16` for ~40% less VRAM with minimal accuracy loss
- CPU: `int8` (required for reasonable speed)
- Never use `float32` on GPU -- no benefit, 2x VRAM

---

## 2. faster-whisper: Transcription & initial_prompt

### Transcribe method -- key parameters
```python
segments, info = model.transcribe(
    audio,                          # numpy float32 array or file path
    language="nl",                  # set explicitly for bilingual (see below)
    beam_size=5,                    # 5 is default; 1 for greedy (faster)
    vad_filter=True,                # enable Silero VAD
    vad_parameters={...},           # see VAD section
    initial_prompt="...",           # vocabulary conditioning (see below)
    condition_on_previous_text=True, # use prior segment as context
    word_timestamps=False,          # enable only if needed (slower)
    temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],  # fallback temperatures
)
```

**Critical:** `segments` is a **generator**. Transcription does not start until you iterate. To get all text:
```python
text = " ".join(seg.text for seg in segments).strip()
```

### initial_prompt for custom vocabulary
The `initial_prompt` parameter conditions Whisper by providing text that looks like the start of the transcript. It is NOT an instruction -- Whisper continues in the style/vocabulary you establish.

**How it works internally:**
- Whisper's context window is 448 tokens total; `initial_prompt` is capped at 224 tokens.
- The prompt only directly applies to the **first 30-second segment**. After that, `condition_on_previous_text=True` carries context forward from decoded text.
- The prompt biases the model toward recognizing specific words, names, and terms.

**Effective patterns:**
```python
# Include proper nouns, technical terms, and domain vocabulary
initial_prompt = "Whisper, CUDA, CTranslate2, pystray, NumPy, PyAutoGUI"

# For bilingual Dutch/English -- include words from BOTH languages
initial_prompt = "vergadering, deployment, Kubernetes, configuratie, pipeline, overzicht"

# For formatting control -- show the style you want
initial_prompt = "Hello, this is a transcription. The meeting starts at 10:00 AM."

# For punctuation style
initial_prompt = "First sentence. Second sentence. Third sentence."
```

**What works:**
- Proper nouns and names: high reliability
- Technical terms and acronyms: good reliability
- Punctuation and capitalization style: moderate reliability
- Longer prompts (more examples) are more reliable than short ones

**What does NOT work:**
- Instructions like "Format as bullet points" -- ignored
- Forcing accents or dialects not in the audio
- Overriding what the model actually hears

**Pitfall with condition_on_previous_text:**
- `True` (default): previous segment's text becomes the prompt for the next segment. Good for consistency, but hallucinations can snowball.
- `False`: each segment starts fresh from initial_prompt only. Safer for short push-to-talk utterances.
- For push-to-talk (single short utterance per transcription call), this parameter does not matter much since there is typically only one segment.

### Building a dynamic initial_prompt from a vocabulary list
```python
def build_prompt(vocab_words: list[str], max_tokens: int = 200) -> str:
    """Build an initial_prompt from vocabulary words.

    Keep under ~200 tokens to leave headroom in the 224-token window.
    Approximate: 1 word ~ 1-2 tokens for English, more for Dutch.
    """
    # Include a mix of both languages and domain terms
    prompt = ", ".join(vocab_words)
    # Rough safety check: 200 words ~ 200-400 tokens
    words = prompt.split()
    if len(words) > 150:
        prompt = " ".join(words[:150])
    return prompt
```

---

## 3. faster-whisper: Language Detection & Code-Switching

### The core problem
Whisper detects language from the **first 30 seconds** of audio and assumes the entire audio is in that language. For code-switching (mixing Dutch and English mid-sentence), this is problematic.

### Strategies for bilingual Dutch/English

**Strategy A: Set language explicitly (recommended for push-to-talk)**
```python
# Set to the user's dominant language
segments, info = model.transcribe(audio, language="nl")
```
When `language` is set explicitly, Whisper skips detection and transcribes in that language. Surprisingly, it can still handle embedded English words/phrases within Dutch reasonably well, because large-v3 was trained on multilingual data.

**Strategy B: Leave language=None for auto-detection**
- Works when utterances are mostly one language
- Risk: may detect wrong language and translate instead of transcribe
- Risk: Dutch can be confused with Afrikaans or German

**Strategy C: Use initial_prompt to bias language detection**
```python
# Include words from your dominant language to bias detection
segments, info = model.transcribe(
    audio,
    language=None,  # auto-detect
    initial_prompt="Dit is een vergadering over de deployment pipeline."
)
```

**Recommendation for push-to-talk voice typing:**
- Default to `language="nl"` (or the user's dominant language)
- Provide a config option to switch to `language="en"` or `language=None`
- Include bilingual vocabulary in `initial_prompt` regardless of language setting
- Check `info.language_probability` -- if below 0.7, the detection was uncertain

---

## 4. faster-whisper: VAD Configuration

### Default parameters vs Silero-VAD defaults
faster-whisper uses **conservative** defaults compared to standalone Silero-VAD:

| Parameter | faster-whisper default | Silero-VAD default | Notes |
|-----------|----------------------|-------------------|-------|
| threshold | 0.5 | 0.5 | Same |
| min_silence_duration_ms | 2000 | 100 | FW is 20x more conservative |
| speech_pad_ms | 400 | 30 | FW pads much more |
| min_speech_duration_ms | 0 | 250 | FW keeps all speech |
| max_speech_duration_s | inf | inf | Same |

### Recommended VAD settings by use case

**Push-to-talk voice typing (this project's primary use case):**
```python
vad_parameters = {
    "threshold": 0.5,
    "min_silence_duration_ms": 500,   # lower than default 2000
    "speech_pad_ms": 300,             # slightly less padding
    "min_speech_duration_ms": 100,    # discard very short noise bursts
    "max_speech_duration_s": 60,      # safety cap
}
```
Rationale: push-to-talk audio is short (1-30s) and intentional. We want responsive detection with minimal padding, but still enough to avoid clipping word edges.

**Noisy environment fallback:**
```python
vad_parameters = {
    "threshold": 0.6,                 # more conservative speech detection
    "min_silence_duration_ms": 1000,
    "speech_pad_ms": 400,
    "min_speech_duration_ms": 200,    # ignore short noise bursts
}
```

### VAD pipeline internals (useful for debugging)
1. Silero VAD v6 ONNX model processes audio in 512-sample windows (32ms at 16kHz)
2. Speech probabilities are thresholded to find speech/silence boundaries
3. Segments shorter than `min_speech_duration_ms` are discarded
4. Adjacent segments separated by less than `min_silence_duration_ms` are merged
5. `speech_pad_ms` is added before/after each final segment
6. Audio chunks are sent to Whisper; timestamp offsets are tracked for restoration

**Performance impact:** VAD can reduce processing time by 25-45% by skipping silence. For push-to-talk, the savings are smaller (less silence) but VAD still helps avoid hallucinations on silence.

---

## 5. sounddevice: Real-Time Audio Capture

### InputStream configuration for voice recording
```python
import sounddevice as sd
import numpy as np

stream = sd.InputStream(
    samplerate=16000,     # Whisper requires 16 kHz
    channels=1,           # mono is sufficient and halves data
    dtype="float32",      # Whisper expects float32
    device=None,          # None = system default mic
    callback=audio_callback,
    blocksize=0,          # 0 = let PortAudio choose optimal size
    latency="low",        # "low" for interactive, "high" for stability
)
```

### Callback rules (critical for stability)
The audio callback runs in a **separate high-priority thread** managed by PortAudio. Violating these rules causes buffer overflows, glitches, or crashes:

**DO in the callback:**
- Copy data: `self._buffer.append(indata.copy())` -- the `copy()` is essential
- Check status flags for overflow/underflow
- Append to a pre-allocated list or put into a `queue.Queue`

**NEVER in the callback:**
- Allocate large memory (numpy concatenation, list comprehension)
- Do file I/O or network I/O
- Acquire locks that might be held by other threads (use lock-free queues)
- Do heavy computation (FFT, resampling, ML inference)
- Print or log (I/O can block)

### Buffer management pattern
```python
import threading
import numpy as np
import sounddevice as sd

class Recorder:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        if status:
            # Log outside callback via a flag or queue -- not here
            pass
        self._buffer.append(indata.copy())

    def start(self):
        with self._lock:
            self._buffer = []
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()

    def stop(self) -> np.ndarray | None:
        with self._lock:
            if self._stream is None:
                return None
            self._stream.stop()
            self._stream.close()
            self._stream = None
            if not self._buffer:
                return None
            audio = np.concatenate(self._buffer, axis=0).flatten()
            self._buffer = []
        return audio
```

### Status flag monitoring
```python
def _callback(self, indata, frames, time_info, status):
    if status.input_overflow:
        self._overflow_count += 1  # atomic int increment is safe
    self._buffer.append(indata.copy())
```

### Device selection
```python
# List available devices
print(sd.query_devices())

# Select by index
sd.InputStream(device=3, ...)

# Select by name substring (case-insensitive, space-separated parts)
sd.InputStream(device="USB Microphone", ...)

# The device string includes the host API name at the end,
# e.g. "Microphone (USB Audio) [Windows WASAPI]"
```

**Windows-specific notes:**
- Default host API on Windows is usually WASAPI (Windows Audio Session API)
- WASAPI exclusive mode (`sd.WasapiSettings(exclusive=True)`) gives lowest latency but locks the device
- For voice recording, shared mode (default) is fine
- `blocksize=0` lets WASAPI choose the optimal buffer size for your hardware
- If you get `PortAudioError`, the mic may be in use by another app or disabled in Windows Sound settings

### Sample rate handling
```python
# Whisper REQUIRES 16 kHz input. If your mic doesn't support 16 kHz natively,
# sounddevice/PortAudio will resample automatically. But it's better to:
device_info = sd.query_devices(device, "input")
native_rate = int(device_info["default_samplerate"])

if native_rate != 16000:
    # Option A: let PortAudio resample (usually fine)
    stream = sd.InputStream(samplerate=16000, ...)

    # Option B: record at native rate and resample manually (higher quality)
    import scipy.signal
    audio_16k = scipy.signal.resample_poly(audio, 16000, native_rate)
```

---

## 6. pystray: System Tray Icon

### Threading model
- `icon.run()` is **blocking** and runs a message loop
- On Windows, `icon.run()` is safe to call from any thread (unlike macOS which requires main thread)
- The `setup` parameter runs a callable in a separate thread once the icon is ready

**Recommended pattern for Windows:**
```python
import pystray
from PIL import Image

class App:
    def run(self):
        # icon.run() blocks, so register hotkeys etc. in setup
        self._icon = pystray.Icon("myapp", icon_image, "My App", menu)
        self._icon.run(setup=self._on_ready)

    def _on_ready(self, icon):
        icon.visible = True  # required on some platforms
        self._register_hotkeys()
        # This runs in a separate thread -- icon message loop is on the calling thread
```

### Dynamic icon updates (recording state)
```python
# Pre-build icon images at startup (avoid creating images in hot path)
ICON_IDLE = build_icon(recording=False)
ICON_RECORDING = build_icon(recording=True)

def update_state(self, recording: bool):
    """Safe to call from any thread on Windows."""
    if self._icon is not None:
        self._icon.icon = ICON_RECORDING if recording else ICON_IDLE
        self._icon.title = "Recording..." if recording else "Transcriber"
```

Setting `icon.icon` to a new `Image` object triggers an immediate update on Windows. No need for `update_menu()` unless menu item properties changed.

### Menu patterns
```python
menu = pystray.Menu(
    pystray.MenuItem("Transcriber", None, enabled=False),  # label, not clickable
    pystray.Menu.SEPARATOR,
    pystray.MenuItem(
        "Language",
        pystray.Menu(  # submenu
            pystray.MenuItem("Dutch", lambda: set_lang("nl"),
                             checked=lambda item: current_lang == "nl"),
            pystray.MenuItem("English", lambda: set_lang("en"),
                             checked=lambda item: current_lang == "en"),
            pystray.MenuItem("Auto", lambda: set_lang(None),
                             checked=lambda item: current_lang is None),
        )
    ),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem("Quit", on_quit),
)
```

**Dynamic menu properties:** Pass callables instead of values for `checked`, `enabled`, `text`. They are re-evaluated when the menu is opened or `icon.update_menu()` is called.

### Shutdown
```python
def on_quit(self, icon, item):
    keyboard.unhook_all()  # clean up hotkeys first
    icon.stop()            # exits the icon.run() message loop
```

**Pitfall:** If `icon.stop()` is called before hotkey cleanup, the app may hang because keyboard hooks still hold references.

---

## 7. keyboard: Global Hotkeys & Push-to-Talk

### Library status warning
The `keyboard` library (boppreh/keyboard) was **archived and marked unmaintained in February 2026**. It still works on Windows but will not receive bug fixes. Consider migrating to `pynput` for long-term maintenance.

**For now, keyboard works and has better Windows suppression support than pynput.**

### Push-to-talk pattern
```python
import keyboard

class HotkeyManager:
    def __init__(self, hotkey="ctrl+shift+space"):
        self.hotkey = hotkey
        # Extract the trigger key (last key in combo) for release detection
        self._trigger_key = hotkey.split("+")[-1].strip()

    def register(self, on_press, on_release):
        # suppress=True prevents the hotkey from reaching other apps (Windows only)
        keyboard.add_hotkey(self.hotkey, on_press, suppress=True)
        keyboard.on_release_key(self._trigger_key, on_release)

    def unregister(self):
        keyboard.unhook_all()
```

### Key suppression (Windows only)
- `suppress=True` in `add_hotkey()` blocks the hotkey keys from reaching the foreground app
- This prevents `Ctrl+Shift+Space` from triggering actions in other apps
- The suppression has a configurable timeout; if the callback takes too long, keys are released
- `suppress` does NOT work on Linux or macOS -- on those platforms keys always pass through

### Callback threading model
- Keyboard callbacks run in the **keyboard hook thread**, which is a single background thread
- Heavy work in callbacks blocks ALL keyboard event processing
- **Always offload work to a separate thread:**
```python
def _on_release(self, event):
    if not self._recording:
        return
    # Do NOT transcribe here -- it blocks keyboard processing
    threading.Thread(target=self._stop_and_transcribe, daemon=True).start()
```

### Common pitfalls
1. **Key bounce / double triggers:** `add_hotkey` can fire multiple times if keys bounce. Use a lock or flag:
   ```python
   def _on_press(self):
       with self._lock:
           if self._recording:
               return  # already recording
           self._recording = True
       self.recorder.start()
   ```

2. **Release detection scope:** `on_release_key("space")` fires for ANY release of space, not just when the hotkey combo was active. Guard with a state flag.

3. **Blocking the hook thread:** If your callback blocks for >500ms, Windows may decide the hook is unresponsive and skip events. Always use `threading.Thread` for anything non-trivial.

4. **Admin requirements:** The keyboard library uses a low-level keyboard hook (`SetWindowsHookEx`). Some environments (e.g., certain Remote Desktop sessions, UAC-elevated apps) may not receive events. Running as administrator can help.

5. **Exit safety:** Always include a way to exit. If key suppression goes wrong, the keyboard can become unresponsive. Register `keyboard.add_hotkey("ctrl+alt+q", emergency_quit)` as a safety valve.

### pynput alternative (for future migration)
```python
from pynput import keyboard

def on_activate():
    start_recording()

def on_deactivate():
    stop_recording()

# GlobalHotKeys does not support suppress on Windows
with keyboard.GlobalHotKeys({"<ctrl>+<shift>+<space>": on_activate}) as h:
    h.join()
```
Note: pynput `GlobalHotKeys` does not natively support key suppression or push-to-talk (hold-to-record) patterns as cleanly as the keyboard library. For push-to-talk, you would need to use `keyboard.Listener` with manual state tracking.

---

## 8. pyautogui / pyperclip: Clipboard Paste

### Core pattern: copy, paste, restore
```python
import pyperclip
import pyautogui
import time
import threading

pyautogui.FAILSAFE = False  # disable corner-abort for headless operation

_paste_lock = threading.Lock()

def paste_text(text: str):
    """Thread-safe: copy text to clipboard, paste, restore original clipboard."""
    with _paste_lock:
        _paste_impl(text)

def _paste_impl(text: str):
    # 1. Save original clipboard
    original = None
    try:
        original = pyperclip.paste()
    except Exception:
        pass  # clipboard may be empty or contain non-text data

    try:
        # 2. Copy our text
        pyperclip.copy(text)
        time.sleep(0.05)  # let clipboard propagate

        # 3. Paste into active window
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.05)  # let the app process the paste
    finally:
        # 4. Restore original clipboard
        if original is not None:
            time.sleep(0.2)  # wait for paste to complete before overwriting
            try:
                pyperclip.copy(original)
            except Exception:
                pass
```

### Timing values (tuned for Windows)
| Sleep | Location | Purpose | Safe range |
|-------|----------|---------|------------|
| 50ms | After `pyperclip.copy()` | Clipboard propagation | 30-100ms |
| 50ms | After `pyautogui.hotkey()` | App processes paste | 30-100ms |
| 200ms | Before clipboard restore | Ensure paste completed | 150-500ms |

**Pitfall:** Too-short delays cause race conditions where the original clipboard is restored before the app reads the paste. Too-long delays feel sluggish. 200ms restore delay is a good balance.

### Thread safety
- The Windows clipboard is a **global shared resource** -- only one process can open it at a time
- `_paste_lock` serializes our own paste operations, but other apps can still interfere
- pyperclip internally uses `win32clipboard` (via ctypes) which handles `OpenClipboard`/`CloseClipboard`
- If another app holds the clipboard open, `pyperclip.copy()` may fail silently or raise

### Clipboard non-text content limitation
- `pyperclip.paste()` only reads **text** (CF_UNICODETEXT) from the clipboard
- If the user copied an image, file, or rich text, `pyperclip.paste()` returns empty string or raises
- The "restore" will then overwrite their image/file with an empty string

**Robust alternative using win32clipboard:**
```python
import win32clipboard

def save_clipboard():
    """Save all clipboard formats. Returns list of (format, data) tuples."""
    saved = []
    win32clipboard.OpenClipboard()
    try:
        fmt = 0
        while True:
            fmt = win32clipboard.EnumClipboardFormats(fmt)
            if fmt == 0:
                break
            try:
                data = win32clipboard.GetClipboardData(fmt)
                saved.append((fmt, data))
            except Exception:
                pass  # some formats can't be read
    finally:
        win32clipboard.CloseClipboard()
    return saved

def restore_clipboard(saved):
    """Restore previously saved clipboard formats."""
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        for fmt, data in saved:
            try:
                win32clipboard.SetClipboardData(fmt, data)
            except Exception:
                pass
    finally:
        win32clipboard.CloseClipboard()
```
This preserves images, files, and rich text across the paste operation. Requires `pywin32`.

### pyautogui gotchas on Windows
- `pyautogui.FAILSAFE = False` -- disable the "move mouse to corner to abort" feature, which interferes with background operation
- `pyautogui.hotkey("ctrl", "v")` sends key events to the **currently focused window**. If focus changed between recording-stop and paste, text goes to the wrong window.
- `pyautogui.PAUSE` (default 0.1s) adds a delay after every pyautogui call. Set to 0 for faster operation: `pyautogui.PAUSE = 0`
- Some apps (e.g., terminals, VMs) intercept Ctrl+V differently. Consider `pyautogui.hotkey("shift", "insert")` as a fallback.

---

## 9. Architecture: Threading Model

### Thread inventory for this app
| Thread | Owner | Role | Blocking? |
|--------|-------|------|-----------|
| Main thread | pystray `icon.run()` | Windows message loop for tray icon | Yes (blocked) |
| Keyboard hook thread | `keyboard` library | Receives all key events, runs callbacks | Must stay responsive |
| PortAudio callback thread | `sounddevice` | Receives audio chunks from mic | Must stay responsive |
| Worker thread(s) | App code | Transcription + paste (spawned per utterance) | OK to block |

### Critical rule: never block the keyboard hook thread
```python
# BAD -- blocks keyboard processing during transcription
def on_key_release(event):
    audio = recorder.stop()
    text = transcriber.transcribe(audio)  # takes 1-5 seconds!
    paste_text(text)

# GOOD -- offload to worker thread
def on_key_release(event):
    threading.Thread(target=_stop_and_transcribe, daemon=True).start()
```

### Lock ordering to prevent deadlocks
If using multiple locks, always acquire in the same order:
1. `_recording_lock` (state transitions)
2. `_recorder_lock` (audio stream)
3. `_paste_lock` (clipboard operations)

Never hold a lock while calling into another component that acquires its own lock.

---

## 10. Performance Optimization Checklist

### Startup time
- [ ] Load Whisper model in a background thread while showing the tray icon
- [ ] Use `large-v3-turbo` instead of `large-v3` to halve load time and VRAM
- [ ] Pre-build both icon images at import time (not per state change)

### Transcription latency (time from key-release to text appearing)
- [ ] VAD filter with low `min_silence_duration_ms` (500) to skip silence quickly
- [ ] `beam_size=5` is a good default; `beam_size=1` (greedy) is faster but less accurate
- [ ] Set `language` explicitly to skip the 30-second language detection scan
- [ ] Use `condition_on_previous_text=False` for push-to-talk (no prior context needed)
- [ ] `temperature=0.0` as a single value (not a list) skips fallback decoding passes

### Memory
- [ ] Clear audio buffer immediately after concatenation in `stop()`
- [ ] Use `int8_float16` compute type to reduce VRAM by ~40%
- [ ] Consider `small` or `medium` model for machines with < 6 GB VRAM

### Reliability
- [ ] Always `copy()` audio data in sounddevice callback
- [ ] Use `threading.Lock` around recording state transitions
- [ ] Set `daemon=True` on worker threads so they die with the main process
- [ ] Add try/except around every paste operation (clipboard can fail)
- [ ] Handle `sd.PortAudioError` when mic is unavailable
