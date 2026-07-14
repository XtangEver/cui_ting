# core/config.py
import os
import yaml
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ModelConfig:
    api_key: str
    base_url: str
    model: str
    extra_headers: Optional[dict] = None
    verify_ssl: bool = True


@dataclass(frozen=True)
class WhisperConfig:
    model: str = "medium"
    download_root: Path = Path("D:/models")
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 8
    audio_chunk_seconds: int = 1200
    audio_context_seconds: int = 15
    vad_filter: bool = True


@dataclass
class AppConfig:
    models: Dict[str, ModelConfig]
    whisper: WhisperConfig
    llm_max_tokens: int
    chunk_size: int
    chunk_overlap: int
    cookies_file: str
    input_file: str
    output_dir: str
    subtitle_first: bool = True
    enable_refine: bool = True


def _load_model_from_env(name: str) -> Optional[ModelConfig]:
    """从环境变量加载模型配置，格式: {NAME}_API_KEY, {NAME}_BASE_URL, {NAME}_MODEL"""
    prefix = name.upper()
    api_key = os.environ.get(f"{prefix}_API_KEY")
    if not api_key:
        return None
    return ModelConfig(
        api_key=api_key,
        base_url=os.environ.get(f"{prefix}_BASE_URL", ""),
        model=os.environ.get(f"{prefix}_MODEL", ""),
    )


def _missing_model_env_vars(name: str) -> list[str]:
    prefix = name.upper()
    variables = (
        f"{prefix}_API_KEY",
        f"{prefix}_BASE_URL",
        f"{prefix}_MODEL",
    )
    return [variable for variable in variables if not os.environ.get(variable, "").strip()]


def _auto_discover_models() -> Dict[str, ModelConfig]:
    """扫描所有 *_API_KEY 环境变量，自动发现已配置的模型"""
    models = {}
    seen_prefixes = set()
    for key in os.environ:
        if key.endswith("_API_KEY"):
            prefix = key[:-8]  # remove _API_KEY
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            name = prefix.lower()
            cfg = _load_model_from_env(name)
            if cfg:
                models[name] = cfg
    return models


class ConfigManager:
    def __init__(self, config_path: str = "config.yaml"):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件未找到: {config_path}")
        self.base_dir = Path(config_path).resolve().parent
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

    def _resolve_app_path(self, value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            path = self.base_dir / path
        return str(path.resolve())

    def get_app_config(self) -> AppConfig:
        cfg = self.config

        settings = cfg.get('settings', {})
        enable_refine = settings.get('enable_refine', True)

        model_names = cfg.get('models', [])
        models = {}
        for name in model_names:
            if enable_refine:
                missing_variables = _missing_model_env_vars(name)
                if missing_variables:
                    raise ValueError(
                        f"模型 '{name}' 缺少必需的环境变量: "
                        + ", ".join(missing_variables)
                    )
            mc = _load_model_from_env(name)
            if mc is not None:
                models[name] = mc
        if enable_refine and not models:
            raise ValueError("未检测到任何模型配置，请在 config.yaml 和 .env 中配置模型")

        whisper_settings = cfg.get('whisper', {})
        whisper = WhisperConfig(
            model=whisper_settings.get('model', 'medium'),
            download_root=Path(whisper_settings.get('download_root', 'D:/models')),
            device=whisper_settings.get('device', 'cpu'),
            compute_type=whisper_settings.get('compute_type', 'int8'),
            cpu_threads=whisper_settings.get('cpu_threads', 8),
            audio_chunk_seconds=whisper_settings.get('audio_chunk_seconds', 1200),
            audio_context_seconds=whisper_settings.get('audio_context_seconds', 15),
            vad_filter=whisper_settings.get('vad_filter', True),
        )
        if whisper.audio_chunk_seconds <= 0:
            raise ValueError("audio_chunk_seconds must be greater than zero")
        if whisper.audio_context_seconds < 0:
            raise ValueError("audio_context_seconds must not be negative")
        if whisper.audio_chunk_seconds <= 2 * whisper.audio_context_seconds:
            raise ValueError("audio_chunk_seconds must exceed twice audio_context_seconds")
        if whisper.cpu_threads <= 0:
            raise ValueError("cpu_threads must be greater than zero")

        llm_max_tokens = cfg.get('llm', {}).get('max_tokens', 128000)
        if llm_max_tokens <= 0:
            raise ValueError("llm_max_tokens must be greater than zero")

        chunk_size = settings.get('chunk_size', 5120)
        chunk_overlap = settings.get('chunk_overlap', 256)
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be non-negative and less than chunk_size")

        return AppConfig(
            models=models,
            whisper=whisper,
            llm_max_tokens=llm_max_tokens,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            cookies_file=self._resolve_app_path(settings.get('cookies_file', 'cookie/bili_cookies.txt')),
            input_file=self._resolve_app_path(settings.get('input_file', 'input_data.json')),
            output_dir=self._resolve_app_path(settings.get('output_dir', './output')),
            subtitle_first=settings.get('subtitle_first', True),
            enable_refine=enable_refine,
        )
