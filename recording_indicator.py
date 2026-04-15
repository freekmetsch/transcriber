"""Floating recording indicator — Win+H-style overlay at top-center of screen."""

import logging
import threading
import tkinter as tk

log = logging.getLogger("transcriber.recording_indicator")


class RecordingIndicator:
    """Minimal always-on-top overlay showing recording state.

    Runs on its own Tk thread. Thread-safe: call show()/hide() from any thread.
    """

    def __init__(self):
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._dot: int | None = None
        self._dot_visible: bool = True
        self._pulse_id: str | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self):
        """Start the Tk thread. Call once during app init."""
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_tk(self):
        bg = "#1e1e1e"
        win_w, win_h = 180, 36

        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.9)
        self._root.configure(bg=bg)

        screen_w = self._root.winfo_screenwidth()
        x = (screen_w - win_w) // 2
        self._root.geometry(f"{win_w}x{win_h}+{x}+12")

        self._canvas = tk.Canvas(
            self._root, width=win_w, height=win_h,
            bg=bg, highlightthickness=0,
        )
        self._canvas.pack()

        # Red recording dot
        cx, cy, r = 20, win_h // 2, 6
        self._dot = self._canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill="#E74C3C", outline="",
        )

        # "Listening..." label
        self._canvas.create_text(
            cx + r + 12, cy,
            text="Listening\u2026",
            fill="#e0e0e0", font=("Segoe UI", 11),
            anchor="w",
        )

        self._root.withdraw()
        self._ready.set()
        self._root.mainloop()

    def _pulse(self):
        """Toggle dot visibility for a pulsing effect."""
        if self._canvas is None:
            return
        self._dot_visible = not self._dot_visible
        self._canvas.itemconfig(
            self._dot, fill="#E74C3C" if self._dot_visible else "#1e1e1e",
        )
        self._pulse_id = self._root.after(500, self._pulse)

    def show(self):
        """Show the indicator. Thread-safe."""
        if self._root:
            self._root.after(0, self._do_show)

    def _do_show(self):
        self._dot_visible = True
        self._canvas.itemconfig(self._dot, fill="#E74C3C")
        self._root.deiconify()
        self._root.lift()
        self._pulse_id = self._root.after(500, self._pulse)

    def hide(self):
        """Hide the indicator. Thread-safe."""
        if self._root:
            self._root.after(0, self._do_hide)

    def _do_hide(self):
        if self._pulse_id is not None:
            self._root.after_cancel(self._pulse_id)
            self._pulse_id = None
        self._root.withdraw()

    def destroy(self):
        """Shut down the Tk thread."""
        if self._root:
            self._root.after(0, self._root.destroy)
