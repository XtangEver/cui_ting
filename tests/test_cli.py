import json
from pathlib import Path

import pytest
import yaml

import cli


def test_e2e_manifest_has_four_unique_duration_buckets_across_platforms():
    videos = json.loads(Path("tests/e2e_videos.json").read_text(encoding="utf-8"))
    duration_ranges = {
        "5m": (180, 600),
        "30m": (1200, 2400),
        "1h": (2700, 4500),
        "2h": (6000, 8400),
    }

    assert len(videos) == 4
    assert all(
        set(video) == {"name", "platform", "url", "duration_seconds", "bucket"}
        for video in videos
    )
    assert len({video["name"] for video in videos}) == 4
    assert len({video["url"] for video in videos}) == 4
    assert {video["bucket"] for video in videos} == set(duration_ranges)
    assert {video["platform"] for video in videos} == {"youtube", "bilibili"}
    assert all(
        duration_ranges[video["bucket"]][0]
        <= video["duration_seconds"]
        <= duration_ranges[video["bucket"]][1]
        for video in videos
    )


def test_runtime_requirements_are_windows_cli_only():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()
    assert "faster-whisper" in requirements
    for unsupported in ("mlx-whisper", "fastapi", "uvicorn", "sqlalchemy"):
        assert unsupported not in requirements


@pytest.fixture(autouse=True)
def _configured_test_model(monkeypatch):
    monkeypatch.setenv("TESTMODEL_API_KEY", "test-key")
    monkeypatch.setenv("TESTMODEL_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("TESTMODEL_MODEL", "test-model")
    monkeypatch.setattr(cli, "_preflight_media_tools", lambda: None, raising=False)


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("a:b?c", "a_b_c"),
        ("name. ", "name"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("LPT9.log", "_LPT9.log"),
        ("COM10", "COM10"),
        ("..", "unnamed"),
        (". ", "unnamed"),
        ("a/b\\c", "a_b_c"),
        ("line\x00break", "line_break"),
    ],
)
def test_sanitize_folder_name(raw, safe):
    assert cli.sanitize_folder_name(raw) == safe


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("COM¹", "_COM¹"),
        ("com².txt", "_com².txt"),
        ("CoM³", "_CoM³"),
        ("lpt¹.log", "_lpt¹.log"),
        ("LPT²", "_LPT²"),
        ("LpT³.txt", "_LpT³.txt"),
    ],
)
def test_sanitize_folder_name_rejects_superscript_device_variants(raw, safe):
    assert cli.sanitize_folder_name(raw) == safe


def test_detect_cookie_uses_project_cookie_files(tmp_path):
    assert (
        cli.detect_cookie("https://www.bilibili.com/video/BV1x", tmp_path).name
        == "bili_cookies.txt"
    )
    assert (
        cli.detect_cookie("https://youtu.be/abcdefghijk", tmp_path).name
        == "youtube_cookies.txt"
    )


def test_validate_batch_tasks_returns_safe_names_and_urls(tmp_path):
    tasks = cli.validate_batch_tasks(
        {"a:b": "https://example.com/one", "C:\\outside": "http://example.com/two"},
        tmp_path,
    )

    assert tasks == [
        ("a_b", "https://example.com/one"),
        ("C__outside", "http://example.com/two"),
    ]
    assert all((tmp_path / name).resolve().is_relative_to(tmp_path.resolve()) for name, _ in tasks)


@pytest.mark.parametrize(
    "tasks",
    [
        None,
        [],
        {1: "https://example.com"},
        {"": "https://example.com"},
        {"   ": "https://example.com"},
        {"name": 123},
        {"name": ""},
        {"name": "ftp://example.com/file"},
        {"name": "https:///missing-host"},
    ],
)
def test_validate_batch_tasks_rejects_invalid_json_values(tasks, tmp_path):
    with pytest.raises(ValueError):
        cli.validate_batch_tasks(tasks, tmp_path)


@pytest.mark.parametrize(
    "url",
    [
        "https://:80",
        "https://user@:443",
        "https://[broken",
    ],
)
def test_validate_batch_tasks_rejects_missing_or_malformed_hostname(url, tmp_path):
    with pytest.raises(ValueError, match=r"HTTP\(S\) URL"):
        cli.validate_batch_tasks({"name": url}, tmp_path)


@pytest.mark.parametrize(
    "tasks",
    [
        {"a:b": "https://example.com/1", "a?b": "https://example.com/2"},
        {"Name": "https://example.com/1", "name": "https://example.com/2"},
        {"folder": "https://example.com/1", "folder. ": "https://example.com/2"},
    ],
)
def test_rejects_names_that_collide_after_sanitizing(tasks, tmp_path):
    with pytest.raises(ValueError, match="目录名冲突"):
        cli.validate_batch_tasks(tasks, tmp_path)


def _write_config(tmp_path: Path, tasks: dict, *, enable_refine: bool = True) -> Path:
    input_path = tmp_path / "tasks.json"
    input_path.write_text(json.dumps(tasks), encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "models": ["testmodel"],
                "whisper": {},
                "settings": {
                    "enable_refine": enable_refine,
                    "input_file": input_path.name,
                    "output_dir": "output",
                },
            }
        ),
        encoding="utf-8",
    )
    return config_path


class _FakeSummarizer:
    def __init__(self, calls, failing_names, **kwargs):
        self.calls = calls
        self.failing_names = failing_names
        self.kwargs = kwargs

    def process(self, url, output_dir):
        name = Path(output_dir).name
        self.calls.append((name, url))
        if name in self.failing_names:
            raise RuntimeError(f"safe failure for {name}")
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / "source.mp3").write_bytes(b"audio")
        (output / "source_raw.md").write_text(
            "# 原始转录文本\n\n[00:00:00] text", encoding="utf-8"
        )
        (output / "source_refined.md").write_text(
            "# 结构化摘要\n\nrefined", encoding="utf-8"
        )
        return {
            "output_dir": output_dir,
            "results": [
                {
                    "audio_path": str(output / "source.mp3"),
                    "raw_file": str(output / "source_raw.md"),
                    "refined_file": str(output / "source_refined.md"),
                }
            ],
        }


def test_batch_runs_media_tool_preflight_once_before_tasks(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path,
        {
            "one": "https://youtu.be/abcdefghijk",
            "two": "https://youtu.be/lmnopqrstuv",
        },
    )
    calls = []
    monkeypatch.setattr(cli, "_preflight_media_tools", lambda: calls.append("check"))
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())

    summary = cli.run_batch(str(config_path), summarizer_factory=_factory_spy())

    assert summary.exit_code == 0
    assert calls == ["check"]


def test_batch_fails_before_processing_when_media_tools_are_missing(
    tmp_path, monkeypatch
):
    config_path = _write_config(
        tmp_path, {"one": "https://youtu.be/abcdefghijk"}
    )
    factory = _factory_spy()
    monkeypatch.setattr(
        cli,
        "_preflight_media_tools",
        lambda: (_ for _ in ()).throw(RuntimeError("请安装 FFmpeg 并加入 PATH")),
    )

    with pytest.raises(RuntimeError, match="安装 FFmpeg.*PATH"):
        cli.run_batch(str(config_path), summarizer_factory=factory)

    assert factory.calls == []


def test_batch_marks_task_failed_when_process_returns_without_final_artifacts(
    tmp_path, monkeypatch
):
    config_path = _write_config(
        tmp_path, {"empty": "https://youtu.be/abcdefghijk"}
    )
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())

    class EmptySummarizer:
        def process(self, url, output_dir):
            return {"results": []}

    summary = cli.run_batch(
        str(config_path), summarizer_factory=lambda **kwargs: EmptySummarizer()
    )

    assert summary.succeeded == []
    assert summary.failed == ["empty"]


def _factory_spy(failing_names=()):
    created = []
    calls = []

    def factory(**kwargs):
        summarizer = _FakeSummarizer(calls, set(failing_names), **kwargs)
        created.append(summarizer)
        return summarizer

    factory.created = created
    factory.calls = calls
    return factory


def test_batch_continues_after_one_failure_and_returns_nonzero(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path,
        {
            "bad": "https://youtu.be/abcdefghijk",
            "ok": "https://youtu.be/lmnopqrstuv",
        },
    )
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())
    factory = _factory_spy({"bad"})

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.succeeded == ["ok"]
    assert summary.skipped == []
    assert summary.failed == ["bad"]
    assert summary.exit_code == 1
    assert factory.calls == [
        ("bad", "https://youtu.be/abcdefghijk"),
        ("ok", "https://youtu.be/lmnopqrstuv"),
    ]


def test_batch_continues_when_one_completion_probe_fails(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path,
        {
            "bad-probe": "https://youtu.be/abcdefghijk",
            "ok": "https://youtu.be/lmnopqrstuv",
        },
    )
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())
    probed = []

    def completion_probe(output_dir, enable_refine):
        probed.append(Path(output_dir).name)
        if Path(output_dir).name == "bad-probe":
            raise PermissionError("completion probe denied")
        return False

    monkeypatch.setattr(cli, "_task_is_complete", completion_probe)
    factory = _factory_spy()

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert probed == ["bad-probe", "ok"]
    assert summary.failed == ["bad-probe"]
    assert summary.succeeded == ["ok"]
    assert summary.skipped == []
    assert summary.exit_code == 1
    assert factory.calls == [("ok", "https://youtu.be/lmnopqrstuv")]


def test_batch_redacts_configured_secrets_from_task_errors(
    tmp_path, monkeypatch, caplog
):
    config_path = _write_config(
        tmp_path, {"bad": "https://youtu.be/abcdefghijk"}
    )
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())

    class LeakySummarizer:
        def process(self, url, output_dir):
            raise RuntimeError("request failed with Authorization: Bearer test-key")

    def factory(**kwargs):
        return LeakySummarizer()

    with caplog.at_level("ERROR"):
        summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.failed == ["bad"]
    assert "test-key" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_batch_creates_one_shared_transcriber_for_cookie_summarizers(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path,
        {
            "bili": "https://www.bilibili.com/video/BV1x",
            "youtube-1": "https://youtu.be/abcdefghijk",
            "youtube-2": "https://youtube.com/watch?v=lmnopqrstuv",
        },
    )
    transcribers = []

    def transcriber_factory(config):
        transcriber = object()
        transcribers.append((config, transcriber))
        return transcriber

    monkeypatch.setattr(cli, "Transcriber", transcriber_factory)
    factory = _factory_spy()

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.exit_code == 0
    assert len(transcribers) == 1
    assert len(factory.created) == 2
    assert {item.kwargs["cookies_file"].name for item in factory.created} == {
        "bili_cookies.txt",
        "youtube_cookies.txt",
    }
    assert all(
        item.kwargs["transcriber"] is transcribers[0][1] for item in factory.created
    )


def test_batch_routes_nested_config_cookies_from_configured_cookie_directory(
    tmp_path, monkeypatch
):
    project_dir = tmp_path / "project"
    config_dir = project_dir / ".e2e"
    config_dir.mkdir(parents=True)
    (project_dir / "secrets").mkdir()
    (config_dir / "tasks.json").write_text(
        json.dumps(
            {
                "bili": "https://www.bilibili.com/video/BV1x",
                "youtube": "https://youtu.be/abcdefghijk",
            }
        ),
        encoding="utf-8",
    )
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "models": ["testmodel"],
                "whisper": {},
                "settings": {
                    "enable_refine": True,
                    "input_file": "tasks.json",
                    "output_dir": "../output",
                    "cookies_file": "../secrets/bili_cookies.txt",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())
    factory = _factory_spy()

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.exit_code == 0
    assert {item.kwargs["cookies_file"] for item in factory.created} == {
        (project_dir / "secrets" / "bili_cookies.txt").resolve(),
        (project_dir / "secrets" / "youtube_cookies.txt").resolve(),
    }


def test_batch_accounts_for_complete_tasks_as_skipped_before_processing(
    tmp_path, monkeypatch
):
    config_path = _write_config(
        tmp_path,
        {
            "complete": "https://youtu.be/abcdefghijk",
            "partial": "https://youtu.be/lmnopqrstuv",
            "fresh": "https://youtu.be/12345678901",
        },
    )
    output_dir = tmp_path / "output"
    (output_dir / "complete").mkdir(parents=True)
    (output_dir / "complete" / "source.mp3").write_bytes(b"audio")
    (output_dir / "complete" / "source_raw.md").write_text("[00:00:00] raw", encoding="utf-8")
    (output_dir / "complete" / "source_refined.md").write_text(
        "# 结构化摘要\n\nrefined", encoding="utf-8"
    )
    (output_dir / "partial").mkdir()
    (output_dir / "partial" / "source.mp3").write_bytes(b"audio")
    (output_dir / "partial" / "source_raw.md").write_text("[00:00:00] raw", encoding="utf-8")
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())
    factory = _factory_spy()

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.skipped == ["complete"]
    assert summary.succeeded == ["partial", "fresh"]
    assert summary.failed == []
    assert [name for name, _ in factory.calls] == ["partial", "fresh"]


def test_batch_without_refinement_needs_only_raw_output_to_skip(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path,
        {"complete": "https://youtu.be/abcdefghijk"},
        enable_refine=False,
    )
    task_dir = tmp_path / "output" / "complete"
    task_dir.mkdir(parents=True)
    (task_dir / "source.mp3").write_bytes(b"audio")
    (task_dir / "source_raw.md").write_text("[00:00:00] raw", encoding="utf-8")
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())
    factory = _factory_spy()

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.skipped == ["complete"]
    assert summary.succeeded == []
    assert factory.calls == []


def test_completion_probe_accepts_hundred_hour_raw_timestamp(tmp_path):
    task_dir = tmp_path / "hundred-hour"
    task_dir.mkdir()
    (task_dir / "source.mp3").write_bytes(b"audio")
    (task_dir / "source_raw.md").write_text(
        "# 原始转录文本\n\n[100:00:00] long recording", encoding="utf-8"
    )

    assert cli._task_is_complete(task_dir, enable_refine=False)


def test_batch_does_not_skip_zero_byte_audio_cache(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path,
        {"stale": "https://youtu.be/abcdefghijk"},
        enable_refine=False,
    )
    task_dir = tmp_path / "output" / "stale"
    task_dir.mkdir(parents=True)
    (task_dir / "source.mp3").write_bytes(b"")
    (task_dir / "source_raw.md").write_text(
        "[00:00:00] stale", encoding="utf-8"
    )
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())
    factory = _factory_spy()

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.skipped == []
    assert summary.succeeded == ["stale"]


def test_batch_skips_completed_multi_part_outputs(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path, {"complete": "https://youtu.be/abcdefghijk"}
    )
    task_dir = tmp_path / "output" / "complete"
    task_dir.mkdir(parents=True)
    for basename in ("source_part1", "source_part2"):
        (task_dir / f"{basename}.mp3").write_bytes(b"audio")
        (task_dir / f"{basename}_raw.md").write_text("[00:00:00] raw", encoding="utf-8")
        (task_dir / f"{basename}_refined.md").write_text(
            "# 结构化摘要\n\nrefined", encoding="utf-8"
        )
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())
    factory = _factory_spy()

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.skipped == ["complete"]
    assert summary.succeeded == []
    assert factory.calls == []


def test_batch_processes_partial_multi_part_outputs(tmp_path, monkeypatch):
    config_path = _write_config(
        tmp_path, {"partial": "https://youtu.be/abcdefghijk"}
    )
    task_dir = tmp_path / "output" / "partial"
    task_dir.mkdir(parents=True)
    for basename in ("source_part1", "source_part2"):
        (task_dir / f"{basename}.mp3").write_bytes(b"audio")
    (task_dir / "source_part1_raw.md").write_text("[00:00:00] raw", encoding="utf-8")
    (task_dir / "source_part1_refined.md").write_text("# 结构化摘要\n\nrefined", encoding="utf-8")
    # Stale aggregate files must not hide the missing part-2 outputs.
    (task_dir / "source_raw.md").write_text("raw", encoding="utf-8")
    (task_dir / "source_refined.md").write_text("refined", encoding="utf-8")
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())
    factory = _factory_spy()

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.skipped == []
    assert summary.succeeded == ["partial"]
    assert factory.calls == [("partial", "https://youtu.be/abcdefghijk")]


@pytest.mark.parametrize(
    ("raw_text", "refined_text"),
    [
        ("", "# 结构化摘要\n\nrefined"),
        ("not anchored", "# 结构化摘要\n\nrefined"),
        ("[00:00:00] raw", "# 结构化摘要\n\n"),
    ],
)
def test_batch_rebuilds_empty_or_malformed_final_cache(
    tmp_path, monkeypatch, raw_text, refined_text
):
    config_path = _write_config(
        tmp_path, {"stale": "https://youtu.be/abcdefghijk"}
    )
    task_dir = tmp_path / "output" / "stale"
    task_dir.mkdir(parents=True)
    (task_dir / "source.mp3").write_bytes(b"audio")
    (task_dir / "source_raw.md").write_text(raw_text, encoding="utf-8")
    (task_dir / "source_refined.md").write_text(refined_text, encoding="utf-8")
    monkeypatch.setattr(cli, "Transcriber", lambda config: object())
    factory = _factory_spy()

    summary = cli.run_batch(str(config_path), summarizer_factory=factory)

    assert summary.skipped == []
    assert summary.succeeded == ["stale"]
    assert factory.calls == [("stale", "https://youtu.be/abcdefghijk")]


def test_main_returns_batch_exit_code(monkeypatch, tmp_path):
    received = []

    class Summary:
        exit_code = 1
        succeeded = []
        skipped = []
        failed = ["bad"]

    monkeypatch.setattr(cli, "run_batch", lambda path: received.append(path) or Summary())

    result = cli.main(["--config", str(tmp_path / "custom.yaml")])

    assert result == 1
    assert received == [str(tmp_path / "custom.yaml")]


def test_main_returns_nonzero_for_invalid_batch(monkeypatch, tmp_path):
    def fail(_path):
        raise ValueError("invalid input")

    monkeypatch.setattr(cli, "run_batch", fail)

    assert cli.main(["--config", str(tmp_path / "invalid.yaml")]) == 1
