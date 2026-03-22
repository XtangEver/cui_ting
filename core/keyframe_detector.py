import json
import logging
import re

from .llm_processor import LLMProcessor

logger = logging.getLogger(__name__)

KEYFRAME_DETECTION_PROMPT = """你是一个视频内容分析助手。以下是一段带时间戳的视频转录文本。

请分析文本，找出所有**暗示画面中有重要视觉内容**的位置。识别以下信号：
- 明确提到图表、数据、代码、架构图（如"如图所示"、"可以看到"、"这张图"、"左边/右边"）
- 提到具体的数据展示（如"数据显示"、"这个曲线"、"表格中"）
- 提到代码或技术架构（如"代码如下"、"架构是这样的"）
- 话题或场景明显切换的位置

输出格式为 JSON 数组，每个元素包含 timestamp（秒数）和 reason（触发原因）：
```json
[
  {{"timestamp": 754, "reason": "提到'如图所示'，疑似 PPT 切换"}},
  {{"timestamp": 1823, "reason": "提到具体数据图表"}}
]
```

如果文本中没有视觉参考信号，返回空数组 `[]`。

转录文本：
{text}"""


def parse_keyframe_response(response: str) -> list[dict]:
    cleaned = response.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        logger.warning("无法解析关键帧检测响应: %s", response[:200])
    return []


def apply_offset(keyframes: list[dict], offset: float = 1.5) -> list[dict]:
    """Apply offset for ffmpeg capture, preserving original timestamp for text matching."""
    return [
        {**kf, "capture_timestamp": kf["timestamp"] + offset}
        for kf in keyframes
    ]


class KeyframeDetector:
    def __init__(self, llm_processor: LLMProcessor):
        self.llm = llm_processor

    def detect(self, anchored_text: str, model_name: str, offset: float = 1.5) -> list[dict]:
        """Returns keyframes with both 'timestamp' (original, for text matching)
        and 'capture_timestamp' (offset, for ffmpeg)."""
        logger.info("正在使用 LLM 检测关键帧位置...")
        prompt = KEYFRAME_DETECTION_PROMPT.format(text=anchored_text)
        response = self.llm.call_llm(model_name, prompt)
        keyframes = parse_keyframe_response(response)
        keyframes = apply_offset(keyframes, offset=offset)
        logger.info("检测到 %d 个关键帧位置", len(keyframes))
        return keyframes
