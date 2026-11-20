#!/usr/bin/env bash
# Use the same ROS Action definitions and providers as the competition robot.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${ROBOT_AI_SRC:-}" ]]; then
  revision=4456355aa480d45d39731016b661f38a2aca214f
  checkout=".ros-source/$revision"
  if [[ ! -d "$checkout/.git" ]]; then
    git init -q "$checkout"
    git -C "$checkout" remote add origin https://github.com/Limoncello-Zoey/NankaiRoboCup2026.git
  fi
  if ! git -C "$checkout" cat-file -e "$revision^{commit}" 2>/dev/null; then
    git -C "$checkout" fetch --depth=1 --filter=blob:none origin "$revision"
  fi
  git -C "$checkout" sparse-checkout set src/ai
  git -C "$checkout" checkout -q --detach "$revision"
  export ROBOT_AI_SRC="$PWD/$checkout/src/ai"
fi

docker compose -f compose.yaml -f compose.ros.yaml up -d --build --no-deps ros
