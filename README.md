# TIGAS

[![TIGAS CI](https://github.com/emanuele-artioli/TIGAS/actions/workflows/ci.yml/badge.svg)](https://github.com/emanuele-artioli/TIGAS/actions/workflows/ci.yml)

Thin-Client Interactive Gaussian Adaptive Streaming over HTTP/3.

This implementation uses native components:

- Native renderer/encoder (`native/renderer_encoder`): C++17 + FFmpeg, GOP=1 and no B-frames.
- Transport server (`server`): HTTP/3 + WebTransport over QUIC.
- Browser client (`client`): dash.js player + WebTransport control datagrams.
- Evaluation (`evaluation`): true `libvmaf` via FFmpeg.

## Setup (one-time after clone)

Everything in this section is intended to be done once, right after cloning the repository.

### 1) Dependencies

Linux + NVIDIA full target:

- NVIDIA GPU with NVENC support (`h264_nvenc` / `hevc_nvenc`)
- Linux `tc` (for shaping)

macOS local development is supported with CPU fallback codec (for example `libx264`). Other setups could also work but have not been tested.

### 2) Python environment

```bash
cd /Users/manu/Desktop/TIGAS && conda activate tigas

conda env create -f environment.yaml
python -m playwright install chromium
```

### 3) Renderer build

```bash
cd /Users/manu/Desktop/TIGAS && conda activate tigas

cmake -S native/renderer_encoder -B native/renderer_encoder/build
cmake --build native/renderer_encoder/build -j
```

### 4) Dev certificates (for HTTPS/HTTP3 local runs)

```bash
cd /Users/manu/Desktop/TIGAS && conda activate tigas

bash scripts/generate_dev_cert.sh certs
```

This generates a CA-signed leaf certificate chain and prints an **SPKI hash** saved to `certs/spki.hash`.
Chrome requires this hash via `--ignore-certificate-errors-spki-list=<hash>` — the standard
`--ignore-certificate-errors` flag does **not** apply to QUIC connections.

### 5) Go modules

```bash
cd /Users/manu/Desktop/TIGAS && conda activate tigas

cd server
go mod tidy
cd ..
```

## Running

Each mode below is self-contained with the commands needed to run it.

### 1) Basic mode

Basic mode is live by design: rendering, encoding, CMAF chunk creation, and HTTP/3 serving happen concurrently.
It now auto-opens Chrome on the DASH-IF reference player, preloaded with your local MPD.

```bash
cd /Users/manu/Desktop/TIGAS && conda activate tigas

python3 scripts/run_basic_mode.py \
	--movement movement_traces/Linear.json \
	--ply '/Users/manu/Desktop/Datasets/3DGS_PLY_sample_data/PLY(postshot)/cactus_splat3_30kSteps_142k_splats.ply' \
	--output artifacts/basic \
	--max-frames 1800 \
	--fps 60 \
	--codec libx264 \
	--crf 20
```

The command prints the MPD URL and launches a QUIC/SPKI-configured Chrome profile directly on the DASH-IF reference player.

The built-in default is DASH-IF reference player auto-launch, but you can copy the printed MPD URL into other dash.js players too.

Because the server is QUIC-only (no TCP fallback), if you launch manually you still need QUIC/SPKI flags:

```bash
cd /Users/manu/Desktop/TIGAS && conda activate tigas
scripts/launch_quic_chrome.sh https://localhost:4433/
```

Notes:

- Firefox is not supported for this QUIC/WebTransport path.
- If using a different port (for example `--addr :4443`), pass the matching URL to `launch_quic_chrome.sh`.
- The launcher uses an isolated temporary Chrome profile and forces QUIC for the target origin.
- Console lines about GCM/Updater/Crashpad are expected noise and are not TIGAS failures.
- If browser still cannot connect, first verify server is running: `lsof -nP -iUDP:4433` (or your selected port).
- The launcher writes a netlog at `/tmp/tigas-quic-netlog-YYYYmmdd-HHMMSS.json` for deeper QUIC diagnostics.
- By default `run_basic_mode.py` keeps the QUIC server alive for 120 seconds after producer completion (`--linger-seconds`).

### 2) Interactive mode (planned)

Status: user-input controls (mouse/keyboard camera navigation) are not implemented yet. The current client sends pose datagrams from `movement_traces/Linear.json` automatically.

### 3) Test mode (basic-mode live path + headless + quality evaluation)

This is the end-to-end quality gate mode. It reuses the live basic-mode path internally (server + live DASH), then extends it with headless playback verification, ground-truth/lossy exports, frame extraction, and VMAF/alignment checks.

```bash
cd /Users/manu/Desktop/TIGAS && conda activate tigas

python3 scripts/run_test_mode.py \
	--movement movement_traces/Linear.json \
	--network network_traces/lte.csv \
	--ply '/Users/manu/Desktop/Datasets/3DGS_PLY_sample_data/PLY(postshot)/cactus_splat3_30kSteps_142k_splats.ply' \
	--output artifacts/test_mode \
	--codec h264_nvenc \
	--max-frames 300
```

Useful options:

```bash
# CPU fallback
python3 scripts/run_test_mode.py ... --codec libx264 --disable-cuda

# strict per-frame SEI gate
python3 scripts/run_test_mode.py ... --require-sei-strict
```

Expected key outputs:

- `artifacts/test_mode/live/stream.mpd`
- `artifacts/test_mode/live/headless_status.json`
- `artifacts/test_mode/evaluation/ground_truth_lossless.mkv`
- `artifacts/test_mode/evaluation/test_stream_lossy.mp4`
- `artifacts/test_mode/frames/ground_truth/*.png`
- `artifacts/test_mode/frames/lossy/*.png`
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
