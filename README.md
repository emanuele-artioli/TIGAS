# TIGAS

[![TIGAS CI](https://github.com/emanuele-artioli/TIGAS/actions/workflows/ci.yml/badge.svg)](https://github.com/emanuele-artioli/TIGAS/actions/workflows/ci.yml)

Thin-Client Interactive Gaussian Adaptive Streaming over HTTP/3.

This implementation uses native components:

- Native renderer/encoder (`native/renderer_encoder`): C++17 + FFmpeg, GOP=1 and no B-frames.
- Transport server (`server`): HTTP/3 + WebTransport over QUIC.
- Browser client (`client`): dash.js player + WebTransport control datagrams.
- Evaluation (`evaluation`): true `libvmaf` via FFmpeg.

## Setup (one-time after clone)

Everything in this section is intended to be done once, then reused for all later runs.

### 1) Dependencies

Linux + NVIDIA full target:

- NVIDIA GPU with NVENC support (`h264_nvenc` / `hevc_nvenc`)
- Linux `tc` (for shaping)

macOS local development is supported with CPU fallback codec (for example `libx264`).

### 2) Python environment

```bash
conda env create -f environment.yaml
conda activate tigas
python -m playwright install chromium
```

### 3) Renderer build

```bash
cmake -S native/renderer_encoder -B native/renderer_encoder/build
cmake --build native/renderer_encoder/build -j
```

### 4) Dev certificates (for HTTPS/HTTP3 local runs)

```bash
bash scripts/generate_dev_cert.sh certs
```

### 5) Go modules

```bash
cd server
go mod tidy
cd ..
```

## Running

Each mode below is self-contained with the commands needed to run it.

### 1) Basic mode (trace-driven playback in DASH player)

This mode renders/encodes from movement trace + PLY, packages DASH, serves via HTTP/3, and displays in browser.

```bash
cd /Users/manu/Desktop/TIGAS

# render + encode (lossy) + metadata
native/renderer_encoder/build/tigas_renderer_encoder \
	--movement movement_traces/Linear.json \
	--output-dir artifacts/basic \
	--ply '/Users/manu/Desktop/Datasets/3DGS_PLY_sample_data/PLY(postshot)/cactus_splat3_30kSteps_142k_splats.ply' \
	--max-frames 300 \
	--fps 60 \
	--codec libx264 \
	--crf 20

# package DASH
python3 scripts/package_dash.py \
	--inputs artifacts/basic/test_stream_lossy.mp4 \
	--output artifacts/basic \
	--fps 60

# serve (terminal A)
cd server
go run ./cmd/tigas-server \
	--cert ../certs/server.crt \
	--key ../certs/server.key \
	--static ../client \
	--segments ../artifacts/basic \
	--movement ../movement_traces
```

Open `https://localhost:4433/` in browser.

### 2) Interactive mode (planned)

Status: not implemented yet. The current client sends pose datagrams from `movement_traces/Linear.json` automatically.

For now, run the same command sequence as Basic mode. When interactive controls are added, this subsection will include the extra client control step/flags.

### 3) Headless mode (no GUI)

This mode runs server + headless browser and writes artifacts (for example `control_messages.bin`, `headless_status.json`) without opening a visible UI.

```bash
cd /Users/manu/Desktop/TIGAS

# prepare stream artifacts first (same as Basic encode/package, minimal example)
native/renderer_encoder/build/tigas_renderer_encoder \
	--movement movement_traces/Linear.json \
	--output-dir artifacts/headless \
	--ply '/Users/manu/Desktop/Datasets/3DGS_PLY_sample_data/PLY(postshot)/cactus_splat3_30kSteps_142k_splats.ply' \
	--max-frames 240 \
	--fps 60 \
	--codec libx264 \
	--crf 22

python3 scripts/package_dash.py \
	--inputs artifacts/headless/test_stream_lossy.mp4 \
	--output artifacts/headless \
	--fps 60

# start server (terminal A)
cd server
go run ./cmd/tigas-server \
	--cert ../certs/server.crt \
	--key ../certs/server.key \
	--static ../client \
	--segments ../artifacts/headless \
	--movement ../movement_traces \
	--control-log ../artifacts/headless/control_messages.bin

# run headless browser (terminal B)
cd ..
python3 scripts/headless_client.py \
	--url https://localhost:4433/ \
	--duration 25 \
	--insecure \
	--status-output artifacts/headless/headless_status.json
```

### 4) Test mode (headless + ground truth + quality evaluation)

This is the end-to-end quality gate mode.

```bash
cd /Users/manu/Desktop/TIGAS

python3 scripts/run_test_mode.py \
	--movement movement_traces/Linear.json \
	--network network_traces/lte.csv \
	--ply '/Users/manu/Desktop/Datasets/3DGS_PLY_sample_data/PLY(postshot)/cactus_splat3_30kSteps_142k_splats.ply' \
	--output artifacts/test_mode \
	--codec h264_nvenc \
	--max-frames 1200
```

Useful options:

```bash
# CPU fallback
python3 scripts/run_test_mode.py ... --codec libx264 --disable-cuda

# strict per-frame SEI gate
python3 scripts/run_test_mode.py ... --require-sei-strict
```

Expected key outputs:

- `artifacts/test_mode/ground_truth_lossless.mkv`
- `artifacts/test_mode/test_stream_lossy.mp4`
- `artifacts/test_mode/stream.mpd`
- `artifacts/test_mode/vmaf_results.json`
- `artifacts/test_mode/summary.json`

Exit code:

- `0` when quality/alignment gates pass
- `2` when gates fail

## Extra commands and comments

### `tc` shaping (Linux only)

```bash
sudo python3 scripts/network_shaper.py \
	--interface eth0 \
	--trace network_traces/lte.csv \
	--latency-ms 50 \
	--loss-percent 1.0

# stop after N seconds
sudo python3 scripts/network_shaper.py \
	--interface eth0 \
	--trace network_traces/lte.csv \
	--max-seconds 120

# cleanup only
sudo python3 scripts/network_shaper.py \
	--interface eth0 \
	--trace network_traces/lte.csv \
	--cleanup-only
```

### Tests

```bash
PYTHONPATH=. python3 -m pytest -q
```

### CI

Workflow is in `.github/workflows/ci.yml`:

- `cpu-native-vmaf` on `ubuntu-latest`
- optional `nvenc-native-vmaf` on self-hosted Linux NVIDIA runner

### Notes

- On macOS, prefer `libx264` for local runs.
- If server fails with `bind: address already in use`, free port `4433` first.
- Client ABR profile endpoint is `GET /abr-profile`.
