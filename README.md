# cui_ting Windows CLI

面向 Windows 11 的批量视频/音频下载、转录与 LLM 精炼命令行工具。本发布只支持 CLI 工作流；仓库中的 Web 相关源码不属于本版本的支持范围。

## 功能与支持范围

- 从 `input_data.json` 批量读取任务；支持 Bilibili、YouTube 以及下载器能够识别的 HTTP(S) 地址。
- 优先复用站点字幕；没有可用字幕时使用本地 Faster Whisper 转录。
- 默认使用 Whisper `medium`、CPU INT8，模型目录为 `D:\models`。
- 长音频按 1,200 秒核心区间切块，并为边界保留 15 秒上下文。
- 可选调用 OpenAI 兼容 LLM 精炼文本，默认请求上限配置为 128,000 tokens。
- 单个任务失败后继续处理后续任务，并支持输出与转录缓存恢复。

## 快速开始

需要 Windows 11 x64、Conda、Python 3.11，以及已加入 `PATH` 的 FFmpeg 和 FFprobe。Faster Whisper 的本地依赖还需要 Microsoft Visual C++ 2015–2022 Redistributable (x64)。

在包含 `cli.py` 的项目根目录打开 PowerShell：

```powershell
conda create -n cui_ting python=3.11 -y
conda run -n cui_ting python -m pip install --upgrade pip
conda run -n cui_ting python -m pip install -r requirements.txt
conda run -n cui_ting python -m pip check
ffmpeg -version
ffprobe -version
```

开发和测试依赖位于 `requirements-dev.txt`：

```powershell
conda run -n cui_ting python -m pip install -r requirements-dev.txt
```

## 隐私文件配置

从安全示例创建本地配置，不要把真实密钥或 Cookie 提交到 Git：

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force cookie
notepad .env
```

`.env` 使用 `NANYAN_API_KEY`、`NANYAN_BASE_URL` 和 `NANYAN_MODEL`。示例中的值都是占位符，须替换为自己的 OpenAI 兼容服务配置。若修改 `config.yaml` 的 `models` 名称，环境变量前缀也要改成对应的大写名称。

Cookie 必须是 Netscape `cookies.txt` 文本格式：

- Bilibili：`cookie/bili_cookies.txt`
- YouTube 及其他站点：`cookie/youtube_cookies.txt`

公开视频有时无需 Cookie；登录、会员、年龄或风控限制通常需要有效 Cookie。`.env`、Cookie 文本和私有密钥均已被忽略。

## 批量任务配置

复制示例后编辑本地任务文件：

```powershell
Copy-Item input_data.example.json input_data.json
notepad input_data.json
```

文件必须是“任务名到 HTTP(S) URL”的 JSON 对象。任务名不能为空；Windows 非法文件名字符会被替换，清理后重名会被拒绝。不要添加注释或尾随逗号。`input_data.json` 是本地运行数据，已被 Git 忽略。

## Windows 转录与 LLM 配置

仓库中的 `config.yaml` 与本版本行为一致：

```yaml
models: [nanyan]
whisper:
  model: medium
  download_root: "D:/models"
  device: cpu
  compute_type: int8
  cpu_threads: 8
  audio_chunk_seconds: 1200
  audio_context_seconds: 15
  vad_filter: true
llm:
  max_tokens: 128000
settings:
  input_file: "input_data.json"
  output_dir: "test_case"
  chunk_size: 20480
  chunk_overlap: 256
  cookies_file: "cookie/bili_cookies.txt"
  subtitle_first: true
  enable_refine: true
```

首次本地转录时会将 `medium` 模型下载到 `D:\models`。如果 D 盘不可用，请先修改 `whisper.download_root`。只需转录时可将 `settings.enable_refine` 设为 `false`，此时无需 LLM 环境变量。

## 运行 CLI

从项目根目录执行：

```powershell
conda run --no-capture-output -n cui_ting python cli.py
```

指定其他配置文件：

```powershell
conda run --no-capture-output -n cui_ting python cli.py --config config.yaml
```

退出码 `0` 表示所有任务成功或已有完整产物而跳过；退出码 `1` 表示至少一个任务失败，或批处理启动前的配置/输入检查失败。运行后可查看 `$LASTEXITCODE`。

## 输出与断点恢复

默认输出到 `test_case/<任务名>/`。常见产物包括 `source.mp3`、`source_raw.md`、启用精炼时的 `source_refined.md`、下载字幕 `subtitle.*.vtt`，以及 `.transcription_cache/<音频名>/chunk_*.json`。长媒体可能生成 `source_part1.*`、`source_part2.*` 等分段产物。

再次运行同一任务会复用完整音频、有效下载清单、原始文本、精炼文本和有效转录块。损坏或字段不完整的块缓存会自动重建。

- 普通重试：直接重新运行 CLI。
- 重做单个转录块：删除对应 `chunk_*.json`，并删除该音频的聚合 `*_raw.md` 和 `*_refined.md` 后重跑。
- 重做某个音频：删除其 `.transcription_cache/<音频名>/` 及对应 raw/refined 文件后重跑。
- 从头重做任务：删除该任务的整个输出目录后重跑。

音频、原始文本及启用精炼时的精炼文本都完整且非空时，该任务会被判定完成并跳过。

## 常见问题

- 找不到 FFmpeg/FFprobe：重新打开 PowerShell，分别运行 `ffmpeg -version` 和 `ffprobe -version`，确认二进制目录在 `PATH`。
- Faster Whisper 导入失败或 DLL 缺失：安装 x64 Visual C++ Redistributable，重新安装 `requirements.txt`，再运行 `conda run -n cui_ting python -c "import faster_whisper"`。
- 模型目录不可写：创建 `D:\models`，或在 `config.yaml` 中改为当前用户有权限的绝对路径。
- LLM 配置失败：核对 `.env` 的三个变量名、兼容服务地址和模型占位值是否已替换；不要粘贴或分享完整环境文件。
- 下载被拒绝：重新导出相应站点的 Netscape Cookie 文本，并覆盖对应 Cookie 文件。
- CPU 转录较慢：`medium` + CPU INT8 以兼容性为目标；可调整线程数或选择更小的 Whisper 模型，但精度可能下降。

## 本地验证

```powershell
conda run -n cui_ting python -m pytest tests -q -m "not e2e"
conda run -n cui_ting python -m pip check
```

## 发布版本

本 Windows CLI 发布对应 Git 标签 `windows-v1.0.0`。
