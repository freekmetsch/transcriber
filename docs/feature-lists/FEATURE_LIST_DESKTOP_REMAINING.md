# Feature List: Desktop Remaining Work

Date: 2026-04-15
Status: Active
Scope: Everything left to build on the Windows desktop before moving to Android
Owner: Freek

---

## What's Done

- [x] **Phase 1 — Desktop MVP**: push-to-talk hotkey, recording, faster-whisper transcription, clipboard paste
- [x] **Phase 2 — LLM Post-Processing**: Ollama integration, formatting commands (EN+NL), graceful fallback
- [x] **Phase 3 — Vocabulary Brain**: SQLite DB, prompt conditioning, correction tracking, auto-learning, vocab CLI (59/59 tests)

---

## What's Left (desktop only)

### Phase 3.5: UX Polish
> Detailed plan: `FEATURE_LIST_UX_POLISH.md`

The brain works but nobody will use it if corrections don't flow in naturally.

- [ ] **3.5A: Auto-show correction window** — appears after each transcription near the tray, doesn't steal focus, auto-hides after 8s. Configurable: auto / hotkey / off.
- [ ] **3.5B: Quick-add vocabulary** — "Add to vocab" button in the correction window. Pre-fills term + phonetic hint from the correction. One-click add, prompt rebuilds immediately.
- [ ] **3.5C: Toast notifications** — `winotify` for auto-learn events ("Brain learned: Freek"), Ollama failures (once per session), import confirmations. Silent, 5s, optional dependency.
- [ ] **3.5D: Vocabulary manager window** — Tkinter Toplevel from tray menu. List all terms, add/remove/edit priority, export/import JSON via file dialog.
- [ ] **3.5E: Dynamic tray menu** — live vocabulary count in the tray menu or tooltip. Refresh after any brain mutation.

### Phase 5A: Vocabulary Sync (desktop side)
> The Android side exports JSON to a Syncthing-shared folder. Desktop needs to pick it up.

- [ ] **File watcher** — monitor Syncthing folder for new/changed `brain_export.json`
- [ ] **Auto-import on change** — union merge, last-write-wins for conflicts on same term
- [ ] **Export on brain change** — write `brain_export.json` to Syncthing folder after corrections/auto-learn/manual edits
- [ ] **Conflict log** — log merge conflicts for manual review (rare for single user, but safe)

### Phase 5B: Streaming Text Preview (nice-to-have)
> Show partial transcription while the user is still speaking.

- [ ] **Floating preview window** — small, semi-transparent, positioned near tray
- [ ] **Chunked transcription** — transcribe every ~2s while still recording via faster-whisper
- [ ] **Final replace** — full result replaces preview on hotkey release
- [ ] **Toggle** — configurable on/off (off = lower latency, current behavior)

### Phase 5C: Voice Commands (nice-to-have)
> Detect command phrases and execute them instead of typing them.

- [ ] **Command detection** — LLM post-processor classifies utterance as command vs dictation
- [ ] **Starter set**: "select all", "undo", "new line", "new paragraph"
- [ ] **Bilingual**: support both EN and NL command phrases

### Phase 5D: Whisper Fine-Tuning (future)
> The ultimate accuracy improvement — requires correction data to accumulate first.

- [ ] **Training script** — Hugging Face Transformers + LoRA on collected audio + corrections
- [ ] **Audio capture** — save audio segments alongside corrections (audio_hash in corrections table already exists)
- [ ] **Custom checkpoint** — produces a fine-tuned model usable on desktop and Android
- [ ] **Minimum data**: ~30 minutes of corrected audio before fine-tuning is viable

---

## Recommended Build Order

1. **Phase 3.5** (UX Polish) — highest impact, makes everything else more useful because corrections start flowing
2. **Phase 5A** (Sync) — needed before Android launch so vocab is shared
3. **Phase 5B** (Preview) — nice QoL but not blocking anything
4. **Phase 5C** (Commands) — low priority, formatting commands in Phase 2 cover the common cases
5. **Phase 5D** (Fine-tuning) — only viable after weeks of correction data

---

## Resume Pack

**Current state**: Phases 1-3 complete. Desktop is fully functional for dictation with vocabulary learning.

**Next step**: Phase 3.5 (UX Polish). See `FEATURE_LIST_UX_POLISH.md` for the detailed plan.

**Next command**: `/run`
