# core/summarizer.py
import glob
import logging
import os
from typing import Dict, Any, List

from .config import ConfigManager
from .downloader import AudioDownloader
from .llm_processor import LLMProcessor
from .subtitle_downloader import SubtitleDownloader
from .text_processor import TextProcessor
from .timestamp_utils import TimestampedSegment, segments_to_anchored_text, parse_anchored_text
from .transcriber import Transcriber

logger = logging.getLogger(__name__)

RAW_HEADER = "# 原始转录文本\n\n"
REFINED_HEADER = "# 结构化摘要\n\n"


class VideoSummarizer:
    """视频总结器：字幕优先 → 结构化文本摘要"""

    def __init__(self, config_path: str = "config.yaml", cookies_file: str = None):
        self.config_manager = ConfigManager(config_path)
        self.app_config = self.config_manager.get_app_config()

        if cookies_file:
            self.app_config.cookies_file = cookies_file

        self.downloader = AudioDownloader(self.app_config.cookies_file)
        self.subtitle_downloader = SubtitleDownloader(self.app_config.cookies_file)
        self.transcriber = Transcriber(self.app_config.whisper_path)
        self.llm_processor = LLMProcessor(self.app_config.models)
        self.text_processor = TextProcessor(
            self.app_config.chunk_size,
            self.app_config.chunk_overlap
        )

    def _find_existing_audio_files(self, output_dir: str, video_id: str = None) -> List[str]:
        search_dirs = [output_dir]
        if video_id:
            search_dirs.append(os.path.join(output_dir, video_id))
        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            existing = sorted(glob.glob(os.path.join(d, "source*.mp3")))
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
            logger.info("  原始转录已存在，从缓存加载: %s", found_raw)
            with open(found_raw, 'r', encoding='utf-8') as f:
                content = f.read().replace(RAW_HEADER, "")
            # Try timestamped format first, fall back to plain text
            if content.strip().startswith("["):
                return parse_anchored_text(content)
            lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
            return [TimestampedSegment(start=0.0, end=0.0, text=l) for l in lines]

        # Try subtitles first
        segments = None
        if self.app_config.subtitle_first:
            segments = self.subtitle_downloader.download_subtitles(url, output_dir)

        # Fallback to Whisper
        if not segments:
            segments = self.transcriber.transcribe(audio_path)

        # Save raw text without timestamps
        plain_text = "\n".join(seg.text for seg in segments)
        with open(raw_file, 'w', encoding='utf-8') as f:
            f.write(f"{RAW_HEADER}{plain_text}")
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
        if found_refined:
            logger.info("  结构化摘要已存在: %s", found_refined)
            if progress_callback:
                progress_callback("log", {"message": "LLM 结果已缓存，跳过"})
            return found_refined

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

        with open(refined_file, 'w', encoding='utf-8') as f:
            f.write(f"{REFINED_HEADER}{refined_text}")
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
                'percent': int(idx / total * 100),
                'detail': f'第 {idx}/{total} 部分'
            })

        # Stage 1: Acquire timestamped text
        segments = self._acquire_text(url, audio_path, output_dir, video_id, part_basename)

        if progress_callback:
            progress_callback("log", {"message": "转录完成"})
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
        if model_name is None:
            model_name = next(iter(self.app_config.models))

        logger.info("开始处理视频: %s (模型: %s)", url, model_name)

        if progress_callback:
            progress_callback("stage_update", {"stage": "downloading", "status": "active"})

        video_id = AudioDownloader.extract_video_id(url)
        if output_dir is None:
            output_dir = f"output/{video_id}"
        os.makedirs(output_dir, exist_ok=True)

        # Download audio
        existing_audio = self._find_existing_audio_files(output_dir, video_id)
        if existing_audio:
            logger.info("检测到已存在的音频文件，跳过下载: %s", existing_audio)
            if progress_callback:
                progress_callback("log", {"message": "音频已缓存，跳过下载"})
            merged_files = existing_audio
        else:
            _, video_id, merged_files = self.downloader.download_and_merge(
                url, output_dir=output_dir, progress_callback=progress_callback
            )

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
