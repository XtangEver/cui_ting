# core/llm_processor.py
import logging

import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMProcessor:
    """LLM处理器"""

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

    STRUCTURED_REFINE_PROMPT = """请对以下带时间戳的视频转录文本进行结构化整理。要求：

1. **保留时间戳锚点**：每个段落开头必须保留原始 [HH:MM:SS] 时间戳。
2. **去冗余**：删除重复语句、口头禅、无意义语气词。
3. **保原意**：不得删减事实、观点、数据或逻辑关系；保持原始立场。区分"事实陈述"与"个人观点"，保留说话人的不确定性表述（如"我觉得可能"）。
4. **结构化**：
   - 按话题自动分段，每段聚焦一个主题
   - 为每个主要话题段落添加 Markdown 二级标题（## ）
   - 自动补全标点
5. **语言规范**：非简体中文译为简体中文；专业术语保留英文原词。
6. **仅基于原文**：不添加原文中没有的信息或推断。

输出格式：带时间戳锚点和章节标题的 Markdown 文本。直接开始正文，不要额外说明。

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
        return response.choices[0].message.content

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
