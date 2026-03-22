# cli.py
import json
import logging
import os
from pathlib import Path

from core.config import ConfigManager
from core.summarizer import VideoSummarizer

logger = logging.getLogger(__name__)

COOKIE_MAP = {
    "bilibili.com": "cookie/bili_cookies.txt",
}
DEFAULT_COOKIE = "cookie/youtube_cookies.txt"


def load_input_json(json_path: str) -> dict:
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def detect_cookie(url: str) -> str:
    url_lower = url.lower()
    for domain, cookie_path in COOKIE_MAP.items():
        if domain in url_lower:
            return cookie_path
    return DEFAULT_COOKIE


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )


def main():
    setup_logging()

    logger.info("cui_ting - 视频转录与智能摘要工具")

    try:
        config_manager = ConfigManager("config.yaml")
        app_config = config_manager.get_app_config()
    except Exception as e:
        logger.error("配置加载失败: %s", e)
        return

    input_json_path = app_config.input_file
    output_base_dir = app_config.output_dir

    logger.info("输入任务文件: %s", input_json_path)
    logger.info("输出根目录: %s", output_base_dir)
    logger.info("默认模型: %s", app_config.default_model)

    try:
        batch_tasks = load_input_json(input_json_path)
        logger.info("成功加载 %d 个任务", len(batch_tasks))
    except Exception as e:
        logger.error("无法加载输入文件 '%s': %s", input_json_path, e)
        return

    Path(output_base_dir).mkdir(parents=True, exist_ok=True)

    # 按 cookie 分组缓存 summarizer，避免重复创建
    summarizer_cache: dict[str, VideoSummarizer] = {}

    for folder_name, url in batch_tasks.items():
        logger.info("=" * 50)
        logger.info("处理任务: %s | URL: %s", folder_name, url)

        try:
            cookie_file = detect_cookie(url)
            logger.info("Cookie: %s", cookie_file)

            if not os.path.exists(cookie_file):
                logger.warning("Cookie 文件不存在: %s", cookie_file)

            # 复用同一 cookie 的 summarizer
            if cookie_file not in summarizer_cache:
                summarizer_cache[cookie_file] = VideoSummarizer(
                    config_path="config.yaml",
                    cookies_file=cookie_file
                )
            summarizer = summarizer_cache[cookie_file]

            project_output_dir = os.path.join(output_base_dir, folder_name)
            os.makedirs(project_output_dir, exist_ok=True)

            result = summarizer.process(
                url=url,
                model_name=app_config.default_model,
                output_dir=project_output_dir
            )

            logger.info("任务 '%s' 完成! 输出: %s", folder_name, result['output_dir'])

        except Exception as e:
            logger.exception("任务 '%s' 失败", folder_name)

    logger.info("所有任务处理完毕! 结果路径: %s", os.path.abspath(output_base_dir))


if __name__ == "__main__":
    main()
