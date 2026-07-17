# core/llm_processor.py
import logging
import re

import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)

_MAX_LLM_RETRIES = 2
_LLM_TIMEOUT = httpx.Timeout(connect=30.0, read=600.0, write=30.0, pool=30.0)


class LLMProcessor:
    """LLM处理器"""

    _THINK_PATTERN = re.compile(
        r'<(?:think|thinking)(?:\s[^>]*)?>.*?</(?:think|thinking)\s*>',
        re.DOTALL
    )

    _PROMPT_ECHO_PATTERNS = [
        "请对以下文本进行",
        "请对以下原始文本进行",
        "The user wants me to",
        "我需要对以下",
        "Let me process",
    ]

    STRUCTURED_REFINE_PROMPT = """以下文本由 Whisper 根据演讲者语音转录生成。请在最大限度保留原文内容、观点、事实、数据、逻辑关系和表达顺序的前提下，对文本进行清洗和结构化整理。

要求：
1. 删除无实际语义的口头禅、语气词、重复词句和自我修正残留，例如“呃”“嗯”“那个”“然后”“就是说”等。
2. 对语义重复的内容进行合并，但必须保留其中独有的信息；具有强调、递进、对比或论证作用的重复不得删除。
3. 修正明显的断句、标点、语序和语病，使文本连贯、规范，但不得新增信息、改变原意或将原文压缩为摘要。
4. 非简体中文内容翻译为简体中文；专业术语、技术名词、产品名、模型名、机构名和缩写保留常用英文原词，例如 Transformer、GPU、FDA、LLM。
5. 对疑似 Whisper 识别错误的内容，仅在能够根据上下文明确判断时修正；无法确定时保留原文，不得猜测。
6. 根据主题将全文拆分为若干子部分，并为每个子部分添加简洁标题，保持原文整体论述顺序。
7. 每个子部分末尾添加以“结论：”开头的结论段落。结论只能归纳该部分原文已经表达的内容，不得引入新观点、新事实或额外推论。若原文未形成明确结论，应如实说明。
8. 除标题、整理后的正文和结论外，不要输出任何说明。

待处理文本：
{text}"""


    def __init__(
        self,
        config: dict,
        max_tokens: int = 128000,
        client_factory=None,
    ):
        self.model_configs = config
        self.max_tokens = max_tokens
        self.client_factory = client_factory or OpenAI
        self._clients: dict[str, OpenAI] = {}

    def _get_client(self, model_name: str) -> OpenAI:
        if model_name not in self._clients:
            model_cfg = self.model_configs.get(model_name)
            if model_cfg is None:
                raise ValueError(f"未配置的模型: {model_name}")

            custom_headers = model_cfg.extra_headers or {}
            if not model_cfg.verify_ssl or custom_headers:
                http_client = httpx.Client(
                    verify=model_cfg.verify_ssl,
                    headers=custom_headers,
                    timeout=_LLM_TIMEOUT,
                )
                self._clients[model_name] = self.client_factory(
                    api_key=model_cfg.api_key,
                    base_url=model_cfg.base_url,
                    http_client=http_client,
                    max_retries=_MAX_LLM_RETRIES,
                    timeout=_LLM_TIMEOUT,
                )
            else:
                self._clients[model_name] = self.client_factory(
                    api_key=model_cfg.api_key,
                    base_url=model_cfg.base_url,
                    max_retries=_MAX_LLM_RETRIES,
                    timeout=_LLM_TIMEOUT,
                )
        return self._clients[model_name]

    def call_llm(self, model_name: str, prompt: str) -> str:
        return self._call_llm(model_name, prompt)

    def _call_llm(self, model_name: str, prompt: str) -> str:
        model_cfg = self.model_configs.get(model_name)
        if model_cfg is None:
            raise ValueError(f"未配置的模型: {model_name}")

        client = self._get_client(model_name)
        stream = client.chat.completions.create(
            model=model_cfg.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=self.max_tokens,
            stream=True,
        )
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
            rc = getattr(delta, 'reasoning_content', None)
            if rc:
                reasoning_parts.append(rc)

        content = ''.join(content_parts)
        reasoning = ''.join(reasoning_parts)
        if not content and reasoning:
            content = reasoning
        content = self._THINK_PATTERN.sub('', content).strip()

        first_line = content.split('\n', 1)[0][:100]
        for pattern in self._PROMPT_ECHO_PATTERNS:
            if pattern in first_line:
                logger.warning("Possible prompt echo detected in LLM response (model: %s)", model_name)
                break

        return content

    def refine(self, text: str, model_name: str) -> str:
        logger.info("正在进行文本去噪 (模型: %s)...", model_name)
        prompt = self.STRUCTURED_REFINE_PROMPT.format(text=text)
        result = self._call_llm(model_name, prompt)
        logger.info("文本去噪完成")
        return result

    def structured_refine(self, text: str, model_name: str) -> str:
        logger.info("正在进行结构化文本整理 (模型: %s)...", model_name)
        prompt = self.STRUCTURED_REFINE_PROMPT.format(text=text)
        result = self._call_llm(model_name, prompt)
        logger.info("结构化整理完成")
        return result
