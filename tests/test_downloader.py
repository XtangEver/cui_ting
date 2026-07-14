from pathlib import Path

import pytest

import core.downloader as downloader_module
from core.downloader import AudioDownloader


def test_playlist_aborts_when_any_part_download_fails(tmp_path, monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def download(self, urls):
            if urls == ["part-2"]:
                raise RuntimeError("download failed")
            output = Path(self.options["outtmpl"].replace("%(ext)s", "m4a"))
            output.write_bytes(b"audio")

    downloader = AudioDownloader()
    monkeypatch.setattr(downloader_module.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(downloader, "_get_duration", lambda path: 10.0)
    merge_calls = []
    monkeypatch.setattr(
        downloader,
        "_merge_audio_files",
        lambda *args: merge_calls.append(args) or ["partial.mp3"],
    )

    with pytest.raises(RuntimeError, match=r"分片 2.*下载失败"):
        downloader._process_playlist(
            "https://example.com/playlist",
            str(tmp_path),
            [{"url": "part-1"}, {"url": "part-2"}],
            3600,
        )

    assert merge_calls == []


def test_playlist_rejects_missing_part_output(tmp_path, monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def download(self, urls):
            return None

    downloader = AudioDownloader()
    monkeypatch.setattr(downloader_module.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    with pytest.raises(RuntimeError, match=r"分片 1.*未生成"):
        downloader._process_playlist(
            "https://example.com/playlist",
            str(tmp_path),
            [{"url": "part-1"}],
            3600,
        )


def test_playlist_publishes_manifest_only_after_every_merge_batch_succeeds(
    tmp_path, monkeypatch
):
    url = "https://example.com/playlist"
    temp_dir = tmp_path / "temp_parts"
    temp_dir.mkdir()
    (temp_dir / "part_1.m4a").write_bytes(b"first")
    (temp_dir / "part_2.m4a").write_bytes(b"second")

    downloader = AudioDownloader()
    monkeypatch.setattr(downloader, "_get_duration", lambda path: 10.0)
    attempts = 0

    def merge_with_one_interrupted_attempt(parts, output_dir, temp_dir, max_duration):
        nonlocal attempts
        attempts += 1
        first = Path(output_dir) / "source_part1.mp3"
        first.write_bytes(b"merged first")
        if attempts == 1:
            raise RuntimeError("second batch failed")
        second = Path(output_dir) / "source_part2.mp3"
        second.write_bytes(b"merged second")
        return [str(first), str(second)]

    monkeypatch.setattr(downloader, "_merge_audio_files", merge_with_one_interrupted_attempt)

    with pytest.raises(RuntimeError, match="second batch failed"):
        downloader._process_playlist(
            url,
            str(tmp_path),
            [{"url": "part-1"}, {"url": "part-2"}],
            15,
        )

    assert (tmp_path / "source_part1.mp3").is_file()
    assert not (tmp_path / ".download_manifest.json").exists()

    _, _, outputs = downloader._process_playlist(
        url,
        str(tmp_path),
        [{"url": "part-1"}, {"url": "part-2"}],
        15,
    )

    assert outputs == [
        str(tmp_path / "source_part1.mp3"),
        str(tmp_path / "source_part2.mp3"),
    ]
    assert downloader_module.load_completed_download(tmp_path, url) == [
        str(tmp_path / "source_part1.mp3"),
        str(tmp_path / "source_part2.mp3"),
    ]


@pytest.mark.parametrize(
    "manifest_contents, requested_url",
    [
        ("not-json", "https://example.com/video"),
        (
            '{"schema_version": 1, "source_url": "https://example.com/other", '
            '"outputs": [{"path": "source.mp3", "size": 5, "sha256": "unused"}]}',
            "https://example.com/video",
        ),
    ],
)
def test_completed_download_rejects_corrupt_or_url_mismatched_manifest(
    tmp_path, manifest_contents, requested_url
):
    (tmp_path / "source.mp3").write_bytes(b"audio")
    (tmp_path / ".download_manifest.json").write_text(
        manifest_contents, encoding="utf-8"
    )

    assert downloader_module.load_completed_download(tmp_path, requested_url) == []


def test_completed_download_rejects_audio_changed_after_manifest(tmp_path):
    url = "https://example.com/video"
    audio = tmp_path / "source.mp3"
    audio.write_bytes(b"original")
    downloader_module.publish_download_manifest(tmp_path, url, [str(audio)])

    audio.write_bytes(b"tampered")

    assert downloader_module.load_completed_download(tmp_path, url) == []


def test_manifest_atomic_write_failure_removes_temporary_file(tmp_path, monkeypatch):
    audio = tmp_path / "source.mp3"
    audio.write_bytes(b"audio")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(downloader_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        downloader_module.publish_download_manifest(
            tmp_path, "https://example.com/video", [str(audio)]
        )

    assert not (tmp_path / ".download_manifest.json").exists()
    assert not (tmp_path / ".download_manifest.json.tmp").exists()
