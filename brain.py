"""Vocabulary Brain — SQLite database for custom vocabulary, corrections, and prompt config.

Thread-safe via WAL mode. Supports JSON export/import for sync and backup.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path

log = logging.getLogger("transcriber.brain")

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS vocabulary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE COLLATE NOCASE,
    phonetic_hint TEXT,
    frequency INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    priority TEXT NOT NULL DEFAULT 'normal',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original TEXT NOT NULL,
    corrected TEXT NOT NULL,
    context TEXT,
    audio_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prompt_fragments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fragment TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vocabulary_term ON vocabulary(term);
CREATE INDEX IF NOT EXISTS idx_vocabulary_priority ON vocabulary(priority);
CREATE INDEX IF NOT EXISTS idx_corrections_original ON corrections(original);
"""


class VocabularyBrain:
    """Thread-safe SQLite vocabulary database."""

    def __init__(self, db_path: str | Path = "brain.db"):
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        """Return a thread-local connection (one per thread)."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        """Create tables if they don't exist."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("schema_version", str(_SCHEMA_VERSION)),
        )
        self._conn.commit()
        log.info("Brain database initialized at %s", self.db_path)

    def close(self):
        """Close the thread-local connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    # ── Vocabulary CRUD ──────────────────────────────────────────────

    def add_term(
        self,
        term: str,
        *,
        phonetic_hint: str | None = None,
        source: str = "manual",
        priority: str = "normal",
    ) -> int | None:
        """Add a vocabulary term. Returns the row id, or None if it already exists."""
        try:
            cur = self._conn.execute(
                """INSERT INTO vocabulary (term, phonetic_hint, source, priority)
                   VALUES (?, ?, ?, ?)""",
                (term.strip(), phonetic_hint, source, priority),
            )
            self._conn.commit()
            log.info("Added vocabulary term: %s (source=%s)", term, source)
            return cur.lastrowid
        except sqlite3.IntegrityError:
            log.debug("Term already exists: %s", term)
            return None

    def remove_term(self, term: str) -> bool:
        """Remove a vocabulary term by name. Returns True if deleted."""
        cur = self._conn.execute(
            "DELETE FROM vocabulary WHERE term = ? COLLATE NOCASE", (term.strip(),)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_term(self, term: str) -> dict | None:
        """Get a single vocabulary entry by term name."""
        row = self._conn.execute(
            "SELECT * FROM vocabulary WHERE term = ? COLLATE NOCASE", (term.strip(),)
        ).fetchone()
        return dict(row) if row else None

    def get_all_terms(self) -> list[dict]:
        """Return all vocabulary entries ordered by priority then frequency."""
        rows = self._conn.execute(
            """SELECT * FROM vocabulary
               ORDER BY
                 CASE priority WHEN 'high' THEN 0 ELSE 1 END,
                 frequency DESC,
                 term ASC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_high_priority_terms(self) -> list[str]:
        """Return just the term strings marked as high priority."""
        rows = self._conn.execute(
            "SELECT term FROM vocabulary WHERE priority = 'high' ORDER BY frequency DESC"
        ).fetchall()
        return [r["term"] for r in rows]

    def get_all_term_strings(self) -> list[str]:
        """Return all term strings, high priority first."""
        rows = self._conn.execute(
            """SELECT term FROM vocabulary
               ORDER BY
                 CASE priority WHEN 'high' THEN 0 ELSE 1 END,
                 frequency DESC"""
        ).fetchall()
        return [r["term"] for r in rows]

    def update_term(self, term: str, **kwargs) -> bool:
        """Update fields on an existing term. Valid kwargs: phonetic_hint, priority, frequency."""
        valid_fields = {"phonetic_hint", "priority", "frequency"}
        updates = {k: v for k, v in kwargs.items() if k in valid_fields}
        if not updates:
            return False

        updates["updated_at"] = "datetime('now')"
        set_clause = ", ".join(
            f"{k} = ?" if k != "updated_at" else f"{k} = datetime('now')"
            for k in updates
        )
        values = [v for k, v in updates.items() if k != "updated_at"]
        values.append(term.strip())

        cur = self._conn.execute(
            f"UPDATE vocabulary SET {set_clause} WHERE term = ? COLLATE NOCASE",
            values,
        )
        self._conn.commit()
        return cur.rowcount > 0

    def increment_frequency(self, term: str) -> bool:
        """Bump the frequency counter for a term."""
        cur = self._conn.execute(
            """UPDATE vocabulary
               SET frequency = frequency + 1, updated_at = datetime('now')
               WHERE term = ? COLLATE NOCASE""",
            (term.strip(),),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def term_count(self) -> int:
        """Return total number of vocabulary entries."""
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM vocabulary").fetchone()
        return row["cnt"]

    # ── Corrections ──────────────────────────────────────────────────

    def log_correction(
        self,
        original: str,
        corrected: str,
        context: str | None = None,
        audio_hash: str | None = None,
    ) -> int:
        """Log a user correction. Returns the row id."""
        cur = self._conn.execute(
            """INSERT INTO corrections (original, corrected, context, audio_hash)
               VALUES (?, ?, ?, ?)""",
            (original, corrected, context, audio_hash),
        )
        self._conn.commit()
        log.info("Logged correction: %r → %r", original, corrected)
        return cur.lastrowid

    def get_corrections(self, limit: int = 100) -> list[dict]:
        """Return recent corrections, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM corrections ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_correction_patterns(self, min_count: int = 1) -> list[dict]:
        """Find repeated correction patterns (original → corrected) with their count.

        Returns dicts with keys: original, corrected, count.
        """
        rows = self._conn.execute(
            """SELECT original, corrected, COUNT(*) AS count
               FROM corrections
               GROUP BY original, corrected
               HAVING count >= ?
               ORDER BY count DESC""",
            (min_count,),
        ).fetchall()
        return [dict(r) for r in rows]

    def correction_count(self) -> int:
        """Return total number of logged corrections."""
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM corrections").fetchone()
        return row["cnt"]

    # ── Prompt fragments cache ───────────────────────────────────────

    def get_cached_prompt(self) -> str | None:
        """Return the most recently cached initial_prompt, or None."""
        row = self._conn.execute(
            "SELECT fragment FROM prompt_fragments ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()
        return row["fragment"] if row else None

    def cache_prompt(self, fragment: str):
        """Store a newly generated initial_prompt (replaces old ones)."""
        self._conn.execute("DELETE FROM prompt_fragments")
        self._conn.execute(
            "INSERT INTO prompt_fragments (fragment) VALUES (?)", (fragment,)
        )
        self._conn.commit()

    # ── Settings ─────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Get a setting value by key."""
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        """Set a setting value (insert or update)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    # ── JSON export/import ───────────────────────────────────────────

    def export_json(self) -> dict:
        """Export vocabulary and corrections as a JSON-serializable dict."""
        return {
            "schema_version": _SCHEMA_VERSION,
            "vocabulary": self.get_all_terms(),
            "corrections": self.get_corrections(limit=10000),
        }

    def export_to_file(self, path: str | Path):
        """Export the brain to a JSON file."""
        data = self.export_json()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("Exported brain to %s (%d terms, %d corrections)",
                 path, len(data["vocabulary"]), len(data["corrections"]))

    def import_from_file(self, path: str | Path):
        """Import vocabulary and corrections from a JSON file (merge, not replace)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        imported_terms = 0
        for entry in data.get("vocabulary", []):
            result = self.add_term(
                entry["term"],
                phonetic_hint=entry.get("phonetic_hint"),
                source=entry.get("source", "import"),
                priority=entry.get("priority", "normal"),
            )
            if result is not None:
                imported_terms += 1

        imported_corrections = 0
        for entry in data.get("corrections", []):
            self.log_correction(
                entry["original"],
                entry["corrected"],
                context=entry.get("context"),
                audio_hash=entry.get("audio_hash"),
            )
            imported_corrections += 1

        log.info("Imported %d new terms, %d corrections from %s",
                 imported_terms, imported_corrections, path)
