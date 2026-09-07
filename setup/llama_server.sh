#!/usr/bin/env bash
#
# llama_server.sh — run the local LLM (Qwen2.5-1.5B-Instruct) for intent parsing.
#
# Serves an OpenAI-compatible API on :8080. The voice app posts the transcript
# to /v1/chat/completions and gets back a JSON intent (see src/intent.py).
#
#   setup/llama_server.sh            # foreground
# Persistent (boot) service comes later (Phase 5 systemd).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER="$REPO/tools/llama.cpp/build/bin/llama-server"
MODEL="$REPO/models/qwen2.5-1.5b-instruct-q4_k_m.gguf"

export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}

[[ -x "$SERVER" ]] || { echo "llama-server not built at $SERVER" >&2; exit 1; }
[[ -f "$MODEL"  ]] || { echo "model not found at $MODEL" >&2; exit 1; }

exec "$SERVER" \
  --model "$MODEL" \
  --host 127.0.0.1 --port "${LLAMA_PORT:-8080}" \
  --n-gpu-layers 99 \
  --ctx-size 2048 \
  --threads "$(nproc)" \
  --no-warmup
