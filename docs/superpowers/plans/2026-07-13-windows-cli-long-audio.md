# Windows CLI Long-Audio Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make方式 C a reliable Windows-only batch CLI that uses one CPU INT8 `faster-whisper` `medium` model, transcribes arbitrarily long audio in resumable bounded-memory chunks, and cleans the result through the configured 128k LiteLLM endpoint.

**Architecture:** A focused `AudioChunker` owns FFprobe planning and one-at-a-time FFmpeg extraction; `Transcriber` lazily owns the single Whisper model and persists validated per-chunk JSON results. `VideoSummarizer` keeps stage-level Markdown caches, while `cli.py` owns Windows-safe batch validation, shared heavy dependencies, cookie routing, summaries, and exit codes.

**Tech Stack:** Python 3.11, Conda, pytest, yt-dlp, FFmpeg/FFprobe, faster-whisper/CTranslate2 CPU INT8, OpenAI Python client, PyYAML, python-dotenv.

## Global Constraints

- Only方式 C is supported and verified on Windows; keep the existing Web source but do not install or test its dependencies.
- Use Conda environment `cui_ting`; create it with Python 3.11 when absent.
- Use `faster-whisper` model `medium`, `device="cpu"`, `compute_type="int8"`, and download/cache under `D:\models`.
- Process 1,200-second core intervals with at most 15 seconds of context on each side, one temporary WAV at a time.
- Keep exactly one lazy `WhisperModel` instance for the whole CLI process.
- Read both platform cookies from `D:\work_dir\cui_ting\cookie`; never print or commit their contents.
- Read the LiteLLM API key only from `.env`; use model `example-model`, base URL ending in `/litellm`, and `max_tokens=128000`.
- Do not make real model, video-platform, or LLM calls in unit tests.
- Real acceptance must cover exactly four videos across YouTube and Bilibili at 5m, 30m, 1h, and 2h, with subtitles disabled.
- Preserve unrelated user changes and never stage `.env`, cookies, audio, model files, output data, or transcription caches.

---

## File Map

- Create `core/audio_chunker.py`: duration probing, deterministic core/context planning, FFmpeg extraction, and tool validation.
- Modify `core/config.py`: typed Whisper/LLM settings and config-relative path resolution.
- Modify `core/transcriber.py`: lazy faster-whisper model, chunk iteration, global timestamps, overlap ownership, atomic JSON cache.
- Modify `core/summarizer.py`: dependency injection, atomic Markdown, timestamp-preserving raw cache, shared transcriber support.
- Modify `core/llm_processor.py`: configurable output limit and testable client injection.
- Modify `cli.py`: safe Windows names, shared heavy objects, result accounting, arguments, and meaningful exit codes.
- Modify `config.yaml`: Windows relative paths, medium model/cache, chunking, and Nanyan model alias.
- Modify `requirements.txt`: CLI runtime dependencies only.
- Create `requirements-dev.txt`: pytest tooling.
- Modify `.gitignore`: runtime transcription cache and E2E output exclusions.
- Rewrite `README.md`: Windows方式 C instructions and troubleshooting.
- Create `tests/test_config.py`, `tests/test_audio_chunker.py`, `tests/test_transcriber.py`, `tests/test_summarizer.py`, `tests/test_llm_processor.py`, and `tests/test_cli.py`.
- Create `tests/e2e_videos.json`: four metadata-verified public acceptance links without secrets.

---

### Task 1: Create and Verify the `cui_ting` Environment

**Files:**
- No repository files changed in this task.

**Interfaces:**
- Produces: a Conda environment named `cui_ting` whose `python --version` reports Python 3.11.x.

- [ ] **Step 1: Detect the environment without relying on shell activation**

Run:

```powershell
conda env list --json
```

Expected: valid JSON. Treat an environment path whose final component is `cui_ting` as present.

- [ ] **Step 2: Create it only when missing**

Run when absent:

```powershell
conda create -n cui_ting python=3.11 -y
```

Expected: exit code 0 and no modification to the repository.

- [ ] **Step 3: Verify the interpreter and package manager**

Run:

```powershell
conda run -n cui_ting python --version
conda run -n cui_ting python -m pip --version
```

Expected: Python 3.11.x and pip located inside the `cui_ting` environment.

---

### Task 2: Add Typed Windows Configuration

**Files:**
- Modify: `core/config.py`
- Modify: `config.yaml`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `WhisperConfig(model, download_root, device, compute_type, cpu_threads, audio_chunk_seconds, audio_context_seconds, vad_filter)`.
- Produces: `AppConfig.whisper: WhisperConfig` and `AppConfig.llm_max_tokens: int`.
- Produces: config-relative absolute `input_file`, `output_dir`, and `cookies_file` paths.

- [ ] **Step 1: Write failing configuration tests**

```python
# tests/test_config.py
from pathlib import Path
import pytest
from core.config import ConfigManager


def write_config(tmp_path: Path, chunk=1200, context=15):
    path = tmp_path / "config.yaml"
    path.write_text(f"""
models: []
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
  input_file: input_data.json
  output_dir: test_case
  cookies_file: cookie/bili_cookies.txt
  enable_refine: false
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
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n cui_ting python -m pytest tests/test_config.py -v`

Expected: FAIL because `WhisperConfig` and the new `AppConfig` fields do not exist.

- [ ] **Step 3: Implement the typed configuration**

Add to `core/config.py`:

```python
from pathlib import Path


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
```

Replace `AppConfig.whisper_path` with `whisper: WhisperConfig`, add `llm_max_tokens: int`, remember `self.base_dir = Path(config_path).resolve().parent`, and resolve only non-absolute application paths against `base_dir`. Validate `chunk > 0`, `context >= 0`, `chunk > 2 * context`, `cpu_threads > 0`, and `llm_max_tokens > 0`. Keep the existing rule that model environment variables are mandatory only when `enable_refine` is true; allow an empty `models` list when refinement is disabled.

Update `config.yaml` to the exact schema in the design, use `models: [nanyan]`, and use relative `input_data.json`, `test_case`, and `cookie/bili_cookies.txt` paths.

- [ ] **Step 4: Run configuration tests and the existing import smoke test**

Run:

```powershell
conda run -n cui_ting python -m pytest tests/test_config.py -v
conda run -n cui_ting python -c "from core.config import ConfigManager; print('config import ok')"
```

Expected: all tests PASS and `config import ok`.

- [ ] **Step 5: Commit**

```powershell
git add core/config.py config.yaml tests/test_config.py
git commit -m "feat: add Windows CLI configuration"
```

---

### Task 3: Build the Deterministic Audio Chunker

**Files:**
- Create: `core/audio_chunker.py`
- Create: `tests/test_audio_chunker.py`

**Interfaces:**
- Produces: immutable `AudioChunk(index, core_start, core_end, extract_start, extract_end)`.
- Produces: `AudioChunker.probe_duration(audio_path: Path) -> float`.
- Produces: `AudioChunker.plan(duration: float) -> list[AudioChunk]`.
- Produces: `AudioChunker.extract(audio_path: Path, chunk: AudioChunk, output_path: Path) -> None`.

- [ ] **Step 1: Write failing pure-planning tests**

```python
# tests/test_audio_chunker.py
from pathlib import Path
import subprocess
import pytest
from core.audio_chunker import AudioChunker


def test_short_audio_has_one_clipped_chunk():
    chunks = AudioChunker(1200, 15).plan(300)
    assert [(c.core_start, c.core_end, c.extract_start, c.extract_end) for c in chunks] == [(0, 300, 0, 300)]


def test_long_audio_has_context_but_nonoverlapping_ownership():
    chunks = AudioChunker(1200, 15).plan(2500)
    assert [(c.core_start, c.core_end) for c in chunks] == [(0, 1200), (1200, 2400), (2400, 2500)]
    assert [(c.extract_start, c.extract_end) for c in chunks] == [(0, 1215), (1185, 2415), (2385, 2500)]


def test_probe_rejects_invalid_duration(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "bad", ""))
    with pytest.raises(RuntimeError, match="FFprobe"):
        AudioChunker(1200, 15).probe_duration(tmp_path / "source.mp3")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n cui_ting python -m pytest tests/test_audio_chunker.py -v`

Expected: collection FAIL because `core.audio_chunker` does not exist.

- [ ] **Step 3: Implement planning, probing, and extraction**

```python
# core/audio_chunker.py
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess


@dataclass(frozen=True)
class AudioChunk:
    index: int
    core_start: float
    core_end: float
    extract_start: float
    extract_end: float


class AudioChunker:
    def __init__(self, chunk_seconds: int, context_seconds: int,
                 ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        self.chunk_seconds = chunk_seconds
        self.context_seconds = context_seconds
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def validate_tools(self) -> None:
        for tool in (self.ffmpeg, self.ffprobe):
            if shutil.which(tool) is None:
                raise RuntimeError(f"未找到 {tool}，请安装 FFmpeg 并加入 PATH")

    def plan(self, duration: float) -> list[AudioChunk]:
        if duration <= 0:
            raise ValueError("audio duration must be positive")
        result = []
        core_start = 0.0
        index = 1
        while core_start < duration:
            core_end = min(core_start + self.chunk_seconds, duration)
            result.append(AudioChunk(index, core_start, core_end,
                                     max(0.0, core_start - self.context_seconds),
                                     min(duration, core_end + self.context_seconds)))
            core_start = core_end
            index += 1
        return result

    def probe_duration(self, audio_path: Path) -> float:
        command = [self.ffprobe, "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        try:
            duration = float(result.stdout.strip())
        except ValueError as exc:
            raise RuntimeError(f"FFprobe 无法读取音频时长: {audio_path}") from exc
        if result.returncode != 0 or duration <= 0:
            raise RuntimeError(f"FFprobe 无法读取音频时长: {audio_path}")
        return duration

    def extract(self, audio_path: Path, chunk: AudioChunk, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(chunk.extract_start),
                   "-i", str(audio_path), "-t", str(chunk.extract_end - chunk.extract_start),
                   "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(output_path)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            stderr = result.stderr[-2000:]
            raise RuntimeError(f"FFmpeg 切片失败: {audio_path}: {stderr}")
```

- [ ] **Step 4: Add a real FFmpeg integration test with generated audio**

Append a test that uses `shutil.which`, generates a 3-second sine WAV via FFmpeg, calls `probe_duration`, extracts it, asserts a nonempty output, and marks the test skipped only when FFmpeg is genuinely unavailable.

- [ ] **Step 5: Run tests and commit**

Run: `conda run -n cui_ting python -m pytest tests/test_audio_chunker.py -v`

Expected: all tests PASS.

```powershell
git add core/audio_chunker.py tests/test_audio_chunker.py
git commit -m "feat: add bounded-memory audio chunking"
```

---

### Task 4: Replace MLX with Lazy, Resumable Faster-Whisper

**Files:**
- Modify: `core/transcriber.py`
- Create: `tests/test_transcriber.py`

**Interfaces:**
- Consumes: `WhisperConfig`, `AudioChunker`, and `TimestampedSegment`.
- Produces: `Transcriber(config, chunker=None, model_factory=None)`.
- Produces: `Transcriber.transcribe(audio_path: str, cache_dir: str | None = None) -> list[TimestampedSegment]`.

- [ ] **Step 1: Write failing model, offset, ownership, and resume tests**

Create fakes whose `transcribe()` returns a generator with segments on both sides of the core boundary. Assert:

```python
def test_model_is_lazy_and_created_once(config, chunker, model_factory, tmp_path):
    transcriber = Transcriber(config, chunker, model_factory)
    assert model_factory.calls == []
    transcriber.transcribe(str(tmp_path / "a.mp3"), str(tmp_path / "cache-a"))
    transcriber.transcribe(str(tmp_path / "b.mp3"), str(tmp_path / "cache-b"))
    assert model_factory.calls == [{"model_size_or_path": "medium", "device": "cpu",
                                    "compute_type": "int8", "cpu_threads": 8,
                                    "download_root": "D:\\models"}]


def test_offsets_and_assigns_overlap_by_segment_midpoint(transcriber, tmp_path):
    segments = transcriber.transcribe(str(tmp_path / "source.mp3"), str(tmp_path / "cache"))
    assert [(s.start, s.end, s.text) for s in segments] == [
        (1190.0, 1198.0, "left"),
        (1201.0, 1205.0, "right"),
    ]


def test_valid_cache_skips_extract_and_model(transcriber, chunker, tmp_path):
    audio = str(tmp_path / "source.mp3")
    cache = str(tmp_path / "cache")
    first = transcriber.transcribe(audio, cache)
    second = transcriber.transcribe(audio, cache)
    assert second == first
    assert chunker.extract_calls == 2  # one per planned chunk, not four


def test_corrupt_cache_is_rebuilt_without_losing_other_chunks(transcriber, chunker, tmp_path):
    audio = str(tmp_path / "source.mp3")
    cache = tmp_path / "cache"
    transcriber.transcribe(audio, str(cache))
    (cache / "chunk_000002.json").write_text("broken", encoding="utf-8")
    transcriber.transcribe(audio, str(cache))
    assert chunker.extract_calls == [1, 2, 2]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n cui_ting python -m pytest tests/test_transcriber.py -v`

Expected: FAIL because the existing constructor accepts only a model path and imports `mlx_whisper`.

- [ ] **Step 3: Implement lazy faster-whisper and deterministic cache identity**

Remove the top-level `mlx_whisper` import. Import `WhisperModel` inside the default model factory or `_get_model()` so unit tests do not require a downloaded model. Cache identity must include schema version 1, resolved source path, source size, `st_mtime_ns`, model, compute type, chunk/context seconds, and VAD setting. Use `hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()` as the cache key.

For each `AudioChunk`, write `chunk_000001.json` with identity, interval metadata, and segment dictionaries. Write to `.tmp`, flush, `os.fsync`, then `os.replace`. On cache load, validate every required field and rebuild only the invalid chunk.

Call:

```python
generated, _ = self._get_model().transcribe(
    str(temp_wav),
    beam_size=5,
    vad_filter=self.config.vad_filter,
)
for item in generated:
    start = chunk.extract_start + float(item.start)
    end = chunk.extract_start + float(item.end)
    midpoint = (start + end) / 2
    belongs = chunk.core_start <= midpoint < chunk.core_end
    if chunk.core_end == duration:
        belongs = chunk.core_start <= midpoint <= chunk.core_end
    if belongs and item.text.strip():
        kept.append(TimestampedSegment(start, end, item.text.strip()))
```

Always delete the current temporary WAV in `finally`. Sort the combined result by `(start, end)`.

- [ ] **Step 4: Run focused and regression tests**

Run:

```powershell
conda run -n cui_ting python -m pytest tests/test_transcriber.py -v
conda run -n cui_ting python -m pytest tests/test_audio_chunker.py tests/test_config.py -v
```

Expected: all tests PASS and no import of `mlx_whisper` remains (`rg "mlx_whisper|mlx-whisper" core tests` returns no matches).

- [ ] **Step 5: Commit**

```powershell
git add core/transcriber.py tests/test_transcriber.py
git commit -m "feat: add resumable faster-whisper transcription"
```

---

### Task 5: Preserve Timestamps and Share the Heavy Model in the Pipeline

**Files:**
- Modify: `core/summarizer.py`
- Create: `tests/test_summarizer.py`

**Interfaces:**
- Consumes: optional injected `transcriber`, `llm_processor`, `text_processor`, downloader, and subtitle downloader.
- Produces: atomic `source_raw.md` containing `RAW_HEADER + segments_to_anchored_text(segments)`.
- Produces: one shared `Transcriber` usable by summarizers with different cookies.

- [ ] **Step 1: Write failing pipeline tests**

Test these behaviors with real temporary files and small fakes:

```python
def test_raw_markdown_keeps_global_timestamps(tmp_path, summarizer):
    summarizer.transcriber.segments = [TimestampedSegment(61, 63, "hello")]
    result = summarizer._acquire_text("url", "source.mp3", str(tmp_path), "id", "source")
    assert result[0].start == 61
    assert (tmp_path / "source_raw.md").read_text(encoding="utf-8") == (
        "# 原始转录文本\n\n[00:01:01] hello"
    )


def test_existing_timestamped_raw_skips_transcriber(tmp_path, summarizer):
    (tmp_path / "source_raw.md").write_text(
        "# 原始转录文本\n\n[00:01:01] cached", encoding="utf-8")
    segments = summarizer._acquire_text("url", "source.mp3", str(tmp_path), "id", "source")
    assert segments[0].start == 61
    assert summarizer.transcriber.calls == []


def test_two_cookie_summarizers_use_same_injected_transcriber(shared_transcriber, config_path):
    first = VideoSummarizer(config_path=str(config_path), cookies_file="bili.txt",
                            transcriber=shared_transcriber)
    second = VideoSummarizer(config_path=str(config_path), cookies_file="youtube.txt",
                             transcriber=shared_transcriber)
    assert first.transcriber is shared_transcriber
    assert second.transcriber is shared_transcriber
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n cui_ting python -m pytest tests/test_summarizer.py -v`

Expected: FAIL because dependencies cannot be injected and raw output discards timestamps.

- [ ] **Step 3: Implement injection and atomic Markdown**

Extend `VideoSummarizer.__init__` with keyword-only optional dependencies. Default to production objects, but use the injected transcriber unchanged. Pass the stable directory `Path(output_dir) / ".transcription_cache" / part_basename` into `transcribe`.

Add a module-level helper:

```python
def _atomic_write_text(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, target)
```

Use it for raw and refined files. Save raw with `segments_to_anchored_text`; preserve the existing plain-text fallback parser for old caches.

- [ ] **Step 4: Run pipeline and timestamp regression tests**

Run: `conda run -n cui_ting python -m pytest tests/test_summarizer.py tests/test_transcriber.py tests/test_config.py -v`

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/summarizer.py tests/test_summarizer.py
git commit -m "feat: preserve timestamps across resumable pipeline"
```

---

### Task 6: Configure and Test the 128k LiteLLM Cleanup

**Files:**
- Modify: `core/llm_processor.py`
- Modify: `core/summarizer.py`
- Create: `tests/test_llm_processor.py`

**Interfaces:**
- Produces: `LLMProcessor(config, max_tokens=128000, client_factory=None)`.
- Calls: model `example-model` through environment-derived configuration and `max_tokens=128000`.

- [ ] **Step 1: Write failing request-shape and filtering tests**

```python
def test_sends_configured_model_and_max_tokens(model_config, fake_client):
    processor = LLMProcessor({"nanyan": model_config}, max_tokens=128000,
                             client_factory=lambda **kwargs: fake_client)
    result = processor.structured_refine("input", "nanyan")
    request = fake_client.chat.completions.requests[0]
    assert request["model"] == "example-model"
    assert request["max_tokens"] == 128000
    assert request["messages"][0]["content"].endswith("input")
    assert result == "clean"


def test_removes_thinking_blocks(model_config, fake_client):
    fake_client.response = "<think>secret reasoning</think>clean"
    processor = LLMProcessor({"nanyan": model_config}, max_tokens=128000,
                             client_factory=lambda **kwargs: fake_client)
    assert processor.structured_refine("input", "nanyan") == "clean"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n cui_ting python -m pytest tests/test_llm_processor.py -v`

Expected: FAIL because max tokens are hard-coded to 8192 and client construction is not injectable.

- [ ] **Step 3: Implement the minimal configurable client**

Store `max_tokens` and `client_factory` in `__init__`; make `_get_client` call the factory with the same safe `api_key`, `base_url`, and optional `http_client` arguments as production. Replace `max_tokens=8192` with `max_tokens=self.max_tokens`. Pass `app_config.llm_max_tokens` from `VideoSummarizer`.

Create/update the ignored local `.env` without displaying it. It must contain `NANYAN_API_KEY` with the user-provided secret, `NANYAN_BASE_URL=https://your-openai-compatible-endpoint.example/v1`, and `NANYAN_MODEL=example-model`. Verify only key presence and non-secret URL/model values.

- [ ] **Step 4: Run tests and a no-request configuration smoke test**

Run:

```powershell
conda run -n cui_ting python -m pytest tests/test_llm_processor.py tests/test_summarizer.py -v
conda run -n cui_ting python -c "from core.config import ConfigManager; c=ConfigManager('config.yaml').get_app_config(); assert c.models['nanyan'].model == 'example-model'; print('LLM config ok')"
```

Expected: tests PASS and `LLM config ok`; no network request is sent.

- [ ] **Step 5: Commit only non-secret files**

```powershell
git status --short
git add core/llm_processor.py core/summarizer.py tests/test_llm_processor.py
git commit -m "feat: configure LiteLLM transcript cleanup"
```

Expected: `.env` is absent from staged and committed files.

---

### Task 7: Make Batch CLI Windows-Safe and Script-Friendly

**Files:**
- Modify: `cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Produces: `sanitize_folder_name(name: str) -> str`.
- Produces: `validate_batch_tasks(tasks: object, output_dir: Path) -> list[tuple[str, str]]`.
- Produces: `run_batch(config_path: str, summarizer_factory=VideoSummarizer) -> BatchSummary` and `main(argv=None) -> int`.
- CLI process exits 0 only when the batch is valid and every task succeeds or is already complete.

- [ ] **Step 1: Write failing Windows name, cookie, isolation, and exit-code tests**

```python
@pytest.mark.parametrize(("raw", "safe"), [
    ("a:b?c", "a_b_c"), ("name. ", "name"), ("CON", "_CON"), ("..", "unnamed"),
])
def test_sanitize_folder_name(raw, safe):
    assert sanitize_folder_name(raw) == safe


def test_detect_cookie_uses_project_cookie_files(project_root):
    assert detect_cookie("https://www.bilibili.com/video/BV1x", project_root).name == "bili_cookies.txt"
    assert detect_cookie("https://youtu.be/abcdefghijk", project_root).name == "youtube_cookies.txt"


def test_batch_continues_after_one_failure_and_returns_nonzero(fake_factory, config_path):
    summary = run_batch(str(config_path), summarizer_factory=fake_factory)
    assert summary.succeeded == ["ok"]
    assert summary.failed == ["bad"]
    assert summary.exit_code == 1


def test_rejects_names_that_collide_after_sanitizing(tmp_path):
    with pytest.raises(ValueError, match="目录名冲突"):
        validate_batch_tasks({"a:b": "url1", "a?b": "url2"}, tmp_path)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n cui_ting python -m pytest tests/test_cli.py -v`

Expected: FAIL because the functions and structured summary do not exist.

- [ ] **Step 3: Refactor CLI around a testable return value**

Use `argparse` with `--config` defaulting to the project `config.yaml`. Define `BatchSummary` with `succeeded`, `skipped`, `failed`, and an `exit_code` property. Validate that input JSON is an object of nonempty string names and HTTP(S) URL strings.

Create one `Transcriber(app_config.whisper)` before the task loop. Cache lightweight `VideoSummarizer` objects by cookie path, but inject that same transcriber into each. A task counts as skipped when all expected final outputs already exist before `process`; otherwise it counts as succeeded. Catch `Exception` per task, log the task name and safe exception, append to failed, and continue.

At module bottom use `raise SystemExit(main())` so PowerShell and schedulers receive the result.

- [ ] **Step 4: Run CLI tests and full unit suite**

Run: `conda run -n cui_ting python -m pytest tests -v -m "not e2e"`

Expected: all unit/integration tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add cli.py tests/test_cli.py
git commit -m "feat: harden Windows batch CLI"
```

---

### Task 8: Split Runtime Dependencies and Write Windows CLI Documentation

**Files:**
- Modify: `requirements.txt`
- Create: `requirements-dev.txt`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Produces: reproducible CLI install in `cui_ting` without MLX or Web packages.

- [ ] **Step 1: Add a dependency-policy test and verify it fails**

Add to `tests/test_cli.py`:

```python
def test_runtime_requirements_are_windows_cli_only():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()
    assert "faster-whisper" in requirements
    for unsupported in ("mlx-whisper", "fastapi", "uvicorn", "sqlalchemy"):
        assert unsupported not in requirements
```

Run: `conda run -n cui_ting python -m pytest tests/test_cli.py::test_runtime_requirements_are_windows_cli_only -v`

Expected: FAIL because the current requirements contain MLX and Web dependencies.

- [ ] **Step 2: Replace dependencies and install them**

Set `requirements.txt` to the CLI packages: `yt-dlp`, `openai`, `httpx`, `PyYAML`, `faster-whisper`, `webvtt-py`, and `python-dotenv`, with compatible lower bounds. Set `requirements-dev.txt` to `-r requirements.txt` plus `pytest>=8.0`.

Run:

```powershell
conda run -n cui_ting python -m pip install -r requirements-dev.txt
conda run -n cui_ting python -m pip check
```

Expected: installation and `pip check` exit 0.

- [ ] **Step 3: Update ignores and rewrite README**

Ignore `.transcription_cache/`, `test_case/`, and temporary `*.wav` while retaining existing secret/audio ignores. README must document:

- Windows 11, Conda, Python 3.11, FFmpeg/FFprobe, and Visual C++ Runtime prerequisites.
- Exact `cui_ting` creation/install commands.
- `.env` variable names without the secret.
- `D:\models`, medium CPU INT8, 20-minute core/15-second context behavior.
- `input_data.json`, cookie names, `conda run -n cui_ting python cli.py`, outputs, exit codes, cache recovery, and troubleshooting.
- Explicit statement that方式 A/B source remains but is unsupported on this Windows delivery.

- [ ] **Step 4: Verify docs commands and imports**

Run:

```powershell
conda run -n cui_ting python -m pytest tests -v -m "not e2e"
conda run -n cui_ting python -c "import yt_dlp, faster_whisper, openai, yaml, webvtt; import cli; print('imports ok')"
rg -n "brew install|mlx-whisper|方式 A：|方式 B：" README.md requirements.txt
```

Expected: tests PASS, `imports ok`, and `rg` returns no obsolete supported instructions.

- [ ] **Step 5: Commit**

```powershell
git add requirements.txt requirements-dev.txt .gitignore README.md tests/test_cli.py
git commit -m "docs: add supported Windows CLI setup"
```

---

### Task 9: Verify the Real Model Download and Synthetic Long-Boundary Path

**Files:**
- No production file expected; add regression tests if a failure is found.

**Interfaces:**
- Verifies: `medium` downloads beneath `D:\models`, real CTranslate2 CPU INT8 construction works, and real FFmpeg output reaches faster-whisper.

- [ ] **Step 1: Run preflight**

```powershell
conda run -n cui_ting python --version
ffmpeg -version
ffprobe -version
conda run -n cui_ting python -m pip check
```

Expected: Python 3.11.x and all commands exit 0.

- [ ] **Step 2: Trigger the permitted first model download**

Run a script that constructs `WhisperModel("medium", device="cpu", compute_type="int8", download_root="D:/models")` and prints only `model ready`.

Expected: `model ready`; `D:\models` contains the downloaded CTranslate2 model and the console contains no API key.

- [ ] **Step 3: Generate a speech fixture straddling a shortened test boundary**

Use Windows SAPI or a checked-in-free PowerShell speech synthesis command to create approximately 70 seconds of spoken numbered sentences, then use a test-only `AudioChunker(30, 5)` and real `Transcriber` configuration to force three chunks. Do not change production defaults.

Expected: at least one segment on each side of 30 and 60 seconds, monotonically increasing global timestamps, no identical adjacent segment, and no temporary WAV remaining.

- [ ] **Step 4: Apply systematic debugging if needed**

On any failure, invoke `superpowers:systematic-debugging`, capture the smallest safe reproduction, add a failing automated test, verify RED, make the minimal fix, verify GREEN, then rerun Steps 1–3. Repeat until clean.

- [ ] **Step 5: Commit only actual regression changes**

If no bug is found, make no commit. If fixed, use a commit message that names the verified root cause, without adding generated audio or model files.

---

### Task 10: Select and Record Four Live Acceptance Videos

**Files:**
- Create: `tests/e2e_videos.json`

**Interfaces:**
- Produces: exactly four entries with `name`, `platform`, `url`, `duration_seconds`, and `bucket`.

- [ ] **Step 1: Probe the explicit candidate set with yt-dlp and the platform cookies**

Probe, without downloading media:

```text
5m candidate:  https://www.youtube.com/watch?v=nWwpyclIEu4
30m candidate: https://www.bilibili.com/video/BV1vj421o7Ui/?p=2
1h candidate:  https://www.youtube.com/watch?v=zjkBMFhNj_g
2h candidate:  https://www.bilibili.com/video/BV1SFf2YiEtR/?p=2
```

For YouTube candidates run `conda run -n cui_ting yt-dlp --skip-download --dump-single-json --cookies cookie/youtube_cookies.txt URL`; for Bilibili candidates use the identical command with `cookie/bili_cookies.txt`. Substitute each of the four literal candidate URLs listed immediately above and parse `_type`, `duration`, `acodec`, and `webpage_url` without printing cookie contents.

Expected: a single selected item per URL, a real audio codec, and durations within 180–600, 1200–2400, 2700–4500, and 6000–8400 seconds respectively. The known 1h candidate is expected near 3,588 seconds; Bilibili `?p=` must resolve only the selected part.

- [ ] **Step 2: Replace any invalid candidate deterministically**

If a candidate is unavailable or outside its range, use yt-dlp search/platform search to collect three same-platform spoken-content alternatives, probe all three, and choose the first public single-video result in the required interval. Record only the final URL, not failed candidates, in the manifest.

- [ ] **Step 3: Write and validate the manifest**

The JSON must contain exactly four objects and both platforms. Add a pytest validation that asserts unique URL/name, bucket set `{ "5m", "30m", "1h", "2h" }`, platform set `{ "youtube", "bilibili" }`, and duration within the declared interval.

- [ ] **Step 4: Run validation and commit**

Run: `conda run -n cui_ting python -m pytest tests/test_cli.py -v -k e2e_manifest`

Expected: PASS.

```powershell
git add tests/e2e_videos.json tests/test_cli.py
git commit -m "test: add four-duration video acceptance matrix"
```

---

### Task 11: Run the Four Full Download → Whisper → LLM Acceptances

**Files:**
- Runtime only: ignored `test_case/e2e-*` outputs and logs with credentials redacted.
- Modify production/tests only when a verified defect requires a regression fix.

**Interfaces:**
- Verifies: both cookie routes, all four duration buckets, multiple long-audio chunks, `medium` CPU INT8, global timestamps, LLM cleanup, stage cache, and chunk cache.

- [ ] **Step 1: Create an isolated E2E config and input from the manifest**

Create ignored `.e2e/config.yaml` with `subtitle_first: false`, `enable_refine: true`, `input_file: input_data.json`, and `output_dir: ../test_case/e2e`. Create `.e2e/input_data.json` by converting the four manifest entries to the CLI name-to-URL JSON form. Keep production chunking at 1,200/15 seconds and model `medium`; do not shorten media.

- [ ] **Step 2: Run the full batch in `cui_ting`**

Run: `conda run -n cui_ting python cli.py --config .e2e/config.yaml`

Expected: exit code 0; all four tasks contain nonempty `source_raw.md` and `source_refined.md`. The 30m, 1h, and 2h tasks have at least 2, 3, and 6 valid chunk cache JSON files respectively.

- [ ] **Step 3: Validate output invariants programmatically**

Parse every raw timestamp and assert nondecreasing values within probed duration plus a small decoder tolerance; assert no identical adjacent anchored line around each 1,200-second boundary. Assert refined output is nonempty and does not include `<think>`/`<thinking>` tags, authorization headers, or prompt boilerplate.

- [ ] **Step 4: Verify stage-level rerun**

Record modification times of audio, raw, refined, and chunk JSON files; rerun the same CLI command.

Expected: exit code 0, tasks reported skipped/cached, and modification times unchanged.

- [ ] **Step 5: Verify single-chunk recovery in an isolated copy**

Copy the 30m output to an ignored recovery directory, remove its aggregate raw/refined files and one chunk JSON, then run the corresponding task against that directory while instrumenting logs.

Expected: all intact chunks are cache hits, exactly the deleted chunk is re-extracted/transcribed, and aggregate raw/refined outputs are regenerated.

- [ ] **Step 6: Loop on failures with evidence-first debugging**

For every failure: invoke `superpowers:systematic-debugging`; preserve the failing command, safe stderr, task/bucket, and cache state; identify the root cause; write a minimal failing regression test and confirm RED; implement the smallest fix; confirm GREEN; rerun the failed bucket. If the fix touches shared download, chunk, timestamp, cache, LLM, or CLI code, rerun all four buckets. Continue until every Step 2–5 assertion passes.

- [ ] **Step 7: Commit only source/test/doc fixes**

Never commit E2E outputs or logs. Commit each verified bug fix separately with its regression test.

---

### Task 12: Final Verification and Review

**Files:**
- Review all changed files; no new file required.

- [ ] **Step 1: Invoke verification-before-completion and run the complete suite**

Required sub-skill: `superpowers:verification-before-completion`.

```powershell
conda run -n cui_ting python -m pytest tests -v
conda run -n cui_ting python -m pip check
conda run -n cui_ting python -c "import cli; from core.transcriber import Transcriber; print('final imports ok')"
git diff --check
git status --short
```

Expected: all tests PASS, `pip check` exits 0, imports succeed, no whitespace errors, and only intentional files are changed.

- [ ] **Step 2: Verify forbidden and sensitive content is absent**

Run searches for `mlx_whisper`, `mlx-whisper`, Mac absolute paths, the literal API key, `Authorization: Bearer`, and Cookie file contents across tracked files and staged diff. Do not print matched secret text; report only file names/counts if a sensitive match is found.

Expected: no tracked/staged sensitive match and no MLX/Mac runtime dependency.

- [ ] **Step 3: Request code review**

Required sub-skill: `superpowers:requesting-code-review`. Review against the design spec and this plan, especially cache invalidation, overlap ownership, one-model invariant, batch failure behavior, and E2E evidence. Fix every confirmed issue with TDD and rerun relevant verification.

- [ ] **Step 4: Record final evidence**

Report Conda/Python version, model/cache path, unit test count, the four final URLs and probed durations, per-video output paths, chunk counts, initial/rerun/recovery outcomes, and any bugs fixed. Do not include credentials or cookie content.

- [ ] **Step 5: Commit remaining intentional changes**

Run `git status --short`. Skip an aggregate commit when all reviewed work is already committed task-by-task; otherwise stage only the explicitly reviewed source, test, configuration, dependency, and documentation paths listed in the File Map, then commit with `feat: support Windows CLI long-audio transcription`.
