# core/text_processor.py
from .timestamp_utils import TimestampedSegment, segments_to_anchored_text


class TextProcessor:
    SENTENCE_ENDINGS = '.?!。？！'

    def __init__(self, chunk_size: int = 5120, chunk_overlap: int = 256):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be non-negative and less than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_segments(self, segments: list[TimestampedSegment]) -> list[str]:
        anchored_text = segments_to_anchored_text(segments)
        return self.split_text(anchored_text)

    def _find_last_sentence_end(self, text: str, start: int, end: int) -> int:
        best = -1
        for char in self.SENTENCE_ENDINGS:
            pos = text.rfind(char, start, end)
            if pos > best:
                best = pos
        return best

    def split_text(self, text: str) -> list:
        if len(text) <= self.chunk_size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            if end < len(text):
                newline_pos = text.rfind('\n', start + self.chunk_size // 2, end)
                if newline_pos > 0 and text[newline_pos + 1:newline_pos + 2] == '[':
                    end = newline_pos
                else:
                    sentence_end = self._find_last_sentence_end(text, start, end)
                    if sentence_end > start + self.chunk_size // 2:
                        end = sentence_end + 1
            chunks.append(text[start:end].strip())
            start = end - self.chunk_overlap
            if start >= len(text):
                break
        return chunks

    def merge_results(self, results: list) -> str:
        return '\n'.join(results)
