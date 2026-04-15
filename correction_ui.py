"""Floating correction window for post-transcription editing.

After each transcription, the user can press a hotkey to open a small window
showing the result. They edit the text, press Enter to accept (correction logged),
or Escape to dismiss (no correction logged).
"""

import logging
import threading
import tkinter as tk

log = logging.getLogger("transcriber.correction_ui")


class CorrectionWindow:
    """A lightweight Tkinter popup for correcting transcriptions.

    Runs on its own thread with its own Tk mainloop. Thread-safe: call show()
    from any thread to display the window with new text.
    """

    def __init__(self, on_correction=None):
        """
        Args:
            on_correction: Callback(original: str, corrected: str) called when
                           the user edits and accepts. Skipped if text unchanged.
        """
        self._on_correction = on_correction
        self._original_text: str = ""
        self._root: tk.Tk | None = None
        self._text_widget: tk.Text | None = None
        self._status_label: tk.Label | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self):
        """Start the Tk thread. Call once during app init."""
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_tk(self):
        """Tk mainloop on a background thread."""
        self._root = tk.Tk()
        self._root.title("Correction")
        self._root.geometry("500x200")
        self._root.attributes("-topmost", True)
        self._root.protocol("WM_DELETE_WINDOW", self._dismiss)

        # Dark theme to match a dev aesthetic
        bg = "#2b2b2b"
        fg = "#e0e0e0"
        sel_bg = "#4a90d9"
        self._root.configure(bg=bg)

        # Instructions
        hint = tk.Label(
            self._root,
            text="Edit and press Enter to save correction · Escape to dismiss",
            bg=bg, fg="#888888", font=("Segoe UI", 9),
        )
        hint.pack(pady=(8, 2), padx=10, anchor="w")

        # Text area
        self._text_widget = tk.Text(
            self._root,
            wrap="word",
            font=("Consolas", 12),
            bg="#1e1e1e", fg=fg,
            insertbackground=fg,
            selectbackground=sel_bg,
            selectforeground="#ffffff",
            relief="flat",
            padx=8, pady=8,
            height=5,
        )
        self._text_widget.pack(fill="both", expand=True, padx=10, pady=(2, 4))

        # Status bar
        self._status_label = tk.Label(
            self._root,
            text="",
            bg=bg, fg="#888888", font=("Segoe UI", 9),
            anchor="w",
        )
        self._status_label.pack(fill="x", padx=10, pady=(0, 8))

        # Key bindings
        self._root.bind("<Return>", self._accept)
        self._root.bind("<Escape>", lambda e: self._dismiss())
        # Shift+Enter for actual newline in text
        self._text_widget.bind("<Shift-Return>", lambda e: None)  # allow default
        # Ctrl+Enter also accepts
        self._root.bind("<Control-Return>", self._accept)

        # Start hidden
        self._root.withdraw()
        self._ready.set()
        self._root.mainloop()

    def show(self, text: str):
        """Show the correction window with the given text. Thread-safe."""
        if self._root is None:
            return
        self._original_text = text
        self._root.after(0, self._show_on_tk_thread, text)

    def _show_on_tk_thread(self, text: str):
        """Update UI on the Tk thread."""
        self._text_widget.delete("1.0", "end")
        self._text_widget.insert("1.0", text)
        self._text_widget.focus_set()
        # Select all for easy replacement
        self._text_widget.tag_add("sel", "1.0", "end-1c")
        self._status_label.config(text="")
        # Position near bottom-right of screen
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _accept(self, event=None):
        """User pressed Enter — save correction if text changed."""
        if self._text_widget is None:
            return "break"

        corrected = self._text_widget.get("1.0", "end").strip()
        original = self._original_text.strip()

        if corrected and corrected != original:
            self._status_label.config(text=f"Correction saved", fg="#4CAF50")
            if self._on_correction:
                # Run callback off the Tk thread
                threading.Thread(
                    target=self._on_correction,
                    args=(original, corrected),
                    daemon=True,
                ).start()
            log.info("Correction accepted: %r → %r", original, corrected)
        else:
            self._status_label.config(text="No changes", fg="#888888")
            log.debug("Correction dismissed (no changes)")

        self._root.after(400, self._hide)
        return "break"  # prevent newline insertion

    def _dismiss(self):
        """User pressed Escape — close without saving."""
        log.debug("Correction window dismissed")
        self._hide()

    def _hide(self):
        """Hide the window."""
        if self._root:
            self._root.withdraw()

    def destroy(self):
        """Shut down the Tk thread."""
        if self._root:
            self._root.after(0, self._root.destroy)
