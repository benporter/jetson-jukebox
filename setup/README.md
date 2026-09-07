# setup/

Scripts and instructions to provision the Jetson for this project. External
tools (cloned repos, downloaded models) are **not** committed — recreate them
with the steps here.

## node-sonos-http-api (Sonos control)

Cloned to `tools/node-sonos-http-api/` (gitignored). Recreate:

```bash
# Node is installed in userland via nvm (no sudo):
#   curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
#   nvm install --lts
cd tools
git clone --depth 1 https://github.com/jishi/node-sonos-http-api.git
cd node-sonos-http-api
npm install --no-audit --no-fund
```

Then create `tools/node-sonos-http-api/settings.json` (gitignored) from the
template at `config/sonos-settings.example.json` and fill in your Spotify
Client ID / Secret.

Run it (listens on :5005, auto-discovers Sonos on the LAN):

```bash
cd tools/node-sonos-http-api && node server.js
```

> Auto-start on boot is a later (Phase 5) systemd task; for now run it manually.

## Build dependencies (CUDA toolkit, cmake, ffmpeg, …)

Needed before building the STT (whisper.cpp) and LLM (llama.cpp) layers. The
base JetPack image ships `gcc`/`make` but not the CUDA toolkit, cmake, pip, or
ffmpeg. Install them (multi-GB, ~15–40 min, prompts for sudo):

```bash
setup/install_build_deps.sh
```

Installs `cuda-toolkit-12-6` (nvcc + CUDA runtime — enough for whisper.cpp and
llama.cpp CUDA builds), `cmake`, `build-essential`, `ffmpeg`, `python3-pip/venv`,
`portaudio19-dev`, `libopenblas-dev`, and puts CUDA on PATH via
`/etc/profile.d/cuda.sh`. For TensorRT/cuDNN (e.g. WhisperTRT) install the full
`nvidia-jetpack` instead. Open a new shell afterward so `nvcc` is on PATH.

> GPU is Orin (Ampere), compute capability **sm_87** → build with
> `CMAKE_CUDA_ARCHITECTURES=87`.

## whisper.cpp (STT engine)

Cloned to `tools/whisper.cpp/` (gitignored). Requires the CUDA toolkit + cmake
(see build deps above). Recreate + build with CUDA for the Orin (sm_87):

```bash
cd tools
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
bash ./models/download-ggml-model.sh base.en          # ~142MB model
export PATH=/usr/local/cuda/bin:$PATH
cmake -B build -DGGML_CUDA=1 -DCMAKE_CUDA_ARCHITECTURES=87 -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)" --config Release
# smoke test (should log "using CUDA0 backend"):
./build/bin/whisper-cli -m models/ggml-base.en.bin -f samples/jfk.wav
```

The CUDA build takes ~20 min on the Orin Nano (compiling ggml CUDA kernels).

## llama.cpp (intent-parsing LLM)

Cloned to `tools/llama.cpp/` (gitignored). Build with CUDA (sm_87) and fetch the
Qwen2.5-1.5B-Instruct model:

```bash
cd tools
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
export PATH=/usr/local/cuda/bin:$PATH
cmake -B build -DGGML_CUDA=1 -DCMAKE_CUDA_ARCHITECTURES=87 -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)" --target llama-server llama-cli --config Release

# model (~941MB) into repo models/ (gitignored):
cd ../../models
wget -O qwen2.5-1.5b-instruct-q4_k_m.gguf \
  https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
```

Run the server (OpenAI-compatible API on :8080, all layers on GPU):

```bash
setup/llama_server.sh
```

`src/intent.py` posts the transcript to it and gets back a JSON command
(`{"type":"song","title":...,"artist":...}` etc.). Boot service is a later
(Phase 5) systemd task.

## ReSpeaker XVF3800 mic — control tools + LED

Host-control utility cloned to `tools/reSpeaker_XVF3800_USB_4MIC_ARRAY/`
(gitignored). Recreate:

```bash
cd tools
git clone --depth 1 https://github.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY.git
```

The aarch64 binary lives at `host_control/jetson/xvf_host`. One-time setup
(udev rule for non-root access + boot "LEDs off" service + turns LEDs off now;
prompts for sudo):

```bash
setup/install_respeaker.sh
```

Then control the LED ring (no sudo needed after the udev rule):

```bash
setup/respeaker_led.sh off      # idle
setup/respeaker_led.sh breath   # e.g. "listening" indicator
# modes: off | breath | rainbow | single | doa  (or 0-4)
```

The voice app lights the ring while listening and turns it off when done.

## sonos_play.sh — play a song by name

Resolves a query to a Spotify track id and plays it on a room. See
`docs/sonos-notes.md` for why this bypasses the library's `musicsearch`.

```bash
setup/sonos_play.sh "thunderstruck acdc"
setup/sonos_play.sh "let it go idina menzel" "Boys Room"
KEEP_QUEUE=1 setup/sonos_play.sh "baby shark"   # don't clear the queue first
```
