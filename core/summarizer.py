# core/summarizer.py
import logging
import os
import re
from pathlib import Path
from typing import Dict, Any, List

from .config import ConfigManager
from .downloader import load_completed_download
from .timestamp_utils import TimestampedSegment, segments_to_anchored_text, parse_anchored_text

logger = logging.getLogger(__name__)

RAW_HEADER = "# 原始转录文本\n\n"
REFINED_HEADER = "# 结构化摘要\n\n"


def _atomic_write_text(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


_ANCHORED_LINE = re.compile(r"^\[(\d+):([0-5]\d):([0-5]\d)\]\s+\S.*$")


def load_valid_raw_segments(path: str | Path) -> list[TimestampedSegment] | None:
    """Load a complete anchored raw cache, or return None for stale data."""
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if content.startswith(RAW_HEADER):
        content = content[len(RAW_HEADER):]
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if not lines or not all(_ANCHORED_LINE.fullmatch(line) for line in lines):
        return None
    try:
        segments = parse_anchored_text("\n".join(lines))
    except (TypeError, ValueError):
        return None
    if any(
        previous.start > current.start
        for previous, current in zip(segments, segments[1:])
    ):
        return None
    return segments or None


def is_valid_refined_file(path: str | Path) -> bool:
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if not content.startswith(REFINED_HEADER):
        return False
    body = content[len(REFINED_HEADER):].strip()
    if not body:
        return False

    from .llm_processor import LLMProcessor

    if LLMProcessor._THINK_PATTERN.search(body) or re.search(
        r"<\s*/?\s*(?:think|thinking)\b[^>]*>", body, re.IGNORECASE
    ):
        return False

    first_line = body.splitlines()[0][:200].casefold()
    prompt_markers = [
        *LLMProcessor._PROMPT_ECHO_PATTERNS,
        LLMProcessor.STRUCTURED_REFINE_PROMPT.splitlines()[0].split("，", 1)[0],
    ]
    return not any(marker.casefold() in first_line for marker in prompt_markers)


class VideoSummarizer:
    """视频总结器：字幕优先 → 结构化文本摘要"""

    def __init__(
        self,
        config_path: str = "config.yaml",
        cookies_file: str = None,
        *,
        transcriber=None,
        llm_processor=None,
        text_processor=None,
        downloader=None,
        subtitle_downloader=None,
    ):
        self.config_manager = ConfigManager(config_path)
        self.app_config = self.config_manager.get_app_config()

        if cookies_file:
            self.app_config.cookies_file = cookies_file

        if downloader is None:
            from .downloader import AudioDownloader

            downloader = AudioDownloader(self.app_config.cookies_file)
        if subtitle_downloader is None:
            from .subtitle_downloader import SubtitleDownloader

            subtitle_downloader = SubtitleDownloader(self.app_config.cookies_file)
        if transcriber is None:
            from .transcriber import Transcriber

            transcriber = Transcriber(self.app_config.whisper)
        if llm_processor is None:
            from .llm_processor import LLMProcessor

            llm_processor = LLMProcessor(
                self.app_config.models,
                self.app_config.llm_max_tokens,
            )
        if text_processor is None:
            from .text_processor import TextProcessor

            text_processor = TextProcessor(
                self.app_config.chunk_size,
                self.app_config.chunk_overlap,
            )

        self.downloader = downloader
        self.subtitle_downloader = subtitle_downloader
        self.transcriber = transcriber
        self.llm_processor = llm_processor
        self.text_processor = text_processor

    def _find_existing_audio_files(
        self, output_dir: str, url: str, video_id: str = None
    ) -> List[str]:
        search_dirs = [output_dir]
        if video_id:
            search_dirs.append(os.path.join(output_dir, video_id))
        for d in search_dirs:
            existing = load_completed_download(d, url)
            if existing:
                return existing
        return []

    def _find_file(self, output_dir: str, video_id: str, filename: str) -> str | None:
        for d in (output_dir, os.path.join(output_dir, video_id)):
            path = os.path.join(d, filename)
            if os.path.exists(path):
                return path
        return None

    # ── Stage 1: Acquire text with timestamps ──

    def _acquire_text(self, url: str, audio_path: str, output_dir: str,
                      video_id: str, part_basename: str) -> list[TimestampedSegment]:
        """Get timestamped text: cache first, then subtitle, then Whisper fallback."""
        raw_file = os.path.join(output_dir, f"{part_basename}_raw.md")

        # Check cache — load existing raw file back into segments
        found_raw = self._find_file(output_dir, video_id, f"{part_basename}_raw.md")
        if found_raw:
            cached_segments = load_valid_raw_segments(found_raw)
            if cached_segments is not None:
                logger.info("  原始转录已存在，从缓存加载: %s", found_raw)
                return cached_segments
            logger.warning("  原始转录缓存为空或格式无效，将重建: %s", found_raw)

        # Try subtitles first
        segments = None
        if self.app_config.subtitle_first:
            segments = self.subtitle_downloader.download_subtitles(url, output_dir)

        # Fallback to Whisper
        if not segments:
            cache_dir = Path(output_dir) / ".transcription_cache" / part_basename
            segments = self.transcriber.transcribe(audio_path, str(cache_dir))

        _atomic_write_text(
            raw_file,
            f"{RAW_HEADER}{segments_to_anchored_text(segments)}",
        )
        logger.info("  原始文本已保存: %s", raw_file)

        return segments

    # ── Stage 2: Text refinement ──

    def _refine(self, segments: list[TimestampedSegment],
                output_dir: str, video_id: str,
                part_basename: str, model_name: str,
                progress_callback=None) -> str:
        """LLM structured refinement."""
        refined_file = os.path.join(output_dir, f"{part_basename}_refined.md")

        found_refined = self._find_file(output_dir, video_id, f"{part_basename}_refined.md")
        if found_refined and is_valid_refined_file(found_refined):
            logger.info("  结构化摘要已存在: %s", found_refined)
            if progress_callback:
                progress_callback("log", {"message": "LLM 结果已缓存，跳过"})
            return found_refined
        if found_refined:
            logger.warning("  结构化摘要缓存为空或格式无效，将重建: %s", found_refined)

        chunks = self.text_processor.split_segments(segments)
        logger.info("  文本已分块: %d 块", len(chunks))

        total_chunks = len(chunks)
        if progress_callback:
            progress_callback('progress', {
                'stage': 'refining',
                'percent': 0,
                'detail': f'共 {total_chunks} 块'
            })

        refined_chunks = []
        for i, chunk in enumerate(chunks):
            logger.info("  处理块 %d/%d...", i + 1, len(chunks))
            if progress_callback:
                progress_callback("log", {"message": f"LLM 处理: 第 {i + 1}/{len(chunks)} 块"})
                progress_callback('progress', {
                    'stage': 'refining',
                    'percent': int((i + 1) / total_chunks * 100),
                    'detail': f'第 {i + 1}/{total_chunks} 块'
                })
            refined_chunks.append(
                self.llm_processor.structured_refine(chunk, model_name)
            )

        refined_text = self.text_processor.merge_results(refined_chunks)

        _atomic_write_text(refined_file, f"{REFINED_HEADER}{refined_text}")
        logger.info("  结构化摘要已保存: %s", refined_file)

        if progress_callback:
            progress_callback("log", {"message": "LLM 处理完成"})

        return refined_file

    # ── Main entry point ──

    def _process_part(self, url: str, audio_path: str, idx: int, total: int,
                      output_dir: str, video_id: str, model_name: str,
                      progress_callback=None) -> Dict[str, Any]:
        """Process a single audio segment: transcribe -> [optional] refine."""
        part_basename = os.path.splitext(os.path.basename(audio_path))[0]
        logger.info("处理分段 [%d/%d]: %s", idx, total, part_basename)

        if progress_callback:
            progress_callback("log", {"message": f"正在处理第 {idx}/{total} 部分..."})
            progress_callback('progress', {
                'stage': 'transcribing',
                'percent': int((idx - 1) / total * 100) if total > 1 else 0,
                'detail': f'第 {idx}/{total} 部分'
            })

        # Stage 1: Acquire timestamped text
        if progress_callback:
            progress_callback("log", {"message": "正在使用 Whisper 转录音频，请耐心等待..."})
            progress_callback('progress', {
                'stage': 'transcribing',
                'percent': int((idx - 0.5) / total * 100) if total > 1 else 50,
                'detail': 'Whisper 转录中...'
            })
        segments = self._acquire_text(url, audio_path, output_dir, video_id, part_basename)

        if progress_callback:
            progress_callback("log", {"message": "转录完成"})
            progress_callback('progress', {
                'stage': 'transcribing',
                'percent': int(idx / total * 100),
                'detail': f'第 {idx}/{total} 部分转录完成'
            })
            progress_callback("stage_update", {"stage": "refining", "status": "active"})

        # Stage 2: Refine (optional, controlled by enable_refine)
        refined_file = None
        if self.app_config.enable_refine:
            refined_file = self._refine(
                segments, output_dir, video_id, part_basename, model_name,
                progress_callback=progress_callback,
            )
        else:
            logger.info("  LLM后处理已禁用，跳过精炼步骤")

        return {
            'part_index': idx,
            'audio_path': audio_path,
            'raw_file': os.path.join(output_dir, f"{part_basename}_raw.md"),
            'refined_file': refined_file,
        }

    def process(self, url: str, model_name: str = None, output_dir: str = None,
                progress_callback=None) -> Dict[str, Any]:
        """Process video: download -> transcribe -> refine."""
        if self.app_config.enable_refine and model_name is None:
            model_name = next(iter(self.app_config.models))

        logger.info("开始处理视频: %s (模型: %s)", url, model_name)

        if progress_callback:
            progress_callback("stage_update", {"stage": "downloading", "status": "active"})

        video_id = self.downloader.extract_video_id(url)
        if output_dir is None:
            output_dir = f"output/{video_id}"
        os.makedirs(output_dir, exist_ok=True)

        # Download audio
        existing_audio = self._find_existing_audio_files(output_dir, url, video_id)
        if existing_audio:
            logger.info("检测到已存在的音频文件，跳过下载: %s", existing_audio)
            if progress_callback:
                progress_callback("log", {"message": "音频已缓存，跳过下载"})
            merged_files = existing_audio
        else:
            _, video_id, merged_files = self.downloader.download_and_merge(
                url, output_dir=output_dir, progress_callback=progress_callback
            )

        if not merged_files or any(
            not Path(path).is_file() or Path(path).stat().st_size == 0
            for path in merged_files
        ):
            raise RuntimeError("下载阶段未生成有效音频，终止整个任务")

        if progress_callback:
            progress_callback("log", {"message": "下载完成"})
            progress_callback("stage_update", {"stage": "transcribing", "status": "active"})

        # Process each audio segment
        results = []
        for idx, audio_path in enumerate(merged_files, 1):
            result = self._process_part(
                url, audio_path, idx, len(merged_files),
                output_dir, video_id, model_name,
                progress_callback=progress_callback,
            )
            results.append(result)

        if progress_callback:
            progress_callback("stage_update", {"stage": "refining", "status": "done"})

        logger.info("处理完成! 分段数: %d, 输出目录: %s", len(merged_files), output_dir)

        return {
            'video_id': video_id,
            'output_dir': output_dir,
            'results': results
        }
