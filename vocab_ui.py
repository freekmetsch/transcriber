"""Vocabulary manager window — Tkinter Toplevel accessible from tray menu.

Provides a scrollable list of vocabulary terms with add, remove, edit priority,
export, and import functionality. Dark theme matching the correction window.
"""

import logging
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

log = logging.getLogger("transcriber.vocab_ui")


class VocabularyManager:
    """Vocabulary manager as a Tkinter Toplevel window.

    Must be created and shown from the Tk thread (use schedule_show for thread-safe access).
    Requires an existing Tk root (from CorrectionWindow).
    """

    def __init__(self, root: tk.Tk, brain, on_change=None):
        """
        Args:
            root: The existing Tk root (shared with CorrectionWindow).
            brain: VocabularyBrain instance for data access.
            on_change: Callback() invoked after any vocabulary mutation
                       (add, remove, priority change, import) so the caller
                       can rebuild prompts and refresh the tray menu.
        """
        self._root = root
        self._brain = brain
        self._on_change = on_change
        self._window: tk.Toplevel | None = None

    def schedule_show(self):
        """Thread-safe: schedule showing the window on the Tk thread."""
        if self._root:
            self._root.after(0, self.show)

    def show(self):
        """Show the vocabulary manager. Must be called on the Tk thread."""
        if self._window is not None:
            try:
                self._window.deiconify()
                self._window.lift()
                self._window.focus_force()
                self._refresh_list()
                return
            except tk.TclError:
                self._window = None

        self._build_window()
        self._refresh_list()

    def _build_window(self):
        """Build the vocabulary manager Toplevel."""
        bg = "#2b2b2b"
        fg = "#e0e0e0"

        self._window = tk.Toplevel(self._root)
        self._window.title("Vocabulary Manager")
        self._window.geometry("700x450")
        self._window.attributes("-topmost", True)
        self._window.configure(bg=bg)
        self._window.protocol("WM_DELETE_WINDOW", self._hide)

        # Treeview with columns
        columns = ("term", "hint", "priority", "frequency", "source")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Treeview",
                        background="#1e1e1e", foreground=fg,
                        fieldbackground="#1e1e1e", font=("Consolas", 10))
        style.configure("Dark.Treeview.Heading",
                        background="#3a3a3a", foreground=fg,
                        font=("Segoe UI", 9, "bold"))
        style.map("Dark.Treeview",
                  background=[("selected", "#4a90d9")],
                  foreground=[("selected", "#ffffff")])

        tree_frame = tk.Frame(self._window, bg=bg)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings",
            style="Dark.Treeview", selectmode="browse",
        )
        self._tree.heading("term", text="Term")
        self._tree.heading("hint", text="Phonetic Hint")
        self._tree.heading("priority", text="Priority")
        self._tree.heading("frequency", text="Freq")
        self._tree.heading("source", text="Source")

        self._tree.column("term", width=180, minwidth=100)
        self._tree.column("hint", width=160, minwidth=80)
        self._tree.column("priority", width=80, minwidth=60)
        self._tree.column("frequency", width=60, minwidth=40)
        self._tree.column("source", width=80, minwidth=60)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Button row
        btn_frame = tk.Frame(self._window, bg=bg)
        btn_frame.pack(fill="x", padx=10, pady=(4, 10))

        btn_style = {
            "bg": "#3a3a3a", "fg": "#e0e0e0",
            "activebackground": "#4a4a4a", "activeforeground": "#ffffff",
            "relief": "flat", "font": ("Segoe UI", 9), "cursor": "hand2",
            "padx": 8, "pady": 4,
        }

        tk.Button(btn_frame, text="Add...", command=self._add_term, **btn_style).pack(side="left", padx=(0, 4))
        tk.Button(btn_frame, text="Remove", command=self._remove_term, **btn_style).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Toggle Priority", command=self._toggle_priority, **btn_style).pack(side="left", padx=4)

        tk.Button(btn_frame, text="Import JSON...", command=self._import_json, **btn_style).pack(side="right", padx=(4, 0))
        tk.Button(btn_frame, text="Export JSON...", command=self._export_json, **btn_style).pack(side="right", padx=4)

        # Status bar
        self._status = tk.Label(
            self._window, text="", bg=bg, fg="#888888",
            font=("Segoe UI", 9), anchor="w",
        )
        self._status.pack(fill="x", padx=10, pady=(0, 8))

        # Position near center of screen
        self._window.update_idletasks()
        screen_w = self._window.winfo_screenwidth()
        screen_h = self._window.winfo_screenheight()
        x = (screen_w - 700) // 2
        y = (screen_h - 450) // 2
        self._window.geometry(f"+{x}+{y}")

    def _refresh_list(self):
        """Reload the term list from brain."""
        for item in self._tree.get_children():
            self._tree.delete(item)

        terms = self._brain.get_all_terms()
        for t in terms:
            self._tree.insert("", "end", values=(
                t["term"],
                t.get("phonetic_hint") or "",
                t["priority"],
                t["frequency"],
                t["source"],
            ))
        self._status.config(text=f"{len(terms)} terms", fg="#888888")

    def _add_term(self):
        """Open a small dialog to add a new term."""
        dialog = tk.Toplevel(self._window)
        dialog.title("Add Vocabulary Term")
        dialog.geometry("350x180")
        dialog.attributes("-topmost", True)
        dialog.configure(bg="#2b2b2b")
        dialog.transient(self._window)
        dialog.grab_set()

        bg = "#2b2b2b"
        fg = "#e0e0e0"
        entry_bg = "#1e1e1e"

        term_var = tk.StringVar()
        hint_var = tk.StringVar()
        priority_var = tk.StringVar(value="normal")

        for i, (label_text, var) in enumerate([("Term:", term_var), ("Hint:", hint_var)]):
            row = tk.Frame(dialog, bg=bg)
            row.pack(fill="x", padx=12, pady=(8 if i == 0 else 4, 0))
            tk.Label(row, text=label_text, bg=bg, fg="#aaaaaa", font=("Segoe UI", 9), width=6, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=var, bg=entry_bg, fg=fg, insertbackground=fg,
                     font=("Consolas", 10), relief="flat").pack(side="left", fill="x", expand=True)

        row3 = tk.Frame(dialog, bg=bg)
        row3.pack(fill="x", padx=12, pady=(8, 0))

        priority_btn = tk.Button(
            row3, text="Priority: normal",
            bg="#3a3a3a", fg=fg, activebackground="#4a4a4a", activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 9), cursor="hand2",
        )
        def _toggle():
            new = "high" if priority_var.get() == "normal" else "normal"
            priority_var.set(new)
            priority_btn.config(text=f"Priority: {new}")
        priority_btn.config(command=_toggle)
        priority_btn.pack(side="left")

        def _do_add():
            term = term_var.get().strip()
            if not term:
                return
            self._brain.add_term(term, phonetic_hint=hint_var.get().strip() or None, priority=priority_var.get())
            dialog.destroy()
            self._refresh_list()
            self._notify_change()
            self._status.config(text=f"Added: {term}", fg="#4CAF50")

        tk.Button(
            row3, text="Add", command=_do_add,
            bg="#4a90d9", fg="#ffffff", activebackground="#5ba0e9",
            relief="flat", font=("Segoe UI", 9, "bold"), cursor="hand2", padx=12,
        ).pack(side="right")

        dialog.bind("<Return>", lambda e: _do_add())
        dialog.bind("<Escape>", lambda e: dialog.destroy())

    def _remove_term(self):
        """Remove the selected term."""
        sel = self._tree.selection()
        if not sel:
            return
        values = self._tree.item(sel[0], "values")
        term = values[0]
        if messagebox.askyesno("Remove term", f"Remove '{term}' from vocabulary?", parent=self._window):
            self._brain.remove_term(term)
            self._refresh_list()
            self._notify_change()
            self._status.config(text=f"Removed: {term}", fg="#E74C3C")

    def _toggle_priority(self):
        """Toggle priority of the selected term."""
        sel = self._tree.selection()
        if not sel:
            return
        values = self._tree.item(sel[0], "values")
        term = values[0]
        current = values[2]
        new_priority = "high" if current == "normal" else "normal"
        self._brain.update_term(term, priority=new_priority)
        self._refresh_list()
        self._notify_change()
        self._status.config(text=f"'{term}' → {new_priority} priority", fg="#4CAF50")

    def _export_json(self):
        """Export vocabulary to a JSON file via file dialog."""
        path = filedialog.asksaveasfilename(
            parent=self._window,
            title="Export Vocabulary",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="brain_export.json",
        )
        if path:
            self._brain.export_to_file(path)
            self._status.config(text=f"Exported to {path}", fg="#4CAF50")

    def _import_json(self):
        """Import vocabulary from a JSON file via file dialog."""
        path = filedialog.askopenfilename(
            parent=self._window,
            title="Import Vocabulary",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            count_before = self._brain.term_count()
            self._brain.import_from_file(path)
            count_after = self._brain.term_count()
            imported = count_after - count_before
            self._refresh_list()
            self._notify_change()
            self._status.config(text=f"Imported {imported} new terms from {path}", fg="#4CAF50")

    def _notify_change(self):
        """Notify the caller that vocabulary changed."""
        if self._on_change:
            threading.Thread(target=self._on_change, daemon=True).start()

    def _hide(self):
        """Hide the window (don't destroy — reuse on next show)."""
        if self._window:
            self._window.withdraw()
