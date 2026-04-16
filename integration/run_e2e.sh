#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
uv run python integration/run_e2e.py
