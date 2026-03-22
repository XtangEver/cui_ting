# core/summarizer.py
import glob
import logging
import os
from typing import Dict, Any, List

from .config import ConfigManager
from .downloader import AudioDownloader
from .frame_extractor import FrameExtractor
from .keyframe_detector import KeyframeDetector
from .llm_processor import LLMProcessor
from .markdown_assembler import insert_frames_into_markdown
from .subtitle_downloader import SubtitleDownloader
from .text_processor import TextProcessor
from .timestamp_utils import TimestampedSegment, segments_to_anchored_text, parse_anchored_text
from .transcriber import Transcriber

logger = logging.getLogger(__name__)

RAW_HEADER = "# 原始转录文本\n\n"
REFINED_HEADER = "# 结构化摘要\n\n"


class VideoSummarizer:
    """视频总结器 V2：字幕优先 → 关键帧截图 → 结构化图文摘要"""

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
        self.keyframe_detector = KeyframeDetector(self.llm_processor)
        self.frame_extractor = FrameExtractor(self.app_config.cookies_file)

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

        # Check cache — parse existing raw file back into segments
        found_raw = self._find_file(output_dir, video_id, f"{part_basename}_raw.md")
        if found_raw:
            logger.info("  原始转录已存在，从缓存加载: %s", found_raw)
            with open(found_raw, 'r', encoding='utf-8') as f:
                content = f.read().replace(RAW_HEADER, "")
            return parse_anchored_text(content)

        # Try subtitles first
        segments = None
        if self.app_config.subtitle_first:
            segments = self.subtitle_downloader.download_subtitles(url, output_dir)

        # Fallback to Whisper
        if not segments:
            segments = self.transcriber.transcribe(audio_path)

        # Save raw text with timestamps
        anchored_text = segments_to_anchored_text(segments)
        with open(raw_file, 'w', encoding='utf-8') as f:
            f.write(f"{RAW_HEADER}{anchored_text}")
        logger.info("  原始文本已保存: %s", raw_file)

        return segments

    # ── Stage 2-3: Keyframe detection and extraction ──

    def _extract_keyframes(self, url: str, segments: list[TimestampedSegment],
                           output_dir: str, model_name: str) -> dict[float, str]:
        """Detect keyframe timestamps via LLM, then extract frames."""
        if not self.app_config.extract_frames:
            return {}

        anchored_text = segments_to_anchored_text(segments)
        keyframes = self.keyframe_detector.detect(anchored_text, model_name)

        if not keyframes:
            logger.info("  未检测到需要截图的位置")
            return {}

        return self.frame_extractor.extract_frames(url, keyframes, output_dir)

    # ── Stage 4-5: Text refinement and image insertion ──

    def _refine_and_assemble(self, segments: list[TimestampedSegment],
                             frames: dict[float, str],
                             output_dir: str, video_id: str,
                             part_basename: str, model_name: str) -> str:
        """Stage 4: LLM structured refinement. Stage 5: Insert frames."""
        refined_file = os.path.join(output_dir, f"{part_basename}_refined.md")

        found_refined = self._find_file(output_dir, video_id, f"{part_basename}_refined.md")
        if found_refined:
            logger.info("  结构化摘要已存在: %s", found_refined)
            return found_refined

        # Stage 4: Structured refinement with timestamp anchors
        chunks = self.text_processor.split_segments(segments)
        logger.info("  文本已分块: %d 块", len(chunks))

        refined_chunks = []
        for i, chunk in enumerate(chunks):
            logger.info("  处理块 %d/%d...", i + 1, len(chunks))
            refined_chunks.append(
                self.llm_processor.structured_refine(chunk, model_name)
            )

        refined_text = self.text_processor.merge_results(refined_chunks)

        # Stage 5: Insert frames at timestamp positions
        if frames:
            relative_frames = {}
            for ts, fpath in frames.items():
                rel_path = os.path.relpath(fpath, output_dir)
                relative_frames[ts] = rel_path
            refined_text = insert_frames_into_markdown(refined_text, relative_frames)

        with open(refined_file, 'w', encoding='utf-8') as f:
            f.write(f"{REFINED_HEADER}{refined_text}")
        logger.info("  结构化摘要已保存: %s", refined_file)

        return refined_file

    # ── Main entry point ──

    def _process_part(self, url: str, audio_path: str, idx: int, total: int,
                      output_dir: str, video_id: str, model_name: str) -> Dict[str, Any]:
        """Process a single audio segment through all 5 stages."""
        part_basename = os.path.splitext(os.path.basename(audio_path))[0]
        logger.info("处理分段 [%d/%d]: %s", idx, total, part_basename)

        # Stage 1: Acquire timestamped text
        segments = self._acquire_text(url, audio_path, output_dir, video_id, part_basename)

        # Stage 2-3: Keyframe detection and extraction
        frames = self._extract_keyframes(url, segments, output_dir, model_name)

        # Stage 4-5: Refine and assemble
        refined_file = self._refine_and_assemble(
            segments, frames, output_dir, video_id, part_basename, model_name
        )

        return {
            'part_index': idx,
            'audio_path': audio_path,
            'raw_file': os.path.join(output_dir, f"{part_basename}_raw.md"),
            'refined_file': refined_file,
            'frames': frames,
        }

    def process(self, url: str, model_name: str = None, output_dir: str = None) -> Dict[str, Any]:
        """Process video: download → transcribe → detect keyframes → refine → assemble."""
        if model_name is None:
            model_name = self.app_config.default_model

        logger.info("开始处理视频: %s (模型: %s)", url, model_name)

        video_id = AudioDownloader.extract_video_id(url)
        if output_dir is None:
            output_dir = f"output/{video_id}"
        os.makedirs(output_dir, exist_ok=True)

        # Download audio
        existing_audio = self._find_existing_audio_files(output_dir, video_id)
        if existing_audio:
            logger.info("检测到已存在的音频文件，跳过下载: %s", existing_audio)
            merged_files = existing_audio
        else:
            _, video_id, merged_files = self.downloader.download_and_merge(url, output_dir=output_dir)

        # Process each audio segment
        results = []
        for idx, audio_path in enumerate(merged_files, 1):
            result = self._process_part(
                url, audio_path, idx, len(merged_files),
                output_dir, video_id, model_name
            )
            results.append(result)

        logger.info("处理完成! 分段数: %d, 输出目录: %s", len(merged_files), output_dir)

        return {
            'video_id': video_id,
            'output_dir': output_dir,
            'results': results
        }
