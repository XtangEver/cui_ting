# core/downloader.py
import logging
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Tuple, List

import yt_dlp

logger = logging.getLogger(__name__)

DOWNLOAD_MANIFEST_NAME = ".download_manifest.json"
DOWNLOAD_MANIFEST_SCHEMA = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def publish_download_manifest(
    output_dir: str | os.PathLike[str], url: str, outputs: list[str]
) -> None:
    """Atomically mark a download complete after every output is valid."""
    root = Path(output_dir).resolve()
    records = []
    if not outputs:
        raise RuntimeError("下载完成清单不能包含空输出列表")
    for output in outputs:
        path = Path(output).resolve()
        try:
            relative_path = path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"下载输出不在任务目录内: {path}") from exc
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"下载输出无效: {path}")
        records.append(
            {
                "path": relative_path.as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    manifest = root / DOWNLOAD_MANIFEST_NAME
    temp = manifest.with_name(manifest.name + ".tmp")
    payload = {
        "schema_version": DOWNLOAD_MANIFEST_SCHEMA,
        "source_url": url,
        "outputs": records,
    }
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, manifest)
    finally:
        temp.unlink(missing_ok=True)


def load_completed_download(
    output_dir: str | os.PathLike[str], url: str
) -> list[str]:
    """Return the complete verified output set, never partial glob matches."""
    root = Path(output_dir).resolve()
    manifest = root / DOWNLOAD_MANIFEST_NAME
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            payload.get("schema_version") != DOWNLOAD_MANIFEST_SCHEMA
            or payload.get("source_url") != url
            or not isinstance(payload.get("outputs"), list)
            or not payload["outputs"]
        ):
            return []
        completed = []
        for record in payload["outputs"]:
            if not isinstance(record, dict):
                return []
            relative = record.get("path")
            if not isinstance(relative, str) or not relative:
                return []
            path = (root / relative).resolve()
            path.relative_to(root)
            if (
                not path.is_file()
                or path.stat().st_size == 0
                or path.stat().st_size != record.get("size")
                or _sha256(path) != record.get("sha256")
            ):
                return []
            completed.append(str(path))
        return completed
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, ValueError):
        return []


def _invalidate_download_manifest(output_dir: str | os.PathLike[str]) -> None:
    root = Path(output_dir)
    (root / DOWNLOAD_MANIFEST_NAME).unlink(missing_ok=True)
    (root / f"{DOWNLOAD_MANIFEST_NAME}.tmp").unlink(missing_ok=True)


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
        _invalidate_download_manifest(output_dir)

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
            publish_download_manifest(output_dir, url, [path])
            return path, vid, [path]

    def _process_playlist(self, url: str, output_dir: str, entries: list, max_duration: int, progress_callback=None) -> Tuple[str, str, List[str]]:
        """处理分片下载与合并逻辑"""
        video_id = self.extract_video_id(url)
        temp_dir = os.path.join(output_dir, "temp_parts")
        os.makedirs(temp_dir, exist_ok=True)
        _invalidate_download_manifest(output_dir)
        self.progress_callback = progress_callback
        
        downloaded_parts = []
        
        for i, entry in enumerate(entries):
            if not entry:
                raise RuntimeError(f"分片 {i + 1} 元数据无效，终止整个任务")
            part_url = entry.get('url') or url # 兼容 Bilibili 内部跳转
            part_path = os.path.join(temp_dir, f"part_{i+1}.m4a")
            
            # 断点续传检查
            if os.path.exists(part_path):
                duration = self._get_duration(part_path)
                if duration > 0 and os.path.getsize(part_path) > 0:
                    downloaded_parts.append((part_path, duration))
                    continue
                os.remove(part_path)

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
                if not os.path.isfile(part_path) or os.path.getsize(part_path) == 0:
                    raise RuntimeError("下载命令未生成有效音频文件")
                duration = self._get_duration(part_path)
                if duration <= 0:
                    raise RuntimeError("下载音频时长无效")
                downloaded_parts.append((part_path, duration))
            except Exception as e:
                raise RuntimeError(f"分片 {i + 1} 下载失败，终止整个任务: {e}") from e

        merged_files = self._merge_audio_files(downloaded_parts, output_dir, temp_dir, max_duration)
        if not merged_files:
            raise RuntimeError("播放列表未生成任何合并音频，终止整个任务")
        publish_download_manifest(output_dir, url, merged_files)
        return merged_files[0], video_id, merged_files

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
            result = subprocess.run(cmd, capture_output=True)
            if (
                result.returncode != 0
                or not os.path.isfile(out_file)
                or os.path.getsize(out_file) == 0
            ):
                stderr = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else (result.stderr or "")
                raise RuntimeError(f"FFmpeg 合并失败: {stderr[-2000:]}")
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
