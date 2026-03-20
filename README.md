# TIGAS low-latency H.264 frame pipeline

This folder now contains a per-frame H.264 transport pipeline for TIGAS remote
rendering. The old JPEG-only path is still available as a baseline mode.

The pipeline is designed for low motion-to-photon latency and supports:

- Hardware-preferred H.264 encoding (`h264_nvenc` on Linux, `h264_videotoolbox` on macOS)
- Zero-latency tuning (`zerolatency` where supported)
- No B-frames (`bframes=0` / `bf=0`)
- Periodic Intra-Refresh (`intra-refresh=1`) instead of large periodic IDRs
- Slice-oriented low-latency operation (`sliced-threads=1` where supported)
- Immediate per-frame emission after encoding
- NAL-unit packetization for MTU-safe transport over QUIC datagrams/unreliable streams
- Loss-tolerant client reassembly + decode without ARQ
- ABR that adjusts encoder bitrate/CRF dynamically

## Main files

- `tigas_video_pipeline.py`
	- `VideoEncoder`: low-latency H.264 encoder wrapper (PyAV/FFmpeg backend)
	- `StreamManager`: frame -> NAL units -> QUIC packets
	- `VideoDecoder`: reassembly buffer and decode path
	- `LatencyAwareAbrController`: updates bitrate/CRF from timing + network signals
- `render_websplat_frames.py`
	- Renders hardcoded 6DoF poses from WebSplat and runs either:
		- `--mode h264` (default): H.264 packet stream + loopback decode + ABR updates
		- `--mode jpeg`: legacy JPEG frame dump
- `smoke_test_video_pipeline.py`
	- Synthetic-frame test for encode -> packetize -> decode -> ABR loop

## Hardcoded dataset paths

- PLY: `/home/itec/emanuele/Datasets/3DGS/garden/point_cloud/iteration_30000/point_cloud.ply`
- Scene: `/home/itec/emanuele/Datasets/3DGS/garden/cameras.json`

## Setup

```bash
cd /home/itec/emanuele/TIGAS
conda activate tigas
pip install -r requirements.txt
```

## Run H.264 per-frame pipeline

```bash
cd /home/itec/emanuele/TIGAS
conda activate tigas
python render_websplat_frames.py --mode h264 --save-decoded
```

Useful options:

- `--force-software` to disable hardware codec preference
- `--codec-candidates "h264_nvenc,libx264,h264"` to force codec order
- `--mtu-bytes 1500` to match path MTU assumptions
- `--max-encode-width 4096 --max-encode-height 2304` to cap encode size when software H.264 backends have resolution limits
- `--target-mtp-ms 100` to tune ABR latency budget
- `--simulate-loss 0.02` to emulate packet drops

Outputs:

- Packet dumps: `outputs/websplat_h264_packets/frame_XXXX.qpk`
- Optional decoded loopback frames: `outputs/websplat_h264_decoded/frame_XXXX.jpg`

Notes:

- WebSplat may emit odd frame dimensions. The pipeline automatically crops to
	the nearest even width/height so `yuv420p` H.264 encoders can initialize.

## Run JPEG baseline

```bash
cd /home/itec/emanuele/TIGAS
conda activate tigas
python render_websplat_frames.py --mode jpeg
```

Output directory:

- `outputs/websplat_jpg_frames`

## Run smoke test

```bash
cd /home/itec/emanuele/TIGAS
conda activate tigas
python smoke_test_video_pipeline.py
```

## Integration notes for real QUIC transport

- `StreamManager.emit_frame(...)` emits packets immediately and can write directly
	to QUIC datagrams.
- Packet metadata includes frame/NAL/fragment indices so client reassembly can
	complete a frame without waiting for segment boundaries.
- The decoder drops stale incomplete frames, then relies on inter-frame recovery
	via intra-refresh instead of retransmission.
