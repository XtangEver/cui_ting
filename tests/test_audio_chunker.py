from pathlib import Path
import shutil
import subprocess
import wave

import pytest

from core.audio_chunker import AudioChunk, AudioChunker


def test_short_audio_has_one_clipped_chunk():
    chunks = AudioChunker(1200, 15).plan(300)
    assert [
        (c.core_start, c.core_end, c.extract_start, c.extract_end) for c in chunks
    ] == [(0, 300, 0, 300)]


def test_long_audio_has_context_but_nonoverlapping_ownership():
    chunks = AudioChunker(1200, 15).plan(2500)
    assert [(c.core_start, c.core_end) for c in chunks] == [
        (0, 1200),
        (1200, 2400),
        (2400, 2500),
    ]
    assert [(c.extract_start, c.extract_end) for c in chunks] == [
        (0, 1215),
        (1185, 2415),
        (2385, 2500),
    ]


def test_probe_rejects_invalid_duration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "bad", ""),
    )
    with pytest.raises(RuntimeError, match="FFprobe"):
        AudioChunker(1200, 15).probe_duration(tmp_path / "source.mp3")


def test_probe_failure_includes_bounded_stderr(monkeypatch, tmp_path):
    stderr = "discard-me-" + ("x" * 2500) + "tail-diagnostic"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", stderr),
    )

    with pytest.raises(RuntimeError) as caught:
        AudioChunker(1200, 15).probe_duration(tmp_path / "source.mp3")

    message = str(caught.value)
    assert "tail-diagnostic" in message
    assert "discard-me" not in message
    assert len(message) < 2300


@pytest.mark.parametrize("chunk_seconds,context_seconds", [(0, 0), (30, -1)])
def test_rejects_chunk_settings_that_break_planning(
    chunk_seconds, context_seconds
):
    with pytest.raises(ValueError):
        AudioChunker(chunk_seconds, context_seconds)


@pytest.mark.parametrize("duration", [float("nan"), float("inf")])
def test_plan_rejects_nonfinite_duration(duration):
    with pytest.raises(ValueError, match="positive"):
        AudioChunker(1200, 15).plan(duration)


def test_probe_rejects_nonfinite_duration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "nan", ""),
    )
    with pytest.raises(RuntimeError, match="FFprobe"):
        AudioChunker(1200, 15).probe_duration(tmp_path / "source.mp3")


def test_probe_wraps_tool_timeout(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="FFprobe"):
        AudioChunker(1200, 15).probe_duration(tmp_path / "source.mp3")


def test_extract_wraps_tool_launch_error(monkeypatch, tmp_path):
    def missing_tool(*args, **kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(subprocess, "run", missing_tool)
    chunk = AudioChunk(1, 0, 3, 0, 3)
    with pytest.raises(RuntimeError, match="FFmpeg"):
        AudioChunker(1200, 15).extract(
            tmp_path / "source.wav", chunk, tmp_path / "chunk.wav"
        )


def test_extract_wraps_tool_timeout(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    chunk = AudioChunk(1, 0, 3, 0, 3)
    with pytest.raises(RuntimeError, match="FFmpeg"):
        AudioChunker(1200, 15).extract(
            tmp_path / "source.wav", chunk, tmp_path / "chunk.wav"
        )


def test_validate_tools_reports_missing_tool(monkeypatch):
    monkeypatch.setattr(
        shutil,
        "which",
        lambda tool: None if tool == "ffprobe" else tool,
    )
    with pytest.raises(RuntimeError, match="ffprobe"):
        AudioChunker(1200, 15).validate_tools()


def test_extract_requests_explicit_normalized_wav(monkeypatch, tmp_path):
    output_path = tmp_path / "chunk.audio"
    captured_command = []

    def successful_extract(command, **kwargs):
        captured_command.extend(command)
        output_path.write_bytes(b"audio")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", successful_extract)
    AudioChunker(1200, 15).extract(
        tmp_path / "source.wav",
        AudioChunk(1, 0, 3, 0, 3),
        output_path,
    )

    assert captured_command[captured_command.index("-ac") + 1] == "1"
    assert captured_command[captured_command.index("-ar") + 1] == "16000"
    assert captured_command[captured_command.index("-c:a") + 1] == "pcm_s16le"
    assert captured_command[captured_command.index("-f") + 1] == "wav"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="FFmpeg is not available on PATH",
)
def test_real_ffmpeg_probe_and_extract(tmp_path):
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "chunk.audio"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s32le",
            "-y",
            str(source_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    chunker = AudioChunker(1200, 15)
    duration = chunker.probe_duration(source_path)
    assert duration == pytest.approx(3.0, abs=0.1)

    chunker.extract(source_path, chunker.plan(duration)[0], output_path)
    assert output_path.is_file()
    assert output_path.stat().st_size > 0
    with wave.open(str(output_path), "rb") as extracted:
        assert extracted.getnchannels() == 1
        assert extracted.getframerate() == 16000
        assert extracted.getsampwidth() == 2
        assert extracted.getcomptype() == "NONE"
