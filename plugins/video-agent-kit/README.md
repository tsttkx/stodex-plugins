# Video Agent Kit

在 Stodex 会话里查看画面、剪视频、做字幕和配音。插件随 Stodex 市场安装两个本地 MCP 服务、14 个技能、两个会话命令和七个审阅角色。

## 开始使用

1. 在 Stodex 的插件广场选择 Video Agent Kit 并安装。
2. 在聊天框输入 `/`，选择本插件的 `setup-guide`。它会检查实际启动 MCP 的 Python、FFmpeg、FFprobe 和可用语音引擎。
3. 选择同一插件的 `video-edit`，或直接描述任务。例如“把我选的视频剪出第 2 到 8 秒，加一句标题字幕，另存为 MP4”。从本地文件开始即可剪辑，输出总是写入新的文件。

## 运行条件

本机需 Python 3.10 或以上。FFmpeg 和 FFprobe 可在 PATH 中，也可通过用户目录中的 `.stodex/video-agent-kit.json` 的 `ffmpeg_dir` 字段指定可执行文件所在目录。更换 Python 时可在启动 Stodex 前设置 `STODEX_PLUGIN_PYTHON`。插件以 Python 隔离模式启动，附加 Python 包须安装在它实际使用的解释器环境中。

在「设置 → 视频与音频模型」中可为以下用途分别配置服务。本地剪辑、字幕、抽帧、素材拼接、静音检测和动画帧编码都直接调用 FFmpeg。

| 用途 | 本机 | 兼容 API |
| --- | --- | --- |
| 语音转文字 | faster-whisper 及其权重，或 whisper.cpp 命令和 GGML 模型 | `/audio/transcriptions` |
| 文字转语音 | Windows 系统语音、macOS say 或 Linux espeak-ng | `/audio/speech`，输出 WAV |
| 视频生成 | 运行中的 ComfyUI、已安装模型和可输出视频的 API 工作流 | 提交 `/videos`，用任务 ID 查询状态和下载 |

剪辑、提取时间点截图和视频信息可以直接使用。视频理解与录屏复刻还需要会话模型能够读取返回的画面；多人镜头替换需要提供对齐的替换素材和灰度遮罩。语音识别返回引擎提供的时间戳；只有纯文本时，应先核对时间轴再制作字幕。远端生成的模型名称、尺寸、时长、语音和额度由用户所选的服务提供。密钥由 Stodex 本机设置管理。

`video-edit` 服务提供媒体和模型工具。`runtime` 提供环境检查和仅绑定本机的静态构建预览。每个项目可以使用同一份本机媒体设置。
