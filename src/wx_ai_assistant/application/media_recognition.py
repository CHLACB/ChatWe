from __future__ import annotations

from dataclasses import dataclass

from wx_ai_assistant.core.text_sanitize import sanitize_text
from wx_ai_assistant.domain.enums import MessageType
from wx_ai_assistant.domain.models import Message
from wx_ai_assistant.ports.speech_gateway import SpeechGateway
from wx_ai_assistant.ports.vision_gateway import VisionGateway


@dataclass(frozen=True)
class MediaRecognitionResult:
    text: str
    description: str = ""
    media_path: str | None = None
    media_mime_type: str | None = None


class MediaRecognitionService:
    """Turns non-text WeChat messages into text that can enter the AI context.

    The first implementation is intentionally conservative: it only preserves
    text already exposed by WeChat/UIA and emits explicit placeholders for
    unrecognized media. OCR/VLM/STT engines can be plugged in here without
    changing ListenerManager, SendQueue, or LangGraph.
    """

    def __init__(
        self,
        vision_gateway: VisionGateway | None = None,
        enable_vision: bool = False,
        speech_gateway: SpeechGateway | None = None,
        enable_speech: bool = False,
    ):
        self.vision_gateway = vision_gateway
        self.enable_vision = enable_vision
        self.speech_gateway = speech_gateway
        self.enable_speech = enable_speech

    def recognize(self, message: Message) -> Message:
        if message.message_type == MessageType.TEXT:
            message.content = sanitize_text(message.content)
            return message

        result = self._recognize_with_wechat_voice_text(message) or self._recognize_with_speech(message) or self._recognize_with_vision(message) or self._placeholder_result(message)
        message.content = sanitize_text(result.text)
        message.media_description = sanitize_text(result.description)
        message.media_path = result.media_path
        message.media_mime_type = result.media_mime_type
        return message

    def _recognize_with_vision(self, message: Message) -> MediaRecognitionResult | None:
        if (
            not self.enable_vision
            or self.vision_gateway is None
            or message.message_type not in {MessageType.IMAGE, MessageType.STICKER}
            or not message.media_path
        ):
            return None
        try:
            description = sanitize_text(
                self.vision_gateway.describe_image(message.media_path, message.message_type)
            ).strip()
        except Exception as exc:
            description = f"视觉识别失败: {exc}"
            return MediaRecognitionResult(
                text=f"[{self._media_label(message.message_type)}识别失败] {description}",
                description=description,
                media_path=message.media_path,
                media_mime_type=message.media_mime_type,
            )
        if not description:
            return None
        return MediaRecognitionResult(
            text=f"[{self._media_label(message.message_type)}识别] {description}",
            description=description,
            media_path=message.media_path,
            media_mime_type=message.media_mime_type,
        )

    def _recognize_with_wechat_voice_text(self, message: Message) -> MediaRecognitionResult | None:
        if message.message_type != MessageType.VOICE:
            return None
        text = self._extract_visible_voice_transcript(message.content)
        if not text:
            return None
        return MediaRecognitionResult(
            text=f"[语音转写] {text}",
            description=text,
            media_path=message.media_path,
            media_mime_type=message.media_mime_type,
        )

    def _recognize_with_speech(self, message: Message) -> MediaRecognitionResult | None:
        if (
            not self.enable_speech
            or self.speech_gateway is None
            or message.message_type != MessageType.VOICE
            or not message.media_path
        ):
            return None
        try:
            transcript = sanitize_text(self.speech_gateway.transcribe_audio(message.media_path)).strip()
        except Exception as exc:
            description = f"语音识别失败: {exc}"
            return MediaRecognitionResult(
                text=f"[语音识别失败] {description}",
                description=description,
                media_path=message.media_path,
                media_mime_type=message.media_mime_type,
            )
        if not transcript:
            return None
        return MediaRecognitionResult(
            text=f"[语音转写] {transcript}",
            description=transcript,
            media_path=message.media_path,
            media_mime_type=message.media_mime_type,
        )

    def _placeholder_result(self, message: Message) -> MediaRecognitionResult:
        original = sanitize_text(message.content).strip()
        if message.message_type == MessageType.IMAGE:
            description = original or "图片内容尚未识别"
            return MediaRecognitionResult(
                text=f"[图片识别待补充] {description}",
                description=description,
            )
        if message.message_type == MessageType.STICKER:
            description = original or "表情包含义尚未识别"
            return MediaRecognitionResult(
                text=f"[表情包识别待补充] {description}",
                description=description,
            )
        if message.message_type == MessageType.VOICE:
            description = original or "语音尚未转写"
            return MediaRecognitionResult(
                text=f"[语音转写待补充] {description}",
                description=description,
                media_path=message.media_path,
                media_mime_type=message.media_mime_type,
            )
        return MediaRecognitionResult(
            text=original or "[暂不支持的消息类型]",
            description=original,
        )

    def _media_label(self, message_type: MessageType) -> str:
        if message_type == MessageType.STICKER:
            return "表情包"
        if message_type == MessageType.IMAGE:
            return "图片"
        if message_type == MessageType.VOICE:
            return "语音"
        return "媒体"

    def _extract_visible_voice_transcript(self, content: str) -> str:
        original = sanitize_text(content).strip()
        if not original:
            return ""
        generic_markers = {"[语音]", "语音", "语音消息"}
        if original in generic_markers:
            return ""
        for marker in ("语音转文字", "语音转写", "转文字", "转写"):
            if marker in original:
                text = original.split(marker, 1)[1].strip(" ：:[]")
                return text if text and text not in generic_markers else ""
        if original.startswith("[语音]"):
            text = original.replace("[语音]", "", 1).strip(" ：:")
            return text if text else ""
        return ""
