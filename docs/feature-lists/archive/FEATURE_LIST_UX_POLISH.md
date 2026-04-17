# Feature List: UX Polish — Professional Feel for Daily-Driver Dictation

Date: 2026-04-15
Status: Planned
Scope: Audio feedback, clipboard-free typing, auto-start, overlay polish, tray polish
Owner: Freek

---

## Problem Framing

The streaming pipeline works. The transcription quality is good. But the *feel* is still a developer prototype:

1. **Silent state transitions** — pressing the hotkey gives zero audio feedback. User must look at the overlay to confirm recording started. In a workflow where you're looking at the document you're dictating into, this breaks flow.
2. **Clipboard pollution** — every paste clobbers the clipboard. Even with session-level save/restore, there's a timing window where Ctrl+V gives unexpected text. Streaming mode makes this worse (many rapid pastes).
3. **Manual startup** — user must open a terminal and run `python app.py` every time. A daily-driver app should start with Windows.
4. **Static overlay** — hard cuts on show/hide. No interactivity. No elapsed time. Feels like a debug panel, not a product.
5. **Correction popup interrupts streaming** — the auto-popup was designed for batch mode. In streaming mode it fires per-segment, which is disruptive.
6. **Tray tooltip is useless** — shows "Transcriber" with no hint of how to use it. Every new session the user must remember the hotkey.

**Root cause**: The pipeline is solid but the interaction layer hasn't been polished. These are all small touches that compound into a professional feel.

**Goal**: Make every interaction feel responsive, automatic, and polished. Zero new features — just make what exists feel great.

---

## Scope

### In Scope
- Embedded start/stop/error sounds (WAV, async playback)
- SendInput clipboard-free text insertion for streaming mode
- Auto-start on Windows login (Registry Run key, tray toggle)
- Overlay polish: fade transitions, elapsed timer, hover-reveal stop button, smooth pulse
- WS_EX_NOACTIVATE on overlay so clicks don't steal focus
- Disable correction auto-popup in streaming (change default to hotkey mode)
- Tray tooltip with hotkey hint and recording duration

### Out of Scope
- Settings UI (future phase)
- Session history panel (future phase)
- Mic input level meter (future phase)
- Light theme / appearance customization (future phase)
- First-run wizard (future phase)
- App-aware dictation profiles (future phase)

---

## Chosen Approach

### Audio feedback: Embedded WAV with winsound

Generate sine-wave tones programmatically at import time using `struct` + `wave` + `io.BytesIO`. Store as `bytes` constants. Play via `winsound.PlaySound(data, SND_MEMORY | SND_ASYNC)`.

- **Start tone**: ascending two-note — 880 Hz then 1100 Hz, 80ms each, sine wave with 5ms fade-in/out to prevent clicks
- **Stop tone**: descending — 1100 Hz then 880 Hz, 80ms each
- **Error tone**: low single note — 330 Hz, 200ms

Total embedded size: ~15 KB in memory. Generated at import time, played from memory, no disk I/O, no temp files. `SND_ASYNC` returns immediately — zero latency impact on the hotkey.

**Why this over alternatives**:
- `winsound.Beep()` sounds robotic and blocks the calling thread
- External WAV files add deployment complexity
- In-memory bytes via `io.BytesIO` + `wave` module is self-contained and clean

### Text insertion: keyboard.write() with modifier release

The `keyboard` library (already a dependency) has `keyboard.write(text)` which internally uses `SendInput` + `KEYEVENTF_UNICODE`. This types text character-by-character without touching the clipboard.

**Hybrid approach**:
- **Streaming segments** (<200 chars): use `keyboard.write()` — fast for short text, no clipboard disruption
- **Batch mode** (any length): keep existing clipboard paste — faster for long text
- **Configurable**: `ui.output_method: auto | type | paste` (default: `auto`)

Before typing, release any held modifier keys via `GetAsyncKeyState` + `SendInput` key-up events. This prevents Ctrl/Shift from the hotkey interfering with typed characters.

**Why keyboard.write() over rolling our own ctypes**:
- Already a dependency (zero new imports)
- Handles UTF-16 surrogate pairs for all Unicode including Dutch characters
- Battle-tested across Windows versions
- We add the modifier-release wrapper (~15 lines of ctypes)

### Auto-start: Registry Run key

`winreg` (stdlib) to write `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Transcriber`. Value: `"path\to\pythonw.exe" "path\to\app.py"`.

**Why this over alternatives**:
| Alternative | Why Rejected |
|---|---|
| **Startup folder shortcut** | Requires pywin32 or PowerShell subprocess to create .lnk files. More complex for no benefit. |
| **Task Scheduler** | Overkill. Entry hidden from Task Manager > Startup. Less discoverable for the user. |

Registry key appears in Task Manager > Startup and Settings > Apps > Startup. User can disable it from Windows UI without touching the app. `winreg` is stdlib — zero new dependencies.

### Overlay polish: Fade + timer + hover-stop + smooth pulse

Five micro-improvements:

1. **Fade transitions**: Animate `-alpha` from 0 to 0.9 on show (5 steps over 120ms) and reverse on hide. Uses `_root.after()` chain. Prevents the jarring hard-cut.

2. **Elapsed timer**: Show "0:42" right-aligned in the overlay, updating every second via `_root.after(1000, ...)`. Helps user gauge dictation length and confirms the app is still alive.

3. **Hover-reveal stop button**: When mouse enters the overlay, a subtle "Stop" label fades in on the right side. When mouse leaves, it fades out. Clicking it stops recording. Clean and discoverable without cluttering the default view.

4. **WS_EX_NOACTIVATE**: Set via `ctypes.windll.user32.SetWindowLongW()` after window creation. Prevents the overlay from stealing focus when clicked, so the active text field keeps focus.

5. **Smoother pulse**: Instead of binary on/off toggle every 500ms, graduate the dot color through 8 intensity steps over 1.6s for a breathing effect.

### Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| **ctypes SendInput wrapper (custom 50-line implementation)** | Reinvents what `keyboard.write()` already does. No benefit since keyboard is already imported. |
| **Overlay rounded corners via canvas shape** | Tk on Windows doesn't support window-level rounded corners cleanly. Adds complexity for minimal visual gain on Windows 10/11. |
| **Startup folder .lnk shortcut** | Requires PowerShell subprocess or pywin32 COM to create .lnk. Registry is simpler, equally visible to user, zero dependencies. |
| **Remove correction UI entirely** | Premature. Changing correction_mode to "hotkey" disables auto-popup but keeps manual access for occasional use. Full removal is a separate decision. |

---

## Harden Audit Findings

| # | Finding | Severity | Mitigation in Plan |
|---|---------|----------|--------------------|
| 1 | **Modifier key interference with SendInput**: If Ctrl/Shift still logically held when keyboard.write() fires, characters get interpreted as shortcuts (e.g., Ctrl+S instead of "s") | High | `_release_modifiers()` function using `GetAsyncKeyState` check + explicit key-up `SendInput` events before every `keyboard.write()` call. 50ms sleep after release for OS to process. |
| 2 | **keyboard.write() thread safety**: Rapid calls from the StreamingRecorder worker thread could interleave with hotkey events on the keyboard listener thread | Medium | Keep `_paste_lock` serialization around `type_text()`. Same lock used for clipboard paste — mutual exclusion guaranteed. |
| 3 | **WS_EX_NOACTIVATE + click binding**: Tk's `<Button-1>` may not fire on a non-activating window on some Windows versions | Medium | Test on target machine. If click handler doesn't fire, hover-reveal still works visually and user always has the hotkey. Stop button is convenience, not the only path. |
| 4 | **winsound SND_ASYNC on short-lived threads**: Sound playback cuts off if calling thread exits before playback completes | Low | Sounds are triggered from the hotkey callback which runs on the keyboard listener thread (daemon, long-lived). Not a practical issue. |
| 5 | **Registry auto-start path breaks if app directory moves**: Absolute path in registry becomes invalid | Low | On startup, if auto-start is enabled, verify the registered path matches current location. Log warning if mismatched. Re-enable from tray menu fixes it. |
| 6 | **Overlay alpha animation on slow machines**: 5 animation frames in 120ms could stutter if Tk event loop is busy during transcription | Low | Graceful degradation: if overlay is being hidden while a fade-in is still running, cancel the in-progress animation and jump to target state. |

---

## Phase Plan

### Phase P1: UX Polish (single phase, single /run context)
**Goal**: Every interaction feels responsive and automatic.
**Risk tier**: R2 (cross-cutting, multiple files)
**Estimated effort**: L (6 tickets, 2 new files, 4 modified files)
**Context strategy**: Single /run window, sequential tickets

---

## Phase P1 — Execution Tickets

### P1-1: Sound module with embedded WAV tones

**File**: New file `sounds.py`
**Action**: Create module that generates and plays start/stop/error tones
**Risk tier**: R1

**Design**:
```python
"""Audio feedback tones for recording state transitions.

Tones are generated as sine waves at import time and stored in memory.
Playback is async (non-blocking) via winsound.
"""

import io
import logging
import math
import struct
import wave
import winsound

log = logging.getLogger("transcriber.sounds")

def _generate_tone(frequency: float, duration_ms: int, volume: float = 0.3,
                   sample_rate: int = 16000, fade_ms: int = 5) -> bytes:
    """Generate a sine wave tone as WAV bytes in memory.

    Args:
        frequency: Tone frequency in Hz.
        duration_ms: Duration in milliseconds.
        volume: Amplitude 0.0-1.0.
        sample_rate: Sample rate in Hz.
        fade_ms: Linear fade-in/out to prevent click artifacts.
    """
    n_samples = int(sample_rate * duration_ms / 1000)
    fade_samples = int(sample_rate * fade_ms / 1000)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            # Sine wave
            sample = math.sin(2 * math.pi * frequency * i / sample_rate)
            # Apply volume
            sample *= volume
            # Fade in/out
            if i < fade_samples:
                sample *= i / fade_samples
            elif i > n_samples - fade_samples:
                sample *= (n_samples - i) / fade_samples
            # Pack as 16-bit signed integer
            wf.writeframes(struct.pack("<h", int(sample * 32767)))
    return buf.getvalue()


def _generate_two_tone(freq1: float, freq2: float,
                       duration_ms: int = 80, **kwargs) -> bytes:
    """Generate two consecutive tones as a single WAV."""
    # Generate individual PCM data (skip WAV headers)
    # Then combine into one WAV
    sample_rate = kwargs.get("sample_rate", 16000)
    n_per_tone = int(sample_rate * duration_ms / 1000)
    fade_ms = kwargs.get("fade_ms", 5)
    fade_samples = int(sample_rate * fade_ms / 1000)
    volume = kwargs.get("volume", 0.3)

    frames = bytearray()
    for freq in (freq1, freq2):
        for i in range(n_per_tone):
            sample = math.sin(2 * math.pi * freq * i / sample_rate)
            sample *= volume
            if i < fade_samples:
                sample *= i / fade_samples
            elif i > n_per_tone - fade_samples:
                sample *= (n_per_tone - i) / fade_samples
            frames.extend(struct.pack("<h", int(sample * 32767)))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


# Pre-generate tones at import time
_SOUND_START = _generate_two_tone(880, 1100)      # Ascending — recording on
_SOUND_STOP = _generate_two_tone(1100, 880)       # Descending — recording off
_SOUND_ERROR = _generate_tone(330, 200, volume=0.2)  # Low buzz — error

_enabled = True


def set_enabled(enabled: bool):
    """Enable or disable all sound playback."""
    global _enabled
    _enabled = enabled


def play_start():
    """Play start-recording tone. Non-blocking."""
    if _enabled:
        try:
            winsound.PlaySound(_SOUND_START,
                               winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            log.debug("Could not play start sound")


def play_stop():
    """Play stop-recording tone. Non-blocking."""
    if _enabled:
        try:
            winsound.PlaySound(_SOUND_STOP,
                               winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            log.debug("Could not play stop sound")


def play_error():
    """Play error tone. Non-blocking."""
    if _enabled:
        try:
            winsound.PlaySound(_SOUND_ERROR,
                               winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            log.debug("Could not play error sound")
```

**Verification**: `python -m py_compile sounds.py` then `python -c "import sounds; sounds.play_start(); import time; time.sleep(0.5)"`

---

### P1-2: SendInput text insertion in output.py

**File**: `output.py`
**Action**: Add `type_text()` and `output_text_streaming()` with modifier key release
**Risk tier**: R2

**New functions added to output.py**:
```python
import ctypes
import keyboard as kb

# Windows virtual key codes for modifier keys
_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12     # Alt
_VK_LWIN = 0x5B
_VK_RWIN = 0x5C
_VK_MODIFIERS = (_VK_SHIFT, _VK_CONTROL, _VK_MENU, _VK_LWIN, _VK_RWIN)

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002

# ctypes structures for SendInput (modifier release only)
class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]

class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUT_UNION)]

_SendInput = ctypes.windll.user32.SendInput
_GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState


def _release_modifiers():
    """Release any held modifier keys to prevent interference with typed text."""
    for vk in _VK_MODIFIERS:
        if _GetAsyncKeyState(vk) & 0x8000:
            inp = _INPUT(type=_INPUT_KEYBOARD,
                         union=_INPUT_UNION(ki=_KEYBDINPUT(
                             wVk=vk, wScan=0, dwFlags=_KEYEVENTF_KEYUP,
                             time=0, dwExtraInfo=None)))
            _SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def type_text(text: str):
    """Type text into the active window via SendInput (keyboard.write).

    No clipboard involvement. Thread-safe (uses _paste_lock).
    Releases modifier keys before typing to prevent Ctrl/Shift interference.
    """
    with _paste_lock:
        _release_modifiers()
        time.sleep(0.05)
        kb.write(text, delay=0)


# Characters above this threshold use clipboard paste (faster for bulk)
_TYPE_THRESHOLD = 200


def output_text_streaming(text: str, method: str = "auto"):
    """Output text using the configured method.

    Args:
        text: Text to output into the active window.
        method: "auto" = type for short text, paste for long text.
                "type" = always use SendInput (keyboard.write).
                "paste" = always use clipboard paste.
    """
    if method == "type" or (method == "auto" and len(text) <= _TYPE_THRESHOLD):
        try:
            type_text(text)
        except Exception:
            log.warning("type_text failed, falling back to clipboard paste")
            paste_text_streaming(text)
    else:
        paste_text_streaming(text)
```

**Import change at top of output.py**: add `import ctypes` and `import keyboard as kb`.

**Existing functions unchanged**: `paste_text()`, `paste_text_streaming()`, `save_clipboard()`, `restore_clipboard()` remain for backward compat and batch mode.

**Verification**: `python -m py_compile output.py`

---

### P1-3: Auto-start on login

**File**: New file `autostart.py`
**Action**: Registry-based auto-start with enable/disable/toggle/is_enabled
**Risk tier**: R1

**Design**:
```python
"""Windows auto-start via Registry Run key.

Adds/removes an entry in HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
that launches the transcriber on login using pythonw.exe (windowless).
"""

import logging
import os
import sys
import winreg

log = logging.getLogger("transcriber.autostart")

_APP_NAME = "Transcriber"
_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_launch_command() -> str:
    """Build the command string for auto-start using absolute paths."""
    python = sys.executable
    # Prefer pythonw.exe for windowless launch
    if python.endswith("python.exe"):
        pythonw = python.replace("python.exe", "pythonw.exe")
        if os.path.exists(pythonw):
            python = pythonw
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "app.py"))
    return f'"{python}" "{script}"'


def is_enabled() -> bool:
    """Check if auto-start is currently registered."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except FileNotFoundError:
        return False


def enable():
    """Register auto-start in the Windows registry."""
    cmd = _get_launch_command()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH,
                        0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, cmd)
    log.info("Auto-start enabled: %s", cmd)


def disable():
    """Remove auto-start from the Windows registry."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH,
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _APP_NAME)
        log.info("Auto-start disabled")
    except FileNotFoundError:
        log.debug("Auto-start was not enabled")


def toggle() -> bool:
    """Toggle auto-start. Returns the new state (True = enabled)."""
    if is_enabled():
        disable()
        return False
    else:
        enable()
        return True
```

**Also in app.py `main()`**: Add `os.chdir(os.path.dirname(os.path.abspath(__file__)))` so paths resolve correctly when launched from registry (working dir would otherwise be `C:\Windows\System32`).

**Verification**: `python -m py_compile autostart.py` then `python -c "import autostart; print(autostart.is_enabled())"`

---

### P1-4: Overlay polish — fade, timer, hover-stop, smooth pulse

**File**: `recording_indicator.py`
**Action**: Rewrite with fade transitions, elapsed timer, hover-reveal stop button, WS_EX_NOACTIVATE, smooth pulse
**Risk tier**: R2

**New `__init__` signature**:
```python
def __init__(self, on_stop=None):
    self._on_stop = on_stop  # Callback for click-to-stop
```

**1. WS_EX_NOACTIVATE** (called once after window creation in `_run_tk`):
```python
def _set_no_activate(self):
    """Prevent overlay from stealing focus when clicked."""
    try:
        hwnd = ctypes.windll.user32.GetParent(self._root.winfo_id())
        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                            style | WS_EX_NOACTIVATE)
    except Exception:
        log.debug("Could not set WS_EX_NOACTIVATE")
```

**2. Fade-in on show** (5 steps: 0.0 -> 0.2 -> 0.4 -> 0.6 -> 0.8 -> 0.9, 24ms per step = 120ms total):
```python
def _fade_in_step(self, step):
    alphas = (0.0, 0.2, 0.4, 0.6, 0.8, 0.9)
    if step < len(alphas):
        self._root.attributes("-alpha", alphas[step])
        self._root.after(24, lambda: self._fade_in_step(step + 1))

def _do_show(self):
    self._current_state = "listening"
    self._apply_state()
    self._canvas.itemconfig(self._result_text, text="")
    self._start_timer()
    self._root.attributes("-alpha", 0.0)
    self._root.deiconify()
    self._root.lift()
    self._fade_in_step(0)
```

**3. Fade-out on hide** (reverse, then withdraw):
```python
def _fade_out_step(self, step):
    alphas = (0.9, 0.7, 0.5, 0.3, 0.1, 0.0)
    if step < len(alphas):
        self._root.attributes("-alpha", alphas[step])
        if step < len(alphas) - 1:
            self._root.after(24, lambda: self._fade_out_step(step + 1))
        else:
            self._root.withdraw()
            self._root.attributes("-alpha", 0.9)  # Reset for next show
```

**4. Elapsed timer** (right-aligned canvas text, updates every 1s):
```python
# In _run_tk, add timer text item:
self._timer_text = self._canvas.create_text(
    win_w - 12, cy_top,
    text="", fill="#666666", font=("Segoe UI", 9),
    anchor="e",
)

# Timer methods:
def _start_timer(self):
    self._timer_start = time.monotonic()
    self._timer_id = self._root.after(1000, self._update_timer)

def _update_timer(self):
    elapsed = int(time.monotonic() - self._timer_start)
    minutes, seconds = divmod(elapsed, 60)
    self._canvas.itemconfig(self._timer_text, text=f"{minutes}:{seconds:02d}")
    self._timer_id = self._root.after(1000, self._update_timer)

def _cancel_timer(self):
    if self._timer_id is not None:
        self._root.after_cancel(self._timer_id)
        self._timer_id = None
    self._canvas.itemconfig(self._timer_text, text="")
```

**5. Hover-reveal stop button** (right side of overlay):
```python
# In _run_tk, add stop button elements (initially invisible):
self._stop_bg = self._canvas.create_rectangle(
    win_w - 64, 4, win_w - 4, win_h - 4,
    fill="#1e1e1e", outline="",  # Same as background — invisible
)
self._stop_label = self._canvas.create_text(
    win_w - 34, win_h // 2,
    text="Stop", fill="#1e1e1e",  # Same as background — invisible
    font=("Segoe UI", 9),
)

# Hover bindings:
self._canvas.bind("<Enter>", lambda e: self._on_hover_enter())
self._canvas.bind("<Leave>", lambda e: self._on_hover_leave())
self._canvas.tag_bind(self._stop_bg, "<Button-1>", lambda e: self._on_stop_click())
self._canvas.tag_bind(self._stop_label, "<Button-1>", lambda e: self._on_stop_click())

def _on_hover_enter(self):
    self._canvas.itemconfig(self._stop_bg, fill="#333333")
    self._canvas.itemconfig(self._stop_label, fill="#e0e0e0")

def _on_hover_leave(self):
    self._canvas.itemconfig(self._stop_bg, fill="#1e1e1e")
    self._canvas.itemconfig(self._stop_label, fill="#1e1e1e")

def _on_stop_click(self):
    if self._on_stop:
        self._on_stop()
```

**6. Smoother pulse** (8-step graduated color cycle, 200ms per step = 1.6s full cycle):
```python
_PULSE_STEPS_RED = [
    "#E74C3C", "#D9443A", "#C83D35", "#993025",
    "#993025", "#C83D35", "#D9443A", "#E74C3C",
]

def _pulse(self):
    if self._canvas is None or not self._pulse_active:
        return
    color = _PULSE_STEPS_RED[self._pulse_step % len(_PULSE_STEPS_RED)]
    self._canvas.itemconfig(self._dot, fill=color)
    self._pulse_step += 1
    self._pulse_id = self._root.after(200, self._pulse)
```

**New instance variables**: `_on_stop`, `_timer_text`, `_timer_id`, `_timer_start`, `_stop_bg`, `_stop_label`, `_pulse_step`

**Verification**: `python -m py_compile recording_indicator.py` + visual inspection

---

### P1-5: Config, tray polish, wire everything into app.py

**Files**: `config.py`, `config.yaml`, `app.py`
**Action**: Add UI config section, wire sounds + type_text + auto-start into app, polish tray
**Risk tier**: R2

**config.py — add `ui` section to DEFAULT_CONFIG**:
```python
"ui": {
    "sounds": True,
    "output_method": "auto",   # auto | type | paste
    "auto_start": False,
},
```

**config.yaml — add `ui` section**:
```yaml
# UI polish settings
ui:
  sounds: true               # Play start/stop/error tones
  output_method: auto        # auto | type | paste (type = SendInput, paste = clipboard)
  auto_start: false          # Start with Windows (toggle via tray menu)
```

**config.yaml — change brain.correction_mode**:
```yaml
brain:
  correction_mode: hotkey    # Was: auto. Overlay provides feedback in streaming mode.
```

**app.py changes**:

1. **New imports**:
```python
import os
import sounds
import autostart
from output import (paste_text, output_text_streaming,
                    save_clipboard, restore_clipboard)
```

2. **Init sounds in `__init__`**:
```python
sounds.set_enabled(self.config["ui"]["sounds"])
```

3. **Pass on_stop callback to RecordingIndicator**:
```python
self._recording_indicator = RecordingIndicator(on_stop=self._toggle_recording)
```

4. **Play sounds in `_toggle_recording`**:
```python
def _toggle_recording(self):
    ...
    with self._lock:
        if self._recording:
            self._recording = False
            sounds.play_stop()
            ...
        else:
            self._recording = True
            sounds.play_start()
            ...
```

5. **Replace `paste_text_streaming` with `output_text_streaming` in `_on_speech_segment`**:
```python
# Was: paste_text_streaming(result)
output_method = self.config["ui"]["output_method"]
output_text_streaming(result, method=output_method)
```

6. **Play error sound on transcription failure**:
```python
except Exception:
    log.exception("Segment transcription failed")
    sounds.play_error()
    self._recording_indicator.set_state("listening")
    return
```

7. **Tray tooltip with hotkey hint**:
```python
def _tray_tooltip(self) -> str:
    hotkey = self.config["hotkey"].replace("+", "+").title()
    if self._brain is not None:
        return f"Transcriber — {hotkey} to dictate ({self._brain.term_count()} terms)"
    return f"Transcriber — {hotkey} to dictate"
```

8. **Auto-start tray menu toggle**:
```python
# In _build_tray_menu, add before Quit:
pystray.MenuItem(
    lambda item: "Start with Windows  \u2713" if autostart.is_enabled()
                 else "Start with Windows",
    lambda icon, item: autostart.toggle(),
),
pystray.Menu.SEPARATOR,
```

9. **Working directory fix in `main()`**:
```python
def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    ...
```

10. **Streaming clipboard management update**: With `output_method: auto/type`, streaming mode no longer needs session-level clipboard save/restore for short segments. Update `_start_streaming` and `_stop_streaming` to only save/restore clipboard when method is `paste`:
```python
def _start_streaming(self):
    self._segment_context = ""
    method = self.config["ui"]["output_method"]
    if method == "paste":
        self._clipboard_original = save_clipboard()
    else:
        self._clipboard_original = None
    ...

def _stop_streaming(self):
    ...
    if self._clipboard_original is not None:
        restore_clipboard(self._clipboard_original)
    ...
```

**Verification**: `python -m py_compile app.py config.py`

---

### P1-6: Integration compile check and smoke test

**Action**: Compile all modified/new files, run existing tests, manual verification
**Risk tier**: R1

**Compile check**:
```bash
python -m py_compile sounds.py
python -m py_compile autostart.py
python -m py_compile output.py
python -m py_compile recording_indicator.py
python -m py_compile config.py
python -m py_compile app.py
python -m pytest tests/ -v
```

**Manual test plan**:
1. Start app (`python app.py`) — verify no errors, tray icon appears
2. Check tray tooltip shows "Transcriber — Ctrl+Shift+Space to dictate (N terms)"
3. Press Ctrl+Shift+Space — **ascending tone plays**, overlay fades in smoothly with "Listening... 0:00"
4. Watch timer increment: 0:01, 0:02, 0:03...
5. Speak a phrase, pause — text appears in active window via SendInput
6. Verify clipboard unchanged: paste Ctrl+V — should be whatever was copied before recording
7. Hover over overlay — "Stop" button fades in on right side
8. Move mouse away — "Stop" button fades out
9. Click "Stop" button — **descending tone plays**, overlay fades out smoothly
10. Right-click tray — "Start with Windows" visible, click it
11. Verify: `reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v Transcriber`
12. Click "Start with Windows" again — toggle off, verify registry entry removed
13. Test error: unplug mic, press hotkey — **error tone plays**
14. Verify correction auto-popup does NOT appear after transcription (mode changed to hotkey)
15. Verify Ctrl+Shift+C still opens correction window manually

---

## Failure Modes and Mitigations

| # | Failure Mode | Trigger | Impact | Mitigation |
|---|---|---|---|---|
| 1 | keyboard.write() types wrong characters | Modifier keys held during typing | Shortcuts triggered instead of text | `_release_modifiers()` before every write call. 50ms delay for OS processing. Falls back to clipboard paste on exception. |
| 2 | keyboard.write() drops characters | Target app can't keep up with rapid input injection | Missing characters in output | Default delay=0 works for all tested apps. If reports arise, add configurable `ui.type_delay_ms`. |
| 3 | Sound plays but recording doesn't start | winsound.PlaySound succeeds but InputStream fails | Confusing — user heard the tone but nothing records | Sound plays first, then stream opens. If stream fails, play error sound. Both in same try/except block. |
| 4 | WS_EX_NOACTIVATE fails | Older Windows or Tk incompatibility | Click on overlay steals focus | Wrapped in try/except. Overlay still works as read-only display. Stop button is convenience, hotkey is primary. |
| 5 | Registry path stale after venv recreation | User recreates virtualenv at different path | Auto-start launches wrong Python | Log warning on startup if registered path doesn't match. Tray menu re-enable fixes it. |
| 6 | Fade animation stutters under load | Tk event loop busy during heavy transcription | Choppy show/hide | Cancel in-progress animation on conflicting action (e.g., hide during fade-in). Jump to final state. |
| 7 | keyboard.write() blocked by target app | Anti-cheat, DRM, or elevated app blocks injected input | Text doesn't appear | `output_text_streaming()` catches exception and falls back to clipboard paste. Logs warning. |

---

## Risk Tier and Verification Matrix

| Ticket | Risk | Verification |
|--------|------|-------------|
| P1-1: Sound module | R1 | `py_compile sounds.py` + audible playback test |
| P1-2: SendInput output | R2 | `py_compile output.py` + clipboard-preservation test |
| P1-3: Auto-start | R1 | `py_compile autostart.py` + registry verify |
| P1-4: Overlay polish | R2 | `py_compile recording_indicator.py` + visual inspection |
| P1-5: Config + app wiring | R2 | `py_compile app.py config.py` + full smoke test |
| P1-6: Integration test | R1 | All compile checks + pytest + manual smoke test |

---

## Resume Pack

**Goal**: Polish the transcriber UX — sounds, clipboard-free typing, auto-start, overlay fade/timer/hover-stop, tray hints. No new features, just make what exists feel professional.

**Current state**: All source files read. Architecture designed. Research complete (SendInput via keyboard.write(), winsound SND_MEMORY, winreg Run key, WS_EX_NOACTIVATE). No code changes made yet.

**What's ready**:
- `sounds.py` — new file, standalone, no dependencies on other app modules
- `autostart.py` — new file, standalone, winreg stdlib only
- `output.py` — add `type_text()`, `output_text_streaming()`, modifier release ctypes
- `recording_indicator.py` — rewrite with fade, timer, hover-stop, smooth pulse, WS_EX_NOACTIVATE
- `config.py` / `config.yaml` — add `ui` section, change correction_mode to hotkey
- `app.py` — wire sounds, output method, auto-start, tray polish, os.chdir

**Start command**: `/run docs/feature-lists/FEATURE_LIST_UX_POLISH.md`

**Execution order**: P1-1 -> P1-2 -> P1-3 -> P1-4 -> P1-5 -> P1-6
(Build standalone modules first, then overlay, then wire into app, then test)

**First files**: `sounds.py` (new, P1-1), then `output.py` (P1-2), then `autostart.py` (new, P1-3)

**Pending verification**: Full integration smoke test after all tickets complete.

---

## Open Questions

**Q1: Sound volume level?** — Default: 0.3 (30%). Reason: Audible in a quiet room without being startling. User can disable entirely via `ui.sounds: false`. Future: configurable volume slider.

**Q2: keyboard.write() inter-character delay?** — Default: 0 (no delay). Reason: SendInput is atomic per character. Most apps handle rapid input fine. If specific apps drop characters, add `ui.type_delay_ms` config later.

**Q3: Auto-start default?** — Default: `false`. Reason: First enable should be a conscious user choice via tray menu. Registry writes should not surprise the user on first install.

**Q4: Overlay fade duration?** — Default: 120ms (5 steps at 24ms each). Reason: Fast enough to feel responsive, slow enough to notice the transition. Reduce to 72ms if it feels sluggish during testing.

**Q5: Type-vs-paste threshold for auto mode?** — Default: 200 characters. Reason: keyboard.write() at 200 chars takes ~10ms. Clipboard paste takes ~280ms regardless of length. Streaming segments are typically 10-80 chars — well under the threshold.
