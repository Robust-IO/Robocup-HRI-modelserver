#!/usr/bin/env bash
set -euo pipefail
uname -m
nvidia-smi
docker --version
docker compose version
printf '\nGPU 容器访问与 BF16 支持请在构建镜像后按部署文档检查。\n'
