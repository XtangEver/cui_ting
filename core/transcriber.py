import hashlib
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Callable

from .audio_chunker import AudioChunk, AudioChunker
from .config import WhisperConfig
from .timestamp_utils import TimestampedSegment

logger = logging.getLogger(__name__)

_CACHE_SCHEMA_VERSION = 1


def _default_model_factory(**kwargs):
    from faster_whisper import WhisperModel

    return WhisperModel(**kwargs)


class Transcriber:
    def __init__(
        self,
        config: WhisperConfig,
        chunker: AudioChunker | None = None,
        model_factory: Callable[..., Any] | None = None,
    ):
        self.config = config
        self.chunker = chunker or AudioChunker(
            config.audio_chunk_seconds, config.audio_context_seconds
        )
        self._model_factory = model_factory or _default_model_factory
        self._model = None

    def _get_model(self):
        if self._model is None:
            self._model = self._model_factory(
                model_size_or_path=self.config.model,
                device=self.config.device,
                compute_type=self.config.compute_type,
                cpu_threads=self.config.cpu_threads,
                download_root=str(self.config.download_root),
            )
        return self._model

    def transcribe(
        self, audio_path: str, cache_dir: str | None = None
    ) -> list[TimestampedSegment]:
        source = Path(audio_path).resolve()
        source_stat = source.stat()
        duration = self.chunker.probe_duration(source)
        chunks = self.chunker.plan(duration)
        identity = self._cache_identity(source, source_stat)
        cache_key = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()
        ).hexdigest()
        cache = (
            Path(cache_dir)
            if cache_dir is not None
            else source.parent / ".whisper_cache" / cache_key
        )
        cache.mkdir(parents=True, exist_ok=True)

        combined = []
        for chunk in chunks:
            cache_path = cache / f"chunk_{chunk.index:06d}.json"
            cached = self._load_cache(
                cache_path, identity, cache_key, chunk, duration
            )
            if cached is not None:
                combined.extend(cached)
                continue

            kept = self._transcribe_chunk(source, cache, chunk, duration)
            self._write_cache(cache_path, identity, cache_key, chunk, kept)
            combined.extend(kept)

        combined.sort(key=lambda segment: (segment.start, segment.end))
        total_chars = sum(len(segment.text) for segment in combined)
        logger.info(
            "转录完成，%d 个分段，共 %d 字符", len(combined), total_chars
        )
        return combined

    def _cache_identity(self, source: Path, source_stat) -> dict[str, Any]:
        return {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "source_path": str(source),
            "source_size": source_stat.st_size,
            "source_mtime_ns": source_stat.st_mtime_ns,
            "model": self.config.model,
            "compute_type": self.config.compute_type,
            "audio_chunk_seconds": self.config.audio_chunk_seconds,
            "audio_context_seconds": self.config.audio_context_seconds,
            "vad_filter": self.config.vad_filter,
        }

    def _transcribe_chunk(
        self,
        source: Path,
        cache_dir: Path,
        chunk: AudioChunk,
        duration: float,
    ) -> list[TimestampedSegment]:
        temp_wav = cache_dir / f"chunk_{chunk.index:06d}.wav"
        try:
            self.chunker.extract(source, chunk, temp_wav)
            generated, _ = self._get_model().transcribe(
                str(temp_wav),
                beam_size=5,
                vad_filter=self.config.vad_filter,
            )
            kept = []
            for item in generated:
                start = chunk.extract_start + float(item.start)
                end = chunk.extract_start + float(item.end)
                text = item.text.strip()
                if (
                    self._is_within_audio_bounds(start, end, chunk, duration)
                    and self._belongs_to_chunk(start, end, chunk, duration)
                    and text
                ):
                    kept.append(TimestampedSegment(start, end, text))
            return kept
        finally:
            temp_wav.unlink(missing_ok=True)

    def _load_cache(
        self,
        path: Path,
        identity: dict[str, Any],
        cache_key: str,
        chunk: AudioChunk,
        duration: float,
    ) -> list[TimestampedSegment] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("cache payload must be an object")
            if payload.get("schema_version") != _CACHE_SCHEMA_VERSION:
                raise ValueError("cache schema mismatch")
            if payload.get("cache_key") != cache_key:
                raise ValueError("cache key mismatch")
            if payload.get("identity") != identity:
                raise ValueError("cache identity mismatch")
            if payload.get("chunk") != self._chunk_metadata(chunk):
                raise ValueError("cache chunk metadata mismatch")
            raw_segments = payload.get("segments")
            if not isinstance(raw_segments, list):
                raise ValueError("cache segments must be a list")

            segments = []
            for raw in raw_segments:
                if not isinstance(raw, dict):
                    raise ValueError("cache segment must be an object")
                if set(raw) != {"start", "end", "text"}:
                    raise ValueError("cache segment fields are invalid")
                if not self._is_finite_number(raw["start"]):
                    raise ValueError("cache segment start is invalid")
                if not self._is_finite_number(raw["end"]):
                    raise ValueError("cache segment end is invalid")
                start = float(raw["start"])
                end = float(raw["end"])
                if end < start:
                    raise ValueError("cache segment ends before it starts")
                if not self._is_within_audio_bounds(
                    start, end, chunk, duration
                ):
                    raise ValueError("cache segment is outside decoded audio")
                if not self._belongs_to_chunk(start, end, chunk, duration):
                    raise ValueError("cache segment is outside chunk ownership")
                if (
                    not isinstance(raw["text"], str)
                    or not raw["text"]
                    or raw["text"] != raw["text"].strip()
                ):
                    raise ValueError("cache segment text is invalid")
                segments.append(
                    TimestampedSegment(
                        start,
                        end,
                        raw["text"],
                    )
                )
            return segments
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("转录缓存无效，将重建 %s: %s", path, exc)
            return None

    @staticmethod
    def _is_finite_number(value: Any) -> bool:
        return type(value) in (int, float) and math.isfinite(value)

    @staticmethod
    def _is_within_audio_bounds(
        start: float, end: float, chunk: AudioChunk, duration: float
    ) -> bool:
        lower_bound = max(0.0, chunk.extract_start)
        upper_bound = min(chunk.extract_end, duration)
        return lower_bound <= start <= end <= upper_bound

    @staticmethod
    def _belongs_to_chunk(
        start: float, end: float, chunk: AudioChunk, duration: float
    ) -> bool:
        midpoint = (start + end) / 2
        if chunk.core_end == duration:
            return chunk.core_start <= midpoint <= chunk.core_end
        return chunk.core_start <= midpoint < chunk.core_end

    @staticmethod
    def _chunk_metadata(chunk: AudioChunk) -> dict[str, Any]:
        return {
            "index": chunk.index,
            "core_start": chunk.core_start,
            "core_end": chunk.core_end,
            "extract_start": chunk.extract_start,
            "extract_end": chunk.extract_end,
        }

    def _write_cache(
        self,
        path: Path,
        identity: dict[str, Any],
        cache_key: str,
        chunk: AudioChunk,
        segments: list[TimestampedSegment],
    ) -> None:
        payload = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "cache_key": cache_key,
            "identity": identity,
            "chunk": self._chunk_metadata(chunk),
            "segments": [
                {"start": item.start, "end": item.end, "text": item.text}
                for item in segments
            ],
        }
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
