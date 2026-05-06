# cui_ting

视频语音转录 + LLM 智能精炼工具，提供 CLI 批量处理和 Web 前端两种使用方式。

自动处理 Bilibili / YouTube 视频：下载音频 → 字幕优先获取文本（含时间戳） → 大模型结构化摘要 → 输出 Markdown。

## 特性

- **Web 前端** — 浏览器输入 B站链接，异步处理，在线预览结果，SQLite 持久化存储
- **多平台支持** — Bilibili、YouTube，自动识别平台并切换 Cookie
- **字幕优先** — 优先使用平台字幕（更准确），无字幕时 fallback 到 Whisper
- **全程时间戳** — 转录文本保留时间戳锚点，摘要中每段可溯源到原始视频位置
- **结构化摘要** — LLM 处理：去噪整理 + 章节标题，输出 Markdown
- **本地转录** — 基于 mlx-whisper，Apple Silicon Metal GPU 加速
- **多 LLM 接入** — 统一 OpenAI 兼容格式，通过环境变量配置
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
│ Stage 2：LLM 结构化整理          │
│ 纯文本去噪，保留时间戳锚点       │
└─────────────────────────────────┘
    ↓
输出：结构化 Markdown
```

## 快速开始

### 1. 环境准备

```bash
# 创建虚拟环境（需要 Python >= 3.10）
conda create -n cui_ting python=3.10
conda activate cui_ting

# 安装依赖
pip install -r requirements.txt

# 安装 FFmpeg（音频下载必需）
brew install ffmpeg
```

### 2. 配置模型

在 `.env` 文件中配置 LLM 模型信息：

```bash
# .env
MINIMAX_API_KEY=sk-your-api-key
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_MODEL=MiniMax-M2.7
```

在 `config.yaml` 中声明启用的模型：

```yaml
models:
  - minimax

whisper:
  model_path: "mlx-community/whisper-medium"

settings:
  chunk_size: 20480
  chunk_overlap: 256
  cookies_file: "cookie/bili_cookies.txt"
  subtitle_first: true
  enable_refine: true
```

**新增模型**只需两步：
1. `.env` 中添加 `{NAME}_API_KEY`、`{NAME}_BASE_URL`、`{NAME}_MODEL`
2. `config.yaml` 的 `models` 列表中添加模型名称

### 3. 准备 Cookie

使用浏览器插件 [Get cookies.txt](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) 导出已登录账号的 Cookie：

| 平台 | 保存路径 |
|------|---------|
| Bilibili | `cookie/bili_cookies.txt` |
| YouTube | `cookie/youtube_cookies.txt` |

### 4a. Web 前端使用

```bash
conda activate cui_ting
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

- **本机访问**: `http://localhost:8000`
- **局域网访问**: `http://<你的IP>:8000`（其他设备如手机可用）

在页面输入 B站视频链接即可，任务异步执行，完成后在线预览精炼文本。

### 4b. CLI 批量使用

编辑 `input_data.json`：

```json
{
  "AI趋势分析": "https://www.bilibili.com/video/BV1xxxxxx"
}
```

```bash
conda activate cui_ting
python cli.py
```

### 输出结构

```
test_case/
├── AI趋势分析/
│   ├── source.mp3              # 下载的音频
│   ├── source_raw.md           # 带时间戳的原始转录
│   └── source_refined.md       # 结构化摘要
└── ...
```

## 断点续传

重复运行时，工具会自动检测已有文件并跳过：

| 检测到的文件 | 跳过的步骤 |
|-------------|-----------|
| `source*.mp3` | 跳过音频下载 |
| `*_raw.md` | 跳过转录 |
| `*_refined.md` | 跳过 LLM 精炼 |

## Web API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| POST | `/api/tasks` | 提交任务 `{"url": "..."}` |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{id}` | 任务详情（含文本） |
| DELETE | `/api/tasks/{id}` | 删除任务 |

## 配置选项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `subtitle_first` | `true` | 优先使用平台字幕 |
| `enable_refine` | `true` | 启用 LLM 后处理（false = 仅下载+转录） |
| `chunk_size` | `20480` | 文本分块大小（字符数） |
| `chunk_overlap` | `256` | 分块重叠区域 |

## 项目结构

```
cui_ting/
├── cli.py                      # CLI 入口
├── config.yaml                 # 全局配置
├── .env                        # 模型密钥（不提交 Git）
├── input_data.json             # 批量任务清单
├── requirements.txt            # Python 依赖
├── cookie/
│   └── bili_cookies.txt        # Bilibili Cookie
├── core/
│   ├── config.py               # 配置解析（YAML + .env）
│   ├── downloader.py           # yt-dlp 音频下载，分P合并
│   ├── subtitle_downloader.py  # 平台字幕下载，VTT 解析
│   ├── transcriber.py          # mlx-whisper 本地转录
│   ├── timestamp_utils.py      # 时间戳工具
│   ├── llm_processor.py        # LLM API 调用
│   ├── text_processor.py       # 文本分块与合并
│   └── summarizer.py           # 流程编排
├── web/
│   ├── app.py                  # FastAPI 应用，API + 后台 Worker
│   ├── database.py             # SQLite ORM，Task 模型
│   └── static/
│       ├── index.html          # 前端页面
│       ├── style.css           # 样式
│       └── app.js              # 前端逻辑
└── data/
    └── cui_ting.db             # SQLite 数据库（自动创建）
```

## 许可证

本项目仅供个人学习与研究使用。请遵守各平台服务条款，勿用于商业用途或大规模爬取。
