import logging
import re

from .timestamp_utils import format_timestamp, parse_timestamp

logger = logging.getLogger(__name__)

_TS_PATTERN = re.compile(r"\[(\d{2}:\d{2}:\d{2})\]")


def insert_frames_into_markdown(markdown: str, frames: dict[float, str]) -> str:
    """Insert frame images into markdown at the best matching timestamp position.

    For each frame (keyed by original_timestamp in seconds), finds the line
    with the closest preceding [HH:MM:SS] anchor and inserts the image after it.
    """
    if not frames:
        return markdown

    # Parse all timestamp anchors from the markdown with their line indices
    lines = markdown.split("\n")
    anchor_lines: list[tuple[int, float]] = []  # (line_index, seconds)
    for i, line in enumerate(lines):
        match = _TS_PATTERN.search(line)
        if match:
            anchor_lines.append((i, parse_timestamp(match.group(1))))

    if not anchor_lines:
        logger.warning("文本中未找到时间戳锚点，无法插入截图")
        return markdown

    # For each frame, find the best line to insert after
    # (closest anchor whose timestamp <= frame timestamp)
    insertions: dict[int, list[str]] = {}  # line_index -> [image markdown lines]
    for frame_ts, img_path in sorted(frames.items()):
        best_line = _find_best_anchor_line(anchor_lines, frame_ts)
        if best_line is not None:
            ts_str = format_timestamp(frame_ts)
            img_md = f"![keyframe at {ts_str}]({img_path})"
            insertions.setdefault(best_line, []).append(img_md)

    # Build output with insertions
    result_lines = []
    for i, line in enumerate(lines):
        result_lines.append(line)
        if i in insertions:
            for img_md in insertions[i]:
                result_lines.append("")
                result_lines.append(img_md)
                result_lines.append("")

    return "\n".join(result_lines)


def _find_best_anchor_line(anchor_lines: list[tuple[int, float]], target_ts: float) -> int | None:
    """Find the line index of the closest timestamp anchor that is <= target_ts.
    If no anchor is <= target_ts, use the first anchor after it."""
    best_line = None
    best_diff = float("inf")

    # First try: closest anchor at or before the target
    for line_idx, anchor_ts in anchor_lines:
        if anchor_ts <= target_ts:
            diff = target_ts - anchor_ts
            if diff < best_diff:
                best_diff = diff
                best_line = line_idx

    # Fallback: if no anchor before target, use closest anchor after
    if best_line is None:
        for line_idx, anchor_ts in anchor_lines:
            diff = abs(anchor_ts - target_ts)
            if diff < best_diff:
                best_diff = diff
                best_line = line_idx

    return best_line
