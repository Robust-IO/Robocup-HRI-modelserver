# 部署与调试

本项目当前未经构建和硬件测试，以下为远端调试入口。基础镜像为 `vllm/vllm-omni:v0.32.0`，包含对应 vLLM；如果目标架构或 GPU 不受该镜像支持，需要选择并验证对应镜像。三个模型固定 revision 见 `scripts/download_models.sh`。

## GPU 和 BF16

构建后可检查容器 GPU 和 PyTorch 对 BF16 的判断：

```bash
docker run --rm --gpus all --entrypoint python3 robocup-model-server:local -c 'import torch; print(torch.cuda.get_device_name()); print("bf16:", torch.cuda.is_bf16_supported())'
```

必须验证 GPU 实际支持 BF16、服务启动日志和真实推理。三个进程的 GPU memory utilization 不是显存硬隔离：并发初始化、CUDA 上下文、TTS 多阶段和临时内存均会影响总量。根据目标 GPU 调整 `.env`；无法加载时检查 `docker compose logs` 和 `nvidia-smi`。三个模型必须同时常驻，不提供卸载切换模式。

## 调用示例

```bash
curl -f http://localhost:8001/v1/models
curl -f http://localhost:8002/v1/models
curl -f http://localhost:8003/v1/models
curl -f http://localhost:8001/v1/audio/transcriptions -F model=qwen3-asr -F file=@input.wav
curl -f http://localhost:8002/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"minicpm5","messages":[{"role":"user","content":"你好"}],"max_tokens":128}'
```

TTS Base 使用参考音频克隆声音。参考音频及文本的请求字段应遵循所选版本的 [vLLM-Omni Speech API](https://docs.vllm.ai/projects/vllm-omni/en/stable/serving/speech_api/)，并在远端验证该版本支持 0.6B Base。ASR 的实时接口与普通文件转写是不同能力，远端需单独验证；本仓库尚未实现 ROS 适配层或端到端对话。

## 离线迁移

在联网机器构建镜像、下载模型后，使用 `docker save -o robocup-model-server.tar robocup-model-server:local` 导出镜像，复制 tar、仓库及模型目录到目标机；使用 `docker load -i robocup-model-server.tar` 导入，配置 `.env` 后运行 `docker compose up -d`。模型目录包含完整 tokenizer、配置和权重。请勿把模型目录、录音或 `.env` 提交到 Git。

端口默认绑定所有宿主机网卡；请通过可信网络或防火墙限制访问。模型服务输出不直接授权机器人动作，业务侧仍须校验结构化结果。
