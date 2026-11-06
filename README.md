# RoboCup 模型基站

一个容器同时运行三个常驻 BF16 模型：Qwen3-ASR-0.6B、MiniCPM5-2B 和 Qwen3-TTS-12Hz-0.6B-Base。基于官方 vLLM-Omni CUDA 镜像；ASR、LLM 使用 vLLM，TTS 使用 vLLM-Omni。模型权重不进入 Git 和镜像。

**当前为待远端调试的初版，尚未构建或在 GPU 上验证。** 三服务同时运行需要支持 BF16 的 NVIDIA GPU 和足够显存；Ubuntu、驱动、GPU 架构及镜像组合必须实测。原项目的 8 GiB 显卡已有显存不足记录。

## 快速开始

安装 NVIDIA 驱动、Docker、Compose 插件和 NVIDIA Container Toolkit，确认 Docker 已配置 GPU runtime。然后：

```bash
cp .env.example .env
./scripts/check_host.sh
docker compose build
./scripts/download_models.sh
docker compose up -d
docker compose logs -f
```

等待三个服务加载，使用 `docker compose ps` 查看健康状态。模型默认下载到 `./models`；如修改 `.env` 中的 `MODEL_DIR`，下载时也要指定同一路径，例如 `MODEL_DIR=/data/models ./scripts/download_models.sh`。首次下载需要网络及足够磁盘；运行时使用本地只读模型，不联网下载。

API 地址默认为 ASR `http://localhost:8001`、LLM `http://localhost:8002`、TTS `http://localhost:8003`。示例与部署限制见 [部署指南](docs/deployment.md)。接口目前直接使用上游 API，没有 ROS 依赖。监听地址映射至宿主机，请只在可信网络中开放端口。
