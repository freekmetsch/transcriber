"""Floating recording indicator — Windows+H-style pill bar.

Compact pill bar with drag handle, mic icon, and menu button.
Features: fade transitions, draggable, position persistence,
WS_EX_NOACTIVATE (no focus steal), state-based mic color changes,
floating text popup above bar.
"""

import ctypes
import json
import logging
import threading
import tkinter as tk
from pathlib import Path

log = logging.getLogger("transcriber.recording_indicator")

# Position persistence
_POS_FILE = Path(__file__).parent / "indicator_pos.json"

# Bar dimensions
_WIN_W, _WIN_H = 200, 48
_MENU_ZONE_X = 160  # Clicks right of this open the menu

# Fade alpha steps (120ms total, 24ms per step)
_FADE_IN_ALPHAS = (0.0, 0.2, 0.4, 0.6, 0.8, 0.92)
_FADE_OUT_ALPHAS = (0.92, 0.7, 0.5, 0.3, 0.1, 0.0)

# Mic color breathing steps for transcribing state (1.6s cycle, 200ms/step)
_PULSE_STEPS = [
    "#F39C12", "#E8921A", "#D9851F", "#C87820",
    "#C87820", "#D9851F", "#E8921A", "#F39C12",
]

# State -> mic icon color
_STATE_COLORS = {
    "listening":    "#e0e0e0",  # White
    "transcribing": "#F39C12",  # Orange
    "processing":   "#4A90D9",  # Blue
}


class RecordingIndicator:
    """Always-on-top pill-bar overlay showing recording state.

    Runs on its own Tk thread. Thread-safe: call show()/hide()/set_state()/show_text()
    from any thread.
    """

    def __init__(self, on_stop=None):
        self._on_stop = on_stop
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._mic_items: list[int] = []
        self._pulse_active: bool = False
        self._pulse_id: str | None = None
        self._pulse_step: int = 0
        self._fade_id: str | None = None
        self._fading: bool = False
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._current_state: str = "listening"
        # Drag
        self._drag_data: dict | None = None
        # Text popup
        self._text_window: tk.Toplevel | None = None
        self._text_canvas: tk.Canvas | None = None
        self._text_item: int | None = None
        self._text_fade_id: str | None = None
        self._text_popup_w: int = 360

    def start(self):
        """Start the Tk thread. Call once during app init."""
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    # --- Position persistence ---

    def _load_position(self) -> tuple[int, int] | None:
        """Load saved bar position from file."""
        try:
            if _POS_FILE.exists():
                data = json.loads(_POS_FILE.read_text(encoding="utf-8"))
                return int(data["x"]), int(data["y"])
        except Exception:
            pass
        return None

    def _save_position(self):
        """Save current bar position to file (called on drag-end only)."""
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
        key_color = "#ff00ff"  # Transparent key — invisible corners for pill shape
        bar_bg = "#1e1e1e"

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.0)
        self._root.attributes("-transparentcolor", key_color)
        self._root.configure(bg=key_color)

        # Position: saved or bottom-center, 60px from bottom edge
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

        # Pill-shaped background (overlapping ovals + rectangle)
        self._draw_pill(self._canvas, 0, 0, _WIN_W, _WIN_H, _WIN_H // 2, bar_bg)

        # Drag handle: 3 thin vertical gray lines (left zone)
        for i in range(3):
            lx = 16 + i * 5
            self._canvas.create_line(lx, 16, lx, 32, fill="#555555", width=1.5)

        # Microphone icon (center)
        self._draw_mic(_WIN_W // 2, _WIN_H // 2, _STATE_COLORS["listening"])

        # Menu dots (right zone)
        self._canvas.create_text(
            _WIN_W - 24, _WIN_H // 2,
            text="\u2022\u2022\u2022", fill="#888888",
            font=("Segoe UI", 11), anchor="center",
        )

        # Mouse bindings
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)

        # Text popup (separate toplevel, hidden by default)
        self._init_text_popup(key_color)

        # Prevent focus stealing on both windows
        self._set_no_activate(self._root)
        self._root.after(100, lambda: self._set_no_activate(self._text_window))

        self._root.withdraw()
        self._ready.set()
        self._root.mainloop()

    def _init_text_popup(self, key_color):
        """Create the floating text popup window (appears above the bar)."""
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
        self._text_item = self._text_canvas.create_text(
            tp_w // 2, tp_h // 2,
            text="", fill="#cccccc", font=("Segoe UI", 10),
            anchor="center", width=tp_w - 24,
        )
        self._text_window.withdraw()

    # --- Drawing helpers ---

    @staticmethod
    def _draw_pill(canvas, x1, y1, x2, y2, r, fill):
        """Draw a pill (rounded rectangle) using overlapping ovals + rectangle."""
        canvas.create_oval(x1, y1, x1 + 2 * r, y2, fill=fill, outline="")
        canvas.create_oval(x2 - 2 * r, y1, x2, y2, fill=fill, outline="")
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="")

    def _draw_mic(self, cx, cy, color):
        """Draw a microphone icon at (cx, cy). Stores item IDs for recoloring."""
        self._mic_items = []
        c = self._canvas
        # Capsule top (oval)
        self._mic_items.append(
            c.create_oval(cx - 5, cy - 14, cx + 5, cy - 2, fill=color, outline=""))
        # Capsule body (rect fills the oval gap)
        self._mic_items.append(
            c.create_rectangle(cx - 5, cy - 10, cx + 5, cy - 2, fill=color, outline=""))
        # Cradle (U-shape arc below capsule)
        self._mic_items.append(
            c.create_arc(cx - 9, cy - 10, cx + 9, cy + 6,
                         start=180, extent=180, style="arc", outline=color, width=2))
        # Stem (vertical line)
        self._mic_items.append(
            c.create_line(cx, cy + 6, cx, cy + 12, fill=color, width=2))
        # Base (horizontal line)
        self._mic_items.append(
            c.create_line(cx - 6, cy + 12, cx + 6, cy + 12, fill=color, width=2))

    def _recolor_mic(self, color):
        """Change the mic icon to a new color."""
        for item_id in self._mic_items:
            itype = self._canvas.type(item_id)
            if itype == "arc":
                self._canvas.itemconfig(item_id, outline=color)
            elif itype == "line":
                self._canvas.itemconfig(item_id, fill=color)
            else:
                self._canvas.itemconfig(item_id, fill=color)

    # --- Mouse handling (drag + menu) ---

    def _on_press(self, event):
        if event.x > _MENU_ZONE_X:
            self._drag_data = None
            self._show_menu()
        else:
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

    def _show_menu(self):
        menu = tk.Menu(
            self._root, tearoff=0,
            bg="#2a2a2a", fg="#e0e0e0",
            activebackground="#444444", activeforeground="#ffffff",
            font=("Segoe UI", 10),
        )
        menu.add_command(label="Stop", command=self._on_stop_click)
        try:
            menu.tk_popup(
                self._root.winfo_x() + _WIN_W - 10,
                self._root.winfo_y() - 5,
            )
        finally:
            menu.grab_release()

    def _on_stop_click(self):
        if self._on_stop:
            self._on_stop()

    # --- WS_EX_NOACTIVATE ---

    @staticmethod
    def _set_no_activate(window):
        """Prevent a window from stealing focus when clicked."""
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
                self._root.attributes("-alpha", 0.92)  # Reset for next show
        else:
            self._fading = False

    def _cancel_fade(self):
        """Cancel any in-progress fade animation."""
        if self._fade_id is not None:
            self._root.after_cancel(self._fade_id)
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
        if self._pulse_id is not None:
            self._root.after_cancel(self._pulse_id)
            self._pulse_id = None

    # --- Text popup positioning ---

    def _position_text_popup(self):
        """Position the text popup centered above the bar."""
        bar_x = self._root.winfo_x()
        bar_y = self._root.winfo_y()
        tp_x = bar_x + (_WIN_W - self._text_popup_w) // 2
        tp_y = bar_y - 40
        self._text_window.geometry(f"+{tp_x}+{tp_y}")

    # --- Public API (all thread-safe) ---

    def show(self):
        """Show the indicator (recording started). Thread-safe."""
        if self._root:
            self._root.after(0, self._do_show)

    def _do_show(self):
        self._cancel_fade()
        self._current_state = "listening"
        self._stop_pulse()
        self._recolor_mic(_STATE_COLORS["listening"])
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
        if self._text_fade_id is not None:
            self._root.after_cancel(self._text_fade_id)
            self._text_fade_id = None
        if self._text_window:
            self._text_window.withdraw()
        self._cancel_fade()
        self._fading = True
        self._fade_out_step(0)

    def set_state(self, state: str):
        """Set display state: 'listening', 'transcribing', or 'processing'. Thread-safe."""
        if self._root and state in _STATE_COLORS:
            self._root.after(0, lambda: self._do_set_state(state))

    def _do_set_state(self, state: str):
        self._current_state = state
        self._stop_pulse()
        self._recolor_mic(_STATE_COLORS[state])
        if state == "transcribing":
            self._start_pulse()

    def show_text(self, text: str):
        """Show transcribed text as popup above bar (auto-fades after 3s). Thread-safe."""
        if self._root:
            self._root.after(0, lambda: self._do_show_text(text))

    def _do_show_text(self, text: str):
        if self._text_fade_id is not None:
            self._root.after_cancel(self._text_fade_id)
        display = text if len(text) <= 60 else text[:57] + "\u2026"
        self._text_canvas.itemconfig(self._text_item, text=display)
        self._position_text_popup()
        self._text_window.deiconify()
        self._text_window.lift()
        self._text_fade_id = self._root.after(3000, self._do_fade_text)

    def _do_fade_text(self):
        self._text_fade_id = None
        if self._text_window:
            self._text_window.withdraw()

    def show_feedback(self, feedback_type: str = "success"):
        """Flash the mic icon briefly to confirm an event. Thread-safe.

        Types: 'success' (green), 'warning' (yellow), 'error' (red).
        Works even if the indicator is currently hidden (shows briefly then hides).
        """
        if self._root:
            self._root.after(0, lambda: self._do_show_feedback(feedback_type))

    def _do_show_feedback(self, feedback_type: str):
        colors = {
            "success": "#2ECC71",
            "warning": "#F1C40F",
            "error": "#E74C3C",
        }
        color = colors.get(feedback_type, "#2ECC71")
        was_hidden = not self._root.winfo_viewable()

        if was_hidden:
            self._cancel_fade()
            self._root.attributes("-alpha", 0.92)
            self._root.deiconify()
            self._root.lift()

        self._stop_pulse()
        self._recolor_mic(color)

        def _revert():
            if was_hidden:
                self._root.withdraw()
            else:
                state_color = _STATE_COLORS.get(self._current_state, "#e0e0e0")
                self._recolor_mic(state_color)
                if self._current_state == "transcribing":
                    self._start_pulse()

        self._root.after(350, _revert)

    def destroy(self):
        """Shut down the Tk thread."""
        if self._root:
            self._root.after(0, self._root.destroy)
