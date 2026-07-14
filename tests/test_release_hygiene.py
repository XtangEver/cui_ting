import re
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
NUMERIC_HTTP_ENDPOINT = re.compile(
    rb"https?://(?:"
    rb"(?:\d{1,3}\.){3}\d{1,3}"
    rb"|\[(?=[0-9a-f:.]*:)[0-9a-f:.]+\]"
    rb")(?::\d+)?",
    re.IGNORECASE,
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def _is_forbidden_tracked_runtime_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path.replace("\\", "/"))
    parts = tuple(part.casefold() for part in path.parts)
    name = path.name.casefold()

    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if name == "input_data.json":
        return True
    if "cookie" in parts and name.endswith(".txt"):
        return True
    if any(
        part in {"test_case", "output", ".e2e", ".transcription_cache", "models", ".cache"}
        for part in parts
    ):
        return True
    if name == ".download_manifest.json":
        return True
    return path.suffix.casefold() in {
        ".mp3",
        ".wav",
        ".m4a",
        ".webm",
        ".part",
        ".vtt",
        ".srt",
        ".pem",
        ".key",
        ".p12",
        ".pfx",
    }


def test_forbidden_tracked_runtime_path_classifier():
    forbidden = {
        ".env",
        ".env.local",
        "input_data.json",
        "cookie/nested/account.txt",
        "output/task/result.json",
        ".e2e/run.log",
        "nested/.transcription_cache/state.json",
        "nested/.download_manifest.json",
        "models/model.bin",
        "media/source.mp3",
        "subtitles/result.vtt",
        "keys/private.pem",
        "keys/private.p12",
    }
    allowed = {
        ".env.example",
        "input_data.example.json",
        "examples/cookie-format.md",
        "docs/output-format.md",
        "models.md",
    }
    assert all(_is_forbidden_tracked_runtime_path(path) for path in forbidden)
    assert not any(_is_forbidden_tracked_runtime_path(path) for path in allowed)


def test_private_runtime_files_are_not_tracked():
    tracked = {
        path.decode("utf-8")
        for path in subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        if path
    }
    forbidden = sorted(path for path in tracked if _is_forbidden_tracked_runtime_path(path))
    assert not forbidden, "forbidden tracked runtime paths: " + ", ".join(forbidden)
    assert (ROOT / ".env.example").is_file()
    assert (ROOT / "input_data.example.json").is_file()


def test_private_runtime_paths_are_ignored():
    candidates = [
        ".env",
        ".env.local",
        "cookie/bili_cookies.txt",
        "cookie/nested/account.txt",
        "input_data.json",
        "test_case/task/source.mp3",
        ".e2e/run.log",
        "models/model.bin",
        "output/task/subtitle.zh.vtt",
        "private.pem",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=ROOT,
        input=b"\0".join(path.encode("utf-8") for path in candidates) + b"\0",
        check=True,
        capture_output=True,
    )
    ignored = {
        path.decode("utf-8") for path in result.stdout.split(b"\0") if path
    }
    assert ignored == set(candidates)
    assert subprocess.run(
        ["git", "check-ignore", "--no-index", ".env.example"], cwd=ROOT
    ).returncode != 0


def test_windows_readme_covers_the_supported_cli_workflow():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = [
        "## 快速开始",
        "## 隐私文件配置",
        "## 批量任务配置",
        "## 运行 CLI",
        "## 输出与断点恢复",
        "## 常见问题",
        "windows-v1.0.0",
    ]
    assert all(item in readme for item in required)
    assert not re.search(r"https?://(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?", readme)


def test_release_guidance_uses_the_exact_public_llm_endpoint_example():
    endpoint = "https://your-openai-compatible-endpoint.example/v1"
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert f"NANYAN_BASE_URL={endpoint}" in env_example

    for relative_path in [
        "docs/superpowers/plans/2026-07-13-windows-cli-long-audio.md",
        "docs/superpowers/specs/2026-07-13-windows-cli-long-audio-design.md",
    ]:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert endpoint in content
        assert "<REDACTED_URL>" not in content


def test_windows_readme_uses_the_conda_environment_for_import_checks():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    command = 'conda run -n cui_ting python -c "import faster_whisper"'
    assert command in readme


def test_windows_readme_cli_commands_disable_conda_output_capture():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    commands = {
        "conda run --no-capture-output -n cui_ting python cli.py",
        "conda run --no-capture-output -n cui_ting python cli.py --config config.yaml",
    }
    assert all(command in readme for command in commands)


def test_numeric_http_endpoint_pattern_is_case_insensitive():
    endpoint = b"HTTP" + b"://" + b"198.51.100.7:8000"
    assert NUMERIC_HTTP_ENDPOINT.fullmatch(endpoint) is not None


def test_numeric_http_endpoint_pattern_covers_bracketed_ipv6():
    endpoint = b"https" + b"://[" + b"2001:db8::7" + b"]:8000"
    assert NUMERIC_HTTP_ENDPOINT.fullmatch(endpoint) is not None


def test_numeric_http_endpoint_line_count_supports_crlf():
    content = b"first\r\nsecond\r\nHTTP" + b"://" + b"198.51.100.7:8000"
    match = re.compile(NUMERIC_HTTP_ENDPOINT.pattern, re.IGNORECASE).search(content)
    assert match is not None
    assert content.count(b"\n", 0, match.start()) + 1 == 3


def test_tracked_text_files_do_not_contain_numeric_http_endpoints():
    tracked = [
        path.decode("utf-8")
        for path in subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        if path
    ]
    findings = []
    for relative_path in tracked:
        content = (ROOT / relative_path).read_bytes()
        if b"\0" in content:
            continue
        for match in NUMERIC_HTTP_ENDPOINT.finditer(content):
            line = content.count(b"\n", 0, match.start()) + 1
            findings.append(f"{relative_path}:{line}")

    assert not findings, "numeric HTTP(S) endpoints found at: " + ", ".join(findings)
