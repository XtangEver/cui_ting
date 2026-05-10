# cui_ting

视频语音转录 + LLM 智能精炼工具。输入 Bilibili / YouTube 链接，自动完成：下载音频 → 字幕/Whisper 转录 → 大模型结构化摘要 → 输出 Markdown。

支持 CLI 批量处理和 Web 前端两种方式。Mac 作为服务器时，可通过 `start.sh` 一键启动外网隧道，手机在任何网络下都能访问。

## 特性

- **一键外网访问** — `bash start.sh` 启动服务 + SSH 隧道，手机直接打开公网 URL 使用
- **实时进度** — Web 前端通过 SSE 展示流水线进度条（下载 → 转录 → 精炼），含百分比、阶段详情和关键日志
- **移动端适配** — 响应式设计，触控友好，手机浏览器完美使用
- **多平台支持** — Bilibili、YouTube，自动识别平台并切换 Cookie
- **字幕优先** — 优先使用平台字幕（更准确），无字幕时 fallback 到 Whisper
- **本地转录** — 基于 mlx-whisper，Apple Silicon Metal GPU 加速
- **多 LLM 接入** — 统一 OpenAI 兼容格式，通过环境变量配置，Web 端可选模型
- **断点续传** — 每个阶段独立缓存，中断后重新运行自动跳过已完成步骤
- **任务管理** — 支持重命名、标签分类、队列排队显示
- **结果导出** — 下载 .md 文件、一键复制全文/原文
- **GitHub 风格渲染** — Markdown 结果页支持标题层级、表格、代码块、目录侧栏（TOC）
- **思考内容过滤** — 自动剥离 LLM 输出中的模型推理/思考内容，防止提示词泄露

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

创建 `.env` 文件：

```bash
MINIMAX_API_KEY=sk-your-api-key
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_MODEL=MiniMax-M2.7
```

编辑 `config.yaml` 声明启用的模型：

```yaml
models:
  - minimax

whisper:
  model_path: "mlx_whisper_medium"

settings:
  chunk_size: 20480
  chunk_overlap: 256
  cookies_file: "cookie/bili_cookies.txt"
  subtitle_first: true
  enable_refine: true
```

**新增模型只需两步：**
1. `.env` 中添加 `{NAME}_API_KEY`、`{NAME}_BASE_URL`、`{NAME}_MODEL`
2. `config.yaml` 的 `models` 列表中添加模型名称

### 3. 准备 Cookie

使用浏览器插件 [Get cookies.txt](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) 导出已登录账号的 Cookie：

| 平台 | 保存路径 |
|------|---------|
| Bilibili | `cookie/bili_cookies.txt` |
| YouTube | `cookie/youtube_cookies.txt` |

### 4. 启动服务

#### 方式 A：一键启动（推荐，支持外网访问）

```bash
bash start.sh
```

启动后自动打印三个访问地址：

```
  📱 手机访问 (任何网络):
     https://xxxxx.serveousercontent.com

  🏠 局域网访问 (同一WiFi):
     http://192.168.x.x:8000

  🖥  本机访问:
     http://localhost:8000
```

手机扫描或输入公网 URL 即可使用，不限网络。

> **注意：** 外网隧道依赖 FlClash 代理（127.0.0.1:7890）。每次启动生成新的随机 URL。

#### 方式 B：仅局域网使用

```bash
conda activate cui_ting
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

同一 WiFi 下的设备访问 `http://<Mac的IP>:8000`。

#### 方式 C：CLI 批量处理

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

### 5. 停止服务

```bash
bash stop.sh
```

## 使用说明

### Web 前端

1. 在输入框粘贴 B站视频链接或 BV 号
2. 可选：添加标签（逗号分隔）、展开「高级选项」选择模型或关闭精炼
3. 点击「开始转录」
4. 实时查看流水线进度条：下载 → 转录（Whisper 动画指示）→ 精炼，含百分比和详情
5. 排队任务显示「排队中 (第 N 位)」
6. 完成后点击任务卡片进入结果页
7. 结果页支持「精炼文本」和「原始转录」标签切换，GitHub 风格 Markdown 渲染
8. 工具栏支持「下载 .md」「复制全文」「复制原文」
9. 长文档自动显示目录侧栏（3个以上标题时）
10. 可点击编辑按钮重命名任务

### CLI 模式

1. 在 `input_data.json` 中写入任务（名称 → URL）
2. 运行 `python cli.py`
3. 输出保存在 `test_case/<任务名>/` 下

## 输出结构

```
test_case/
├── AI趋势分析/
│   ├── source.mp3              # 下载的音频
│   ├── source_raw.md           # 带时间戳的原始转录
│   └── source_refined.md       # 结构化摘要
└── ...
```

## 断点续传

重复运行时自动检测已有文件并跳过：

| 已有文件 | 跳过的步骤 |
|---------|-----------|
| `source*.mp3` | 跳过音频下载 |
| `*_raw.md` | 跳过转录 |
| `*_refined.md` | 跳过 LLM 精炼 |

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

## Web API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面（任务列表） |
| GET | `/result/{task_id}` | 前端页面（结果详情） |
| POST | `/api/auth/login` | 登录 |
| GET | `/api/auth/check` | 检查登录状态 |
| POST | `/api/auth/logout` | 退出登录 |
| POST | `/api/tasks` | 提交任务 `{"url": "...", "tags": "", "model": "", "enable_refine": true}` |
| GET | `/api/tasks` | 任务列表（含 `queue_position`） |
| GET | `/api/tasks/{id}` | 任务详情（含 raw/refined 文本、tags、model） |
| PATCH | `/api/tasks/{id}` | 更新任务（重命名 `title` 或更新 `tags`） |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| GET | `/api/tasks/{id}/stream` | SSE 实时事件流 |
| GET | `/api/models` | 可用模型列表 |

SSE 事件类型：`stage_update`（阶段变更）、`progress`（进度百分比+详情）、`log`（日志）、`complete`（完成）、`task_error`（失败）。

## 项目结构

```
cui_ting/
├── cli.py                      # CLI 入口
├── config.yaml                 # 全局配置
├── .env                        # 模型密钥（不提交 Git）
├── input_data.json             # 批量任务清单
├── requirements.txt            # Python 依赖
├── start.sh                    # 一键启动（uvicorn + SSH 隧道）
├── stop.sh                     # 停止所有服务
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
│   └── summarizer.py           # 流程编排（支持 progress_callback）
├── web/
│   ├── app.py                  # FastAPI 应用，API + SSE + 后台 Worker
│   ├── database.py             # SQLite ORM，Task 模型
│   └── static/
│       ├── index.html          # 两页 SPA（任务列表 + 结果详情）
│       ├── style.css           # Indigo 主题，移动端适配
│       └── app.js              # SSE 集成，Markdown 渲染
├── deploy/
│   ├── nginx.conf              # Nginx 反向代理配置
│   └── cui_ting.service        # systemd 服务配置
└── data/
    └── cui_ting.db             # SQLite 数据库（自动创建）
```

## 配置选项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `subtitle_first` | `true` | 优先使用平台字幕 |
| `enable_refine` | `true` | 启用 LLM 后处理（false = 仅下载+转录） |
| `chunk_size` | `20480` | 文本分块大小（字符数） |
| `chunk_overlap` | `256` | 分块重叠区域 |

## 许可证

本项目仅供个人学习与研究使用。请遵守各平台服务条款，勿用于商业用途或大规模爬取。
