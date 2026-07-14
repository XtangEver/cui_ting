import pytest

from core.timestamp_utils import (
    TimestampedSegment,
    format_timestamp,
    parse_anchored_text,
    parse_timestamp,
    segments_to_anchored_text,
)


def test_hundred_hour_timestamp_round_trips_through_anchored_text():
    start = 100 * 3600 + 2 * 60 + 3
    anchored = segments_to_anchored_text(
        [TimestampedSegment(start=start, end=start + 1, text="long recording")]
    )

    assert anchored == "[100:02:03] long recording"
    parsed = parse_anchored_text(anchored)
    assert [(segment.start, segment.text) for segment in parsed] == [
        (start, "long recording"),
    ]
    assert parse_timestamp(format_timestamp(start)) == start


@pytest.mark.parametrize("timestamp", ["100:60:00", "100:00:60"])
def test_parse_anchored_text_does_not_interpret_out_of_range_timestamp(timestamp):
    parsed = parse_anchored_text(f"[{timestamp}] invalid")

    assert [(segment.start, segment.text) for segment in parsed] == [
        (0.0, f"[{timestamp}] invalid"),
    ]
