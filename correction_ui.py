"""Floating correction window for post-transcription editing.

Supports three modes (set via config):
- auto:   Window auto-shows after each transcription, auto-hides after timeout.
          Does NOT steal focus — user can ignore it or click to edit.
- hotkey: Window only appears when user presses the correction hotkey.
- off:    Correction window disabled entirely.

Also includes a quick-add vocabulary panel (Ctrl+Shift+A when focused).
"""

import logging
import threading
import tkinter as tk

log = logging.getLogger("transcriber.correction_ui")


class CorrectionWindow:
    """A lightweight Tkinter popup for correcting transcriptions.

    Runs on its own thread with its own Tk mainloop. Thread-safe: call show()
    or show_passive() from any thread to display the window with new text.
    """

    def __init__(self, on_correction=None, on_vocab_add=None):
        """
        Args:
            on_correction: Callback(original: str, corrected: str) called when
                           the user edits and accepts. Skipped if text unchanged.
            on_vocab_add:  Callback(term: str, hint: str, priority: str) called
                           when the user adds a term via the quick-add panel.
        """
        self._on_correction = on_correction
        self._on_vocab_add = on_vocab_add
        self._original_text: str = ""
        self._root: tk.Tk | None = None
        self._text_widget: tk.Text | None = None
        self._status_label: tk.Label | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

        # Auto-hide timer
        self._auto_hide_id: str | None = None
        self._user_interacted = False

        # Quick-add vocab panel widgets
        self._vocab_frame: tk.Frame | None = None
        self._vocab_visible = False
        self._vocab_term_var: tk.StringVar | None = None
        self._vocab_hint_var: tk.StringVar | None = None
        self._vocab_priority_var: tk.StringVar | None = None

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

        # Dark theme
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

        # Button row
        btn_frame = tk.Frame(self._root, bg=bg)
        btn_frame.pack(fill="x", padx=10, pady=(0, 2))

        self._vocab_btn = tk.Button(
            btn_frame,
            text="Add to vocab (Ctrl+Shift+A)",
            command=self._toggle_vocab_panel,
            bg="#3a3a3a", fg="#e0e0e0",
            activebackground="#4a4a4a", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 9),
            cursor="hand2",
        )
        self._vocab_btn.pack(side="left")

        # Status bar
        self._status_label = tk.Label(
            self._root,
            text="",
            bg=bg, fg="#888888", font=("Segoe UI", 9),
            anchor="w",
        )
        self._status_label.pack(fill="x", padx=10, pady=(0, 4))

        # Quick-add vocab panel (hidden by default)
        self._build_vocab_panel(bg, fg)

        # Key bindings
        self._root.bind("<Return>", self._accept)
        self._root.bind("<Escape>", lambda e: self._dismiss())
        self._text_widget.bind("<Shift-Return>", lambda e: None)  # allow default
        self._root.bind("<Control-Return>", self._accept)
        self._root.bind("<Control-Shift-A>", lambda e: self._toggle_vocab_panel())
        self._root.bind("<Control-Shift-a>", lambda e: self._toggle_vocab_panel())

        # Track user interaction to cancel auto-hide
        self._root.bind("<FocusIn>", self._on_user_interact)
        self._root.bind("<Button-1>", self._on_user_interact)
        self._text_widget.bind("<Key>", self._on_user_interact)

        # Start hidden
        self._root.withdraw()
        self._ready.set()
        self._root.mainloop()

    def _build_vocab_panel(self, bg: str, fg: str):
        """Build the quick-add vocabulary panel (initially hidden)."""
        self._vocab_frame = tk.Frame(self._root, bg="#333333", relief="flat")

        self._vocab_term_var = tk.StringVar()
        self._vocab_hint_var = tk.StringVar()
        self._vocab_priority_var = tk.StringVar(value="normal")

        entry_bg = "#1e1e1e"
        entry_fg = fg
        label_font = ("Segoe UI", 9)
        entry_font = ("Consolas", 10)

        # Row 1: Term
        row1 = tk.Frame(self._vocab_frame, bg="#333333")
        row1.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(row1, text="Term:", bg="#333333", fg="#aaaaaa", font=label_font, width=8, anchor="w").pack(side="left")
        tk.Entry(row1, textvariable=self._vocab_term_var, bg=entry_bg, fg=entry_fg,
                 insertbackground=fg, font=entry_font, relief="flat").pack(side="left", fill="x", expand=True)

        # Row 2: Hint
        row2 = tk.Frame(self._vocab_frame, bg="#333333")
        row2.pack(fill="x", padx=8, pady=2)
        tk.Label(row2, text="Hint:", bg="#333333", fg="#aaaaaa", font=label_font, width=8, anchor="w").pack(side="left")
        tk.Entry(row2, textvariable=self._vocab_hint_var, bg=entry_bg, fg=entry_fg,
                 insertbackground=fg, font=entry_font, relief="flat").pack(side="left", fill="x", expand=True)

        # Row 3: Priority toggle + Add button
        row3 = tk.Frame(self._vocab_frame, bg="#333333")
        row3.pack(fill="x", padx=8, pady=(2, 6))

        self._priority_btn = tk.Button(
            row3, text="Priority: normal",
            command=self._toggle_priority,
            bg="#3a3a3a", fg="#e0e0e0",
            activebackground="#4a4a4a", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 9), cursor="hand2",
        )
        self._priority_btn.pack(side="left")

        add_btn = tk.Button(
            row3, text="Add",
            command=self._do_vocab_add,
            bg="#4a90d9", fg="#ffffff",
            activebackground="#5ba0e9", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 9, "bold"), cursor="hand2",
            padx=12,
        )
        add_btn.pack(side="right")

    def _toggle_vocab_panel(self):
        """Show or hide the quick-add vocabulary panel."""
        if self._vocab_visible:
            self._vocab_frame.pack_forget()
            self._vocab_visible = False
            self._root.geometry("500x200")
        else:
            # Pre-fill term with selected text or corrected text
            try:
                selected = self._text_widget.get("sel.first", "sel.last").strip()
            except tk.TclError:
                selected = ""
            corrected = self._text_widget.get("1.0", "end").strip()
            self._vocab_term_var.set(selected or corrected)
            self._vocab_hint_var.set(self._original_text.strip() if selected == "" else "")
            self._vocab_priority_var.set("normal")
            self._priority_btn.config(text="Priority: normal")

            self._vocab_frame.pack(fill="x", padx=10, pady=(0, 4), before=self._status_label)
            self._vocab_visible = True
            self._root.geometry("500x290")

    def _toggle_priority(self):
        """Toggle between normal and high priority."""
        current = self._vocab_priority_var.get()
        new_val = "high" if current == "normal" else "normal"
        self._vocab_priority_var.set(new_val)
        self._priority_btn.config(text=f"Priority: {new_val}")

    def _do_vocab_add(self):
        """Add the term to vocabulary via callback."""
        term = self._vocab_term_var.get().strip()
        if not term:
            self._status_label.config(text="Term cannot be empty", fg="#E74C3C")
            return

        hint = self._vocab_hint_var.get().strip() or None
        priority = self._vocab_priority_var.get()

        if self._on_vocab_add:
            threading.Thread(
                target=self._on_vocab_add,
                args=(term, hint, priority),
                daemon=True,
            ).start()

        self._status_label.config(text=f"Added '{term}' to vocabulary", fg="#4CAF50")
        # Hide the vocab panel
        self._vocab_frame.pack_forget()
        self._vocab_visible = False
        self._root.geometry("500x200")

    def show(self, text: str):
        """Show the correction window with focus (hotkey mode). Thread-safe."""
        if self._root is None:
            return
        self._original_text = text
        self._root.after(0, self._show_focused, text)

    def show_passive(self, text: str, timeout: int = 8):
        """Show the correction window without stealing focus (auto mode). Thread-safe.

        Args:
            text: The transcribed text to display.
            timeout: Seconds before auto-hiding. 0 means no auto-hide.
        """
        if self._root is None:
            return
        self._original_text = text
        self._root.after(0, self._show_no_focus, text, timeout)

    def _show_focused(self, text: str):
        """Show with focus — used for hotkey-triggered correction."""
        self._cancel_auto_hide()
        self._user_interacted = True  # hotkey means user wants to interact
        self._text_widget.delete("1.0", "end")
        self._text_widget.insert("1.0", text)
        self._text_widget.focus_set()
        self._text_widget.tag_add("sel", "1.0", "end-1c")
        self._status_label.config(text="")
        self._hide_vocab_panel()
        self._position_near_tray()
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _show_no_focus(self, text: str, timeout: int):
        """Show without stealing focus — used for auto-show after transcription."""
        self._cancel_auto_hide()
        self._user_interacted = False
        self._text_widget.delete("1.0", "end")
        self._text_widget.insert("1.0", text)
        self._status_label.config(text="Auto-hiding in a few seconds · Click to edit", fg="#888888")
        self._hide_vocab_panel()
        self._position_near_tray()
        self._root.deiconify()
        self._root.lift()
        # Do NOT call focus_force() — let the target app keep focus

        if timeout > 0:
            self._auto_hide_id = self._root.after(timeout * 1000, self._auto_hide)

    def _position_near_tray(self):
        """Position the window near the bottom-right of the screen (near system tray)."""
        self._root.update_idletasks()
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        win_w = self._root.winfo_width()
        win_h = self._root.winfo_height()
        x = screen_w - win_w - 20
        y = screen_h - win_h - 80  # above taskbar
        self._root.geometry(f"+{x}+{y}")

    def _on_user_interact(self, event=None):
        """User clicked or typed — cancel auto-hide and take focus."""
        if not self._user_interacted:
            self._user_interacted = True
            self._cancel_auto_hide()
            self._text_widget.focus_set()
            self._text_widget.tag_add("sel", "1.0", "end-1c")
            self._status_label.config(text="Edit and press Enter to save · Escape to dismiss", fg="#888888")

    def _cancel_auto_hide(self):
        """Cancel any pending auto-hide timer."""
        if self._auto_hide_id is not None:
            self._root.after_cancel(self._auto_hide_id)
            self._auto_hide_id = None

    def _auto_hide(self):
        """Auto-hide fired — dismiss without saving."""
        self._auto_hide_id = None
        if not self._user_interacted:
            log.debug("Correction window auto-hidden (timeout)")
            self._hide()

    def _accept(self, event=None):
        """User pressed Enter — save correction if text changed."""
        if self._text_widget is None:
            return "break"

        corrected = self._text_widget.get("1.0", "end").strip()
        original = self._original_text.strip()

        if corrected and corrected != original:
            self._status_label.config(text="Correction saved", fg="#4CAF50")
            if self._on_correction:
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
        self._cancel_auto_hide()
        log.debug("Correction window dismissed")
        self._hide()

    def _hide(self):
        """Hide the window and reset state."""
        if self._root:
            self._cancel_auto_hide()
            self._hide_vocab_panel()
            self._root.withdraw()

    def _hide_vocab_panel(self):
        """Hide the vocab panel if visible."""
        if self._vocab_visible:
            self._vocab_frame.pack_forget()
            self._vocab_visible = False
            self._root.geometry("500x200")

    def destroy(self):
        """Shut down the Tk thread."""
        if self._root:
            self._root.after(0, self._root.destroy)
