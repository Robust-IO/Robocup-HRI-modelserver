#!/usr/bin/env bash
set -Eeuo pipefail
pids=()
cleanup() {
  trap - TERM INT EXIT
  if ((${#pids[@]})); then
    kill -TERM "${pids[@]}" 2>/dev/null || true
    wait || true
  fi
}
trap 'exit 143' TERM
trap 'exit 130' INT
trap cleanup EXIT

vllm serve /models/asr --served-model-name qwen3-asr --host 0.0.0.0 --port 8001 --dtype bfloat16 --gpu-memory-utilization "${ASR_GPU_MEMORY:-0.25}" --max-model-len "${ASR_MAX_MODEL_LEN:-4096}" &
pids+=("$!")
vllm serve /models/llm --served-model-name minicpm5 --host 0.0.0.0 --port 8002 --dtype bfloat16 --gpu-memory-utilization "${LLM_GPU_MEMORY:-0.30}" --max-model-len "${LLM_MAX_MODEL_LEN:-4096}" &
pids+=("$!")
vllm serve /models/tts --omni --served-model-name qwen3-tts --host 0.0.0.0 --port 8003 --dtype bfloat16 --gpu-memory-utilization "${TTS_GPU_MEMORY:-0.25}" &
pids+=("$!")
wait -n "${pids[@]}"
status=$?
echo "A model service exited (status $status); stopping the container." >&2
exit "$status"
