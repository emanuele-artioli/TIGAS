# Runtime Dataflow

This document describes the intended end-to-end dataflow for both interactive and headless execution.

## Interactive Mode Sequence

1. Browser samples camera pose and local bandwidth estimate.
2. Browser serializes uplink datagram with pose and bitrate intent.
3. Server receives datagram over unreliable QUIC.
4. Intelligence layer optionally predicts pose at render horizon.
5. Renderer produces raw frame for selected LOD and time offset.
6. Encoder produces compressed frame and CMAF fragment.
7. MoQ publisher emits object with priority metadata.
8. Browser receives object, demuxes fragment, and decodes via WebCodecs.
9. Optional WebGPU super-resolution upscales frame before presentation.
10. Metrics and timestamps are emitted asynchronously throughout.

## Headless Ablation Sequence

1. Trace replayer loads JSON movement timeline.
2. Optional network trace loader applies deterministic bitrate targets.
3. Replay clock emits deterministic pose datagrams.
4. Runtime runner executes rendering path (no evaluation file generation).

## Offline Evaluation Sequence

1. Evaluation runner invokes runtime headless loop through a callback boundary.
2. Evaluation layer persists frames and per-frame metrics.
3. Evaluation layer computes quality proxy (SSIM versus full-reference run).
4. Evaluation layer encodes video outputs and writes tradeoff reports.
5. Curve stage compares latency, quality proxy, and throughput across sweeps.

## Timing and Clocking

- Uplink timestamp is always preserved.
- `time_offset_ms` is propagated from predictor to renderer for 4DGS compatibility.
- Metric events use monotonic nanosecond timestamps where possible.

## Failure Handling Strategy

1. Datagram loss: accept newest available control state.
2. Predictor failure: fallback to no-op passthrough.
3. Renderer overload: ABR server lowers LOD or bitrate.
4. Encoder stall: skip frame and preserve live playback.
5. Client post-processing failure: bypass super-resolution.
