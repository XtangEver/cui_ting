from pathlib import Path

import pytest

import core.summarizer as summarizer_module
from core.downloader import publish_download_manifest
from core.summarizer import RAW_HEADER, REFINED_HEADER, VideoSummarizer
from core.timestamp_utils import TimestampedSegment


class FakeTranscriber:
    def __init__(self, segments=None):
        self.segments = segments or []
        self.calls = []

    def transcribe(self, audio_path, cache_dir):
        self.calls.append((audio_path, cache_dir))
        return self.segments


class FakeDownloader:
    pass


class FakeSubtitleDownloader:
    def __init__(self, segments=None):
        self.segments = segments
        self.calls = []

    def download_subtitles(self, url, output_dir):
        self.calls.append((url, output_dir))
        return self.segments


class FakeLLMProcessor:
    def structured_refine(self, text, model_name):
        return f"refined {text}"


class FakeTextProcessor:
    def split_segments(self, segments):
        return [segments[0].text]

    def merge_results(self, results):
        return "\n".join(results)


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        """
models: []
whisper:
  model: medium
settings:
  subtitle_first: false
  enable_refine: false
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def shared_transcriber():
    return FakeTranscriber()


@pytest.fixture
def summarizer(config_path):
    return VideoSummarizer(
        config_path=str(config_path),
        transcriber=FakeTranscriber(),
        llm_processor=FakeLLMProcessor(),
        text_processor=FakeTextProcessor(),
        downloader=FakeDownloader(),
        subtitle_downloader=FakeSubtitleDownloader(),
    )


def test_raw_markdown_keeps_global_timestamps(tmp_path, summarizer):
    summarizer.transcriber.segments = [TimestampedSegment(61, 63, "hello")]

    result = summarizer._acquire_text(
        "url", "source.mp3", str(tmp_path), "id", "source"
    )

    assert result[0].start == 61
    assert (tmp_path / "source_raw.md").read_text(encoding="utf-8") == (
        "# 原始转录文本\n\n[00:01:01] hello"
    )
    assert summarizer.transcriber.calls == [
        (
            "source.mp3",
            str(tmp_path / ".transcription_cache" / "source"),
        )
    ]
    assert not (tmp_path / "source_raw.md.tmp").exists()


def test_process_without_refinement_does_not_require_a_model(tmp_path, config_path):
    class ProcessDownloader:
        def extract_video_id(self, url):
            return "video-id"

        def download_and_merge(self, url, output_dir, progress_callback=None):
            audio_path = Path(output_dir) / "source.mp3"
            audio_path.write_bytes(b"audio")
            return "title", "video-id", [str(audio_path)]

    class RejectingLLMProcessor:
        def structured_refine(self, text, model_name):
            raise AssertionError("LLM refinement must stay disabled")

    transcriber = FakeTranscriber([TimestampedSegment(0, 1, "transcribed")])
    summarizer = VideoSummarizer(
        config_path=str(config_path),
        transcriber=transcriber,
        llm_processor=RejectingLLMProcessor(),
        text_processor=FakeTextProcessor(),
        downloader=ProcessDownloader(),
        subtitle_downloader=FakeSubtitleDownloader(),
    )
    output_dir = tmp_path / "output"

    result = summarizer.process(
        "https://example.com/video", model_name=None, output_dir=str(output_dir)
    )

    assert result["video_id"] == "video-id"
    assert result["results"][0]["refined_file"] is None
    assert (output_dir / "source_raw.md").read_text(encoding="utf-8") == (
        f"{RAW_HEADER}[00:00:00] transcribed"
    )


def test_existing_timestamped_raw_skips_transcriber(tmp_path, summarizer):
    (tmp_path / "source_raw.md").write_text(
        "# 原始转录文本\n\n[00:01:01] cached", encoding="utf-8"
    )

    segments = summarizer._acquire_text(
        "url", "source.mp3", str(tmp_path), "id", "source"
    )

    assert segments[0].start == 61
    assert summarizer.transcriber.calls == []


def test_malformed_plain_text_raw_is_rebuilt(tmp_path, summarizer):
    (tmp_path / "source_raw.md").write_text(
        f"{RAW_HEADER}first line\nsecond line", encoding="utf-8"
    )
    summarizer.transcriber.segments = [TimestampedSegment(5, 6, "rebuilt")]

    segments = summarizer._acquire_text(
        "url", "source.mp3", str(tmp_path), "id", "source"
    )

    assert [(item.start, item.end, item.text) for item in segments] == [
        (5, 6, "rebuilt"),
    ]
    assert summarizer.transcriber.calls
    assert (tmp_path / "source_raw.md").read_text(encoding="utf-8") == (
        f"{RAW_HEADER}[00:00:05] rebuilt"
    )


def test_two_cookie_summarizers_use_same_injected_transcriber(
    shared_transcriber, config_path
):
    dependencies = {
        "llm_processor": FakeLLMProcessor(),
        "text_processor": FakeTextProcessor(),
        "downloader": FakeDownloader(),
        "subtitle_downloader": FakeSubtitleDownloader(),
    }
    first = VideoSummarizer(
        config_path=str(config_path),
        cookies_file="bili.txt",
        transcriber=shared_transcriber,
        **dependencies,
    )
    second = VideoSummarizer(
        config_path=str(config_path),
        cookies_file="youtube.txt",
        transcriber=shared_transcriber,
        **dependencies,
    )

    assert first.transcriber is shared_transcriber
    assert second.transcriber is shared_transcriber


def test_default_llm_processor_uses_configured_max_tokens(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
models: []
whisper:
  model: medium
llm:
  max_tokens: 4242
settings:
  subtitle_first: false
  enable_refine: false
""",
        encoding="utf-8",
    )
    calls = []

    class RecordingLLMProcessor:
        def __init__(self, models, max_tokens):
            calls.append((models, max_tokens))

    monkeypatch.setattr(
        "core.llm_processor.LLMProcessor", RecordingLLMProcessor
    )

    VideoSummarizer(
        config_path=str(config_path),
        transcriber=FakeTranscriber(),
        text_processor=FakeTextProcessor(),
        downloader=FakeDownloader(),
        subtitle_downloader=FakeSubtitleDownloader(),
    )

    assert calls == [({}, 4242)]


def test_refined_markdown_is_written_atomically(tmp_path, summarizer):
    path = summarizer._refine(
        [TimestampedSegment(0, 1, "hello")],
        str(tmp_path),
        "id",
        "source",
        "model",
    )

    assert Path(path).read_text(encoding="utf-8") == (
        f"{REFINED_HEADER}refined hello"
    )
    assert not (tmp_path / "source_refined.md.tmp").exists()


def test_header_only_refined_cache_is_rebuilt(tmp_path, summarizer):
    refined = tmp_path / "source_refined.md"
    refined.write_text(REFINED_HEADER, encoding="utf-8")

    path = summarizer._refine(
        [TimestampedSegment(0, 1, "hello")],
        str(tmp_path),
        "id",
        "source",
        "model",
    )

    assert Path(path).read_text(encoding="utf-8") == f"{REFINED_HEADER}refined hello"


def test_atomic_write_removes_temp_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "result.md"

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(summarizer_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        summarizer_module._atomic_write_text(str(target), "content")

    assert not (tmp_path / "result.md.tmp").exists()


def test_process_rejects_empty_download_result(tmp_path, config_path):
    class EmptyDownloader:
        def extract_video_id(self, url):
            return "video-id"

        def download_and_merge(self, url, output_dir, progress_callback=None):
            return "", "video-id", []

    summarizer = VideoSummarizer(
        config_path=str(config_path),
        transcriber=FakeTranscriber(),
        llm_processor=FakeLLMProcessor(),
        text_processor=FakeTextProcessor(),
        downloader=EmptyDownloader(),
        subtitle_downloader=FakeSubtitleDownloader(),
    )

    with pytest.raises(RuntimeError, match="未生成有效音频"):
        summarizer.process("https://example.com/video", output_dir=str(tmp_path / "out"))


def test_process_redownloads_when_only_partial_merge_output_remains(
    tmp_path, config_path
):
    url = "https://example.com/playlist"
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    residual = output_dir / "source_part1.mp3"
    residual.write_bytes(b"interrupted first batch")

    class CompletingDownloader:
        def __init__(self):
            self.calls = 0

        def extract_video_id(self, requested_url):
            return "video-id"

        def download_and_merge(self, requested_url, output_dir, progress_callback=None):
            self.calls += 1
            first = Path(output_dir) / "source_part1.mp3"
            second = Path(output_dir) / "source_part2.mp3"
            first.write_bytes(b"complete first batch")
            second.write_bytes(b"complete second batch")
            return str(first), "video-id", [str(first), str(second)]

    downloader = CompletingDownloader()
    summarizer = VideoSummarizer(
        config_path=str(config_path),
        transcriber=FakeTranscriber([TimestampedSegment(0, 1, "transcribed")]),
        llm_processor=FakeLLMProcessor(),
        text_processor=FakeTextProcessor(),
        downloader=downloader,
        subtitle_downloader=FakeSubtitleDownloader(),
    )

    result = summarizer.process(url, output_dir=str(output_dir))

    assert downloader.calls == 1
    assert len(result["results"]) == 2


def test_process_reuses_only_complete_url_matching_download_manifest(
    tmp_path, config_path
):
    url = "https://example.com/video"
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    audio = output_dir / "source.mp3"
    audio.write_bytes(b"complete audio")
    publish_download_manifest(output_dir, url, [str(audio)])

    class RejectingDownloader:
        def extract_video_id(self, requested_url):
            return "video-id"

        def download_and_merge(self, *args, **kwargs):
            raise AssertionError("valid completed download must be reused")

    summarizer = VideoSummarizer(
        config_path=str(config_path),
        transcriber=FakeTranscriber([TimestampedSegment(0, 1, "transcribed")]),
        llm_processor=FakeLLMProcessor(),
        text_processor=FakeTextProcessor(),
        downloader=RejectingDownloader(),
        subtitle_downloader=FakeSubtitleDownloader(),
    )

    result = summarizer.process(url, output_dir=str(output_dir))

    assert [item["audio_path"] for item in result["results"]] == [str(audio.resolve())]


def test_raw_cache_accepts_hundred_hour_timestamp(tmp_path):
    raw = tmp_path / "source_raw.md"
    raw.write_text(f"{RAW_HEADER}[100:00:00] long recording", encoding="utf-8")

    segments = summarizer_module.load_valid_raw_segments(raw)

    assert segments is not None
    assert [(segment.start, segment.text) for segment in segments] == [
        (100 * 3600, "long recording"),
    ]


def test_raw_cache_rejects_decreasing_segment_starts(tmp_path):
    raw = tmp_path / "source_raw.md"
    raw.write_text(
        f"{RAW_HEADER}[00:00:10] later\n[00:00:09] earlier",
        encoding="utf-8",
    )

    assert summarizer_module.load_valid_raw_segments(raw) is None


@pytest.mark.parametrize("timestamp", ["100:60:00", "100:00:60"])
def test_raw_cache_rejects_out_of_range_minutes_and_seconds(tmp_path, timestamp):
    raw = tmp_path / "source_raw.md"
    raw.write_text(f"{RAW_HEADER}[{timestamp}] invalid", encoding="utf-8")

    assert summarizer_module.load_valid_raw_segments(raw) is None


@pytest.mark.parametrize(
    "body",
    [
        "<think>private reasoning</think>clean result",
        '<THINKING data-kind="hidden">private reasoning</THINKING>clean result',
        "请对以下原始文本进行一次性精炼处理，输出干净文本",
    ],
)
def test_refined_cache_rejects_llm_artifacts(tmp_path, body):
    refined = tmp_path / "source_refined.md"
    refined.write_text(f"{REFINED_HEADER}{body}", encoding="utf-8")

    assert not summarizer_module.is_valid_refined_file(refined)


def test_refined_cache_allows_normal_body_that_mentions_thinking(tmp_path):
    refined = tmp_path / "source_refined.md"
    refined.write_text(
        f"{REFINED_HEADER}正文讨论 thinking 模型与思考方法。", encoding="utf-8"
    )

    assert summarizer_module.is_valid_refined_file(refined)
