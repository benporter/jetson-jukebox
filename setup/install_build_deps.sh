#!/usr/bin/env bash
#
# install_build_deps.sh — system packages needed to build the STT/LLM layers.
#
# Installs the CUDA toolkit (nvcc) plus build tools, and puts CUDA on PATH.
# Run once (prompts for sudo). This is a multi-GB download — expect 15-40 min.
#
#   setup/install_build_deps.sh
#
# NOTE on CUDA choice:
#   We install `cuda-toolkit-12-6` (~3GB): nvcc + CUDA runtime, which is all
#   whisper.cpp and llama.cpp CUDA builds require. If we later adopt WhisperTRT
#   (needs TensorRT) or cuDNN, install the full SDK instead:
#       sudo apt-get install -y nvidia-jetpack
set -euo pipefail

echo "==> apt update…"
sudo apt-get update

echo "==> Installing CUDA toolkit + build dependencies…"
sudo apt-get install -y \
  cuda-toolkit-12-6 \
  cmake \
  build-essential \
  ffmpeg \
  python3-pip \
  python3-venv \
  portaudio19-dev \
  libopenblas-dev

# Python runtime deps (user site, so the systemd daemon as `jetson` imports them).
# Not under sudo on purpose — --user must land in the jetson user's ~/.local.
REQS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/requirements.txt"
if [[ -f "$REQS" ]]; then
  echo "==> Installing Python runtime deps (--user) from requirements.txt…"
  python3 -m pip install --user -r "$REQS"
fi

# Put CUDA on PATH for all login shells (idempotent).
PROFILE=/etc/profile.d/cuda.sh
echo "==> Writing $PROFILE (CUDA on PATH)…"
sudo tee "$PROFILE" >/dev/null <<'EOF'
# CUDA toolkit (installed by setup/install_build_deps.sh)
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}
EOF

echo
echo "==> Verifying…"
export PATH=/usr/local/cuda/bin:$PATH
if command -v nvcc >/dev/null 2>&1; then
  nvcc --version | grep -i release || true
  echo "OK: nvcc found at $(command -v nvcc)"
else
  echo "WARNING: nvcc still not on PATH. Expected /usr/local/cuda/bin/nvcc." >&2
  ls -d /usr/local/cuda* 2>/dev/null || true
fi
cmake --version | head -1
echo
echo "==> Done. Open a NEW shell (or 'source $PROFILE') so nvcc is on PATH,"
echo "    then I can build whisper.cpp with CUDA."
