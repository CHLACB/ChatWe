from __future__ import annotations

from typing import Protocol


class SpeechGateway(Protocol):
    """Boundary for voice-message transcription.

    This is separate from AiGateway. Speech recognition only turns an audio file
    into text; the chat model still decides whether and how to reply.
    """

    def transcribe_audio(self, audio_path: str, prompt: str = "") -> str:
        ...
