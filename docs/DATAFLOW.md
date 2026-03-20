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
2. Replay clock emits deterministic pose datagrams.
3. Remaining pipeline follows the interactive server path.
4. Metrics drain writes parquet output per experiment configuration.
5. Report stage compares latency, quality proxy, and throughput.

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
