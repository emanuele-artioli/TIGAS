# TIGAS

[![TIGAS CI](https://github.com/emanuele-artioli/TIGAS/actions/workflows/ci.yml/badge.svg)](https://github.com/emanuele-artioli/TIGAS/actions/workflows/ci.yml)

Thin-Client Interactive Gaussian Adaptive Streaming over HTTP/3.

This implementation follows the blueprint architecture with native components:

- **Native renderer/encoder** (`native/renderer_encoder`): C++17, FFmpeg libavcodec/libavformat, NVENC-first encoding path, GOP=1 and no B-frames.
- **Transport server** (`server`): HTTP/3 + WebTransport over QUIC, shared origin for DASH chunks and control datagrams.
- **Browser client** (`client`): dash.js ULL playback + WebTransport datagram 6DoF control channel.
- **Evaluation** (`evaluation`): true `libvmaf` via FFmpeg.
- **Orchestration scripts** (`scripts`): build, package CMAF DASH, run test mode, headless client, network shaping (`tc`).

## Dependencies

### Linux + NVIDIA (full pipeline)

- NVIDIA GPU with NVENC support (`h264_nvenc` / `hevc_nvenc`)
- FFmpeg 6+ with `libvmaf`
- CMake 3.20+
- Go 1.23+
- Chrome/Chromium
- Linux `tc` (for trace-based network shaping)

### Python tooling

```bash
conda env create -f environment.yaml
conda activate tigas
python -m playwright install chromium
```

## Build native renderer/encoder

```bash
cmake -S native/renderer_encoder -B native/renderer_encoder/build
cmake --build native/renderer_encoder/build -j
```

Binary output:

- `native/renderer_encoder/build/tigas_renderer_encoder`

## Run end-to-end test mode (native + true VMAF)

```bash
python3 scripts/run_test_mode.py \
	--movement movement_traces/Linear.json \
	--network network_traces/lte.csv \
	--ply /Users/manu/Desktop/Datasets/3DGS_PLY_sample_data/PLY(postshot)/cactus_splat3_30kSteps_142k_splats.ply \
	--output artifacts/test_mode \
	--codec h264_nvenc \
	--max-frames 1200
```

Outputs:

- `artifacts/test_mode/ground_truth_lossless.mkv`
- `artifacts/test_mode/test_stream_lossy.mp4`
- `artifacts/test_mode/frame_metadata.csv`
- `artifacts/test_mode/sei_messages.json`
- `artifacts/test_mode/stream.mpd` and `chunk_*.m4s`
- `artifacts/test_mode/vmaf_results.json`
- `artifacts/test_mode/summary.json`

Exit code:

- `0` when `vmaf_mean >= 80`
- `2` when below threshold

## HTTP/3 + WebTransport server

Generate local TLS certs:

```bash
bash scripts/generate_dev_cert.sh certs
```

Run server:

```bash
cd server
go mod tidy
go run ./cmd/tigas-server \
	--cert ../certs/server.crt \
	--key ../certs/server.key \
	--static ../client \
	--segments ../artifacts/test_mode \
	--movement ../movement_traces
```

## Headless browser execution

```bash
python3 scripts/headless_client.py --url https://localhost:4433/ --duration 60 --insecure
```

## Network shaping (`tc`, Linux only)

```bash
sudo python3 scripts/network_shaper.py \
	--interface eth0 \
	--trace network_traces/lte.csv \
	--latency-ms 50 \
	--loss-percent 1.0
```

## Tests

```bash
PYTHONPATH=. pytest -q
```

## CI

GitHub Actions workflow is defined in `.github/workflows/ci.yml` with:

- `cpu-native-vmaf`: always runs on `ubuntu-latest`, builds native pipeline with `libx264`, computes true VMAF, and fails when `vmaf_mean < 80`.
- `nvenc-native-vmaf`: optional (`workflow_dispatch` input `run_nvenc=true`) on `self-hosted,linux,x64,nvidia`, validates `h264_nvenc` + true VMAF.

PR quality comments:

- CPU job auto-comments on pull requests.
- NVENC manual runs can update the same PR comment by passing `pr_number` in `workflow_dispatch`.

The workflow uses `assets/sample_cube_ascii.ply` as an in-repo deterministic CI asset.

## Notes

- `tc` shaping and NVENC require Linux + NVIDIA; on macOS, use a fallback codec (e.g. `libx264` or `h264_videotoolbox`) for local functional validation.
- The server and client are structured so DASH requests and WebTransport datagrams share QUIC/HTTP3 as required by the blueprint.
