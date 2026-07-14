# Windows CLI 与长音频转录适配设计

## 目标

将项目适配到当前 Windows 11 主机，仅交付和验证方式 C（CLI JSON 批处理）。保留方式 A/B 的 Web 源码，但不再将其纳入 Windows 依赖、文档承诺或测试范围。无平台字幕时，使用 CPU INT8 的 `faster-whisper` `medium` 模型转录；超长音频必须在调用模型前切片，并以固定内存占用顺序处理。

## 已确认的运行环境与约束

- 目标系统：64 位 Windows 11。
- 当前主机：32 GB 内存、Intel Arc 140T、无 NVIDIA CUDA。
- 已安装 FFmpeg 8.1.1 和 FFprobe 8.1.1。
- Whisper 后端：`faster-whisper`，`device=cpu`，`compute_type=int8`。
- Whisper 模型：`medium`，允许首次运行自动下载，下载与缓存根目录固定为 `D:\models`。
- 输入方式：`input_data.json` 中的“任务名称 -> Bilibili/YouTube URL”批量映射。
- Cookie 目录：`D:\work_dir\cui_ting\cookie`；Bilibili 使用 `bili_cookies.txt`，YouTube 使用 `youtube_cookies.txt`。
- LLM：OpenAI 兼容的 LiteLLM 接口，模型名 `example-model`，上下文上限 128k。
- LLM 凭据只能从 `.env`/环境变量读取，不得进入 Git、日志、测试夹具或文档。
- Python 运行环境：Conda 环境名必须为 `cui_ting`；不存在时自动按 Python 3.11 创建。

## 范围

### 本次实现

- 用 `faster-whisper` 替换 Apple Silicon 专用的 `mlx-whisper`。
- 为单个长音频和已有的多段音频增加统一的外部切片转录。
- 支持逐片缓存、失败续跑、全局时间戳恢复和重叠去重。
- 使配置、路径、任务目录名、CLI 退出码和依赖适配 Windows。
- 继续按字幕优先、Whisper 回退、LLM 清洗的顺序工作。
- 更新 README 为 Windows CLI 使用说明，并提供可复现的环境安装步骤。

### 明确不实现

- 不适配或验证方式 A/B、FastAPI、SSE、systemd、Nginx、隧道和移动端页面。
- 不使用 Intel Arc GPU；不引入 CUDA、OpenVINO 或 DirectML。
- 不增加桌面 GUI、Web UI、任务并行或分布式执行。
- 不把 Cookie 或 API Key 提交到仓库。

## 方案选择

### 方案一：一次性生成全部音频切片

实现简单、切片文件本身可用于续跑，但长音频会长期占用较多磁盘。

### 方案二：逐片生成临时音频并缓存转录结果（采用）

每次仅生成当前片的临时 WAV，转录成功后原子写入小型 JSON 缓存并删除 WAV。该方案同时限制内存与临时磁盘占用，并保留可靠的断点续传能力。

### 方案三：整段交给 `faster-whisper`

代码最少，但音频解码可能随总时长占用内存，无法满足超长音频的内存约束，因此不采用。

## 架构与组件

### 配置

`core/config.py` 扩展强类型配置，`config.yaml` 使用 Windows 可移植写法：

```yaml
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
  subtitle_first: true
  enable_refine: true
```

相对路径以配置文件所在目录为基准解析，而不是依赖启动时的当前目录。`D:/models` 与要求的 `D:\models` 指向同一路径，且避免 YAML 反斜杠转义问题。模型目录启动时自动创建。

LLM 环境变量使用一个不含密钥的模型别名，例如：

```dotenv
NANYAN_API_KEY=<secret>
NANYAN_BASE_URL=https://your-openai-compatible-endpoint.example/v1
NANYAN_MODEL=example-model
```

OpenAI 客户端会在该 `base_url` 后调用 `/chat/completions`。`max_tokens` 默认与提供的接口示例一致，但输入仍按 20,480 字符分块，并保留 256 字符重叠，不利用 128k 上限发送超大单次请求。

### 音频切片器

新增独立的音频切片单元，职责仅包括：

1. 用 FFprobe 获取音频总时长并验证结果大于零。
2. 将时间轴划分为连续的 1,200 秒核心归属区间。
3. 每个区间向前、向后各扩展最多 15 秒作为上下文，首尾裁剪到合法范围。
4. 用参数列表调用 FFmpeg，输出 16 kHz、单声道、16-bit PCM 临时 WAV；不通过 shell 拼接命令。
5. 无论成功或异常都尝试删除临时 WAV。

例如核心区间 `[1200, 2400)` 实际提取 `[1185, 2415)`。上下文用于降低边界截断导致的漏字风险，不直接决定最终归属。

### 转录器

`Transcriber` 延迟创建且在整个 CLI 进程中只创建一个 `WhisperModel`，即使批次同时含 Bilibili 与 YouTube 任务，也不能因不同 Cookie 创建两份 `medium` 模型。字幕命中时不加载或下载 Whisper 模型。

每个音频文件按如下步骤处理：

1. 根据音频路径和切片参数建立专属缓存目录。
2. 若当前片缓存合法，则直接读取，不运行 FFmpeg 或 Whisper。
3. 否则生成当前临时 WAV，并调用 `faster-whisper`；必须迭代其 segment 生成器以实际完成转录。
4. 将片内时间戳加上实际提取起点，转换为原音频全局时间戳。
5. 仅保留 segment 时间中点落在当前核心归属区间的结果；最后一个区间包含音频终点。该规则确定性地消除上下文重叠产生的重复文本。
6. 以“同目录临时 JSON -> `os.replace`”方式原子写入缓存，然后删除临时 WAV。
7. 所有片完成后按开始时间合并并返回 `TimestampedSegment` 列表。

缓存 JSON 包含 schema 版本、源文件指纹、切片参数、模型参数、片索引、核心区间、提取区间和结果 segments。源文件大小/修改时间或相关配置不匹配时，不得复用旧缓存。缓存损坏时记录警告并重做该片，不因单个坏缓存终止整个批次。

### 原始转录与 LLM 清洗

字幕和 Whisper 最终统一产生 `TimestampedSegment`。`source_raw.md` 使用 `[HH:MM:SS] 文本` 保存全局时间戳，使中断后从最终文件恢复时不会丢失时间信息。LLM 清洗继续使用现有语义分块与结构化提示词，依次请求 `example-model` 并合并输出为 `source_refined.md`。

原始文件和精炼文件继续作为阶段级断点：已有合法 `source_raw.md` 时跳过字幕/Whisper，已有合法 `source_refined.md` 时跳过 LLM。片级 JSON 只服务于尚未产出完整 raw 文件时的转录续跑。

### CLI 批处理与 Cookie

CLI 保持串行执行，避免同时运行多个 CPU `medium` 推理。Cookie 仍按 URL 域名选择，并使用项目根目录下的绝对解析路径。Cookie 缺失只告警，允许 yt-dlp 尝试无登录下载；Cookie 内容永远不记录。

任务名称需转换为安全的 Windows 目录名：替换 `< > : \ / | ? *` 和控制字符、去除尾部空格/句点、规避 `CON`、`PRN`、`AUX`、`NUL`、`COM1..9`、`LPT1..9`，并阻止 `.`、`..` 或绝对路径逃逸输出根目录。净化后重名时必须报清晰错误，而不是覆盖另一任务。

单项失败时记录异常并继续后续任务。结束时打印成功、因最终产物已存在而跳过、失败的数量和名称；全部成功返回 0，输入/配置整体无效或存在任务失败时返回非零退出码。

### 依赖与兼容性

Windows CLI 的 `requirements.txt` 只保留 CLI 所需包，并用 `faster-whisper` 替换 `mlx-whisper`。Web 源码继续留在仓库，但 FastAPI、Uvicorn 和 SQLAlchemy 不属于本次受支持安装。文档建议使用 Python 3.11 的独立虚拟环境，避免当前系统 Python 3.14 上第三方二进制轮子的兼容风险。

所有安装、测试和真实任务都必须通过名为 `cui_ting` 的 Conda 环境执行。实施开始时先运行 `conda env list`；若环境不存在，执行 `conda create -n cui_ting python=3.11 -y`，随后用 `conda run -n cui_ting ...` 安装依赖和运行命令，避免依赖交互式 shell 的 `conda activate` 状态。

启动前检查 FFmpeg 和 FFprobe；缺失时给出包含安装和 PATH 提示的可操作错误。CTranslate2 的 Windows CPU wheel 还依赖 Microsoft Visual C++ Runtime，README 需说明该前置条件。

## 数据流

1. CLI 加载配置、环境变量和任务 JSON，验证输出目录与任务名。
2. 按 URL 选择 Cookie，检查已有阶段产物。
3. yt-dlp 优先尝试平台字幕；有字幕则直接解析为带时间戳 segments。
4. 无字幕时下载音频，FFprobe 规划核心区间。
5. FFmpeg 逐片创建临时 WAV，单例 `faster-whisper medium` 顺序转录，缓存并删除 WAV。
6. 合并全局时间戳，原子写入 raw Markdown。
7. 按字符和语义边界切分 raw segments，调用 LLM 清洗，合并并原子写入 refined Markdown。
8. 输出任务级结果与批次汇总，返回对应进程退出码。

## 错误处理与安全

- 配置、输入 JSON 或模型环境变量缺失时，在开始批次前失败并给出字段名，不输出密钥值。
- 模型首次下载失败时保留现有音频和切片缓存，重跑可继续。
- FFprobe 无法读取时长、FFmpeg 返回非零或未生成有效文件时，错误必须包含工具名、源文件和安全截断后的 stderr。
- Whisper 单片失败时不写完成缓存；已完成片缓存保留。
- LLM 单块失败时不写最终 refined 文件；raw 与转录缓存保留。
- 所有最终文本和 JSON 使用临时文件加 `os.replace`，避免把半成品误认为完成。
- Cookie、Authorization header、API Key 和完整环境变量不得进入日志。
- `.env`、`cookie/*`、音频、临时 WAV 和运行缓存保持 Git 忽略。

## 测试与验收

### 自动化测试

- 配置：Windows 路径、相对路径基准、默认值、非法切片参数、模型缓存目录。
- 切片规划：短于 20 分钟、刚好 20 分钟、多个片、首尾上下文和小于上下文的极短音频。
- 时间戳：片内到全局偏移、核心区间中点归属、边界恰好相等、最后一片终点和稳定排序。
- 缓存：首次写入、有效复用、损坏重做、源指纹变化、参数变化和原子替换。
- 转录器：懒加载、CPU INT8 `medium` 参数、生成器消费、整个 CLI 进程仅一个模型实例。
- CLI：Cookie 路由、Windows 名称净化、重名拒绝、失败隔离、汇总与退出码。
- LLM：正确的模型名、`max_tokens=128000`、思考标签过滤和请求分块。

自动化测试不得真实下载模型、访问视频站或调用付费 LLM；通过依赖注入替换 FFmpeg/FFprobe、Whisper、yt-dlp 和 OpenAI 客户端，但断言真实业务输入输出，而不是只断言替身调用次数。

### 当前 Windows 主机验收

- 确认 `cui_ting` Conda 环境存在且为 Python 3.11；若原先不存在则由实施流程创建。在该环境中安装 CLI 依赖并成功导入所有核心模块。
- `ffmpeg -version`、`ffprobe -version` 和 CLI 配置检查成功。
- 使用合成的跨边界音频验证真实 FFmpeg 切片、临时文件清理和全局时间戳合并。
- 运行完整测试套件且无失败。
- 在不打印凭据的前提下验证 LLM 配置可构造客户端；真实网络请求仅在明确需要端到端任务时发生。
- README 中的 PowerShell 命令可从项目根目录直接执行。

### 四档真实视频端到端矩阵

实施阶段创建一个不含凭据的端到端视频清单，记录任务名、平台、URL、yt-dlp 实测时长和目标档位。清单必须恰好包含 4 个仍可访问、以连续语音为主的视频，并同时覆盖 YouTube 与 Bilibili（每个平台至少一个）：

| 档位 | 可接受实测时长 |
|---|---:|
| 约 5 分钟 | 3–10 分钟 |
| 约 30 分钟 | 20–40 分钟 |
| 约 1 小时 | 45–75 分钟 |
| 约 2 小时 | 100–140 分钟 |

候选链接不能只按标题或页面描述判断。必须先在 `cui_ting` 环境中用 yt-dlp 读取元数据，确认是单个可下载视频、时长落入档位且有音轨；多 P 合集的总标题时长不能冒充单个样本时长。若链接在正式测试前删除、登录受限或时长元数据变化，替换为同平台、同档位候选，并在清单中记录最终实际使用的链接。

四个样本的验收配置临时设为 `subtitle_first: false`，强制执行 FFmpeg 切片与 Whisper，不能因平台字幕存在而绕过本次核心链路。每个样本必须依次完成：

1. 使用对应平台 Cookie 下载音频。
2. 使用 CPU INT8 `medium` 转录；30 分钟及以上样本验证多个核心切片，2 小时样本验证至少 6 个 20 分钟核心切片。
3. 合并全局时间戳，检查时间单调、无越界、边界附近无完全重复 segment。
4. 调用 `example-model` 完成全部文本块清洗并生成 refined Markdown。
5. 再次运行相同批次，确认跳过下载、Whisper 和 LLM；删除一个片缓存并在没有最终 raw 文件的隔离副本中重跑，确认只重做缺失片。

真实端到端测试可能耗时较长，但不得用较小 Whisper 模型、截断音频或跳过 LLM 代替。运行中出现故障时，先保存安全的错误证据，增加能复现问题的自动化回归测试，再进行最小修复并重新执行失败档位；修复可能影响公共链路时重新执行全部四档。循环直到自动化测试与四个真实样本全部成功。

## 成功标准

- 仓库不再导入或安装 `mlx-whisper` 作为 Windows CLI 依赖。
- `medium` 模型首次运行下载到 `D:\models`，之后从该目录复用。
- 任意时长单音频都在模型调用前切成最多 1,230 秒（20 分钟核心加两侧上下文）的临时片，且任一时刻最多存在一个当前临时 WAV。
- 转录结果时间戳相对原始音频连续、全局正确，重叠上下文不产生重复 segment。
- 中断后能够复用所有已完成片缓存，不重做已成功片。
- Bilibili/YouTube Cookie 自动选择正确，且敏感信息不进入 Git 或日志。
- CLI 批次中一个任务失败不会阻断后续任务，最终退出码能被脚本可靠判断。
- Windows 方式 C 的安装、配置、批处理、断点续传和输出结构有完整文档；方式 A/B 不作支持承诺。
- 所有操作均在 `cui_ting` Conda Python 3.11 环境完成，且 5m、30m、1h、2h 四档真实 YouTube/Bilibili 视频均完成下载、强制 Whisper 转录、LLM 清洗和续跑验证。
