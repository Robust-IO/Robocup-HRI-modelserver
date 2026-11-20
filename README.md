# RoboCup 模型基站

本项目在一台 NVIDIA GPU 主机上运行三个常驻模型，供局域网内的机器人或其他客户端通过 HTTP 调用：

| 服务 | 模型 | 默认端口 | 作用 |
| --- | --- | --- | --- |
| ASR | Qwen3-ASR-0.6B，BF16 | 8001 | 音频转文字 |
| LLM | MiniCPM5-2B 官方 4-bit | 8002 | 文本对话 |
| TTS | Kokoro-82M-v1.1-zh，CPU | 8003 | 固定音色的中英文语音合成 |

服务基于 `vllm/vllm-omni:v0.32.0`，依次初始化后同时常驻。ASR 和 LLM 使用上游 HTTP API，TTS 提供精简的兼容接口；比赛时可启动独立 ROS 2 容器向机器人提供模型 Action。模型权重不进入 Git 和 Docker 镜像。

## 运行环境

基站需要 NVIDIA GPU、支持 BF16 的驱动环境、Docker、Docker Compose 插件和已配置的 NVIDIA Container Toolkit。首次构建和下载模型需要网络及足够磁盘空间。此前 GPU TTS 配置在 12 GiB RTX 4080 上做过短请求检查；新的 CPU TTS 配置尚需实机验证。

在项目根目录运行宿主机检查：

```bash
./scripts/check_host.sh
```

脚本检查机器架构、`nvidia-smi`、Docker 和 Compose；它不检查容器是否能使用 GPU。构建镜像后可进一步检查容器 GPU 与 BF16：

```bash
docker run --rm --gpus all --entrypoint python3 robocup-model-server:local \
  -c 'import torch; print(torch.cuda.get_device_name()); print("bf16:", torch.cuda.is_bf16_supported())'
```

## 构建和启动

以下命令在**基站项目根目录**执行。

1. 准备本地配置。若已有 `.env`，先检查内容，避免覆盖：

   ```bash
   cp .env.example .env
   ```

2. 构建镜像，然后下载固定版本的模型：

   ```bash
   docker compose build
   ./scripts/download_models.sh
   ```

   下载脚本使用刚构建的镜像，默认将模型写入项目的 `./models`。网络中断后可重新运行脚本；运行时容器以只读方式挂载模型目录并使用离线模式。旧的 `models/tts` 不会自动删除。

   如果在 `.env` 中把 `MODEL_DIR` 改成例如 `/data/models`，下载时也必须显式指定相同目录：

   ```bash
   MODEL_DIR=/data/models ./scripts/download_models.sh
   ```

   下载脚本不会自动读取 `.env`。`models/llm-gptq` 保存官方 4-bit 权重；`models/llm` 保存与当前部署一致的原模型 tokenizer 和配置，不包含 BF16 权重。

   Kokoro 使用 sherpa-onnx 维护者提供的 ONNX 转换模型，固定版本下载到 `models/tts-kokoro-onnx`。

3. 启动容器并查看日志：

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

   按 `Ctrl+C` 退出日志跟踪，不会停止容器。服务依次启动，等待期间可在另一终端查看状态：

   ```bash
   docker compose ps
   nvidia-smi
   ```

   `healthy` 表示三个服务的健康检查通过。修改启动脚本或镜像文件后，使用 `docker compose up -d --build` 重新构建并启动；结束运行使用 `docker compose down`。

4.关闭容器
 ```bash
 docker compose stop
 ```

## 比赛基站启动（ROS 2 Domain 42）

在 Linux 基站上先按上节启动三个模型。已有模型容器正在提供服务时，直接在本仓库根目录执行：

```bash
./scripts/start_ros.sh
docker compose -f compose.yaml -f compose.ros.yaml logs -f ros
```

首次启动需 Docker Compose 2.17+、BuildKit，以及本机 Git 对比赛主仓库的读取权限。脚本取出与比赛接口匹配的固定源码，构建 Humble 镜像并后台启动 ROS 节点。日志出现 `llm: ready`、`tts: ready`、`asr_wav: ready` 后可按 Ctrl+C 退出日志。再次运行脚本会复用源码及构建缓存。如果基站已有与 Orin 相同版本的比赛源码，可以指定 `ROBOT_AI_SRC=/绝对路径/NankaiRoboCup2026/src/ai ./scripts/start_ros.sh`。

ROS 容器使用宿主机网络与默认 Fast DDS，按本仓库配置的 ASR_PORT、LLM_PORT、TTS_PORT 访问基站回环地址。Orin 和基站接入允许 DDS 组播、单播互通的局域网。在 Orin 已加载 Humble 和项目 overlay 的容器终端执行：

```bash
export ROS_DOMAIN_ID=42 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ros2 node list --no-daemon --spin-time 8
for name in chat speak transcribe_wav; do ros2 action info "/robot1/ai/$name"; done
```

每个 Action 应显示一个服务端，依次为 `/robot1/llm_node`、`/robot1/tts_node`、`/robot1/transcribe_wav_node`。Speak 的实际播放还需要 Orin 的扬声器节点。停止基站 ROS 节点使用 `docker compose -f compose.yaml -f compose.ros.yaml stop ros`。

## 局域网调用

在基站上查看局域网 IPv4 地址：

```bash
ip -brief -4 address
```

下面假设基站地址为 `192.168.3.9`。在**客户端机器**执行命令前，请将该地址替换为基站的实际地址；客户端的 `localhost` 指向客户端自己。先检查服务可达：

```bash
curl -f http://192.168.3.9:8001/v1/models
curl -f http://192.168.3.9:8002/v1/models
curl -f http://192.168.3.9:8003/v1/models
```

### 文本对话

```bash
curl -f http://192.168.3.9:8002/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "minicpm5",
    "messages": [{"role": "user", "content": "你好，请用一句话介绍你自己。"}],
    "chat_template_kwargs": {"enable_thinking": false},
    "temperature": 0,
    "max_tokens": 128
  }'
```

回答位于返回 JSON 的 `choices[0].message.content`。

### 音频转文字

客户端本地的 WAV 或 MP3 文件可通过 multipart 上传：

```bash
curl -sS -w '\nHTTP %{http_code}\n' \
  http://192.168.3.9:8001/v1/audio/transcriptions \
  -F model=qwen3-asr \
  -F file=@input.mp3
```

返回 JSON 中的 `text` 是识别结果。若返回 `Invalid or unsupported audio file`，先检查音频是否完整；扩展名为 `.mp3` 不保证文件内容可解码。若客户端已安装 FFmpeg，可尝试转换为新的 WAV 文件后重新上传：

```bash
ffmpeg -n -i input.mp3 -map 0:a:0 -vn -ac 1 -ar 16000 -c:a pcm_s16le input_asr.wav
curl -sS -w '\nHTTP %{http_code}\n' \
  http://192.168.3.9:8001/v1/audio/transcriptions \
  -F model=qwen3-asr \
  -F file=@input_asr.wav
```

`-n` 避免覆盖已有文件；若原始音频损坏，转换结果可能不完整，请检查时长和内容。

### 文字转语音

TTS 使用固定声音，无需参考音频。客户端可直接请求 WAV：

```bash
curl -f http://192.168.3.9:8003/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"model":"kokoro-tts","input":"你好，欢迎来到机器人比赛。","response_format":"wav"}' \
  -o output.wav
```

将 `response_format` 改为 `mp3` 并将输出文件改为 `output.mp3` 可请求 MP3。可选 `speed` 范围为 0.5 至 2.0；文本最多 500 字符。旧的 `qwen3-tts`、`melo-tts`、`ref_audio`、`task_type` 和音色克隆参数不适用，新接口会返回错误，不会忽略这些参数。

纯英文使用英文预设音色；含中文文本使用中文预设音色，均由 sherpa-onnx 处理文本。中英混读、实际音质和速度需在目标机验证。

## 配置与限制

- `.env` 控制模型目录、宿主机端口、显存预算及 ASR/LLM 最大序列长度；默认端口为 8001、8002、8003。
- 当前 LLM 使用官方 `MiniCPM5-2B-GPTQ` 4-bit 权重；其配置声明 AWQ 格式，不使用 CPU 权重卸载。ASR 和 LLM 默认最大序列长度均为 4096 tokens；CPU TTS 不使用 vLLM 的 KV cache，具体缓存及限制见[部署指南](docs/deployment.md)。
- 当前配置针对低显存和单请求场景；建议客户端依次调用模型。健康检查、短请求通过不代表长音频或长期运行已验证。
- 默认端口监听所有宿主机网卡，接口可在未认证的情况下访问；请只在可信网络中开放，并按需通过防火墙限制来源。
- 若客户端无法连接，检查基站 IP、局域网客户端隔离和 TCP 端口访问规则。模型输出用于机器人动作前，业务侧仍需校验。

更多 GPU 调试和离线迁移说明见[部署指南](docs/deployment.md)。
