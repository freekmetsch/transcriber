"""Floating recording indicator — Win+H-style overlay with polish.

Features: fade transitions, elapsed timer, hover-reveal stop button,
WS_EX_NOACTIVATE (no focus steal), smooth breathing pulse.
"""

import ctypes
import logging
import threading
import time
import tkinter as tk

log = logging.getLogger("transcriber.recording_indicator")

# State -> display configuration
_STATE_CONFIG = {
    "listening":    {"dot": "#E74C3C", "pulse": True,  "text": "Listening\u2026",    "color": "#e0e0e0"},
    "transcribing": {"dot": "#F39C12", "pulse": False, "text": "Transcribing\u2026", "color": "#F39C12"},
    "processing":   {"dot": "#4A90D9", "pulse": False, "text": "Processing\u2026",   "color": "#4A90D9"},
}

# 8-step graduated pulse for breathing effect (1.6s full cycle at 200ms/step)
_PULSE_STEPS_RED = [
    "#E74C3C", "#D9443A", "#C83D35", "#993025",
    "#993025", "#C83D35", "#D9443A", "#E74C3C",
]

# Fade alpha steps (120ms total, 24ms per step)
_FADE_IN_ALPHAS = (0.0, 0.2, 0.4, 0.6, 0.8, 0.9)
_FADE_OUT_ALPHAS = (0.9, 0.7, 0.5, 0.3, 0.1, 0.0)


class RecordingIndicator:
    """Always-on-top overlay showing recording state and transcribed text.

    Runs on its own Tk thread. Thread-safe: call show()/hide()/set_state()/show_text()
    from any thread.
    """

    def __init__(self, on_stop=None):
        self._on_stop = on_stop  # Callback for click-to-stop
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._dot: int | None = None
        self._state_text: int | None = None
        self._result_text: int | None = None
        self._timer_text: int | None = None
        self._stop_bg: int | None = None
        self._stop_label: int | None = None
        self._pulse_active: bool = False
        self._pulse_id: str | None = None
        self._pulse_step: int = 0
        self._fade_id: str | None = None
        self._text_fade_id: str | None = None
        self._timer_id: str | None = None
        self._timer_start: float = 0.0
        self._fading: bool = False
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._current_state: str = "listening"

    def start(self):
        """Start the Tk thread. Call once during app init."""
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_tk(self):
        bg = "#1e1e1e"
        win_w, win_h = 420, 52

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.0)
        self._root.configure(bg=bg)

        screen_w = self._root.winfo_screenwidth()
        x = (screen_w - win_w) // 2
        self._root.geometry(f"{win_w}x{win_h}+{x}+12")

        self._canvas = tk.Canvas(
            self._root, width=win_w, height=win_h,
            bg=bg, highlightthickness=0,
        )
        self._canvas.pack()

        # Red recording dot (left side)
        cx, cy_top, r = 20, 16, 6
        self._dot = self._canvas.create_oval(
            cx - r, cy_top - r, cx + r, cy_top + r,
            fill="#E74C3C", outline="",
        )

        # State text (center, top line)
        self._state_text = self._canvas.create_text(
            cx + r + 12, cy_top,
            text="Listening\u2026",
            fill="#e0e0e0", font=("Segoe UI", 11),
            anchor="w",
        )

        # Elapsed timer (right-aligned, top line)
        self._timer_text = self._canvas.create_text(
            win_w - 72, cy_top,
            text="", fill="#666666", font=("Segoe UI", 9),
            anchor="e",
        )

        # Transcribed text (second line, grey, smaller)
        self._result_text = self._canvas.create_text(
            cx + r + 12, 38,
            text="",
            fill="#888888", font=("Segoe UI", 9),
            anchor="w", width=win_w - 50,
        )

        # Hover-reveal stop button (right side, initially invisible)
        self._stop_bg = self._canvas.create_rectangle(
            win_w - 64, 4, win_w - 4, win_h - 4,
            fill=bg, outline="",
        )
        self._stop_label = self._canvas.create_text(
            win_w - 34, win_h // 2,
            text="Stop", fill=bg,
            font=("Segoe UI", 9),
        )

        # Hover bindings
        self._canvas.bind("<Enter>", lambda e: self._on_hover_enter())
        self._canvas.bind("<Leave>", lambda e: self._on_hover_leave())
        self._canvas.tag_bind(self._stop_bg, "<Button-1>", lambda e: self._on_stop_click())
        self._canvas.tag_bind(self._stop_label, "<Button-1>", lambda e: self._on_stop_click())

        # Set WS_EX_NOACTIVATE to prevent focus stealing
        self._set_no_activate()

        self._root.withdraw()
        self._ready.set()
        self._root.mainloop()

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

    # --- Hover-reveal stop button ---

    def _on_hover_enter(self):
        self._canvas.itemconfig(self._stop_bg, fill="#333333")
        self._canvas.itemconfig(self._stop_label, fill="#e0e0e0")
        # Move timer out of the way when stop button is visible
        self._canvas.itemconfig(self._timer_text, state="hidden")

    def _on_hover_leave(self):
        bg = "#1e1e1e"
        self._canvas.itemconfig(self._stop_bg, fill=bg)
        self._canvas.itemconfig(self._stop_label, fill=bg)
        self._canvas.itemconfig(self._timer_text, state="normal")

    def _on_stop_click(self):
        if self._on_stop:
            self._on_stop()

    # --- Fade animations ---

    def _fade_in_step(self, step):
        if self._root is None:
            return
        if step < len(_FADE_IN_ALPHAS):
            self._root.attributes("-alpha", _FADE_IN_ALPHAS[step])
            self._fade_id = self._root.after(24, lambda: self._fade_in_step(step + 1))
        else:
            self._fading = False

    def _fade_out_step(self, step):
        if self._root is None:
            return
        if step < len(_FADE_OUT_ALPHAS):
            self._root.attributes("-alpha", _FADE_OUT_ALPHAS[step])
            if step < len(_FADE_OUT_ALPHAS) - 1:
                self._fade_id = self._root.after(24, lambda: self._fade_out_step(step + 1))
            else:
                self._fade_id = None
                self._fading = False
                self._root.withdraw()
                self._root.attributes("-alpha", 0.9)  # Reset for next show
        else:
            self._fading = False

    def _cancel_fade(self):
        """Cancel any in-progress fade animation."""
        if self._fade_id is not None:
            self._root.after_cancel(self._fade_id)
            self._fade_id = None
        self._fading = False

    # --- Elapsed timer ---

    def _start_timer(self):
        self._timer_start = time.monotonic()
        self._canvas.itemconfig(self._timer_text, text="0:00")
        self._timer_id = self._root.after(1000, self._update_timer)

    def _update_timer(self):
        if self._root is None:
            return
        elapsed = int(time.monotonic() - self._timer_start)
        minutes, seconds = divmod(elapsed, 60)
        self._canvas.itemconfig(self._timer_text, text=f"{minutes}:{seconds:02d}")
        self._timer_id = self._root.after(1000, self._update_timer)

    def _cancel_timer(self):
        if self._timer_id is not None:
            self._root.after_cancel(self._timer_id)
            self._timer_id = None
        if self._canvas:
            self._canvas.itemconfig(self._timer_text, text="")

    # --- Smooth pulse animation (breathing effect) ---

    def _pulse(self):
        if self._canvas is None or not self._pulse_active:
            return
        color = _PULSE_STEPS_RED[self._pulse_step % len(_PULSE_STEPS_RED)]
        self._canvas.itemconfig(self._dot, fill=color)
        self._pulse_step += 1
        self._pulse_id = self._root.after(200, self._pulse)

    def _start_pulse(self):
        if not self._pulse_active:
            self._pulse_active = True
            self._pulse_step = 0
            self._pulse_id = self._root.after(200, self._pulse)

    def _stop_pulse(self):
        self._pulse_active = False
        if self._pulse_id is not None:
            self._root.after_cancel(self._pulse_id)
            self._pulse_id = None

    # --- Public API (all thread-safe) ---

    def show(self):
        """Show the indicator (recording started). Thread-safe."""
        if self._root:
            self._root.after(0, self._do_show)

    def _do_show(self):
        self._cancel_fade()
        self._current_state = "listening"
        self._apply_state()
        self._canvas.itemconfig(self._result_text, text="")
        self._start_timer()
        self._root.attributes("-alpha", 0.0)
        self._root.deiconify()
        self._root.lift()
        self._fading = True
        self._fade_in_step(0)

    def hide(self):
        """Hide the indicator (recording stopped). Thread-safe."""
        if self._root:
            self._root.after(0, self._do_hide)

    def _do_hide(self):
        self._stop_pulse()
        self._cancel_timer()
        # Cancel any pending text fade
        if self._text_fade_id is not None:
            self._root.after_cancel(self._text_fade_id)
            self._text_fade_id = None
        # If currently fading in, cancel and fade out instead
        self._cancel_fade()
        self._fading = True
        self._fade_out_step(0)

    def set_state(self, state: str):
        """Set display state: 'listening', 'transcribing', or 'processing'. Thread-safe."""
        if self._root and state in _STATE_CONFIG:
            self._root.after(0, lambda: self._do_set_state(state))

    def _do_set_state(self, state: str):
        self._current_state = state
        self._apply_state()

    def _apply_state(self):
        """Apply the current state's visual configuration."""
        cfg = _STATE_CONFIG[self._current_state]
        self._canvas.itemconfig(self._dot, fill=cfg["dot"])
        self._canvas.itemconfig(self._state_text, text=cfg["text"], fill=cfg["color"])

        self._stop_pulse()
        if cfg["pulse"]:
            self._start_pulse()

    def show_text(self, text: str):
        """Show transcribed text briefly (auto-fades after 3s). Thread-safe."""
        if self._root:
            self._root.after(0, lambda: self._do_show_text(text))

    def _do_show_text(self, text: str):
        # Cancel any pending fade
        if self._text_fade_id is not None:
            self._root.after_cancel(self._text_fade_id)

        # Truncate long text for display
        display = text if len(text) <= 60 else text[:57] + "\u2026"
        self._canvas.itemconfig(self._result_text, text=display)

        # Auto-fade after 3 seconds
        self._text_fade_id = self._root.after(3000, self._do_fade_text)

    def _do_fade_text(self):
        self._text_fade_id = None
        self._canvas.itemconfig(self._result_text, text="")

    def destroy(self):
        """Shut down the Tk thread."""
        if self._root:
            self._root.after(0, self._root.destroy)
