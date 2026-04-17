"""Cloud → local fallback dictation orchestrator.

Cloud path: delegate to any `CloudProvider` (OpenRouter, Groq, ...) — the provider
returns already-polished text.
Local fallback path branches by mode:
  - "streaming" → Whisper + apply_formatting_commands (regex).
  - "batch"     → Whisper + postprocess_text (Ollama).

Keeps `last_language` / `last_language_probability` / `last_path` attributes so the
recording indicator and per-segment timing log can label each result.
"""

import logging

from cloud_dictator import CloudProvider, CloudUnavailable
from modes import Mode
from transcriber import Transcriber

log = logging.getLogger("transcriber.cascade_dictator")


class CascadeDictator:
    def __init__(
        self,
        *,
        cloud: CloudProvider | None,
        transcriber: Transcriber,
        pp_config: dict,
        build_system_prompt,
    ):
        self._cloud = cloud
        self._transcriber = transcriber
        self._pp_config = pp_config
        self._build_system_prompt = build_system_prompt
        self.last_language: str = ""
        self.last_language_probability: float = 0.0
        self.last_path: str = "local"

    def dictate(
        self,
        audio,
        *,
        mode: str,
        vocabulary_text: str,
        previous_segment: str,
        initial_prompt: str | None,
        user_mode: Mode | None = None,
    ) -> str:
        raw_output = user_mode is not None and user_mode.output_format == "raw"
        # StreamingRecorder has already run Silero VAD. A second VAD pass inside
        # Whisper clips word edges, so disable vad_filter on the streaming path.
        local_vad_filter = mode != "streaming"

        # Raw-output modes (e.g. Code): skip cloud polish + local formatting commands.
        # Goes straight to Whisper and returns the verbatim transcript.
        if raw_output:
            raw = self._transcriber.transcribe(
                audio, initial_prompt=initial_prompt, vad_filter=local_vad_filter,
            )
            self.last_language = self._transcriber.last_language
            self.last_language_probability = self._transcriber.last_language_probability
            self.last_path = "local-raw"
            return raw.strip()

        polish_addendum = user_mode.polish_prompt_addendum if user_mode else ""

        if self._cloud is not None:
            try:
                prompt = self._build_system_prompt(
                    vocabulary_text=vocabulary_text,
                    previous_segment=previous_segment,
                    mode=mode,
                    polish_addendum=polish_addendum,
                )
                text = self._cloud.dictate(audio, system_prompt=prompt)
                self.last_language = "en"
                self.last_language_probability = 1.0
                self.last_path = "cloud"
                return text
            except CloudUnavailable:
                pass  # Fall through to local.

        raw = self._transcriber.transcribe(
            audio, initial_prompt=initial_prompt, vad_filter=local_vad_filter,
        )
        self.last_language = self._transcriber.last_language
        self.last_language_probability = self._transcriber.last_language_probability
        self.last_path = "local"
        raw = raw.strip()
        if not raw:
            return ""

        if mode == "streaming":
            from commands import apply_formatting_commands
            return apply_formatting_commands(raw)

        from postprocessor import postprocess_text
        return postprocess_text(raw, self._pp_config, vocabulary_text=vocabulary_text)
