# TIGAS: Modular 3DGS/4DGS Remote Rendering Testbed

This repository is structured as a research-first scaffold for a modular remote rendering pipeline. It is intentionally split into isolated components that communicate through explicit contracts so each module can be implemented, replaced, benchmarked, and ablated independently.

The architecture follows five core runtime stages:

1. Input and control uplink (interactive and headless)
2. Intelligence layer (pose prediction and ABR)
3. Rendering wrapper (3DGS and 4DGS compatible)
4. Media coding and CMAF packaging
5. QUIC or MoQ transport and browser client post-processing

Instrumentation, network shaping, and experiment orchestration are first-class components rather than afterthoughts.

## Repository Layout

```text
TIGAS/
  docs/                     # Architecture and contract documentation
  schemas/                  # JSON schemas for traces, datagrams, metrics
  src/tigas/                # Python module skeletons with interfaces and stubs
  web/                      # Browser-side placeholders (WebTransport/WebCodecs/WebGPU)
  docker/                   # Per-module container definitions
  scripts/                  # Reproducible helper scripts for local runs and ablations
  tests/                    # Contract and smoke tests for placeholder modules
  .github/workflows/        # CI ablation matrix scaffold
```

## Current Status

The codebase includes a functional headless baseline path for both standard
3DGS and compressed SuperSplat PLY inputs and keeps the rest of the modules
contract-first for
incremental implementation. Current capabilities include:

- Detailed module descriptions
- Standardized input and output expectations
- Headless orbit-trace generation for displayless servers
- CPU rendering backend for standard 3DGS (`f_dc_*`, `opacity`, `scale_*`) and
  compressed SuperSplat (`element chunk`, `packed_*`) files
- Splat-style CPU blend pass (color + opacity + scale-driven smoothing) to avoid
  point-only dot rendering
- Headless ablation runner with per-frame metrics and summary export

The goal is to implement components incrementally while preserving a stable high-level architecture.

## Core Contracts

The canonical module contracts are described in:

- `docs/ARCHITECTURE.md`
- `docs/MODULE_IO_CONTRACTS.md`
- `docs/DATAFLOW.md`
- `schemas/*.json`

## Quick Start (Scaffold Validation)

1. Create or activate a Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run placeholder contract tests:

```bash
pytest -q
```

## Runtime-Only Headless Run

The runtime headless path is latency-oriented and avoids evaluation overhead
(no frame-dump metrics, no SSIM, no video encoding).

Run one experiment:

```bash
PYTHONPATH=src python -m tigas.orchestration.run_headless \
  --ply-path "/path/to/scene.compressed.ply" \
  --renderer-backend cpu \
  --quant-bits 8 \
  --num-frames 120 \
  --fps 30 \
  --width 960 \
  --height 540
```

Use `--renderer-backend gsplat_cuda` to run the CUDA path with gsplat.
For `gsplat_cuda`, install `torch`, `gsplat`, and a compatible CUDA toolkit in
the active environment.

The `quant_8bit` LOD keeps the same splat count and applies attribute
quantization (position, color, scale, opacity). Use `--quant-bits` to control
the quantization strength (lower bits = stronger degradation).

Or use the helper script:

```bash
./scripts/run_headless_ablation.sh "/path/to/scene.compressed.ply"
```

## Evaluation Component (Offline)

All evaluation-heavy responsibilities are centralized in `tigas.evaluation`.
This component performs frame export, SSIM proxy computation against full
reference runs, tradeoff-curve generation, and required video encoding.

Run a sparsity/resolution/quantization sweep:

```bash
PYTHONPATH=src python -m tigas.evaluation.run_evaluation \
  --ply-path "/path/to/scene.ply" \
  --renderer-backend gsplat_cuda \
  --output-dir outputs/evaluation \
  --num-frames 120 \
  --fps 30 \
  --max-points 300000 \
  --sparsity-levels "1.0,0.75,0.5,0.25" \
  --resolutions "960x540,1280x720" \
  --quant-bits-list "8,6,4,3"
```

Evaluation outputs:

1. per-run `frames/frame_*.ppm`
2. per-run `frame_metrics.csv` (includes `ssim_vs_full`)
3. per-run `summary.json`
4. per-run `headless_render.mp4` (evaluation requires `ffmpeg`)
5. global `tradeoff_curve.csv` and `tradeoff_curve.md`

Output artifacts per run:

1. `frames/frame_*.ppm` rendered frames
2. `frame_metrics.csv` per-frame render and coverage statistics
3. `summary.json` aggregate evaluation report
4. `headless_render.mp4` optional video if `ffmpeg` is available

## Implementation Strategy

Implement one subsystem at a time in this order:

1. Input control contracts and headless trace replay
2. Pose predictor and ABR baseline policies
3. Renderer wrapper and LOD registry
4. Encoder and CMAF packager interfaces
5. MoQ transport publisher and browser client integration
6. Metrics buffer integration and kernel-level instrumentation

Each step should preserve contract compatibility and keep all other modules mockable.
