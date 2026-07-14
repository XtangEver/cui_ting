from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import subprocess


@dataclass(frozen=True)
class AudioChunk:
    index: int
    core_start: float
    core_end: float
    extract_start: float
    extract_end: float


class AudioChunker:
    def __init__(
        self,
        chunk_seconds: int,
        context_seconds: int,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
    ):
        if chunk_seconds <= 0:
            raise ValueError("chunk_seconds must be positive")
        if context_seconds < 0 or context_seconds >= chunk_seconds:
            raise ValueError(
                "context_seconds must be non-negative and less than chunk_seconds"
            )
        self.chunk_seconds = chunk_seconds
        self.context_seconds = context_seconds
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def validate_tools(self) -> None:
        for tool in (self.ffmpeg, self.ffprobe):
            if shutil.which(tool) is None:
                raise RuntimeError(f"未找到 {tool}，请安装 FFmpeg 并加入 PATH")

    def plan(self, duration: float) -> list[AudioChunk]:
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("audio duration must be positive")

        result = []
        core_start = 0.0
        index = 1
        while core_start < duration:
            core_end = min(core_start + self.chunk_seconds, duration)
            result.append(
                AudioChunk(
                    index,
                    core_start,
                    core_end,
                    max(0.0, core_start - self.context_seconds),
                    min(duration, core_end + self.context_seconds),
                )
            )
            core_start = core_end
            index += 1
        return result

    def probe_duration(self, audio_path: Path) -> float:
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=30
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                f"FFprobe 无法读取音频时长: {audio_path}: {exc}"
            ) from exc
        stderr = (result.stderr or "")[-2000:].strip()
        if result.returncode != 0:
            detail = f": {stderr}" if stderr else ""
            raise RuntimeError(
                f"FFprobe 无法读取音频时长: {audio_path}{detail}"
            )
        try:
            duration = float(result.stdout.strip())
        except ValueError as exc:
            detail = f": {stderr}" if stderr else ""
            raise RuntimeError(
                f"FFprobe 无法读取音频时长: {audio_path}{detail}"
            ) from exc
        if (
            not math.isfinite(duration)
            or duration <= 0
        ):
            detail = f": {stderr}" if stderr else ""
            raise RuntimeError(
                f"FFprobe 无法读取音频时长: {audio_path}{detail}"
            )
        return duration

    def extract(
        self, audio_path: Path, chunk: AudioChunk, output_path: Path
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(chunk.extract_start),
            "-i",
            str(audio_path),
            "-t",
            str(chunk.extract_end - chunk.extract_start),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            "-y",
            str(output_path),
        ]
        extract_duration = chunk.extract_end - chunk.extract_start
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=max(60.0, extract_duration),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"FFmpeg 切片失败: {audio_path}: {exc}") from exc
        if (
            result.returncode != 0
            or not output_path.is_file()
            or output_path.stat().st_size == 0
        ):
            stderr = result.stderr[-2000:]
            raise RuntimeError(f"FFmpeg 切片失败: {audio_path}: {stderr}")
