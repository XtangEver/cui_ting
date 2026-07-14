from dataclasses import dataclass
import re


_ANCHORED_LINE = re.compile(r"^\[(\d+:[0-5]\d:[0-5]\d)\]\s*(.+)$")


@dataclass
class TimestampedSegment:
    start: float
    end: float
    text: str

    @property
    def formatted_start(self) -> str:
        return format_timestamp(self.start)

    @property
    def formatted_end(self) -> str:
        return format_timestamp(self.end)


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_timestamp(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    h, m = int(parts[0]), int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


def segments_to_anchored_text(segments: list[TimestampedSegment]) -> str:
    lines = []
    for seg in segments:
        lines.append(f"[{seg.formatted_start}] {seg.text}")
    return "\n".join(lines)


def parse_anchored_text(text: str) -> list[TimestampedSegment]:
    segments = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        match = _ANCHORED_LINE.fullmatch(line)
        if match:
            start = parse_timestamp(match.group(1))
            segments.append(TimestampedSegment(start=start, end=start, text=match.group(2)))
        elif segments:
            segments[-1] = TimestampedSegment(
                start=segments[-1].start, end=segments[-1].end,
                text=segments[-1].text + " " + line
            )
        else:
            segments.append(TimestampedSegment(start=0.0, end=0.0, text=line))
    return segments
