---
name: python-dev-patterns
description: Python 3.12 debugging discipline, testing patterns, root-cause investigation, and development best practices for desktop applications.
license: MIT
metadata:
  tags: [python, debugging, testing, pytest, desktop]
  sources:
    - community:systematic-debugging (root-cause-first debugging)
    - community:verification-before-completion (evidence before claims)
---

# Python Development Patterns

## Debugging Discipline

**NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.**

1. Read error messages completely — stack traces contain the answer.
2. Reproduce consistently before proposing fixes.
3. Check recent changes (`git diff`).
4. Form a single hypothesis, test minimally, one variable at a time.
5. If 3+ fixes fail: question the architecture, don't try fix #4.

### Root cause tracing
When a bug appears deep in the call stack, trace backward to the source:
1. Find the immediate cause (which line errors).
2. Ask: what called this with a bad value?
3. Keep tracing up until you find where the bad value originates.
4. Fix at the source, not the symptom.

Use `traceback.format_stack()` when you can't trace manually:
```python
import traceback
logger.debug("transcribe called:\n%s", "".join(traceback.format_stack()))
```

### Defense-in-depth validation
After finding a bug, validate at every layer data passes through:
1. **Entry point**: reject invalid input at the boundary.
2. **Business logic**: ensure data makes sense for this operation.
3. **Environment guard**: refuse dangerous operations in test context.
4. **Debug instrumentation**: log context for forensics.

All four layers are necessary — different code paths bypass different checks.

## Threading Patterns (Desktop App)

This app uses multiple threads: main (pystray), keyboard hooks, PortAudio audio callback, worker threads for transcription. Key rules:

### Lock ordering
When multiple locks exist, always acquire in the same order to prevent deadlocks:
```python
# Document the order
# 1. _recording_lock (app state)
# 2. _paste_lock (clipboard)
# Never acquire _recording_lock while holding _paste_lock
```

### Never block the hook thread
The keyboard library's hook thread delivers ALL keyboard events system-wide. Blocking it causes noticeable input lag:
```python
# BAD: heavy work on hook thread
def on_key_release(event):
    audio = recorder.stop()           # blocks for concatenation
    text = transcriber.transcribe(audio)  # blocks for GPU inference

# GOOD: signal and move work to a worker thread
def on_key_release(event):
    threading.Thread(target=_stop_and_transcribe, daemon=True).start()
```

### GIL-safe patterns
CPython's GIL makes `list.append()` atomic, but don't rely on it:
```python
# Fragile (works on CPython only)
self._buffer.append(data)

# Robust (works everywhere)
with self._lock:
    self._buffer.append(data)

# Best for producer-consumer (no lock needed)
import queue
self._queue = queue.SimpleQueue()
self._queue.put(data)
```

## Testing Discipline

### Red-green-refactor
1. **RED**: Write one minimal test. Run it. Watch it fail for the right reason.
2. **GREEN**: Write simplest code to pass. All tests green.
3. **REFACTOR**: Clean up. Tests stay green.

Use `@pytest.mark.asyncio` for async tests. Use `tmp_path` fixture for file operations.

### Testing Anti-Patterns

**Anti-Pattern 1: Testing Mock Behavior**
```python
# BAD: only proves mock was wired up
def test_transcriber(mock_whisper):
    result = transcribe(audio)
    mock_whisper.assert_called_once()

# GOOD: test real behavior with realistic mock output
def test_transcriber(mock_whisper_segments):
    result = transcribe(audio)
    assert "hello world" in result.lower()
```

**Anti-Pattern 2: Mocking Without Understanding**
```python
# BAD: mock prevents side effect the test depends on
@patch("transcriber.WhisperModel")
def test_fallback(mock_model):
    mock_model.side_effect = RuntimeError()
    # But we're testing CUDA→CPU fallback, which needs the real constructor...

# GOOD: mock at the right level
@patch("transcriber.WhisperModel.__init__")
def test_fallback(mock_init):
    mock_init.side_effect = [RuntimeError(), None]  # CUDA fails, CPU succeeds
```

**Gate before mocking:**
1. What side effects does the real method have?
2. Does this test depend on any of them?
3. Mock at the lowest level that removes the slow/external part.

**Anti-Pattern 3: Incomplete Mocks**
```python
# BAD: partial mock, missing fields downstream code needs
mock_segment = {"text": "hello"}

# GOOD: use a proper object with all expected attributes
from unittest.mock import Mock
mock_segment = Mock(text=" hello world", start=0.0, end=1.5)
```

**Rule:** Mock the COMPLETE data structure. If a Pydantic model or dataclass exists, use it.

### Red Flags — STOP
- Mock setup longer than test logic.
- Assertion on mock call counts but not on actual output.
- Methods only called in test files.
- Can't explain why a mock is needed.
