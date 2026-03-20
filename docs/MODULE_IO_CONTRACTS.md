# Module I/O Contracts

This document defines stable interfaces between modules. These contracts are implementation-agnostic and are the primary compatibility boundary for ablation studies.

## 1. Uplink Datagram Contract

Fields (required):

1. `seq_id`: Monotonic unsigned integer
2. `timestamp_ms`: Sender timestamp in milliseconds
3. `camera_matrix_4x4`: Row-major 16-float camera transform
4. `requested_lod`: Symbolic LOD id (for example `full`, `sampled_50`, `quant_8bit`)
5. `target_bitrate_kbps`: Integer target bitrate

Semantics:

- Must fit in one unreliable QUIC datagram payload.
- Latest datagram supersedes earlier stale datagrams.

## 2. Pose Predictor Contract

Input:

- Current pose datagram
- Optional history window
- Current RTT estimate

Output:

- Predicted pose aligned to render time horizon
- Confidence score in [0, 1]

## 3. ABR Contract

Client-side input:

- Throughput samples
- Buffer occupancy
- Decode latency samples

Client-side output:

- Requested bitrate and fallback LOD

Server-side input:

- Render frame times
- Encoder queue depth
- GPU utilization signal

Server-side output:

- Enforced LOD
- Encoder preset override

## 4. Renderer Contract

Input:

1. `pose_matrix_4x4`
2. `lod_id`
3. `time_offset_ms`

Output:

- Raw frame buffer with metadata (`width`, `height`, `pixel_format`, `frame_id`, `is_keyframe_hint`)

## 5. Media Coder Contract

Input:

- Raw frame object
- Encoder policy (`codec`, `bitrate`, `gop`, `qp_hint`)

Output:

- Encoded access unit
- CMAF fragment bytes
- Priority class for MoQ object scheduling

## 6. Transport Contract

Input:

- Uplink control datagrams
- Downlink object fragments with priority metadata

Output:

- Delivery and timing events for instrumentation

## 7. Metrics Contract

Producer write fields:

- `component`
- `event_type`
- `timestamp_ns`
- `seq_id`
- `duration_us`
- `value`

Consumer responsibilities:

- Batch drain without blocking producers
- Flush to parquet with schema version tag
