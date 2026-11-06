#!/usr/bin/env bash
set -euo pipefail
# Downloads run in the same image used for inference; the host needs only Docker.
model_dir="${MODEL_DIR:-$(pwd)/models}"
mkdir -p "$model_dir"
model_dir="$(cd "$model_dir" && pwd)"
docker run --rm -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 -e HF_HUB_DISABLE_XET=1 --entrypoint python3 -v "$model_dir:/models" robocup-model-server:local -c '
from huggingface_hub import snapshot_download
for repo, revision, name in [
    ("Qwen/Qwen3-ASR-0.6B", "5eb144179a02acc5e5ba31e748d22b0cf3e303b0", "asr"),
    ("openbmb/MiniCPM5-2B-GPTQ", "48d57c14fba6b1f86109e1a54fafb0848c163f04", "llm-gptq"),
    ("Qwen/Qwen3-TTS-12Hz-0.6B-Base", "5d83992436eae1d760afd27aff78a71d676296fc", "tts"),
]:
    snapshot_download(repo_id=repo, revision=revision, local_dir="/models/" + name)
snapshot_download(repo_id="openbmb/MiniCPM5-2B", revision="f97400052a43d642bbc6e9975e2397e3ae6a6b52", local_dir="/models/llm", allow_patterns=["config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "chat_template.jinja"])
'
