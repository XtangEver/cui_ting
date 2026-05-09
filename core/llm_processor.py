# core/llm_processor.py
import logging
import re

import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMProcessor:
    """LLM处理器"""

    _THINK_PATTERN = re.compile(
        r'<(?:think|thinking)(?:\s[^>]*)?>.*?</(?:think|thinking)\s*>',
        re.DOTALL
    )

    _PROMPT_ECHO_PATTERNS = [
        "请对以下文本进行",
        "The user wants me to",
        "我需要对以下",
        "Let me process",
    ]

    PROMPT_REFINE = """请对以下文本进行一次性精炼处理，输出一段**干净、连贯、结构清晰的简体中文文本**，要求如下：

1. **去冗余**：彻底删除重复语句、口头禅（如"呃""那个""然后"）、无意义语气词（如"啊""嗯""好吧"等）。
2. **保原意**：不得删减任何事实、观点、数据或逻辑关系；保持原始立场和论证顺序。
3. **强梳理**：
   - 自动补全标点（句号、逗号、分号等）；
   - 按语义合理分段（每段聚焦一个主题）；
   - 若原文逻辑松散，可微调语序使其通顺，但**不得新增内容或改变因果/时序关系**。
4. **语言规范**：
   - 非简体中文内容须准确译为简体中文；
   - **专业术语、技术名词、产品名、机构名等保留英文原词**（如 Transformer、GPU、FDA、LLM）。

> 输出仅为一段整理后的文本，**不要标题、不要说明、不要分块、不要列表**，直接开始正文。

文本内容：
{text}"""

    STRUCTURED_REFINE_PROMPT = """请对以下原始文本进行一次性精炼处理，输出**干净、连贯、结构清晰的简体中文文本**，要求如下：

1. **去冗余**：彻底删除重复语句、口头禅（如“呃”“那个”“然后”）、无意义语气词（如“啊”“嗯”“好吧”等），适当梳理表达使语言更精炼。
2. **保原意**：不得删减任何事实、观点、数据或逻辑关系；保持原始立场和论证顺序。
3. **强梳理**：
   - 自动补全标点（句号、逗号、分号等）；
   - 按语义合理分段（每段聚焦一个主题）；
   - 若原文逻辑松散，可微调语序使其通顺，但**不得新增内容或改变因果/时序关系**。
4. **语言规范**：
   - 所有非简体中文内容一律翻译为简体中文；
   - **但以下英文关键词保留原词，不翻译**：公认的技术术语、产品名、机构名、品牌名、缩写等，如 Transformer、AI、GPU、FDA、LLM、Chrome 等；
   - 若遇到无法确定是否保留的英文词，以行业惯例为准，宜保留原词。
5. **段落观点加粗**：
   - 每个自然段开头，用**黑体加粗**提炼该段落的核心观点（一句概括）；
   - 加粗格式统一使用 Markdown 语法 `**核心观点**`；
   - 观点句之后接详细阐述，形成“**观点** + 展开”的段落结构。

> 输出为精炼后的文本，**可合理分段**，每段开头按要求加粗核心观点；**不要标题、不要项目符号列表、不要说明**，直接开始正文。

文本内容：
{text}"""


    def __init__(self, config: dict):
        self.model_configs = config
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
                    headers=custom_headers
                )
                self._clients[model_name] = OpenAI(
                    api_key=model_cfg.api_key,
                    base_url=model_cfg.base_url,
                    http_client=http_client
                )
            else:
                self._clients[model_name] = OpenAI(
                    api_key=model_cfg.api_key,
                    base_url=model_cfg.base_url
                )
        return self._clients[model_name]

    def call_llm(self, model_name: str, prompt: str) -> str:
        return self._call_llm(model_name, prompt)

    def _call_llm(self, model_name: str, prompt: str) -> str:
        model_cfg = self.model_configs.get(model_name)
        if model_cfg is None:
            raise ValueError(f"未配置的模型: {model_name}")

        client = self._get_client(model_name)
        response = client.chat.completions.create(
            model=model_cfg.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=8192
        )
        content = response.choices[0].message.content
        content = self._THINK_PATTERN.sub('', content).strip()

        # Best-effort prompt echo detection (log only, don't block)
        first_line = content.split('\n', 1)[0][:100]
        for pattern in self._PROMPT_ECHO_PATTERNS:
            if pattern in first_line:
                logger.warning("Possible prompt echo detected in LLM response (model: %s)", model_name)
                break

        return content

    def refine(self, text: str, model_name: str) -> str:
        logger.info("正在进行文本去噪 (模型: %s)...", model_name)
        prompt = self.PROMPT_REFINE.format(text=text)
        result = self._call_llm(model_name, prompt)
        logger.info("文本去噪完成")
        return result

    def structured_refine(self, text: str, model_name: str) -> str:
        logger.info("正在进行结构化文本整理 (模型: %s)...", model_name)
        prompt = self.STRUCTURED_REFINE_PROMPT.format(text=text)
        result = self._call_llm(model_name, prompt)
        logger.info("结构化整理完成")
        return result
