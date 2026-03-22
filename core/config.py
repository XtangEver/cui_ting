# core/config.py
import os
import yaml
from typing import Optional, Dict
from dataclasses import dataclass


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
    default_model: str
    cookies_file: str
    input_file: str
    output_dir: str
    subtitle_first: bool = True
    extract_frames: bool = True
    frame_offset: float = 1.5


class ConfigManager:
    def __init__(self, config_path: str = "config.yaml"):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件未找到: {config_path}")
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

    @staticmethod
    def _resolve_api_key(name: str, yaml_value: str) -> str:
        """优先从环境变量 {NAME}_API_KEY 读取，否则使用 yaml 中的值"""
        env_key = f"{name.upper()}_API_KEY"
        return os.environ.get(env_key, yaml_value)

    def get_app_config(self) -> AppConfig:
        cfg = self.config

        models = {}
        for name, m in cfg.get('models', {}).items():
            models[name] = ModelConfig(
                api_key=self._resolve_api_key(name, m.get('api_key', '')),
                base_url=m.get('base_url', ''),
                model=m.get('model', ''),
                extra_headers=m.get('extra_headers'),
                verify_ssl=m.get('verify_ssl', True)
            )

        whisper_path = cfg.get('whisper', {}).get('model_path', 'mlx-community/whisper-medium')

        settings = cfg.get('settings', {})
        return AppConfig(
            models=models,
            whisper_path=whisper_path,
            chunk_size=settings.get('chunk_size', 5120),
            chunk_overlap=settings.get('chunk_overlap', 256),
            default_model=settings.get('default_llm_model', 'glm'),
            cookies_file=settings.get('cookies_file', 'cookie/bili_cookies.txt'),
            input_file=settings.get('input_file', 'input_data.json'),
            output_dir=settings.get('output_dir', './output'),
            subtitle_first=settings.get('subtitle_first', True),
            extract_frames=settings.get('extract_frames', True),
            frame_offset=settings.get('frame_offset', 1.5),
        )
