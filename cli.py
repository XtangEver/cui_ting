import argparse
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from core.config import ConfigManager
from core.audio_chunker import AudioChunker
from core.summarizer import (
    VideoSummarizer,
    is_valid_refined_file,
    load_valid_raw_segments,
)
from core.transcriber import Transcriber

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
WINDOWS_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
    *(f"COM{number}" for number in "¹²³"),
    *(f"LPT{number}" for number in "¹²³"),
}


@dataclass
class BatchSummary:
    succeeded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


def load_input_json(json_path: str) -> object:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_folder_name(name: str) -> str:
    safe_name = WINDOWS_INVALID_NAME_CHARS.sub("_", name).rstrip(" .")
    if not safe_name or safe_name in {".", ".."}:
        return "unnamed"
    device_name = safe_name.split(".", 1)[0].upper()
    if device_name in WINDOWS_RESERVED_NAMES:
        safe_name = f"_{safe_name}"
    return safe_name


def validate_batch_tasks(tasks: object, output_dir: Path) -> list[tuple[str, str]]:
    if not isinstance(tasks, dict):
        raise ValueError("输入 JSON 必须是任务名到 URL 的对象")

    output_root = Path(output_dir).resolve()
    validated: list[tuple[str, str]] = []
    used_names: dict[str, str] = {}
    for name, url in tasks.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("任务名必须是非空字符串")
        if not isinstance(url, str):
            raise ValueError(f"任务 '{name}' 的 URL 必须是字符串")

        try:
            parsed_url = urlparse(url)
            hostname = parsed_url.hostname
        except ValueError:
            parsed_url = None
            hostname = None
        if (
            parsed_url is None
            or parsed_url.scheme.lower() not in {"http", "https"}
            or not hostname
        ):
            raise ValueError(f"任务 '{name}' 的 URL 必须是有效的 HTTP(S) URL")

        safe_name = sanitize_folder_name(name)
        collision_key = safe_name.casefold()
        if collision_key in used_names:
            raise ValueError(
                f"目录名冲突: '{used_names[collision_key]}' 与 '{name}' 都映射为 "
                f"'{safe_name}'"
            )

        task_path = (output_root / safe_name).resolve()
        if not task_path.is_relative_to(output_root) or task_path == output_root:
            raise ValueError(f"任务 '{name}' 的输出目录超出输出根目录")

        used_names[collision_key] = name
        validated.append((safe_name, url))
    return validated


def detect_cookie(
    url: str,
    project_root: Path = PROJECT_ROOT,
    *,
    cookie_dir: Path | None = None,
) -> Path:
    hostname = (urlparse(url).hostname or "").lower()
    cookie_name = "youtube_cookies.txt"
    if hostname == "bilibili.com" or hostname.endswith(".bilibili.com"):
        cookie_name = "bili_cookies.txt"
    base_dir = (
        Path(cookie_dir).resolve()
        if cookie_dir is not None
        else Path(project_root).resolve() / "cookie"
    )
    return (base_dir / cookie_name).resolve()


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _task_is_complete(output_dir: Path, enable_refine: bool) -> bool:
    audio_files = sorted(
        path
        for path in output_dir.glob("source*.mp3")
        if path.is_file() and path.stat().st_size > 0
    )
    if not audio_files:
        return False

    expected_outputs = []
    for audio_file in audio_files:
        expected_outputs.append(output_dir / f"{audio_file.stem}_raw.md")
        if enable_refine:
            expected_outputs.append(output_dir / f"{audio_file.stem}_refined.md")
    for path in expected_outputs:
        if path.name.endswith("_raw.md"):
            if load_valid_raw_segments(path) is None:
                return False
        elif not is_valid_refined_file(path):
            return False
    return True


def _process_result_is_complete(result: object, enable_refine: bool) -> bool:
    if not isinstance(result, dict):
        return False
    parts = result.get("results")
    if not isinstance(parts, list) or not parts:
        return False
    for part in parts:
        if not isinstance(part, dict):
            return False
        audio_path = Path(part.get("audio_path", ""))
        raw_path = Path(part.get("raw_file", ""))
        if (
            not audio_path.is_file()
            or audio_path.stat().st_size == 0
            or load_valid_raw_segments(raw_path) is None
        ):
            return False
        if enable_refine:
            refined_path = part.get("refined_file")
            if not refined_path or not is_valid_refined_file(refined_path):
                return False
    return True


def _preflight_media_tools() -> None:
    AudioChunker(chunk_seconds=1, context_seconds=0).validate_tools()


def _safe_exception_message(
    error: Exception, secrets: tuple[str, ...] = ()
) -> str:
    message = " ".join(str(error).splitlines()).strip()
    for secret in sorted((secret for secret in secrets if secret), key=len, reverse=True):
        message = message.replace(secret, "[REDACTED]")
    message = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)\S+",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(
        r"(?i)(api[_-]?key\s*[:=]\s*)\S+",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(
        r"(?i)(cookie\s*:\s*).+",
        r"\1[REDACTED]",
        message,
    )
    return (message or type(error).__name__)[:500]


def run_batch(
    config_path: str, summarizer_factory=VideoSummarizer
) -> BatchSummary:
    config_manager = ConfigManager(config_path)
    app_config = config_manager.get_app_config()
    batch_tasks = validate_batch_tasks(
        load_input_json(app_config.input_file), Path(app_config.output_dir)
    )
    _preflight_media_tools()

    output_base_dir = Path(app_config.output_dir).resolve()
    output_base_dir.mkdir(parents=True, exist_ok=True)
    cookie_dir = Path(app_config.cookies_file).resolve().parent
    shared_transcriber = Transcriber(app_config.whisper)
    configured_secrets = tuple(
        model.api_key for model in app_config.models.values() if model.api_key
    )
    summarizer_cache: dict[Path, VideoSummarizer] = {}
    summary = BatchSummary()

    logger.info("输入任务文件: %s", app_config.input_file)
    logger.info("输出根目录: %s", output_base_dir)
    logger.info("成功加载 %d 个任务", len(batch_tasks))

    for folder_name, url in batch_tasks:
        task_output_dir = output_base_dir / folder_name
        try:
            if _task_is_complete(task_output_dir, app_config.enable_refine):
                logger.info("任务 '%s' 最终产物已存在，跳过", folder_name)
                summary.skipped.append(folder_name)
                continue

            cookie_file = detect_cookie(url, cookie_dir=cookie_dir)
            if not cookie_file.exists():
                logger.warning("Cookie 文件不存在: %s", cookie_file)

            if cookie_file not in summarizer_cache:
                summarizer_cache[cookie_file] = summarizer_factory(
                    config_path=str(Path(config_path).resolve()),
                    cookies_file=cookie_file,
                    transcriber=shared_transcriber,
                )
            summarizer = summarizer_cache[cookie_file]

            task_output_dir.mkdir(parents=True, exist_ok=True)
            result = summarizer.process(url=url, output_dir=str(task_output_dir))
            if not _process_result_is_complete(result, app_config.enable_refine):
                raise RuntimeError("处理返回后未生成完整、非空且格式有效的最终产物")
            summary.succeeded.append(folder_name)
            logger.info("任务 '%s' 完成，输出: %s", folder_name, task_output_dir)
        except Exception as error:
            summary.failed.append(folder_name)
            logger.error(
                "任务 '%s' 失败: %s",
                folder_name,
                _safe_exception_message(error, configured_secrets),
            )

    logger.info(
        "批处理完成: 成功 %d %s; 跳过 %d %s; 失败 %d %s",
        len(summary.succeeded),
        summary.succeeded,
        len(summary.skipped),
        summary.skipped,
        len(summary.failed),
        summary.failed,
    )
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="cui_ting 视频转录与智能摘要工具")
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config.yaml"),
        help="配置文件路径（默认: 项目根目录下的 config.yaml）",
    )
    args = parser.parse_args(argv)

    setup_logging()
    logger.info("cui_ting - 视频转录与智能摘要工具")

    try:
        return run_batch(args.config).exit_code
    except Exception as error:
        logger.error("批处理启动失败: %s", _safe_exception_message(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
