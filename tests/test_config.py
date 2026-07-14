from pathlib import Path
import pytest
from core.config import ConfigManager


def write_config(
    tmp_path: Path,
    chunk=1200,
    context=15,
    *,
    models=None,
    enable_refine=False,
    text_chunk_size=5120,
    text_chunk_overlap=256,
):
    model_names = models or []
    path = tmp_path / "config.yaml"
    path.write_text(f"""
models: {model_names}
whisper:
  model: medium
  download_root: D:/models
  device: cpu
  compute_type: int8
  cpu_threads: 8
  audio_chunk_seconds: {chunk}
  audio_context_seconds: {context}
  vad_filter: true
llm:
  max_tokens: 128000
settings:
  chunk_size: {text_chunk_size}
  chunk_overlap: {text_chunk_overlap}
  input_file: input_data.json
  output_dir: test_case
  cookies_file: cookie/bili_cookies.txt
  enable_refine: {str(enable_refine).lower()}
""", encoding="utf-8")
    return path


def test_loads_windows_whisper_settings_and_resolves_relative_paths(tmp_path):
    cfg = ConfigManager(write_config(tmp_path)).get_app_config()
    assert cfg.whisper.model == "medium"
    assert cfg.whisper.download_root == Path("D:/models")
    assert cfg.whisper.device == "cpu"
    assert cfg.whisper.compute_type == "int8"
    assert cfg.whisper.audio_chunk_seconds == 1200
    assert cfg.whisper.audio_context_seconds == 15
    assert cfg.llm_max_tokens == 128000
    assert cfg.input_file == str((tmp_path / "input_data.json").resolve())


@pytest.mark.parametrize("chunk,context", [(0, 15), (1200, -1), (30, 15)])
def test_rejects_invalid_chunk_settings(tmp_path, chunk, context):
    with pytest.raises(ValueError, match="audio_"):
        ConfigManager(write_config(tmp_path, chunk, context)).get_app_config()


@pytest.mark.parametrize(
    "chunk_size,chunk_overlap",
    [(0, 0), (-1, 0), (100, -1), (100, 100), (100, 101)],
)
def test_rejects_invalid_text_chunk_settings(tmp_path, chunk_size, chunk_overlap):
    config_path = write_config(
        tmp_path,
        text_chunk_size=chunk_size,
        text_chunk_overlap=chunk_overlap,
    )

    with pytest.raises(ValueError, match="chunk_size|chunk_overlap"):
        ConfigManager(config_path).get_app_config()


@pytest.mark.parametrize(
    ("missing_variable", "present_values"),
    [
        ("CLEANER_API_KEY", {"CLEANER_BASE_URL": "https://example.invalid", "CLEANER_MODEL": "model"}),
        ("CLEANER_BASE_URL", {"CLEANER_API_KEY": "key", "CLEANER_MODEL": "model"}),
        ("CLEANER_MODEL", {"CLEANER_API_KEY": "key", "CLEANER_BASE_URL": "https://example.invalid"}),
    ],
)
def test_refinement_reports_each_missing_model_field(
    tmp_path, monkeypatch, missing_variable, present_values
):
    for variable in ("CLEANER_API_KEY", "CLEANER_BASE_URL", "CLEANER_MODEL"):
        monkeypatch.delenv(variable, raising=False)
    for variable, value in present_values.items():
        monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=missing_variable):
        ConfigManager(
            write_config(tmp_path, models=["cleaner"], enable_refine=True)
        ).get_app_config()


def test_refinement_error_lists_all_missing_model_fields_without_values(tmp_path, monkeypatch):
    for variable in ("CLEANER_API_KEY", "CLEANER_BASE_URL", "CLEANER_MODEL"):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(ValueError) as exc_info:
        ConfigManager(
            write_config(tmp_path, models=["cleaner"], enable_refine=True)
        ).get_app_config()

    message = str(exc_info.value)
    assert "CLEANER_API_KEY" in message
    assert "CLEANER_BASE_URL" in message
    assert "CLEANER_MODEL" in message
    assert "https://" not in message


def test_refinement_disabled_allows_no_model_configuration(tmp_path):
    cfg = ConfigManager(
        write_config(tmp_path, models=[], enable_refine=False)
    ).get_app_config()

    assert cfg.models == {}
    assert cfg.enable_refine is False
