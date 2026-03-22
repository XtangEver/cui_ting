import logging
import os
import shutil
import subprocess
from pathlib import Path

import yt_dlp

from .timestamp_utils import format_timestamp

logger = logging.getLogger(__name__)


def frame_filename(timestamp_seconds: float) -> str:
    ts = format_timestamp(timestamp_seconds)
    return f"frame_{ts.replace(':', '_')}.jpg"


def build_ffmpeg_command(video_path: str, timestamp: float, output_path: str) -> list[str]:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    return [
        ffmpeg, "-ss", str(timestamp), "-i", video_path,
        "-vframes", "1", "-q:v", "2", "-y", output_path,
    ]


class FrameExtractor:
    def __init__(self, cookies_path: str | None = None):
        self.cookies_path = cookies_path

    def extract_frames(self, url: str, keyframes: list[dict], output_dir: str) -> dict[float, str]:
        """Extract frames. Returns {original_timestamp: frame_path}.
        Uses capture_timestamp (with offset) for ffmpeg, but keys result by
        original timestamp so it matches text anchors."""
        if not keyframes:
            return {}
        frames_dir = os.path.join(output_dir, "frames")
        os.makedirs(frames_dir, exist_ok=True)
        needed = []
        result = {}
        for kf in keyframes:
            original_ts = kf["timestamp"]
            capture_ts = kf.get("capture_timestamp", original_ts)
            fname = frame_filename(capture_ts)
            fpath = os.path.join(frames_dir, fname)
            if os.path.exists(fpath):
                logger.info("关键帧已存在: %s", fpath)
                result[original_ts] = fpath
            else:
                needed.append((original_ts, capture_ts, fpath))
        if not needed:
            return result
        video_path = self._download_video(url, output_dir)
        if not video_path:
            logger.warning("视频下载失败，跳过截图")
            return result
        for original_ts, capture_ts, fpath in needed:
            self._extract_single_frame(video_path, capture_ts, fpath)
            if os.path.exists(fpath):
                result[original_ts] = fpath
        try:
            os.remove(video_path)
            logger.info("已删除临时视频文件: %s", video_path)
        except OSError:
            pass
        logger.info("截图完成: %d/%d 帧", len(result), len(keyframes))
        return result

    def _download_video(self, url: str, output_dir: str) -> str | None:
        existing = list(Path(output_dir).glob("temp_video.*"))
        if existing:
            return str(existing[0])
        cookiefile = self.cookies_path if self.cookies_path and os.path.exists(self.cookies_path) else None
        outtmpl = os.path.join(output_dir, "temp_video.%(ext)s")
        ydl_opts = {
            "format": "worstvideo[ext=mp4]/worstvideo/worst",
            "outtmpl": outtmpl,
            "cookiefile": cookiefile,
            "quiet": True,
            "nocheckcertificate": True,
        }
        logger.info("正在下载低画质视频用于截图...")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            downloaded = list(Path(output_dir).glob("temp_video.*"))
            if downloaded:
                return str(downloaded[0])
        except Exception as e:
            logger.warning("视频下载失败: %s", e)
        return None

    def _extract_single_frame(self, video_path: str, timestamp: float, output_path: str):
        cmd = build_ffmpeg_command(video_path, timestamp, output_path)
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("截图失败 @%.1fs: %s", timestamp, e)
