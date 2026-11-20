#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
exec docker compose -f compose.yaml -f compose.ros.yaml stop ros models
