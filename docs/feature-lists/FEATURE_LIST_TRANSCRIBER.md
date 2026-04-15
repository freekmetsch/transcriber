# Feature List: Personal Transcriber — Cross-Platform Voice-to-Text

Date: 2026-04-15
Status: In Progress (Phase 3.5 complete)
Scope: Windows desktop app + Android voice input service + shared vocabulary brain
Owner: Freek

---

## Problem Framing

Current voice typing tools (Gboard, Windows+H) fail on three fronts:
1. **Code-switching**: No support for mid-sentence Dutch+English mixing, which is how the user naturally speaks.
2. **Custom vocabulary**: Proper nouns (names), technical jargon, and domain-specific terms are consistently misrecognized. No way to teach the system.
3. **Formatting**: Raw transcription without reliable punctuation, capitalization, or paragraph control makes voice typing unusable for anything beyond rough notes.

**Goal**: A personal voice-to-text system that runs on Windows (desktop) and Android (mobile), handles Dutch+English code-switching, learns the user's vocabulary over time, and produces well-formatted text ready for emails, chat, and documentation.

---

## Scope

### In Scope
- Windows system tray app with global hotkey dictation (like Win+H but better)
- Android voice input service that works with any keyboard (HeliBoard recommended)
- Local-first transcription using faster-whisper (desktop) and whisper.cpp (Android)
- LLM post-processing via Ollama for punctuation, formatting, and code-switch cleanup
- Custom vocabulary database with learning from corrections
- Formatting voice commands ("period", "comma", "new line", "new paragraph")
- Vocabulary sync between desktop and Android
- Cloud fallback for transcription when local models underperform

### Out of Scope (for now)
- iOS support
- macOS/Linux support
- Context-awareness per app (different behavior in email vs chat)
- AI assistant features (user has a separate assistant)
- Meeting/conversation transcription (future feature)
- Auto-translation
- Advanced voice commands (select, delete, undo) — nice-to-have, deferred

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  SHARED BRAIN                        │
│  SQLite DB: vocabulary, corrections, prompt config   │
│  Syncs between desktop and mobile                    │
└──────────┬──────────────────────────┬────────────────┘
           │                          │
    ┌──────▼──────┐           ┌───────▼───────┐
    │  DESKTOP    │           │   ANDROID     │
    │  (Python)   │           │   (Kotlin)    │
    │             │           │               │
    │ Hotkey →    │           │ Mic button →  │
    │ Record →    │           │ Record →      │
    │ faster-     │           │ whisper.cpp   │
    │ whisper →   │           │ (JNI) →       │
    │ Ollama →    │           │ Post-process →│
    │ Paste       │           │ Return text   │
    └─────────────┘           └───────────────┘
```

### Key Insight: Android Doesn't Need a Custom Keyboard

Android's IME framework has a standard `ACTION_RECOGNIZE_SPEECH` intent. Any keyboard's mic button routes to the device's default speech recognizer. We build a standalone **RecognitionService** app — HeliBoard (or any keyboard) calls it automatically. Zero keyboard forking required.

---

## Chosen Approach: Python Desktop + Kotlin RecognitionService + Shared SQLite Brain

### Why This Approach

1. **Desktop in Python** — the user's comfort zone. The entire pipeline (`keyboard` + `sounddevice` + `faster-whisper` + `pyautogui` + `pystray`) is well-established on Windows. No Rust/TypeScript learning curve.
2. **Android as a RecognitionService** — dramatically smaller scope than forking a keyboard. whisper.cpp has official Android JNI bindings. Pairs with unmodified HeliBoard.
3. **Shared SQLite brain** — vocabulary, corrections, and prompt config in one portable database. SQLite works natively on both Python and Android/Kotlin.
4. **Ollama post-processing** — already running on user's PC. Handles punctuation, formatting, code-switch cleanup, and custom vocabulary correction in a single pass. Small model (e.g., Phi-3, Qwen2.5 3B) keeps latency low.
5. **Local-first** — no ongoing API costs for the core pipeline. Cloud fallback optional.

### Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| **Fork Handy or Whispering** (Tauri/Rust desktop apps) | Outside user's language expertise (Rust/TypeScript). Desktop-only — no mobile story. Maintaining a fork of a rapidly evolving Rust project is high overhead for a solo dev. |
| **Fork FUTO Keyboard** (Android) | FUTO Source First License restricts redistribution. Can't share or publish modifications. Also couples voice input to a specific keyboard — the RecognitionService approach is more flexible. |
| **Fork HeliBoard + embed Whisper** (Android) | Unnecessary complexity. HeliBoard already delegates voice input via Android's standard intent system. Building a RecognitionService is cleaner, simpler, and works with ANY keyboard. |
| **Cloud-first (OpenAI Whisper API everywhere)** | Ongoing cost (~$0.006/min), requires internet, privacy tradeoff. User has 16GB VRAM — local inference is free and fast. Cloud as fallback, not primary. |
| **Build from existing project (WhisperWriter, nerd-dictation)** | These are decent starting points but would need heavy modification for: code-switching post-processing, vocabulary learning, Android sync. Building clean from scratch with a clear architecture is less technical debt than retrofitting. |

---

## Phase Plan

### Phase 1: Desktop MVP
**Goal**: Replace Win+H with a working voice-to-text pipeline on Windows.
**Context strategy**: single-window
**Risk tier**: R1 (localized, low blast radius)
**Estimated effort**: M (multi-file, ~2-3 sessions)

#### What Gets Built
- System tray app with `pystray` (icon, menu: settings, quit)
- Global hotkey via `keyboard` library (e.g., Ctrl+Shift+Space) — push-to-talk (hold to record, release to transcribe)
- Audio recording via `sounddevice` (16kHz mono, WAV buffer)
- Transcription via `faster-whisper` with `large-v3` model, CUDA GPU acceleration
  - `vad_filter=True` (built-in Silero VAD) for automatic speech boundary detection
  - No language forcing — let Whisper auto-detect per segment for Dutch+English
- Text output via clipboard paste (`pyperclip` + `pyautogui.hotkey('ctrl', 'v')`)
  - Save/restore clipboard contents to avoid data loss
- Basic error handling: mic not found, model load failure, GPU fallback to CPU
- Configuration via YAML or JSON file (hotkey, model path, device selection)

#### Verification
- Manual smoke test: hotkey → speak English → text appears in Notepad
- Manual smoke test: hotkey → speak Dutch → text appears correctly
- Manual smoke test: hotkey → speak mixed Dutch+English → both languages captured
- Test in: Notepad, browser text field, terminal, VS Code

#### Files
```
transcriber/
├── app.py              # Entry point, system tray, hotkey binding
├── recorder.py         # Microphone recording (sounddevice)
├── transcriber.py      # faster-whisper inference
├── output.py           # Clipboard paste into active window
├── config.py           # Configuration loading
└── config.yaml         # User configuration
```

---

### Phase 2: LLM Post-Processing Pipeline
**Goal**: Transform raw Whisper output into well-formatted, code-switch-clean text.
**Context strategy**: single-window
**Risk tier**: R1
**Estimated effort**: M (~1-2 sessions)

#### What Gets Built
- Ollama integration via HTTP API (localhost:11434)
- Post-processing prompt chain:
  1. Fix punctuation, capitalization, paragraph breaks
  2. Clean up code-switching artifacts (e.g., Whisper sometimes outputs Dutch words with English spelling)
  3. Apply custom vocabulary corrections (from brain DB — Phase 3 dependency, use hardcoded list initially)
  4. Parse formatting commands: "period" → `.`, "comma" → `,`, "new line" → `\n`, "new paragraph" → `\n\n`, "exclamation mark" → `!`, "question mark" → `?`, "colon" → `:`, "open quote / close quote" → `"`
- Configurable: post-processing on/off toggle, model selection
- Fallback: if Ollama is unavailable, output raw Whisper text (still usable)
- Latency budget: target <1 second for post-processing (use small model: Phi-3-mini, Qwen2.5-3B, or similar)

#### Key Design Decision: Prompt Engineering
The post-processing prompt is the critical piece for code-switching quality. It needs to:
- Understand that mixed Dutch+English is intentional, not an error
- Know the user's proper nouns and technical terms
- Handle formatting commands in both languages (user may say "punt" or "period")
- NOT translate — preserve the language as spoken

Example system prompt structure:
```
You are a dictation post-processor. The user dictates in mixed Dutch and English.
Your job:
1. Add correct punctuation and capitalization.
2. Convert formatting commands to their symbols (period→. comma→, etc.)
3. Preserve the exact language the user spoke — do NOT translate.
4. Apply these known vocabulary corrections: [from brain DB]
5. Output ONLY the corrected text. No commentary.
```

#### Verification
- Test: raw Whisper output with missing punctuation → formatted output
- Test: "Hello comma this is a test period new line" → "Hello, this is a test.\n"
- Test: mixed Dutch+English sentence preserved correctly
- Test: Ollama unavailable → graceful fallback to raw text
- Latency measurement: end-to-end from speech end to text appearing

#### Files (new/modified)
```
transcriber/
├── postprocessor.py    # Ollama post-processing pipeline
├── commands.py         # Formatting command definitions (both EN and NL)
├── app.py              # Modified: insert post-processing step
└── config.yaml         # Modified: Ollama settings
```

---

### Phase 3: Vocabulary Brain
**Goal**: Build the learning system that makes recognition improve over time.
**Context strategy**: single-window
**Risk tier**: R2 (shared data, corrections affect output quality)
**Estimated effort**: M (~2 sessions)

#### What Gets Built

**3A: Vocabulary Database (SQLite)**
- Tables:
  - `vocabulary`: custom words/phrases with phonetic hints, frequency, source (manual/auto)
  - `corrections`: log of user corrections (original → corrected, timestamp, context)
  - `prompt_fragments`: cached initial_prompt strings generated from vocabulary
  - `settings`: per-user settings and preferences
- Thread-safe access (SQLite WAL mode)
- Export/import as JSON (for sync and backup)

**3B: Whisper Prompt Conditioning**
- Generate `initial_prompt` from vocabulary DB: include proper nouns, technical terms, frequently used phrases
- The `initial_prompt` parameter biases Whisper's decoder toward expected vocabulary
- Rebuild prompt when vocabulary changes
- Research shows this reduces WER by ~25% on domain-specific terms

**3C: Correction Tracking and Auto-Learning**
- Desktop app gets a "correction mode": after transcription, user can press a hotkey to open a small correction window
- User edits the text → correction is logged (original, corrected, audio hash)
- After N corrections of the same pattern (e.g., "Freak" → "Freek"), auto-add to vocabulary
- Configurable threshold for auto-learning (default: 3 identical corrections)

**3D: Manual Vocabulary Management**
- Simple GUI or CLI tool to:
  - Add/remove vocabulary entries
  - View correction history
  - Export/import vocabulary as JSON
  - Mark entries as "high priority" (always in initial_prompt) vs "contextual"

#### Verification
- Test: add proper noun → appears in initial_prompt → Whisper recognizes it
- Test: correct same error 3 times → auto-added to vocabulary
- Test: export vocabulary as JSON → import on fresh install → same behavior
- Test: DB corruption → graceful fallback (recreate from JSON backup)

#### Files (new/modified)
```
transcriber/
├── brain.py            # SQLite vocabulary database, CRUD operations
├── learning.py         # Correction tracking, auto-learning logic
├── prompt_builder.py   # Generate initial_prompt from vocabulary
├── correction_ui.py    # Correction window (tkinter or similar)
├── transcriber.py      # Modified: use initial_prompt from brain
├── postprocessor.py    # Modified: feed vocabulary to LLM prompt
└── brain.db            # SQLite database (created at runtime)
```

---

### Phase 4: Android Voice Input Service
**Goal**: Bring voice typing to Android, powered by whisper.cpp and the shared vocabulary brain.
**Context strategy**: multi-window (Kotlin/Android is a separate codebase)
**Risk tier**: R2 (new platform, JNI integration)
**Estimated effort**: L (~3-4 sessions)

#### What Gets Built

**4A: RecognitionService App**
- Kotlin app implementing `android.speech.RecognitionService`
- Registers as a speech recognition provider in Android system settings
- When any keyboard's mic button is pressed → our service handles it
- Audio capture via Android `AudioRecord` API
- Transcription via whisper.cpp JNI (from official `examples/whisper.android`)
- Model: `whisper-small` or `whisper-base` for on-device (balance of size vs accuracy)
  - Model download on first launch from Hugging Face
  - Model stored in app's internal storage

**4B: Post-Processing on Android**
- Two options (configurable):
  1. **Local small LLM** on phone (e.g., Phi-3-mini via llama.cpp, if device has enough RAM)
  2. **Network call to desktop Ollama** when on same WiFi (user's desktop is already running Ollama)
  3. **Cloud fallback** via OpenAI API (costs ~$0.006/min, only when local options unavailable)
- If no post-processing available: output raw Whisper text (still functional)

**4C: Vocabulary Integration**
- Read vocabulary from local SQLite DB (same schema as desktop)
- Generate initial_prompt from vocabulary for Whisper conditioning
- Log corrections (user manually fixes text after dictation → correction logged)

**4D: Settings UI**
- Model selection (tiny/base/small/medium)
- Post-processing toggle and method (local/network/cloud/off)
- Vocabulary management (view, add, remove entries)
- Desktop Ollama connection settings (IP, port)

#### Verification
- Install app → set as default speech recognizer → HeliBoard mic button triggers our service
- Dictate in English → text returned to keyboard → appears in text field
- Dictate in Dutch → correct output
- Dictate mixed → both languages preserved
- Airplane mode → fully offline transcription works (with on-device model)

#### Project Structure
```
android/
├── app/
│   ├── src/main/
│   │   ├── java/com/transcriber/
│   │   │   ├── WhisperRecognitionService.kt   # Core RecognitionService
│   │   │   ├── WhisperEngine.kt               # JNI wrapper for whisper.cpp
│   │   │   ├── PostProcessor.kt               # LLM post-processing
│   │   │   ├── VocabularyBrain.kt             # SQLite vocabulary DB
│   │   │   ├── PromptBuilder.kt               # initial_prompt generation
│   │   │   └── SettingsActivity.kt            # Settings UI
│   │   ├── cpp/
│   │   │   ├── whisper.cpp                    # whisper.cpp source (git submodule)
│   │   │   └── jni_bridge.cpp                 # JNI bindings
│   │   └── AndroidManifest.xml
│   └── build.gradle.kts
└── build.gradle.kts
```

---

### Phase 5: Sync and Polish
**Goal**: Connect desktop and mobile vocabulary, add quality-of-life features.
**Context strategy**: multi-window
**Risk tier**: R2 (data sync, conflict resolution)
**Estimated effort**: M (~2 sessions)

#### What Gets Built

**5A: Vocabulary Sync**
- **MVP approach**: Export/import JSON files manually (Google Drive, email, USB)
- **Better approach**: Simple sync via shared folder (Google Drive / Syncthing)
  - Desktop watches for changes in sync folder, imports new entries
  - Android exports corrections on a schedule or manually
  - Merge strategy: union of entries, last-write-wins for conflicts on same term
- **Future approach**: Lightweight REST API on desktop that Android hits over local network

**5B: Streaming Text Preview (nice-to-have)**
- Desktop: show a small floating window with partial transcription as you speak
- Uses faster-whisper's chunked processing — transcribe every ~2 seconds while still recording
- Final result replaces preview when you release the hotkey
- Can be toggled off for lower-latency raw paste

**5C: Voice Commands (nice-to-have)**
- Detect command phrases before sending to post-processor
- Start with a small set: "select all", "undo", "new line", "new paragraph"
- Commands detected by LLM post-processor (classify as command vs dictation)
- Keep it simple — this is a nice-to-have, not core

**5D: Whisper Fine-Tuning Pipeline (future)**
- Use collected audio + corrections to fine-tune Whisper with LoRA
- Training script using Hugging Face Transformers
- Can fine-tune whisper-small with 30 minutes of audio in ~20 minutes on GPU
- Produces a custom model checkpoint that can be used on both desktop and Android
- This is the ultimate accuracy improvement but requires Phase 3 correction data to accumulate first

---

## Technology Stack Summary

| Component | Desktop (Windows) | Android |
|---|---|---|
| Language | Python 3.12 | Kotlin |
| Speech-to-text | faster-whisper (CUDA) | whisper.cpp (JNI) |
| Model | whisper-large-v3 (~1.5GB) | whisper-small (~500MB) |
| LLM post-processing | Ollama (local) | llama.cpp / network to desktop Ollama / cloud |
| Audio capture | sounddevice | AudioRecord API |
| Text output | clipboard paste (pyautogui) | RecognitionService → IME |
| Hotkey | keyboard library | keyboard mic button (system) |
| System tray | pystray | N/A (background service) |
| Vocabulary DB | SQLite (via sqlite3) | SQLite (via Room/android.database) |
| Config | YAML | SharedPreferences + DataStore |

### Python Dependencies (Desktop)
```
faster-whisper          # Whisper inference (CTranslate2 backend)
sounddevice             # Audio recording
keyboard                # Global hotkeys
pyautogui               # Clipboard paste into active window
pyperclip               # Clipboard access
pystray                 # System tray
Pillow                  # Tray icon image
pyyaml                  # Configuration
requests                # Ollama HTTP API
```

### Estimated Costs
| Item | Cost |
|---|---|
| Local transcription (faster-whisper) | Free |
| Local post-processing (Ollama) | Free |
| Cloud fallback (OpenAI Whisper API) | ~$0.006/minute |
| Cloud fallback (LLM post-processing) | ~$0.001/request |
| Typical daily usage (30 min dictation, all local) | **$0.00** |
| Typical daily usage (30 min, cloud fallback) | **~$0.21** |

---

## Failure Modes and Mitigations

| # | Failure Mode | Trigger | Impact | Mitigation | Residual Risk |
|---|---|---|---|---|---|
| 1 | Code-switching misrecognition | Mid-sentence language switch | Wrong words in output | LLM post-processing cleanup + vocabulary biasing via initial_prompt. Whisper large-v3 handles per-segment switching reasonably well. | Mid-word switches (e.g., Dutch word with English suffix) may still fail. Acceptable — even human listeners struggle with these. |
| 2 | Clipboard contents lost | Paste operation overwrites user's clipboard | User loses copied data | Save clipboard before paste, restore after. Use win32 clipboard API for reliable save/restore. | Edge case: large clipboard items (images) may be slow to save/restore. Add size limit. |
| 3 | Ollama unavailable or slow | Ollama not running, model not loaded, GPU busy | Post-processing fails or adds >2s latency | Graceful fallback to raw Whisper text. Pre-check Ollama health on app startup. Configurable timeout (default 3s). | Raw text without post-processing is still usable, just less formatted. |
| 4 | Whisper model too large for Android | Large-v3 (1.5GB) on low-RAM phone | App crashes, OOM | Default to whisper-small (500MB) on Android. Let user choose model based on device capability. Warn on low memory. | Smaller model = lower accuracy. Cloud fallback compensates. |
| 5 | VAD cuts speech too early | Short pause mid-sentence interpreted as end of speech | Sentence split across two transcriptions | Configurable silence threshold (default 1.5s). Push-to-talk mode on desktop avoids VAD entirely. | May need per-user tuning. Default should work for most. |
| 6 | Vocabulary sync conflicts | Same term edited on both devices before sync | One edit lost | Union merge for new entries. Last-write-wins with timestamp for edits to same term. Conflict log for manual review. | Rare in practice — single user, unlikely to edit same term simultaneously. |
| 7 | Hotkey conflict | Chosen hotkey conflicts with another app | Hotkey doesn't trigger | Configurable hotkey. Detect conflicts on startup and warn. Suggest alternatives. | User may need to try multiple combinations. |
| 8 | Android RecognitionService not selected | User forgets to set app as default recognizer | Mic button uses Google/other recognizer | First-launch setup wizard guides user to Settings > Speech. In-app check on each launch. | Android may reset default after updates. Add persistent notification reminder. |

---

## Risk Tier and Verification Matrix

| Phase | Risk Tier | Verification |
|---|---|---|
| Phase 1: Desktop MVP | R1 | Manual smoke tests in Notepad, browser, terminal, VS Code. Syntax check all Python files. |
| Phase 2: Post-Processing | R1 | Manual test with sample dictations. Latency measurement. Fallback test (kill Ollama). |
| Phase 3: Vocabulary Brain | R2 | Unit tests for DB operations. Integration test: add vocab → verify in initial_prompt → transcribe. Correction flow end-to-end. |
| Phase 4: Android App | R2 | Install and test with HeliBoard. Test offline. Test with multiple keyboards. |
| Phase 5: Sync & Polish | R2 | Round-trip sync test: add on desktop → appears on Android → edit on Android → syncs back. Conflict resolution test. |

---

## "Are We Reinventing the Wheel?" Assessment

**No, and here's why.**

The existing landscape has two halves that don't talk to each other:
- **Desktop dictation apps** (Handy, Whispering, WhisperWriter) — mature, but desktop-only, no vocabulary learning, no code-switching optimization.
- **Android voice input** (FUTO, Kaiboard) — functional, but no desktop counterpart, no shared vocabulary, no LLM post-processing.

What we're building that doesn't exist:
1. **The Brain** — a vocabulary database that learns from corrections and conditions Whisper's decoder. No existing project does this well.
2. **LLM-powered code-switch cleanup** — existing apps either don't post-process or do generic formatting. None optimize for bilingual code-switching.
3. **Cross-platform vocabulary sync** — no project shares learning between desktop and mobile.

What we're NOT building from scratch:
- Speech recognition engine (using faster-whisper / whisper.cpp)
- Android keyboard (using HeliBoard unmodified)
- LLM inference (using Ollama / llama.cpp)
- The models themselves (using pre-trained Whisper, Phi-3, etc.)

**The unique value is the integration and the brain, not the components.**

The RecognitionService approach for Android is particularly elegant — we don't fork any keyboard, we just build the voice input provider. This is maybe 20% of the work of forking a full keyboard app.

---

## Open Questions

**Q1: Which Ollama model for post-processing?**
Default: Start with `qwen2.5:3b` — good multilingual support (Dutch included), fast on 16GB VRAM, small enough to run alongside Whisper. Switch to `phi3:mini` if Qwen's Dutch is insufficient.
Reason: Model choice affects latency and code-switching quality. Easy to swap later.

**Q2: Push-to-talk or toggle mode for desktop hotkey?**
Default: Push-to-talk (hold to record, release to transcribe). Add toggle mode later as an option.
Reason: Push-to-talk is simpler to implement, avoids VAD complexity, and gives user explicit control over recording boundaries. Toggle mode (press once to start, press again to stop) is a nice-to-have.

**Q3: Sync mechanism for vocabulary?**
Default: Start with manual JSON export/import. Add Google Drive or Syncthing auto-sync in Phase 5 based on what the user already uses for file sync.
Reason: Building a sync service is scope creep. Most users already have a file sync solution. Start simple.

**Q4: Android model size?**
Default: Ship with `whisper-base` (~150MB), offer `whisper-small` (~500MB) as optional download. Don't offer larger models on mobile.
Reason: Balance between download size, RAM usage, and accuracy. Cloud fallback covers the accuracy gap.

**Q5: Correction UI on desktop — inline or separate window?**
Default: Small floating window that appears after each transcription showing the result, with an edit field. Press Enter to accept, Escape to dismiss. Corrections auto-logged.
Reason: Inline correction in the target app is much harder (would need to track cursor position across apps). A floating window is simpler and works everywhere.

**Q6: Does the user already use Syncthing, Google Drive, or another file sync tool between phone and PC?**
Default: Assume manual sync (JSON export/import). Ask user before implementing Phase 5.
Reason: The sync implementation depends entirely on what infrastructure the user already has.

**Q7: Formatting commands in Dutch too?**
Default: Yes — support both English and Dutch formatting commands ("punt" = "period", "komma" = "comma", "nieuwe regel" = "new line"). Define in a configurable commands file.
Reason: The user code-switches, so formatting commands may come in either language.

---

## Resume Pack

**Goal**: Build a personal cross-platform voice-to-text system with Dutch+English code-switching support, vocabulary learning, and LLM post-processing.

**Current state**: Phase 3.5 (UX Polish) complete. All source files written, tested (59/59 passing), and syntax-checked. See FEATURE_LIST_UX_POLISH.md for Phase 3.5 details.

**What was built (Phase 1)**:
- `app.py` — System tray app with push-to-talk hotkey (Ctrl+Shift+Space)
- `recorder.py` — Microphone recording via sounddevice (16kHz mono float32)
- `transcriber.py` — faster-whisper inference (large-v3, CUDA with CPU fallback)
- `output.py` — Clipboard paste with save/restore and thread-safe locking
- `config.py` — YAML config loading with deep-merged defaults
- `config.yaml` — Default configuration
- `requirements.txt` — Python dependencies
- `.gitignore` — Standard ignores

**What was built (Phase 2)**:
- `postprocessor.py` — Ollama /api/chat integration with connection reuse (requests.Session), graceful fallback to raw text on any failure
- `commands.py` — Formatting command definitions: EN + NL bilingual (period/punt, comma/komma, new line/nieuwe regel, etc.)
- `app.py` — Modified: post-processing inserted after transcription, Ollama health check on startup
- `config.py` — Modified: postprocessing defaults added (enabled, model, base_url, timeout)
- `config.yaml` — Modified: postprocessing section added
- `requirements.txt` — Modified: added `requests>=2.31.0`

**What was built (Phase 3)**:
- `brain.py` — SQLite vocabulary database (WAL mode, thread-safe, CRUD for vocabulary/corrections/settings, JSON export/import)
- `prompt_builder.py` — Generates Whisper `initial_prompt` from vocabulary DB (high-priority terms first, character budget, caching)
- `learning.py` — Correction tracking with auto-learning (word-level diff, configurable threshold, auto-promotes repeated corrections to vocabulary)
- `correction_ui.py` — Tkinter floating correction window (dark theme, Enter to accept, Escape to dismiss, Shift+Enter for newlines)
- `vocab.py` — CLI tool for vocabulary management (add/remove/list/export/import/stats)
- `transcriber.py` — Modified: accepts `initial_prompt` parameter to bias Whisper decoder
- `postprocessor.py` — Modified: dynamically includes vocabulary terms in LLM system prompt
- `app.py` — Modified: initializes brain on startup, wires prompt conditioning into transcription, correction hotkey (Ctrl+Shift+C), vocabulary export/import in tray menu, proper cleanup on shutdown
- `config.py` — Modified: brain defaults added (enabled, db_path, auto_learn_threshold, prompt_max_chars, correction_hotkey)
- `config.yaml` — Modified: brain section added
- `tests/test_brain.py` — 31 tests for database CRUD, corrections, caching, settings, JSON export/import, WAL mode
- `tests/test_prompt_builder.py` — 12 tests for prompt building, caching, vocabulary formatting
- `tests/test_learning.py` — 14 tests for correction tracking, auto-learning threshold, word-level diff
- `tests/conftest.py` — Pytest config for imports

**Before first run**:
1. Create venv: `python -m venv venv && venv\Scripts\activate`
2. Install deps: `pip install -r requirements.txt`
3. Install test deps: `pip install pytest`
4. Ensure CUDA toolkit is installed for GPU acceleration
5. Ensure Ollama is running: `ollama serve`
6. Pull the post-processing model: `ollama pull qwen2.5:3b`
7. Optionally seed vocabulary: `python vocab.py add "YourName" --hint "misheard-version" --priority high`
8. Run: `python app.py`
9. Whisper model downloads automatically on first run (~3 GB for large-v3)

**Key hotkeys**:
- `Ctrl+Shift+Space` — Push-to-talk (hold to record, release to transcribe)
- `Ctrl+Shift+C` — Open correction window for last transcription

**Resolved user input**:
- Q2: Push-to-talk with Ctrl+Shift+Space (confirmed)
- Q6: Syncthing already running between phone and PC (confirmed)

**Next step**: Phase 4 (Android Voice Input Service). Kotlin RecognitionService app with whisper.cpp JNI, vocabulary integration, and post-processing.

**Next command**: `/run` (Phase 4)
