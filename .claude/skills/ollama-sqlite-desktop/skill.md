---
name: ollama-sqlite-desktop
description: Ollama HTTP API integration patterns and SQLite best practices for a Python desktop voice-to-text app on Windows. Covers connection management, error handling, latency optimization, WAL mode, thread safety, schema migration, and JSON sync.
license: MIT
metadata:
  tags: [ollama, sqlite, python, windows, desktop, voice-to-text]
  sources:
    - context7:/websites/ollama_api (Ollama REST API official docs)
    - context7:/ollama/ollama-python (Ollama Python library docs)
    - context7:/python/cpython (Python sqlite3 module docs)
    - docs.ollama.com/api (API reference: generate, chat, tags, ps)
    - docs.ollama.com/faq (keep_alive, context length, preloading)
    - sqlite.org/wal.html (WAL mode internals)
    - sqlite.org/threadsafe.html (threading modes)
    - ricardoanderegg.com/posts/python-sqlite-thread-safety (thread safety deep dive)
    - eskerda.com/sqlite-schema-migrations-python (PRAGMA user_version migrations)
  date_researched: "2026-04-15"
---

# Part 1: Ollama HTTP API Integration in Python

## 1.1 Two Integration Approaches

### Option A: Raw HTTP via `requests` (no extra dependency)
Best when you want full control and already depend on `requests`.

```python
import requests
import json
import logging

log = logging.getLogger("transcriber.ollama")

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_TIMEOUT = 30  # seconds
HEALTH_TIMEOUT = 3    # seconds


def ollama_health_check() -> bool:
    """Check if Ollama server is reachable and responsive."""
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=HEALTH_TIMEOUT)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def ollama_generate(prompt: str, model: str, system: str = "",
                    timeout: int = DEFAULT_TIMEOUT) -> str | None:
    """Non-streaming generate. Returns full response text or None on failure."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30m",
    }
    if system:
        payload["system"] = system
    try:
        r = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json().get("response", "")
    except requests.ConnectionError:
        log.warning("Ollama not reachable at %s", OLLAMA_BASE)
        return None
    except requests.Timeout:
        log.warning("Ollama request timed out after %ds", timeout)
        return None
    except requests.HTTPError as e:
        log.error("Ollama HTTP error: %s", e)
        return None
```

### Option B: Official `ollama` Python library (recommended)
Cleaner API, built-in streaming support, typed responses.

```python
from ollama import Client, chat, ResponseError
import logging

log = logging.getLogger("transcriber.ollama")

# Custom client with explicit host
client = Client(host="http://localhost:11434")


def postprocess(raw_text: str, model: str, system_prompt: str) -> str | None:
    """Send raw transcription to Ollama for post-processing."""
    try:
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_text},
            ],
            options={"temperature": 0.1, "num_ctx": 2048},
            keep_alive="30m",
        )
        return response.message.content
    except ConnectionError:
        log.warning("Ollama not reachable, returning raw text")
        return None
    except ResponseError as e:
        if e.status_code == 404:
            log.error("Model '%s' not found. Run: ollama pull %s", model, model)
        else:
            log.error("Ollama error %d: %s", e.status_code, e.error)
        return None
```

Install: `pip install ollama`

## 1.2 Key API Endpoints Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/generate` | POST | One-shot text generation from a prompt |
| `/api/chat` | POST | Multi-turn chat (system + user + assistant messages) |
| `/api/tags` | GET | List locally available models (good health check) |
| `/api/ps` | GET | List currently loaded/running models + VRAM usage |
| `/api/show` | POST | Show model details (template, parameters, license) |
| `/api/pull` | POST | Download a model (streams progress) |
| `/v1/chat/completions` | POST | OpenAI-compatible chat endpoint |
| `/v1/models` | GET | OpenAI-compatible model list |

Use `/api/chat` (not `/api/generate`) for dictation post-processing because:
- System prompt is a first-class parameter via the messages array
- Conversation history support if needed later
- Structured output via `format` parameter (JSON mode)

## 1.3 Streaming vs Non-Streaming

**For dictation post-processing, use non-streaming (`"stream": false`).**

Rationale:
- Dictation output is short (typically under 200 tokens)
- Non-streaming returns a single JSON response -- simpler parsing, no line-by-line reassembly
- With a 3B model on GPU, non-streaming adds negligible latency for short outputs
- Streaming is better for long generations or when you need progressive UI updates

If streaming is ever needed (e.g., live preview):
```python
# Streaming with the ollama library
stream = client.chat(
    model="qwen2.5:3b",
    messages=[{"role": "user", "content": raw_text}],
    stream=True,
)
full_response = ""
for chunk in stream:
    token = chunk["message"]["content"]
    full_response += token
    # Optional: update UI progressively
```

## 1.4 Latency Optimization for Real-Time Post-Processing

Target: under 1 second from Whisper output to formatted text.

### Keep the model hot in VRAM
The single biggest latency killer is cold-loading a model from disk to VRAM.

```python
# Option 1: Set keep_alive per request (overrides server default)
response = client.chat(model="qwen2.5:3b", messages=msgs, keep_alive="30m")

# Option 2: Preload on app startup with an empty request
def preload_model(model: str):
    """Send an empty request to load the model into VRAM."""
    try:
        client.chat(
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            keep_alive="-1",  # keep forever until explicitly unloaded
        )
    except Exception:
        pass  # non-critical, model will load on first real request

# Option 3: Set environment variable (system-wide)
# OLLAMA_KEEP_ALIVE=-1  (in Windows system environment variables)
```

**Pitfall**: Even with `OLLAMA_KEEP_ALIVE=-1`, individual API requests can override this. Some client libraries silently send `"keep_alive": "5m"`. Always set `keep_alive` explicitly in every request.

### Reduce context window
Default context is 4096 tokens. Dictation post-processing rarely needs more than 2048.

```python
options = {
    "num_ctx": 2048,      # smaller context = less VRAM, faster prompt eval
    "temperature": 0.1,   # low temperature for deterministic formatting
}
response = client.chat(model=model, messages=msgs, options=options)
```

### Use small, fast models
For dictation post-processing on 16GB VRAM (alongside Whisper large-v3):

| Model | Size | VRAM (Q4) | Speed | Multilingual |
|---|---|---|---|---|
| qwen2.5:3b | ~2 GB | ~2.5 GB | Very fast | Good Dutch support |
| qwen3:4b | ~2.5 GB | ~3 GB | Fast | Excellent multilingual |
| phi3:mini (3.8B) | ~2.3 GB | ~2.8 GB | Fast | Adequate |
| gemma3:4b | ~2.5 GB | ~3 GB | Fast | Good |

qwen2.5:3b or qwen3:4b are recommended starting points for Dutch+English code-switching.

### Additional speed tips
- **Flash Attention**: Set `OLLAMA_FLASH_ATTENTION=1` environment variable (if supported by your GPU)
- **Q4_K_M quantization**: Default for most Ollama models, good balance of speed and quality
- **Avoid loading multiple models**: Whisper large-v3 uses ~4GB VRAM; a 3B LLM uses ~2.5GB; total fits in 16GB

## 1.5 Error Handling and Graceful Fallback

**Critical design rule**: If Ollama is unavailable, output raw Whisper text. Never block the user.

```python
def postprocess_with_fallback(raw_text: str, config: dict) -> str:
    """Post-process transcription via Ollama, falling back to raw text."""
    if not config.get("postprocessing", {}).get("enabled", True):
        return raw_text

    model = config.get("postprocessing", {}).get("model", "qwen2.5:3b")
    timeout = config.get("postprocessing", {}).get("timeout", 5)

    result = postprocess(raw_text, model, build_system_prompt(config))
    if result is None:
        log.info("Ollama fallback: returning raw Whisper text")
        return raw_text
    return result
```

### Error categories and responses

| Error | Cause | Response |
|---|---|---|
| `ConnectionError` | Ollama not running | Fall back to raw text, log warning |
| `ResponseError(404)` | Model not pulled | Log error with pull command, fall back |
| `Timeout` | Model too slow or overloaded | Fall back to raw text |
| `ResponseError(500)` | Server error / OOM | Fall back, suggest smaller model |

### Health check on app startup
```python
def check_ollama_status(model: str) -> dict:
    """Check Ollama server and model availability on startup."""
    status = {"server": False, "model_available": False, "model_loaded": False}
    try:
        # Check server
        tags = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=3).json()
        status["server"] = True

        # Check if model is downloaded
        model_names = [m["name"] for m in tags.get("models", [])]
        # Ollama model names may include :latest tag
        status["model_available"] = any(
            model in name or name.startswith(model) for name in model_names
        )

        # Check if model is currently loaded in VRAM
        ps = requests.get(f"{OLLAMA_BASE}/api/ps", timeout=3).json()
        loaded = [m["model"] for m in ps.get("models", [])]
        status["model_loaded"] = any(model in m for m in loaded)
    except Exception:
        pass
    return status
```

## 1.6 Prompt Engineering for Dictation Post-Processing

### System prompt structure
```python
DICTATION_SYSTEM_PROMPT = """You are a dictation post-processor. The user dictates in mixed Dutch and English.

Rules:
1. Add correct punctuation and capitalization.
2. Convert formatting commands to symbols:
   - "period"/"punt" -> .
   - "comma"/"komma" -> ,
   - "new line"/"nieuwe regel" -> (actual newline)
   - "new paragraph"/"nieuw alinea" -> (double newline)
   - "exclamation mark"/"uitroepteken" -> !
   - "question mark"/"vraagteken" -> ?
   - "colon"/"dubbele punt" -> :
   - "open quote"/"aanhalingsteken openen" -> "
   - "close quote"/"aanhalingsteken sluiten" -> "
3. Preserve the EXACT language the user spoke. Do NOT translate.
4. Mixed Dutch+English in a single sentence is intentional, not an error.
5. Apply these vocabulary corrections: {vocabulary_corrections}
6. Output ONLY the corrected text. No explanations, no commentary."""


def build_system_prompt(config: dict, vocabulary: list[dict] = None) -> str:
    """Build the system prompt with dynamic vocabulary corrections."""
    corrections = ""
    if vocabulary:
        pairs = [f'"{v["wrong"]}" -> "{v["correct"]}"' for v in vocabulary]
        corrections = "\n   - ".join(pairs)
    else:
        corrections = "(none yet)"
    return DICTATION_SYSTEM_PROMPT.format(vocabulary_corrections=corrections)
```

### Prompt engineering tips for small models
- **Be explicit**: Small models (3B-4B) follow literal instructions better than implied ones
- **Use numbered rules**: More reliable than prose paragraphs
- **Short system prompts**: Keep under 500 tokens to minimize prompt eval time
- **Low temperature (0.1)**: Dictation formatting is deterministic, not creative
- **"Output ONLY" instruction**: Prevents small models from adding commentary
- **Test bilingual edge cases**: "Ik heb een meeting met het development team" should stay exactly as-is

## 1.7 Model Management

### Check and pull model on startup
```python
def ensure_model(model: str) -> bool:
    """Ensure the required model is available, pulling if needed."""
    try:
        tags = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=5).json()
        available = [m["name"] for m in tags.get("models", [])]
        if any(model in name for name in available):
            return True

        log.info("Model %s not found, pulling...", model)
        # Pull is a streaming endpoint -- each line is progress JSON
        r = requests.post(
            f"{OLLAMA_BASE}/api/pull",
            json={"model": model},
            stream=True,
            timeout=600,
        )
        for line in r.iter_lines():
            if line:
                progress = json.loads(line)
                status = progress.get("status", "")
                if "pulling" in status:
                    log.info("Pulling %s: %s", model, status)
        return True
    except Exception as e:
        log.error("Failed to ensure model %s: %s", model, e)
        return False
```

## 1.8 Windows-Specific Considerations

- **Ollama runs as a background service** on Windows (installed via the Windows installer). It starts automatically with Windows and listens on localhost:11434.
- **Firewall**: No firewall configuration needed for localhost access.
- **OLLAMA_KEEP_ALIVE**: Set via System Properties > Environment Variables > System variables. Requires Ollama service restart.
- **OLLAMA_FLASH_ATTENTION**: Same -- set as system environment variable.
- **GPU sharing**: Whisper (via faster-whisper/CTranslate2) and Ollama can share the same GPU. Both use CUDA. Ensure combined VRAM usage fits (large-v3 ~4GB + 3B model ~2.5GB = ~6.5GB of 16GB).
- **Process check**: On Windows, check if Ollama is running via `tasklist /FI "IMAGENAME eq ollama.exe"` or simply try the health check endpoint.

---

# Part 2: SQLite Patterns for Desktop Apps on Windows

## 2.1 WAL Mode (Write-Ahead Logging)

**Always enable WAL mode for desktop apps.** It is the single most impactful configuration change.

```python
import sqlite3

def create_connection(db_path: str) -> sqlite3.Connection:
    """Create a properly configured SQLite connection."""
    conn = sqlite3.connect(db_path, timeout=10.0)

    # WAL mode: allows concurrent reads while writing
    conn.execute("PRAGMA journal_mode=WAL")

    # NORMAL sync: good balance of safety and speed
    # (FULL is safest but slower; WAL+NORMAL is the recommended combo)
    conn.execute("PRAGMA synchronous=NORMAL")

    # Enable foreign keys (off by default in SQLite!)
    conn.execute("PRAGMA foreign_keys=ON")

    # Use memory for temp tables (faster than disk)
    conn.execute("PRAGMA temp_store=MEMORY")

    # Row factory for dict-like access
    conn.row_factory = sqlite3.Row

    return conn
```

### What WAL mode does
- **Without WAL (default DELETE mode)**: Writers block all readers. Readers block writers. One operation at a time.
- **With WAL**: Multiple readers can proceed concurrently with a single writer. Writer does not block readers. Readers do not block the writer.
- **WAL is a property of the database file**, not the connection. Set it once and it persists across connections and restarts.
- **WAL creates two companion files**: `brain.db-wal` (write-ahead log) and `brain.db-shm` (shared memory index). These are normal and expected.

### WAL checkpointing
WAL files grow over time. SQLite auto-checkpoints when WAL reaches ~1000 pages, but for long-running desktop apps:

```python
def checkpoint(conn: sqlite3.Connection):
    """Run a WAL checkpoint to merge WAL back into main DB.
    Call periodically (e.g., on app idle, or every 5 minutes)."""
    conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    # PASSIVE: non-blocking, checkpoints what it can
    # FULL: blocks until all WAL is checkpointed
    # TRUNCATE: like FULL, then shrinks WAL file to zero
```

### Pitfall: WAL mode and backup
When backing up a WAL-mode database, you must copy all three files: `.db`, `.db-wal`, `.db-shm`. Or run a TRUNCATE checkpoint first to merge everything into the main file.

## 2.2 Thread-Safe Access Patterns

### The rules
1. **Python's `sqlite3` module defaults to `check_same_thread=True`**: a connection created in one thread cannot be used in another. This is a safety check, not a SQLite limitation.
2. **SQLite itself (compiled in serialized mode, which is the default)** can handle multi-threaded access at the connection level.
3. **One connection per thread is the safest pattern.** This is what SQLite itself recommends.
4. **WAL mode + one connection per thread** = readers never block, writers wait only for other writers.

### Recommended pattern: Thread-local connections

```python
import sqlite3
import threading
from pathlib import Path

class BrainDB:
    """Thread-safe SQLite wrapper using per-thread connections."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        # Initialize DB schema on first creation
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a connection for the current thread."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def read(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Thread-safe read. Multiple threads can read concurrently."""
        conn = self._get_conn()
        return conn.execute(sql, params).fetchall()

    def write(self, sql: str, params: tuple = ()) -> int:
        """Thread-safe write. Serialized via lock for safety."""
        with self._write_lock:
            conn = self._get_conn()
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount

    def write_many(self, sql: str, param_list: list[tuple]) -> int:
        """Batch write in a single transaction."""
        with self._write_lock:
            conn = self._get_conn()
            cursor = conn.executemany(sql, param_list)
            conn.commit()
            return cursor.rowcount

    def close(self):
        """Close the current thread's connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
```

### Why not `check_same_thread=False` with a shared connection?
- It works if you serialize ALL writes yourself (including implicit writes from transactions).
- It is fragile and easy to get wrong.
- Per-thread connections with WAL mode is simpler and more performant for reads.
- The Python docs explicitly warn: "write operations may need to be serialized by the user to avoid data corruption."

### Alternative: Single-writer thread with queue
For apps with a dedicated writer thread (not needed for this app's low write volume, but useful to know):

```python
import queue

class DBWriter(threading.Thread):
    """Dedicated writer thread. All writes go through a queue."""
    def __init__(self, db_path: str):
        super().__init__(daemon=True)
        self.queue = queue.Queue()
        self.db_path = db_path

    def run(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        while True:
            sql, params, result_event = self.queue.get()
            if sql is None:
                break
            try:
                conn.execute(sql, params)
                conn.commit()
            except Exception as e:
                logging.error("DB write error: %s", e)
            if result_event:
                result_event.set()
```

## 2.3 Schema Design for Vocabulary/Correction Tracking

```sql
-- brain.db schema

-- Track schema version for migrations
-- Read with: PRAGMA user_version;
-- Set with: PRAGMA user_version=N;

-- Custom vocabulary entries
CREATE TABLE IF NOT EXISTS vocabulary (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    term        TEXT NOT NULL,              -- the correct term ("Freek")
    phonetic    TEXT,                       -- optional phonetic hint for Whisper
    category    TEXT DEFAULT 'general',     -- 'name', 'technical', 'general'
    priority    TEXT DEFAULT 'normal',      -- 'high' = always in initial_prompt
    frequency   INTEGER DEFAULT 0,         -- usage count
    source      TEXT DEFAULT 'manual',     -- 'manual', 'auto-learned'
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(term COLLATE NOCASE)
);

-- Correction history log
CREATE TABLE IF NOT EXISTS corrections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    original    TEXT NOT NULL,              -- what Whisper produced
    corrected   TEXT NOT NULL,              -- what the user changed it to
    context     TEXT,                       -- surrounding text for context
    audio_hash  TEXT,                       -- hash of audio segment (for future fine-tuning)
    created_at  TEXT DEFAULT (datetime('now'))
);

-- Index for finding repeated corrections (auto-learning)
CREATE INDEX IF NOT EXISTS idx_corrections_pair
    ON corrections(original, corrected);

-- Prompt fragments cache
CREATE TABLE IF NOT EXISTS prompt_cache (
    id          INTEGER PRIMARY KEY,
    fragment    TEXT NOT NULL,              -- generated initial_prompt string
    vocab_hash  TEXT NOT NULL,              -- hash of vocabulary state when generated
    created_at  TEXT DEFAULT (datetime('now'))
);

-- App settings (key-value store)
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT DEFAULT (datetime('now'))
);

PRAGMA user_version=1;
```

### Design notes
- **`COLLATE NOCASE` on vocabulary.term**: Prevents duplicates like "Freek" and "freek"
- **`datetime('now')` defaults**: SQLite stores as ISO 8601 text, sortable and human-readable
- **`audio_hash` in corrections**: Placeholder for Phase 5 fine-tuning pipeline; nullable for now
- **Separate `prompt_cache` table**: Avoids rebuilding the initial_prompt on every transcription; only rebuild when vocabulary changes

## 2.4 Schema Migration with PRAGMA user_version

For a desktop app, a lightweight migration system using `PRAGMA user_version` is simpler and more reliable than Alembic. Alembic is designed for ORM-heavy server apps and has known difficulties with SQLite's limited ALTER TABLE support.

```python
import sqlite3
import logging
from pathlib import Path

log = logging.getLogger("transcriber.brain")

MIGRATIONS = [
    # Version 1: initial schema
    """
    CREATE TABLE IF NOT EXISTS vocabulary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT NOT NULL,
        phonetic TEXT,
        category TEXT DEFAULT 'general',
        priority TEXT DEFAULT 'normal',
        frequency INTEGER DEFAULT 0,
        source TEXT DEFAULT 'manual',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(term COLLATE NOCASE)
    );
    CREATE TABLE IF NOT EXISTS corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original TEXT NOT NULL,
        corrected TEXT NOT NULL,
        context TEXT,
        audio_hash TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_corrections_pair
        ON corrections(original, corrected);
    CREATE TABLE IF NOT EXISTS prompt_cache (
        id INTEGER PRIMARY KEY,
        fragment TEXT NOT NULL,
        vocab_hash TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT DEFAULT (datetime('now'))
    );
    PRAGMA user_version=1;
    """,

    # Version 2: example future migration -- add language column
    """
    ALTER TABLE vocabulary ADD COLUMN language TEXT DEFAULT 'auto';
    PRAGMA user_version=2;
    """,
]


def migrate(db_path: str):
    """Apply pending schema migrations."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    log.info("DB version: %d, available migrations: %d", current_version, len(MIGRATIONS))

    for i, migration_sql in enumerate(MIGRATIONS):
        version = i + 1
        if version <= current_version:
            continue
        log.info("Applying migration %d...", version)
        try:
            conn.executescript(migration_sql)
            log.info("Migration %d applied successfully", version)
        except Exception as e:
            log.error("Migration %d failed: %s", version, e)
            conn.close()
            raise

    conn.close()
```

### Migration rules
- Each migration block ends with `PRAGMA user_version=N;`
- Migrations are idempotent where possible (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`)
- `ALTER TABLE ADD COLUMN` is one of the few ALTER operations SQLite supports natively
- For operations SQLite cannot do (rename column, change type, drop column), use the 12-step table rebuild: create new table, copy data, drop old, rename new
- Always test migrations on a copy of the database before shipping

## 2.5 Export/Import as JSON for Sync

```python
import json
from datetime import datetime


def export_brain(db: BrainDB) -> str:
    """Export vocabulary and settings as JSON for sync."""
    vocabulary = db.read("SELECT * FROM vocabulary ORDER BY term")
    corrections = db.read("SELECT * FROM corrections ORDER BY created_at DESC LIMIT 1000")

    export = {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "vocabulary": [dict(row) for row in vocabulary],
        "corrections": [dict(row) for row in corrections],
    }
    return json.dumps(export, indent=2, ensure_ascii=False)


def import_brain(db: BrainDB, json_str: str, merge_strategy: str = "union"):
    """Import vocabulary from JSON. merge_strategy: 'union' or 'replace'."""
    data = json.loads(json_str)

    if merge_strategy == "replace":
        db.write("DELETE FROM vocabulary")

    for entry in data.get("vocabulary", []):
        db.write(
            """INSERT INTO vocabulary (term, phonetic, category, priority, source)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(term) DO UPDATE SET
                   phonetic = COALESCE(excluded.phonetic, phonetic),
                   priority = excluded.priority,
                   updated_at = datetime('now')""",
            (entry["term"], entry.get("phonetic"), entry.get("category", "general"),
             entry.get("priority", "normal"), entry.get("source", "imported")),
        )
```

### Sync via Syncthing
Since the user has Syncthing between phone and PC:
- Export as `brain_export.json` to a Syncthing-shared folder
- Android app watches for changes and imports on detection
- Use `exported_at` timestamp to determine which export is newer
- Merge strategy: union of vocabulary entries, last-write-wins for conflicts on same term (compare `updated_at`)
- **Never sync the `.db` file directly via Syncthing** -- SQLite database files can corrupt if modified by two processes simultaneously, and Syncthing is not transaction-aware

## 2.6 Connection Configuration Cheat Sheet

```python
# All PRAGMAs to set on every new connection:
PRAGMAS = {
    "journal_mode": "WAL",        # concurrent reads + writes
    "synchronous": "NORMAL",      # safe with WAL, faster than FULL
    "foreign_keys": "ON",         # enforce FK constraints (off by default!)
    "temp_store": "MEMORY",       # temp tables in RAM
    "cache_size": "-8000",        # 8MB page cache (negative = KiB)
    "busy_timeout": "5000",       # wait 5s for locks instead of failing immediately
}

def apply_pragmas(conn: sqlite3.Connection):
    for pragma, value in PRAGMAS.items():
        conn.execute(f"PRAGMA {pragma}={value}")
```

### Why `busy_timeout` matters
Without it, SQLite immediately raises `OperationalError: database is locked` when it encounters a lock. With `busy_timeout=5000`, SQLite retries internally for up to 5 seconds. This is equivalent to `sqlite3.connect(db_path, timeout=5.0)` but can also be set via PRAGMA.

## 2.7 Windows-Specific Considerations

### File locking
- **SQLite uses Windows file locking APIs** (LockFileEx/UnlockFileEx) on NTFS. These work correctly for local files.
- **Never put a SQLite database on a network share** (SMB/CIFS). File locking over network protocols is unreliable and will cause corruption or "database is locked" errors.
- **OneDrive / Google Drive sync**: These tools may try to sync the `.db`, `.db-wal`, and `.db-shm` files independently, causing corruption. Store the database in a directory excluded from cloud sync (e.g., `%LOCALAPPDATA%\Transcriber\`).
- **Antivirus**: Some antivirus software (especially real-time scanning) holds file locks on `.db` files, causing "database is locked" errors. Add the database directory to your antivirus exclusion list if you encounter this.

### Recommended database location
```python
import os
from pathlib import Path

def get_db_path() -> Path:
    """Get the platform-appropriate database path."""
    # %LOCALAPPDATA% is per-user, not synced by OneDrive, not backed up by default
    app_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Transcriber"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "brain.db"
```

### Path encoding
- Use `pathlib.Path` throughout. It handles Windows backslashes correctly.
- `sqlite3.connect()` accepts both `str` and `Path` objects (in Python 3.12).

### Long-running desktop app considerations
- **Close connections on exit**: Register a cleanup function with `atexit` to close all connections and run a final WAL checkpoint.
- **Periodic WAL checkpoint**: In a long-running tray app, run `PRAGMA wal_checkpoint(PASSIVE)` every 5-10 minutes to prevent WAL file bloat.
- **Handle system sleep/resume**: After Windows wakes from sleep, existing connections are still valid (the file is local), but it is good practice to run a quick read query to verify.

```python
import atexit

def setup_db():
    db = BrainDB(get_db_path())
    migrate(str(get_db_path()))

    def cleanup():
        conn = db._get_conn()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.close()

    atexit.register(cleanup)
    return db
```

## 2.8 Common Pitfalls Summary

| Pitfall | Consequence | Fix |
|---|---|---|
| Forgetting `PRAGMA foreign_keys=ON` | FK constraints silently ignored | Set on every new connection |
| Using a shared connection across threads without serialization | Data corruption | Use per-thread connections |
| Storing DB in OneDrive/Dropbox folder | Corruption from partial sync | Use `%LOCALAPPDATA%` |
| Not setting `busy_timeout` | Immediate "database is locked" errors | Set `timeout=10.0` or `PRAGMA busy_timeout=10000` |
| Not enabling WAL mode | Readers block writers and vice versa | `PRAGMA journal_mode=WAL` on first connection |
| Syncing `.db` file directly via Syncthing | Corruption | Sync JSON exports only |
| Not checkpointing WAL periodically | WAL file grows unbounded | Schedule periodic `PRAGMA wal_checkpoint(PASSIVE)` |
| Using Alembic with SQLite for a simple desktop app | Unnecessary complexity, known SQLite quirks | Use `PRAGMA user_version` migration pattern |
| Forgetting `conn.commit()` after writes | Changes lost on connection close | Always commit, or use `with conn:` context manager |
| Not handling `OperationalError` for locked DB | App crashes under contention | Catch and retry, or increase busy_timeout |
