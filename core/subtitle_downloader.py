import logging
import os
import re as _re
from pathlib import Path

import webvtt
import yt_dlp

from .timestamp_utils import TimestampedSegment, parse_timestamp

logger = logging.getLogger(__name__)

LANG_PRIORITY = ["zh-Hans", "zh", "zh-Hant", "en"]


def parse_vtt_file(vtt_path: str) -> list[TimestampedSegment]:
    segments: list[TimestampedSegment] = []
    for caption in webvtt.read(vtt_path):
        text = _re.sub(r'<[^>]+>', '', caption.text).strip().replace("\n", " ")
        if not text:
            continue
        start = parse_timestamp(caption.start)
        end = parse_timestamp(caption.end)
        if segments and segments[-1].text == text:
            segments[-1] = TimestampedSegment(start=segments[-1].start, end=end, text=text)
        else:
            segments.append(TimestampedSegment(start=start, end=end, text=text))
    return segments


class SubtitleDownloader:
    def __init__(self, cookies_path: str | None = None):
        self.cookies_path = cookies_path

    def download_subtitles(self, url: str, output_dir: str) -> list[TimestampedSegment] | None:
        os.makedirs(output_dir, exist_ok=True)
        existing = self._find_existing_subtitle(output_dir)
        if existing:
            logger.info("发现已有字幕文件: %s", existing)
            return parse_vtt_file(existing)
        sub_file = self._download_sub(url, output_dir)
        if sub_file:
            logger.info("字幕下载成功: %s", sub_file)
            return parse_vtt_file(sub_file)
        logger.info("未找到可用字幕，将使用 Whisper 转录")
        return None

    def _find_existing_subtitle(self, output_dir: str) -> str | None:
        for f in Path(output_dir).glob("*.vtt"):
            return str(f)
        return None

    def _download_sub(self, url: str, output_dir: str) -> str | None:
        cookiefile = self.cookies_path if self.cookies_path and os.path.exists(self.cookies_path) else None
        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": LANG_PRIORITY,
            "subtitlesformat": "vtt",
            "skip_download": True,
            "outtmpl": os.path.join(output_dir, "subtitle.%(ext)s"),
            "cookiefile": cookiefile,
            "quiet": True,
            "nocheckcertificate": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            logger.warning("字幕下载失败: %s", e)
            return None
        return self._find_existing_subtitle(output_dir)
