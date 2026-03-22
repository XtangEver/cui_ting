# cui_ting

视频语音转录 + LLM 智能精炼工具。

一键处理 Bilibili / YouTube 视频：自动下载音频 → 字幕优先获取文本（含时间戳） → 关键帧截图 → 大模型结构化摘要 → 输出图文并茂的 Markdown。

## 特性

- **多平台支持** — Bilibili、YouTube，自动识别平台并切换 Cookie
- **字幕优先** — 优先使用平台字幕（更准确），无字幕时自动 fallback 到 Whisper
- **全程时间戳** — 转录文本保留时间戳锚点，摘要中每段可溯源到原始视频位置
- **关键帧截图** — LLM 自动识别视觉内容引用，下载低画质视频提取关键帧
- **结构化摘要** — LLM 两阶段处理：去噪整理 → 图文拼装，输出带章节标题和截图的 Markdown
- **本地转录** — 基于 [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)，Apple Silicon Metal GPU 加速
- **多 LLM 接入** — 支持 OpenRouter、通义千问、智谱 GLM、Gemini、DeepSeek 等
- **批量处理** — JSON 文件定义多个视频任务，一次运行全部完成
- **断点续传** — 每个阶段独立缓存，中断后重新运行自动跳过已完成步骤

## 处理流程

```
输入：视频链接
    ↓
┌─────────────────────────────────┐
│ Stage 1：获取文本（含时间戳）     │
│ 优先级：平台字幕 > Whisper 转录   │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│ Stage 2：LLM 扫描文本            │
│ 定位需要截图的关键帧时间戳        │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│ Stage 3：按需下载低画质视频       │
│ ffmpeg 批量截图                  │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│ Stage 4：LLM 结构化整理          │
│ 纯文本去噪，保留时间戳锚点       │
└─────────────────────────────────┘
    ↓
┌─────────────────────────────────┐
│ Stage 5：图文拼装                │
│ 将截图插入对应时间戳位置          │
└─────────────────────────────────┘
    ↓
输出：结构化 Markdown（含关键帧截图）
```

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境（需要 Python >= 3.10）
conda create -n cui_ting python=3.10
conda activate cui_ting

# 安装依赖
pip install -r requirements.txt

# 安装 FFmpeg（转码和截图必需）
brew install ffmpeg

# （可选）YouTube 反爬支持
pip install "yt-dlp-ejs==$(python -c 'import yt_dlp; print(yt_dlp.version.__version__)')"
brew install deno
```

### 2. 准备 Cookie

使用浏览器插件 [Get cookies.txt](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) 导出已登录账号的 Cookie：

| 平台 | 保存路径 |
|------|---------|
| Bilibili | `cookie/bili_cookies.txt` |
| YouTube | `cookie/youtube_cookies.txt` |

> Cookie 包含登录凭证，请勿上传到 Git。建议在 `.gitignore` 中添加 `cookie/*.txt`。

### 3. 配置 config.yaml

```yaml
# LLM 模型配置
models:
  openrouter_gemini:
    api_key: "sk-or-v1-xxxxxxxx"       # 或通过环境变量 OPENROUTER_GEMINI_API_KEY 设置
    base_url: "https://openrouter.ai/api/v1"
    model: "google/gemini-2.5-flash-preview"
    extra_headers:
      HTTP-Referer: "http://localhost"
      X-Title: "VideoSummarizer"
    verify_ssl: false

# Whisper 模型路径
whisper:
  model_path: "mlx-community/whisper-small"

# 通用设置
settings:
  chunk_size: 20480
  chunk_overlap: 256
  default_llm_model: "openrouter_gemini"
  input_file: "./input_data.json"
  output_dir: "./output"
  # V2 新增
  subtitle_first: true           # 优先使用平台字幕
  extract_frames: true           # 启用关键帧截图
  frame_offset: 1.5              # 截图时间偏移（秒）
```

**API Key 优先级**：环境变量 `{MODEL_NAME}_API_KEY` > config.yaml 中的 `api_key` 字段。

**支持的 Whisper 模型（Apple Silicon 优化）**：

| 模型 | 速度 | 精度 |
|------|------|------|
| `mlx-community/whisper-tiny` | 最快 | 一般 |
| `mlx-community/whisper-base` | 快 | 较好 |
| `mlx-community/whisper-small` | 中 | 好（推荐） |
| `mlx-community/whisper-medium` | 慢 | 最佳 |

### 4. 编写任务清单

编辑 `input_data.json`：

```json
{
  "AI趋势分析": "https://www.bilibili.com/video/BV1xxxxxx",
  "State of AI": "https://youtu.be/EV7WhVT270Q"
}
```

### 5. 运行

```bash
conda activate cui_ting
python cli.py
```

### 输出结构

```
output/
├── AI趋势分析/
│   ├── source.mp3              # 下载的音频
│   ├── source_raw.md           # 带时间戳的原始转录
│   ├── source_refined.md       # 结构化摘要（含截图引用）
│   └── frames/
│       ├── frame_00_02_15.jpg  # 关键帧截图
│       └── frame_00_05_30.jpg
└── ...
```

**source_refined.md 示例：**

```markdown
## 核心论点 1

[00:12:34] 作者提出模型整体架构，左边是 encoder...

![keyframe at 00:12:34](frames/frame_00_12_34.jpg)

进一步说明 cross-attention 层的设计...

## 核心论点 2
...
```

## 断点续传

重复运行时，工具会自动检测已有文件并跳过：

| 检测到的文件 | 跳过的步骤 |
|-------------|-----------|
| `source*.mp3` | 跳过音频下载 |
| `*_raw.md` | 跳过转录（从缓存解析时间戳） |
| `frames/*.jpg` | 跳过已有关键帧截图 |
| `*_refined.md` | 跳过 LLM 精炼和图文拼装 |

## 配置选项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `subtitle_first` | `true` | 优先使用平台字幕（比 Whisper 更准确） |
| `extract_frames` | `true` | 启用关键帧截图（设为 false 回退到纯文本模式） |
| `frame_offset` | `1.5` | 截图时间偏移（秒），补偿语音和画面的延迟 |
| `chunk_size` | `20480` | 文本分块大小（字符数） |
| `chunk_overlap` | `256` | 分块重叠区域 |

## 项目结构

```
cui_ting/
├── cli.py                      # 入口：加载配置、分发任务
├── config.yaml                 # 全局配置
├── input_data.json             # 批量任务清单
├── requirements.txt            # Python 依赖
├── refine_txt.py               # 独立脚本：批量补全缺失的 refined 文件
├── cookie/
│   ├── bili_cookies.txt        # Bilibili Cookie
│   └── youtube_cookies.txt     # YouTube Cookie
├── core/
│   ├── config.py               # 配置解析，环境变量覆盖
│   ├── downloader.py           # yt-dlp 音频下载，分P合并
│   ├── subtitle_downloader.py  # 平台字幕下载，VTT 解析
│   ├── transcriber.py          # mlx-whisper 本地转录（带时间戳）
│   ├── timestamp_utils.py      # 时间戳工具（格式化、解析、段落）
│   ├── keyframe_detector.py    # LLM 关键帧检测
│   ├── frame_extractor.py      # 低画质视频下载 + ffmpeg 截图
│   ├── llm_processor.py        # LLM API 调用（去噪 + 结构化整理）
│   ├── text_processor.py       # 文本分块（中英文句子边界 + 时间戳感知）
│   ├── markdown_assembler.py   # 图文拼装（截图插入时间戳位置）
│   └── summarizer.py           # 5 阶段流程编排
└── tests/                      # 单元测试（29 个）
```

## 常见问题

**Q: YouTube 下载报错 "Only images are available"**

```bash
pip install "yt-dlp-ejs==$(python -c 'import yt_dlp; print(yt_dlp.version.__version__)')"
brew install deno
```

**Q: 没有截图生成**

- 检查 `config.yaml` 中 `extract_frames: true`
- 确保已安装 FFmpeg：`brew install ffmpeg`
- 如果视频内容是纯口语/访谈，LLM 可能判断没有需要截图的视觉内容

**Q: 如何禁用截图只要纯文本摘要**

设置 `extract_frames: false`，管线会跳过 Stage 2-3，只输出文本摘要。

**Q: 如何添加新的 LLM 模型**

在 `config.yaml` 的 `models` 下添加新条目（兼容 OpenAI API 格式），修改 `default_llm_model` 即可。

## 许可证

本项目仅供个人学习与研究使用。请遵守各平台服务条款，勿用于商业用途或大规模爬取。
