import logging
import mlx_whisper
from .timestamp_utils import TimestampedSegment

logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, model_path: str):
        self.model_path = model_path

    def transcribe(self, audio_path: str) -> list[TimestampedSegment]:
        logger.info("正在使用 MLX + Metal 转录音频: %s", audio_path)
        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=self.model_path,
            verbose=False
        )
        segments = [
            TimestampedSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip()
            )
            for seg in result.get("segments", [])
        ]
        total_chars = sum(len(s.text) for s in segments)
        logger.info("转录完成，%d 个分段，共 %d 字符", len(segments), total_chars)
        return segments
