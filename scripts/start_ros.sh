#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")/.."

compose=(docker compose -f compose.yaml -f compose.ros.yaml)
"${compose[@]}" up -d --no-build --pull never --wait models
"${compose[@]}" up -d --no-build --pull never ros
if ! "${compose[@]}" exec -T ros bash -c '
  source /opt/robocup/install/setup.bash
  timeout 90 ros2 topic echo --once --filter "m.service_name == \"base_station_diagnostics\" and m.ready" \
    /robot1/ai/status robocup_interfaces/msg/AiServiceStatus
'; then
  "${compose[@]}" logs --tail=60 ros
  exit 1
fi
echo 'ROS Domain 42 ready: /robot1/ai/chat, /robot1/ai/speak, /robot1/ai/transcribe_wav'
