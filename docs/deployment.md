# 部署与调试

基础镜像为 `vllm/vllm-omni:v0.32.0`；三个模型固定 revision 见 `scripts/download_models.sh`。4-bit 配置需要在目标 GPU 上验证真实推理和显存余量。

## GPU 和 BF16

构建后可检查容器 GPU 和 PyTorch 对 BF16 的判断：

```bash
docker run --rm --gpus all --entrypoint python3 robocup-model-server:local -c 'import torch; print(torch.cuda.get_device_name()); print("bf16:", torch.cuda.is_bf16_supported())'
```

必须验证 GPU 实际支持 BF16、服务启动日志和真实推理。三个进程的 GPU memory utilization 不是显存硬隔离：并发初始化、CUDA 上下文、TTS 多阶段和临时内存均会影响总量。根据目标 GPU 调整 `.env`；无法加载时检查 `docker compose logs` 和 `nvidia-smi`。三个模型必须同时常驻，不提供卸载切换模式。

服务按 ASR、LLM、TTS 顺序启动，每个服务通过健康检查后才启动下一个；单个服务最多等待 10 分钟。串行初始化可避免各服务同时进行显存探测，但不能保证显存足够。修改启动脚本后需重新构建镜像：`docker compose up -d --build`。

低显存配置将 ASR 和 LLM 设为 eager 模式及单请求并发；LLM 使用官方 `MiniCPM5-2B-GPTQ` 4-bit 权重及原模型 tokenizer，不使用 CPU 权重卸载。该模型当前配置声明 AWQ 格式。LLM 最大上下文为 4096 tokens，KV cache 固定为 256 MiB；TTS talker 为 4096 tokens、512 MiB KV cache，两个阶段的并发上限为 1。

官方 4-bit 版本在单模型小样本数学检查中得到 12/12 个正确数学结果，尚未完成比赛指令、结构化输出和长时间运行评测。

ASR 默认最大序列长度为 4096，使用 0.30 显存比例自动确定 KV cache。手动 KV cache 值跳过自动显存探测，不保证其他 GPU 或负载条件下有足够空间。提高长度上限时要重新验证缓存容量和显存；长度包含输入和输出 token，不能直接换算为固定音频秒数。

TTS Code2Wav 阶段使用 eager 模式，以减少 CUDA graph 的显存占用；会影响启动及推理性能，应以真实语音工作负载测量。

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
