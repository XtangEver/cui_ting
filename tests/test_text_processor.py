import pytest

from core.text_processor import TextProcessor


@pytest.mark.parametrize(
    "chunk_size,chunk_overlap",
    [(0, 0), (-1, 0), (100, -1), (100, 100), (100, 101)],
)
def test_constructor_rejects_invalid_chunk_settings(chunk_size, chunk_overlap):
    with pytest.raises(ValueError, match="chunk_size|chunk_overlap"):
        TextProcessor(chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def test_constructor_accepts_zero_overlap():
    processor = TextProcessor(chunk_size=100, chunk_overlap=0)

    assert processor.chunk_size == 100
    assert processor.chunk_overlap == 0
