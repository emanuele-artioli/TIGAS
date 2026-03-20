# Architecture Overview

This document defines the high-level architecture for the TIGAS remote rendering testbed. The design prioritizes modularity, reproducibility, and cross-platform experimentation over early optimization.

## Design Principles

1. Contract-first modules: Every component has explicit input and output types.
2. Dataflow isolation: Components interact only through serialized payloads or typed objects.
3. Replaceable backends: Predictor, renderer, coder, and transport are runtime-pluggable.
4. Ablation-ready operation: Any module can be swapped or disabled for experiments.
5. 4DGS readiness: Pipeline always propagates wall clock or scene time offsets.

## Runtime Modules

### 1. Input and Control

- Interactive source: Browser captures 6-DOF pose at frame cadence.
- Headless source: Trace replayer emits deterministic pose timeline from JSON.
- Uplink format: Datagram payload includes sequence id, timestamp, camera matrix, requested LOD, and target bitrate.

### 2. Intelligence Layer

- Pose predictor predicts camera state at t + RTT.
- Baselines: No-op passthrough and Kalman filter.
- ABR client estimates throughput and requests bitrate or LOD.
- ABR server enforces safe operating points based on frame time and queue pressure.

### 3. Rendering Engine Wrapper

- Single renderer interface accepts (pose, lod, time_offset).
- Backends: CUDA gsplat, WebGPU-compatible path, and CPU fallback.
- LOD manager maps symbolic presets to concrete model variants.

### 4. Media Coder

- Raw RGB frame to encoded elementary stream.
- Elementary stream to CMAF fragmented units.
- Object priority metadata marks keyframes as high priority for MoQ scheduling.

### 5. Transport Layer

- Uplink: Unreliable QUIC datagrams for low-latency control.
- Downlink: MoQ object stream carrying CMAF fragments.
- Session manager coordinates stream identifiers and telemetry markers.

### 6. Browser Client

- WebTransport session management.
- WebCodecs decode path for CMAF chunks.
- Optional WebGPU super-resolution stage for bandwidth-performance tradeoff.

### 7. Instrumentation

- Hot path writes metrics to lock-free ring buffer abstraction.
- Background drain exports rows to parquet.
- eBPF hooks capture kernel-level packet timestamps.
- Traffic shaping scripts emulate 5G, LTE, and Wi-Fi conditions.

### 8. Orchestration and Experiments

- Pipeline orchestrator wires modules by configuration.
- Headless ablation runner executes matrix combinations.
- CI workflow runs reduced matrix and uploads metrics artifacts.

## Execution Modes

1. Interactive live mode: Browser controls camera in real time.
2. Headless replay mode: Trace file drives deterministic experiments.
3. Offline analysis mode: Aggregate parquet metrics for report generation.

## Implementation Notes

- Placeholder code in `src/tigas` is intentionally non-functional and raises explicit errors.
- Subsystems should be implemented without changing contract shapes unless contracts are versioned.
- Add unit tests per module before integrating into the orchestration layer.
