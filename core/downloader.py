# core/downloader.py
import logging
import os
import re
import shutil
import subprocess
from typing import Tuple, List

import yt_dlp

logger = logging.getLogger(__name__)


class AudioDownloader:
    """音频下载器：支持单视频下载及多分片视频自动合并"""

    def __init__(self, cookies_path: str = None):
        self.cookies_path = cookies_path
        self.progress_callback = None

    def _ydl_progress_hook(self, d):
        """yt-dlp progress hook — reports download percentage."""
        if not self.progress_callback:
            return
        if d['status'] == 'downloading':
            total = d.get('_total_bytes') or d.get('_total_bytes_estimate') or 0
            downloaded = d.get('_downloaded_bytes', 0)
            if total > 0:
                percent = int(downloaded / total * 100)
                self.progress_callback('progress', {
                    'stage': 'downloading',
                    'percent': percent,
                    'detail': f'{percent}%'
                })
        elif d['status'] == 'finished':
            self.progress_callback('progress', {
                'stage': 'downloading',
                'percent': 100,
                'detail': '下载完成'
            })

    @staticmethod
    def _find_tool(name: str) -> str:
        """在 PATH 中查找 FFmpeg/FFprobe"""
        path = shutil.which(name)
        return path if path else name

    def download_and_merge(self, url: str, output_dir: str = None, max_duration: int = 3600, progress_callback=None) -> Tuple[str, str, List[str]]:
        """
        主入口：自动识别单视频或播放列表并执行下载合并
        """
        video_id = self.extract_video_id(url)
        if output_dir is None:
            output_dir = f"output/{video_id}"
        os.makedirs(output_dir, exist_ok=True)

        # 获取元数据，检查是否为多条目（播放列表/分P）
        ydl_opts_info = {
            'quiet': True,
            'nocheckcertificate': True,
            'extract_flat': True,
            'cookiefile': self._cookiefile
        }

        logger.info("正在获取资源信息: %s", url)
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        if 'entries' in info and len(info['entries']) > 1:
            logger.info("检测到分P视频/播放列表，共 %d 个片段", len(info['entries']))
            return self._process_playlist(url, output_dir, info['entries'], max_duration, progress_callback=progress_callback)
        else:
            logger.info("检测到单个视频")
            path, vid = self.download(url, output_dir, progress_callback=progress_callback)
            return path, vid, [path]

    def _process_playlist(self, url: str, output_dir: str, entries: list, max_duration: int, progress_callback=None) -> Tuple[str, str, List[str]]:
        """处理分片下载与合并逻辑"""
        video_id = self.extract_video_id(url)
        temp_dir = os.path.join(output_dir, "temp_parts")
        os.makedirs(temp_dir, exist_ok=True)
        self.progress_callback = progress_callback
        
        downloaded_parts = []
        
        for i, entry in enumerate(entries):
            if not entry: continue
            part_url = entry.get('url') or url # 兼容 Bilibili 内部跳转
            part_path = os.path.join(temp_dir, f"part_{i+1}.m4a")
            
            # 断点续传检查
            if os.path.exists(part_path):
                duration = self._get_duration(part_path)
                downloaded_parts.append((part_path, duration))
                continue

            logger.info("下载分片 %d/%d: %s", i + 1, len(entries), entry.get('title', 'Unknown'))
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(temp_dir, f"part_{i+1}.%(ext)s"),
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}],
                'cookiefile': self._cookiefile,
                'quiet': True,
                'progress_hooks': [self._ydl_progress_hook]
            }

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([part_url])
                if os.path.exists(part_path):
                    duration = self._get_duration(part_path)
                    downloaded_parts.append((part_path, duration))
            except Exception as e:
                logger.warning("分片 %d 下载跳过: %s", i + 1, e)

        merged_files = self._merge_audio_files(downloaded_parts, output_dir, temp_dir, max_duration)
        return merged_files[0] if merged_files else "", video_id, merged_files

    def _get_duration(self, path: str) -> float:
        """获取音频时长"""
        ffprobe = self._find_tool('ffprobe')
        cmd = [ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return float(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError, OSError) as e:
            logger.debug("获取音频时长失败 %s: %s", path, e)
            return 0.0

    def _merge_audio_files(self, parts: list, output_dir: str, temp_dir: str, max_duration: int) -> List[str]:
        """使用 FFmpeg Concat 合并音频"""
        ffmpeg = self._find_tool('ffmpeg')
        merged_paths = []
        
        # 简单的分批逻辑（根据 max_duration）
        current_batch = []
        current_dur = 0
        batch_idx = 1

        def do_merge(batch, idx):
            list_file = os.path.join(temp_dir, f"list_{idx}.txt")
            out_file = os.path.join(output_dir, f"source_part{idx}.mp3")
            with open(list_file, 'w', encoding='utf-8') as f:
                for p, _ in batch:
                    f.write(f"file '{os.path.abspath(p)}'\n")
            
            # 先尝试直接 copy 合并，失败则重编码
            cmd = [ffmpeg, '-f', 'concat', '-safe', '0', '-i', list_file, '-c:a', 'libmp3lame', '-b:a', '192k', '-y', out_file]
            subprocess.run(cmd, capture_output=True)
            return out_file

        for p, d in parts:
            if current_dur + d > max_duration and current_batch:
                merged_paths.append(do_merge(current_batch, batch_idx))
                batch_idx += 1
                current_batch = []
                current_dur = 0
            current_batch.append((p, d))
            current_dur += d
        
        if current_batch:
            merged_paths.append(do_merge(current_batch, batch_idx))
            
        return merged_paths

    @property
    def _cookiefile(self) -> str | None:
        """yt-dlp cookiefile 参数：路径存在时返回路径，否则 None"""
        if self.cookies_path and os.path.exists(self.cookies_path):
            return self.cookies_path
        return None

    def download(self, url: str, output_dir: str = None, progress_callback=None) -> Tuple[str, str]:
        """单视频下载"""
        video_id = self.extract_video_id(url)
        if output_dir is None:
            output_dir = f"output/{video_id}"
        os.makedirs(output_dir, exist_ok=True)
        self.progress_callback = progress_callback

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{output_dir}/source.%(ext)s",
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'cookiefile': self._cookiefile,
            'nocheckcertificate': True,
            'progress_hooks': [self._ydl_progress_hook]
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        final_path = os.path.join(output_dir, "source.mp3")
        return final_path, video_id

    @staticmethod
    def extract_video_id(url: str) -> str:
        bv_match = re.search(r'(BV[a-zA-Z0-9]+)', url)
        if bv_match:
            return bv_match.group(1)
        yt_match = re.search(r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
        if yt_match:
            return yt_match.group(1)
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M%S")