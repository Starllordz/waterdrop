#!/usr/bin/env bash
# Waterdrop launcher (Linux / macOS).
set -euo pipefail
cd "$(dirname "$0")"
exec python3 launch.py
