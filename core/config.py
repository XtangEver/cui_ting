# core/config.py
import os
import yaml
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


@dataclass
class AppConfig:
    models: Dict[str, ModelConfig]
    whisper_path: str
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
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

    def get_app_config(self) -> AppConfig:
        cfg = self.config

        model_names = cfg.get('models', [])
        models = {}
        for name in model_names:
            mc = _load_model_from_env(name)
            if mc is None:
                raise ValueError(f"模型 '{name}' 的环境变量未配置，请设置 {name.upper()}_API_KEY")
            models[name] = mc
        if not models:
            raise ValueError("未检测到任何模型配置，请在 config.yaml 和 .env 中配置模型")

        whisper_path = cfg.get('whisper', {}).get('model_path', 'mlx-community/whisper-medium')

        settings = cfg.get('settings', {})
        return AppConfig(
            models=models,
            whisper_path=whisper_path,
            chunk_size=settings.get('chunk_size', 5120),
            chunk_overlap=settings.get('chunk_overlap', 256),
            cookies_file=settings.get('cookies_file', 'cookie/bili_cookies.txt'),
            input_file=settings.get('input_file', 'input_data.json'),
            output_dir=settings.get('output_dir', './output'),
            subtitle_first=settings.get('subtitle_first', True),
            enable_refine=settings.get('enable_refine', True),
        )
