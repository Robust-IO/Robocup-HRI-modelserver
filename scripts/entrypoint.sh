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

wait_ready() {
  local port=$1 deadline=$((SECONDS + 600)) pid
  while (( SECONDS < deadline )); do
    for pid in "${pids[@]}"; do
      if ! kill -0 "$pid" 2>/dev/null; then
        echo "A model service exited during startup; stopping the container." >&2
        return 1
      fi
    done
    if python3 -c 'import sys, urllib.request; urllib.request.urlopen("http://127.0.0.1:" + sys.argv[1] + "/health", timeout=2).close()' "$port" 2>/dev/null; then
      return 0
    fi
    sleep 2
  done
  echo "Service on port $port did not become healthy within 600 seconds." >&2
  return 1
}

vllm serve /models/asr --served-model-name qwen3-asr --host 0.0.0.0 --port 8001 --dtype bfloat16 --gpu-memory-utilization "${ASR_GPU_MEMORY:-0.30}" --max-model-len "${ASR_MAX_MODEL_LEN:-4096}" --enforce-eager --max-num-seqs 1 --max-num-batched-tokens 2048 &
pids+=("$!")
wait_ready 8001
vllm serve /models/llm-gptq --tokenizer /models/llm --served-model-name minicpm5 --host 0.0.0.0 --port 8002 --dtype bfloat16 --gpu-memory-utilization "${LLM_GPU_MEMORY:-0.55}" --max-model-len "${LLM_MAX_MODEL_LEN:-4096}" --enforce-eager --max-num-seqs 1 --max-num-batched-tokens 2048 --kv-cache-memory-bytes 268435456 &
pids+=("$!")
wait_ready 8002
vllm serve /models/tts --omni --deploy-config /app/scripts/qwen3_tts.yaml --served-model-name qwen3-tts --host 0.0.0.0 --port 8003 --dtype bfloat16 --gpu-memory-utilization "${TTS_GPU_MEMORY:-0.25}" &
pids+=("$!")
wait_ready 8003
status=0
wait -n "${pids[@]}" || status=$?
echo "A model service exited (status $status); stopping the container." >&2
exit "$status"
