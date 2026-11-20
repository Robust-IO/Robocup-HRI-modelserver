#!/usr/bin/env bash
set -eo pipefail
source /opt/robocup/install/setup.bash
config=/tmp/robocup-models.yaml
cat > "$config" <<YAML
/**:
  ros__parameters:
    ai.allow_real_backends: true
    asr.base_url: 'http://127.0.0.1:${ASR_PORT:-8001}'
    asr.http_model: qwen3-asr
    llm.backend: http
    llm.base_url: 'http://127.0.0.1:${LLM_PORT:-8002}'
    llm.model: minicpm5
    tts.backend: http
    tts.base_url: 'http://127.0.0.1:${TTS_PORT:-8003}'
    tts.http_model: kokoro-tts
    tts.speed: 0.7
YAML
exec ros2 launch robocup_ai_bringup base_station.launch.py asr_input:=wav \
  "asr_config:=$config" "llm_config:=$config" "tts_config:=$config"
