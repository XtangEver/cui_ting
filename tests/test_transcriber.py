import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.audio_chunker import AudioChunk
from core.config import WhisperConfig
from core.transcriber import Transcriber


class FakeChunker:
    def __init__(self):
        self.extract_calls = []

    def probe_duration(self, audio_path: Path) -> float:
        return 2400.0

    def plan(self, duration: float) -> list[AudioChunk]:
        assert duration == 2400.0
        return [
            AudioChunk(1, 0.0, 1200.0, 0.0, 1215.0),
            AudioChunk(2, 1200.0, 2400.0, 1185.0, 2400.0),
        ]

    def extract(
        self, audio_path: Path, chunk: AudioChunk, output_path: Path
    ) -> None:
        assert audio_path.is_file()
        self.extract_calls.append(chunk.index)
        output_path.write_bytes(b"wav")


class FakeModel:
    def __init__(self):
        self.transcribe_calls = []

    def transcribe(self, audio_path: str, **kwargs):
        self.transcribe_calls.append((audio_path, kwargs))
        index = int(Path(audio_path).stem.rsplit("_", 1)[1])
        if index == 1:
            items = [
                SimpleNamespace(start=1190.0, end=1198.0, text=" left "),
                SimpleNamespace(start=1201.0, end=1205.0, text="duplicate-right"),
                SimpleNamespace(start=10.0, end=12.0, text="   "),
            ]
        else:
            items = [
                SimpleNamespace(start=5.0, end=13.0, text="duplicate-left"),
                SimpleNamespace(start=16.0, end=20.0, text=" right "),
            ]
        return (item for item in items), SimpleNamespace()


class FakeModelFactory:
    def __init__(self, model=None):
        self.model = model or FakeModel()
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.model


@pytest.fixture
def config():
    return WhisperConfig(download_root=Path("D:/models"))


@pytest.fixture
def chunker():
    return FakeChunker()


@pytest.fixture
def model_factory():
    return FakeModelFactory()


@pytest.fixture
def transcriber(config, chunker, model_factory):
    return Transcriber(config, chunker, model_factory)


def make_audio(path: Path, contents: bytes = b"source") -> str:
    path.write_bytes(contents)
    return str(path)


def test_model_is_lazy_and_created_once(config, chunker, model_factory, tmp_path):
    transcriber = Transcriber(config, chunker, model_factory)
    assert model_factory.calls == []

    transcriber.transcribe(
        make_audio(tmp_path / "a.mp3"), str(tmp_path / "cache-a")
    )
    transcriber.transcribe(
        make_audio(tmp_path / "b.mp3"), str(tmp_path / "cache-b")
    )

    assert model_factory.calls == [
        {
            "model_size_or_path": "medium",
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": 8,
            "download_root": "D:\\models",
        }
    ]


def test_offsets_and_assigns_overlap_by_segment_midpoint(transcriber, tmp_path):
    audio = make_audio(tmp_path / "source.mp3")

    segments = transcriber.transcribe(audio, str(tmp_path / "cache"))

    assert [(s.start, s.end, s.text) for s in segments] == [
        (1190.0, 1198.0, "left"),
        (1201.0, 1205.0, "right"),
    ]


def test_valid_cache_skips_extract_and_model(
    transcriber, chunker, model_factory, tmp_path
):
    audio = make_audio(tmp_path / "source.mp3")
    cache = str(tmp_path / "cache")
    first = transcriber.transcribe(audio, cache)
    calls_after_first = len(model_factory.model.transcribe_calls)

    second = transcriber.transcribe(audio, cache)

    assert second == first
    assert chunker.extract_calls == [1, 2]
    assert len(model_factory.model.transcribe_calls) == calls_after_first


def test_corrupt_cache_is_rebuilt_without_losing_other_chunks(
    transcriber, chunker, tmp_path
):
    audio = make_audio(tmp_path / "source.mp3")
    cache = tmp_path / "cache"
    transcriber.transcribe(audio, str(cache))
    (cache / "chunk_000002.json").write_text("broken", encoding="utf-8")

    transcriber.transcribe(audio, str(cache))

    assert chunker.extract_calls == [1, 2, 2]


def test_stale_source_fingerprint_rebuilds_cached_chunks(
    transcriber, chunker, tmp_path
):
    audio_path = tmp_path / "source.mp3"
    audio = make_audio(audio_path)
    cache = str(tmp_path / "cache")
    transcriber.transcribe(audio, cache)
    audio_path.write_bytes(b"changed source size")

    transcriber.transcribe(audio, cache)

    assert chunker.extract_calls == [1, 2, 1, 2]


def test_cache_with_missing_required_segment_field_is_rebuilt(
    transcriber, chunker, tmp_path
):
    audio = make_audio(tmp_path / "source.mp3")
    cache = tmp_path / "cache"
    transcriber.transcribe(audio, str(cache))
    path = cache / "chunk_000001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["segments"][0]["text"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    transcriber.transcribe(audio, str(cache))

    assert chunker.extract_calls == [1, 2, 1]


@pytest.mark.parametrize(
    ("replacement", "expected_calls"),
    [
        ({"start": 1198.0, "end": 1190.0, "text": "left"}, [1, 2, 1]),
        ({"start": 1201.0, "end": 1205.0, "text": "left"}, [1, 2, 1]),
        ({"start": 1190.0, "end": 1198.0, "text": " left "}, [1, 2, 1]),
    ],
    ids=["end-before-start", "midpoint-outside-core", "noncanonical-text"],
)
def test_semantically_corrupt_finite_cached_segment_is_rebuilt(
    transcriber, chunker, tmp_path, replacement, expected_calls
):
    audio = make_audio(tmp_path / "source.mp3")
    cache = tmp_path / "cache"
    transcriber.transcribe(audio, str(cache))
    path = cache / "chunk_000001.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["segments"][0] = replacement
    path.write_text(json.dumps(payload), encoding="utf-8")

    segments = transcriber.transcribe(audio, str(cache))

    assert chunker.extract_calls == expected_calls
    assert [(item.start, item.end, item.text) for item in segments] == [
        (1190.0, 1198.0, "left"),
        (1201.0, 1205.0, "right"),
    ]


@pytest.mark.parametrize(
    ("chunk_index", "replacement"),
    [
        (1, {"start": -1.0, "end": 1.0, "text": "left"}),
        (1, {"start": 1179.0, "end": 1216.0, "text": "left"}),
        (2, {"start": 2390.0, "end": 2410.0, "text": "right"}),
    ],
    ids=["negative-start", "beyond-extraction", "beyond-duration"],
)
def test_cached_segment_outside_decoded_audio_bounds_is_rebuilt(
    transcriber, chunker, tmp_path, chunk_index, replacement
):
    audio = make_audio(tmp_path / "source.mp3")
    cache = tmp_path / "cache"
    transcriber.transcribe(audio, str(cache))
    path = cache / f"chunk_{chunk_index:06d}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["segments"][0] = replacement
    path.write_text(json.dumps(payload), encoding="utf-8")

    segments = transcriber.transcribe(audio, str(cache))

    assert chunker.extract_calls == [1, 2, chunk_index]
    assert [(item.start, item.end, item.text) for item in segments] == [
        (1190.0, 1198.0, "left"),
        (1201.0, 1205.0, "right"),
    ]


def test_generated_segments_outside_decoded_audio_bounds_are_not_cached(
    config, chunker, tmp_path
):
    class InvalidBoundsModel:
        def transcribe(self, audio_path: str, **kwargs):
            index = int(Path(audio_path).stem.rsplit("_", 1)[1])
            if index == 1:
                items = [
                    SimpleNamespace(start=-1.0, end=1.0, text="negative"),
                    SimpleNamespace(
                        start=1179.0, end=1216.0, text="past extraction"
                    ),
                    SimpleNamespace(start=1190.0, end=1198.0, text="valid"),
                ]
            else:
                items = [
                    SimpleNamespace(
                        start=1205.0, end=1225.0, text="past duration"
                    )
                ]
            return (item for item in items), SimpleNamespace()

    transcriber = Transcriber(
        config, chunker, FakeModelFactory(InvalidBoundsModel())
    )
    audio = make_audio(tmp_path / "source.mp3")
    cache = tmp_path / "cache"

    first = transcriber.transcribe(audio, str(cache))
    second = transcriber.transcribe(audio, str(cache))

    assert [(item.start, item.end, item.text) for item in first] == [
        (1190.0, 1198.0, "valid")
    ]
    assert second == first
    chunks = {item.index: item for item in chunker.plan(2400.0)}
    for path in cache.glob("chunk_*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        chunk = chunks[int(path.stem.rsplit("_", 1)[1])]
        assert all(
            chunk.extract_start
            <= segment["start"]
            <= segment["end"]
            <= min(chunk.extract_end, 2400.0)
            for segment in payload["segments"]
        )


def test_final_chunk_accepts_segment_midpoint_at_inclusive_endpoint(
    config, chunker, tmp_path
):
    class FinalEndpointModel:
        def transcribe(self, audio_path: str, **kwargs):
            index = int(Path(audio_path).stem.rsplit("_", 1)[1])
            items = (
                []
                if index == 1
                else [SimpleNamespace(start=1215.0, end=1215.0, text=" end ")]
            )
            return (item for item in items), SimpleNamespace()

    transcriber = Transcriber(
        config, chunker, FakeModelFactory(FinalEndpointModel())
    )
    audio = make_audio(tmp_path / "source.mp3")
    cache = str(tmp_path / "cache")

    first = transcriber.transcribe(audio, cache)
    second = transcriber.transcribe(audio, cache)

    assert [(item.start, item.end, item.text) for item in first] == [
        (2400.0, 2400.0, "end")
    ]
    assert second == first
    assert chunker.extract_calls == [1, 2]


def test_temporary_wav_is_removed_when_model_raises(config, chunker, tmp_path):
    class RaisingModel:
        def transcribe(self, audio_path: str, **kwargs):
            raise RuntimeError("inference failed")

    transcriber = Transcriber(config, chunker, FakeModelFactory(RaisingModel()))
    cache = tmp_path / "cache"

    with pytest.raises(RuntimeError, match="inference failed"):
        transcriber.transcribe(
            make_audio(tmp_path / "source.mp3"), str(cache)
        )

    assert list(cache.glob("*.wav")) == []
