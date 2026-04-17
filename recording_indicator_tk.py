"""Floating recording indicator — Windows+H-style pill bar.

Always-visible pill with gear menu (left), mic toggle button (center), and
close X (right). Features: fade transitions, draggable, position persistence,
WS_EX_NOACTIVATE (no focus steal), state-based mic color, floating text popup.
"""

import ctypes
import json
import logging
import threading
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("transcriber.recording_indicator")

_POS_FILE = Path(__file__).parent / "indicator_pos.json"

_WIN_W, _WIN_H = 230, 48

# Click zones (Canvas x-coordinates)
_GEAR_X_MAX = 30         # x <= 30 → gear (opens menu)
_MIC_X_MIN = 50          # 50 <= x <= 130 → mic button (toggle recording)
_MIC_X_MAX = 130
_MODE_X_MIN = 162        # 162 <= x <= 206 → mode chip (cycle modes)
_MODE_X_MAX = 206
_CLOSE_X_MIN = 208       # x >= 208 → close X (dismiss overlay)

_FADE_IN_ALPHAS = (0.0, 0.2, 0.4, 0.6, 0.8, 0.92)
_FADE_OUT_ALPHAS = (0.92, 0.7, 0.5, 0.3, 0.1, 0.0)

# Mic color breathing steps for transcribing state (1.6s cycle, 200ms/step)
_PULSE_STEPS = [
    "#F39C12", "#E8921A", "#D9851F", "#C87820",
    "#C87820", "#D9851F", "#E8921A", "#F39C12",
]

# State -> mic icon color
_STATE_COLORS = {
    "idle":         "#666666",  # Dim grey — default, between sessions
    "listening":    "#e0e0e0",  # White
    "transcribing": "#F39C12",  # Orange
    "processing":   "#4A90D9",  # Blue
}


class RecordingIndicator:
    """Always-visible pill-bar overlay. Thread-safe public API.

    States:
      idle         — default; dim mic, no level bar, no timer
      listening    — recording; white mic, live level bar, elapsed timer
      transcribing — working on an utterance; pulsing orange mic
      processing   — post-processing; blue mic

    The pill stays visible from start() until dismiss() is called. end_session()
    transitions to idle but does NOT hide the window.
    """

    def __init__(
        self,
        on_mic_click: Callable[[], None] | None = None,
        on_dismiss: Callable[[], None] | None = None,
        get_menu_items: Callable[[], list] | None = None,
        visible_on_start: bool = True,
        get_mode_name: Callable[[], str] | None = None,
        on_mode_click: Callable[[], None] | None = None,
    ):
        self._on_mic_click = on_mic_click
        self._on_dismiss_notify = on_dismiss
        self._get_menu_items = get_menu_items
        self._visible_on_start = visible_on_start
        self._get_mode_name = get_mode_name
        self._on_mode_click = on_mode_click
        self._dismissed = not visible_on_start

        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._mic_items: list[int] = []
        self._pulse_active = False
        self._pulse_id: str | None = None
        self._pulse_step = 0
        self._fade_id: str | None = None
        self._fading = False
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._current_state = "idle"

        self._drag_data: dict | None = None

        self._text_window: tk.Toplevel | None = None
        self._text_canvas: tk.Canvas | None = None
        self._text_item: int | None = None
        self._text_badge_item: int | None = None
        self._text_fade_id: str | None = None
        self._text_popup_w = 360

        self._level_bar: int | None = None
        self._timer_item: int | None = None
        self._timer_start = 0.0
        self._timer_id: str | None = None
        self._gear_item: int | None = None
        self._close_item: int | None = None
        self._mode_chip_rect: int | None = None
        self._mode_chip_text: int | None = None

    def start(self):
        """Start the Tk thread. Call once during app init."""
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    # --- Position persistence ---

    def _load_position(self) -> tuple[int, int] | None:
        try:
            if _POS_FILE.exists():
                data = json.loads(_POS_FILE.read_text(encoding="utf-8"))
                return int(data["x"]), int(data["y"])
        except Exception:
            pass
        return None

    def _save_position(self):
        if self._root is None:
            return
        try:
            _POS_FILE.write_text(
                json.dumps({"x": self._root.winfo_x(), "y": self._root.winfo_y()}),
                encoding="utf-8",
            )
        except Exception:
            log.debug("Could not save indicator position")

    # --- Tk setup ---

    def _run_tk(self):
        key_color = "#ff00ff"
        bar_bg = "#1e1e1e"

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.0)
        self._root.attributes("-transparentcolor", key_color)
        self._root.configure(bg=key_color)

        saved = self._load_position()
        if saved:
            x, y = saved
        else:
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()
            x = (sw - _WIN_W) // 2
            y = sh - _WIN_H - 60
        self._root.geometry(f"{_WIN_W}x{_WIN_H}+{x}+{y}")

        self._canvas = tk.Canvas(
            self._root, width=_WIN_W, height=_WIN_H,
            bg=key_color, highlightthickness=0,
        )
        self._canvas.pack()

        self._draw_pill(self._canvas, 0, 0, _WIN_W, _WIN_H, _WIN_H // 2, bar_bg)

        # Gear glyph (left) — opens popup menu
        self._gear_item = self._canvas.create_text(
            18, _WIN_H // 2,
            text="\u2699", fill="#888888",
            font=("Segoe UI Symbol", 12), anchor="center",
        )

        # Microphone icon (center)
        cx = _WIN_W // 2
        self._draw_mic(cx, _WIN_H // 2, _STATE_COLORS["idle"])

        # Level bar below mic (hidden until update_level fires)
        self._level_bar = self._canvas.create_rectangle(
            cx, 42, cx, 45,
            fill=_STATE_COLORS["idle"], outline="",
        )

        # Elapsed timer between mic and mode chip
        self._timer_item = self._canvas.create_text(
            150, _WIN_H // 2,
            text="", fill="#888888",
            font=("Segoe UI", 9), anchor="center",
        )

        # Mode chip (click to cycle dictation modes)
        self._mode_chip_rect = self._canvas.create_rectangle(
            _MODE_X_MIN + 2, 15, _MODE_X_MAX - 2, 33,
            fill="#2a2a2a", outline="#555555", width=1,
        )
        self._mode_chip_text = self._canvas.create_text(
            (_MODE_X_MIN + _MODE_X_MAX) // 2, _WIN_H // 2,
            text=self._get_mode_name() if self._get_mode_name else "",
            fill="#bbbbbb", font=("Segoe UI", 8), anchor="center",
        )

        # Close X (right) — dismisses the overlay
        self._close_item = self._canvas.create_text(
            _WIN_W - 14, _WIN_H // 2,
            text="\u2715", fill="#888888",
            font=("Segoe UI", 11, "bold"), anchor="center",
        )

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Enter>", self._on_hover_enter)
        self._canvas.bind("<Leave>", self._on_hover_leave)

        self._init_text_popup(key_color)

        self._set_no_activate(self._root)
        self._root.after(100, lambda: self._set_no_activate(self._text_window))

        if self._visible_on_start:
            self._root.attributes("-alpha", 0.0)
            self._root.deiconify()
            self._fading = True
            self._fade_in_step(0)
        else:
            self._root.withdraw()

        self._ready.set()
        self._root.mainloop()

    def _init_text_popup(self, key_color):
        tp_w, tp_h = self._text_popup_w, 32
        self._text_window = tk.Toplevel(self._root)
        self._text_window.overrideredirect(True)
        self._text_window.attributes("-topmost", True)
        self._text_window.attributes("-transparentcolor", key_color)
        self._text_window.configure(bg=key_color)
        self._text_window.geometry(f"{tp_w}x{tp_h}+0+0")

        self._text_canvas = tk.Canvas(
            self._text_window, width=tp_w, height=tp_h,
            bg=key_color, highlightthickness=0,
        )
        self._text_canvas.pack()
        self._draw_pill(self._text_canvas, 0, 0, tp_w, tp_h, tp_h // 2, "#2a2a2a")
        self._text_badge_item = self._text_canvas.create_text(
            18, tp_h // 2,
            text="", fill="#2ECC71",
            font=("Segoe UI", 9, "bold"), anchor="w",
        )
        self._text_item = self._text_canvas.create_text(
            tp_w // 2, tp_h // 2,
            text="", fill="#cccccc", font=("Segoe UI", 10),
            anchor="center", width=tp_w - 24,
        )
        self._text_window.withdraw()

    # --- Drawing helpers ---

    @staticmethod
    def _draw_pill(canvas, x1, y1, x2, y2, r, fill):
        canvas.create_oval(x1, y1, x1 + 2 * r, y2, fill=fill, outline="")
        canvas.create_oval(x2 - 2 * r, y1, x2, y2, fill=fill, outline="")
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")

    def _draw_mic(self, cx, cy, color):
        self._mic_items = []
        c = self._canvas
        self._mic_items.append(
            c.create_oval(cx - 5, cy - 14, cx + 5, cy - 2, fill=color, outline=""))
        self._mic_items.append(
            c.create_rectangle(cx - 5, cy - 10, cx + 5, cy - 2, fill=color, outline=""))
        self._mic_items.append(
            c.create_arc(cx - 9, cy - 10, cx + 9, cy + 6,
                         start=180, extent=180, style="arc", outline=color, width=2))
        self._mic_items.append(
            c.create_line(cx, cy + 6, cx, cy + 12, fill=color, width=2))
        self._mic_items.append(
            c.create_line(cx - 6, cy + 12, cx + 6, cy + 12, fill=color, width=2))

    def _recolor_mic(self, color):
        for item_id in self._mic_items:
            itype = self._canvas.type(item_id)
            if itype == "arc":
                self._canvas.itemconfig(item_id, outline=color)
            elif itype == "line":
                self._canvas.itemconfig(item_id, fill=color)
            else:
                self._canvas.itemconfig(item_id, fill=color)

    # --- Mouse handling ---

    def _on_press(self, event):
        # Gear (left) → menu
        if event.x <= _GEAR_X_MAX:
            self._drag_data = None
            self._show_menu()
            return
        # Close X (right) → dismiss
        if event.x >= _CLOSE_X_MIN:
            self._drag_data = None
            self._do_dismiss(notify=True)
            return
        # Mic zone (center) → toggle recording
        if _MIC_X_MIN <= event.x <= _MIC_X_MAX:
            self._drag_data = None
            if self._on_mic_click is not None:
                try:
                    self._on_mic_click()
                except Exception:
                    log.exception("on_mic_click callback failed")
            return
        # Mode chip zone → cycle modes
        if _MODE_X_MIN <= event.x <= _MODE_X_MAX:
            self._drag_data = None
            if self._on_mode_click is not None:
                try:
                    self._on_mode_click()
                except Exception:
                    log.exception("on_mode_click callback failed")
            return
        # Anywhere else → drag
        self._drag_data = {
            "ox": event.x_root - self._root.winfo_x(),
            "oy": event.y_root - self._root.winfo_y(),
        }

    def _on_drag(self, event):
        if self._drag_data is None:
            return
        x = event.x_root - self._drag_data["ox"]
        y = event.y_root - self._drag_data["oy"]
        self._root.geometry(f"+{x}+{y}")

    def _on_release(self, event):
        if self._drag_data is not None:
            self._drag_data = None
            self._save_position()

    def _on_hover_enter(self, event):
        if self._gear_item is not None:
            self._canvas.itemconfig(self._gear_item, fill="#cccccc")
        if self._close_item is not None:
            self._canvas.itemconfig(self._close_item, fill="#cccccc")

    def _on_hover_leave(self, event):
        if self._gear_item is not None:
            self._canvas.itemconfig(self._gear_item, fill="#888888")
        if self._close_item is not None:
            self._canvas.itemconfig(self._close_item, fill="#888888")

    def _show_menu(self):
        items: list = []
        if self._get_menu_items is not None:
            try:
                items = self._get_menu_items() or []
            except Exception:
                log.exception("get_menu_items raised")
                items = []

        menu = tk.Menu(
            self._root, tearoff=0,
            bg="#2a2a2a", fg="#e0e0e0",
            activebackground="#444444", activeforeground="#ffffff",
            font=("Segoe UI", 10),
        )
        for entry in items:
            if entry is None:
                menu.add_separator()
                continue
            label, callback = entry
            if callback is None:
                menu.add_command(label=label, state="disabled")
            else:
                menu.add_command(label=label, command=callback)
        try:
            menu.tk_popup(
                self._root.winfo_x() + 10,
                self._root.winfo_y() + _WIN_H + 4,
            )
        finally:
            menu.grab_release()

    # --- WS_EX_NOACTIVATE ---

    @staticmethod
    def _set_no_activate(window):
        try:
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        except Exception:
            log.debug("Could not set WS_EX_NOACTIVATE")

    # --- Fade animations ---

    def _fade_in_step(self, step):
        if self._root is None:
            return
        if step < len(_FADE_IN_ALPHAS):
            self._root.attributes("-alpha", _FADE_IN_ALPHAS[step])
            self._fade_id = self._root.after(24, lambda: self._fade_in_step(step + 1))
        else:
            self._fading = False
            self._fade_id = None

    def _fade_out_step(self, step, on_done=None):
        if self._root is None:
            return
        if step < len(_FADE_OUT_ALPHAS):
            self._root.attributes("-alpha", _FADE_OUT_ALPHAS[step])
            if step < len(_FADE_OUT_ALPHAS) - 1:
                self._fade_id = self._root.after(
                    24, lambda: self._fade_out_step(step + 1, on_done))
            else:
                self._fade_id = None
                self._fading = False
                if on_done is not None:
                    on_done()

    def _cancel_fade(self):
        if self._fade_id is not None and self._root is not None:
            try:
                self._root.after_cancel(self._fade_id)
            except Exception:
                pass
            self._fade_id = None
        self._fading = False

    # --- Pulse animation (mic color breathing for transcribing state) ---

    def _pulse(self):
        if self._canvas is None or not self._pulse_active:
            return
        color = _PULSE_STEPS[self._pulse_step % len(_PULSE_STEPS)]
        self._recolor_mic(color)
        self._pulse_step += 1
        self._pulse_id = self._root.after(200, self._pulse)

    def _start_pulse(self):
        if not self._pulse_active:
            self._pulse_active = True
            self._pulse_step = 0
            self._pulse_id = self._root.after(200, self._pulse)

    def _stop_pulse(self):
        self._pulse_active = False
        if self._pulse_id is not None and self._root is not None:
            try:
                self._root.after_cancel(self._pulse_id)
            except Exception:
                pass
            self._pulse_id = None

    # --- Text popup positioning ---

    def _position_text_popup(self):
        bar_x = self._root.winfo_x()
        bar_y = self._root.winfo_y()
        tp_x = bar_x + (_WIN_W - self._text_popup_w) // 2
        tp_y = bar_y - 40
        self._text_window.geometry(f"+{tp_x}+{tp_y}")

    # --- Public API (all thread-safe) ---

    def begin_session(self):
        """Transition to listening state. Restores if dismissed. Thread-safe."""
        if self._root:
            self._root.after(0, self._do_begin_session)

    def _do_begin_session(self):
        if self._dismissed:
            self._do_restore()
        self._cancel_fade()
        self._current_state = "listening"
        self._stop_pulse()
        self._recolor_mic(_STATE_COLORS["listening"])
        self._reset_level_bar()
        self._start_timer()

    def end_session(self):
        """Transition to idle. Window stays visible. Thread-safe."""
        if self._root:
            self._root.after(0, self._do_end_session)

    def _do_end_session(self):
        self._stop_pulse()
        self._cancel_timer()
        self._reset_level_bar()
        if self._text_fade_id is not None:
            try:
                self._root.after_cancel(self._text_fade_id)
            except Exception:
                pass
            self._text_fade_id = None
        if self._text_window:
            self._text_window.withdraw()
        self._current_state = "idle"
        self._recolor_mic(_STATE_COLORS["idle"])

    def dismiss(self):
        """Fade out and withdraw the overlay window. Thread-safe."""
        if self._root:
            self._root.after(0, lambda: self._do_dismiss(notify=True))

    def _do_dismiss(self, notify: bool = True):
        if self._dismissed:
            return
        self._dismissed = True
        self._stop_pulse()
        self._cancel_timer()
        if self._text_window:
            self._text_window.withdraw()
        self._cancel_fade()
        self._fading = True
        self._fade_out_step(0, on_done=self._finish_dismiss)
        if notify and self._on_dismiss_notify is not None:
            try:
                self._on_dismiss_notify()
            except Exception:
                log.exception("on_dismiss callback failed")

    def _finish_dismiss(self):
        if self._root:
            self._root.withdraw()
            self._root.attributes("-alpha", 0.92)

    def restore(self):
        """Deiconify and fade in the overlay. Thread-safe."""
        if self._root:
            self._root.after(0, self._do_restore)

    def _do_restore(self):
        if not self._dismissed:
            return
        self._dismissed = False
        self._cancel_fade()
        self._current_state = "idle"
        self._recolor_mic(_STATE_COLORS["idle"])
        self._reset_level_bar()
        self._root.attributes("-alpha", 0.0)
        self._root.deiconify()
        self._root.lift()
        self._fading = True
        self._fade_in_step(0)

    def toggle_visibility(self):
        """Toggle dismissed state. Thread-safe. Used by overlay-toggle hotkey."""
        if self._root:
            self._root.after(0, self._do_toggle_visibility)

    def _do_toggle_visibility(self):
        if self._dismissed:
            self._do_restore()
        else:
            self._do_dismiss(notify=False)

    def is_dismissed(self) -> bool:
        return self._dismissed

    def refresh_mode(self):
        """Re-render the mode chip label from get_mode_name(). Thread-safe."""
        if self._root:
            self._root.after(0, self._do_refresh_mode)

    def _do_refresh_mode(self):
        if self._mode_chip_text is None or self._canvas is None:
            return
        name = self._get_mode_name() if self._get_mode_name else ""
        self._canvas.itemconfig(self._mode_chip_text, text=name)

    def set_state(self, state: str):
        """Set display state: idle | listening | transcribing | processing. Thread-safe."""
        if self._root and state in _STATE_COLORS:
            self._root.after(0, lambda: self._do_set_state(state))

    def _do_set_state(self, state: str):
        prev = self._current_state
        self._current_state = state
        self._stop_pulse()
        self._recolor_mic(_STATE_COLORS[state])
        if state == "transcribing":
            self._start_pulse()
        elif state in ("listening", "idle") and prev != state:
            self._reset_level_bar()

    def show_text(self, text: str, language: str = "", confidence: float = 1.0):
        """Show transcribed text as popup above bar (auto-fades after 3s). Thread-safe."""
        if self._root:
            self._root.after(0, lambda: self._do_show_text(text, language, confidence))

    def _do_show_text(self, text: str, language: str = "", confidence: float = 1.0):
        if self._dismissed:
            return
        if self._text_fade_id is not None:
            try:
                self._root.after_cancel(self._text_fade_id)
            except Exception:
                pass
        display = text if len(text) <= 60 else text[:57] + "\u2026"
        self._text_canvas.itemconfig(self._text_item, text=display)
        if language:
            if confidence > 0.8:
                badge_color = "#2ECC71"
            elif confidence > 0.5:
                badge_color = "#F1C40F"
            else:
                badge_color = "#E67E22"
            self._text_canvas.itemconfig(
                self._text_badge_item,
                text=language.upper(),
                fill=badge_color,
            )
        else:
            self._text_canvas.itemconfig(self._text_badge_item, text="")
        self._position_text_popup()
        self._text_window.deiconify()
        self._text_window.lift()
        self._text_fade_id = self._root.after(3000, self._do_fade_text)

    def _do_fade_text(self):
        self._text_fade_id = None
        if self._text_window:
            self._text_window.withdraw()

    # --- Level bar ---

    def update_level(self, rms: float):
        """Update the mic level bar. Thread-safe."""
        if self._root and self._current_state == "listening":
            self._root.after(0, self._do_update_level, rms)

    def _do_update_level(self, rms: float):
        if self._level_bar is None or self._canvas is None:
            return
        if self._current_state != "listening":
            return
        width = min(max(rms, 0.0) / 0.05, 1.0) * 50.0
        cx = _WIN_W // 2
        half = width / 2.0
        self._canvas.coords(self._level_bar, cx - half, 42, cx + half, 45)
        color = _STATE_COLORS.get(self._current_state, "#e0e0e0")
        self._canvas.itemconfig(self._level_bar, fill=color)

    def _reset_level_bar(self):
        if self._level_bar is None or self._canvas is None:
            return
        cx = _WIN_W // 2
        self._canvas.coords(self._level_bar, cx, 42, cx, 45)

    # --- Elapsed timer ---

    def _start_timer(self):
        self._cancel_timer()
        self._timer_start = time.monotonic()
        self._canvas.itemconfig(self._timer_item, text="0:00")
        self._timer_id = self._root.after(1000, self._update_timer)

    def _update_timer(self):
        if self._timer_item is None or self._canvas is None:
            return
        elapsed = int(time.monotonic() - self._timer_start)
        self._canvas.itemconfig(
            self._timer_item,
            text=f"{elapsed // 60}:{elapsed % 60:02d}",
        )
        self._timer_id = self._root.after(1000, self._update_timer)

    def _cancel_timer(self):
        if self._timer_id is not None and self._root is not None:
            try:
                self._root.after_cancel(self._timer_id)
            except Exception:
                pass
            self._timer_id = None
        if self._timer_item is not None and self._canvas is not None:
            self._canvas.itemconfig(self._timer_item, text="")

    def show_feedback(self, feedback_type: str = "success"):
        """Flash the mic icon briefly. Works even when dismissed. Thread-safe."""
        if self._root:
            self._root.after(0, lambda: self._do_show_feedback(feedback_type))

    def _do_show_feedback(self, feedback_type: str):
        colors = {
            "success": "#2ECC71",
            "warning": "#F1C40F",
            "error": "#E74C3C",
        }
        color = colors.get(feedback_type, "#2ECC71")
        was_dismissed = self._dismissed

        if was_dismissed:
            self._do_restore()

        self._stop_pulse()
        self._recolor_mic(color)

        def _revert():
            if was_dismissed:
                self._do_dismiss(notify=False)
            else:
                state_color = _STATE_COLORS.get(self._current_state, _STATE_COLORS["idle"])
                self._recolor_mic(state_color)
                if self._current_state == "transcribing":
                    self._start_pulse()

        self._root.after(350, _revert)

    def destroy(self):
        """Shut down the Tk thread."""
        if self._root:
            self._root.after(0, self._root.destroy)
