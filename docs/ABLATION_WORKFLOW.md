# Ablation Workflow

This document defines a repeatable headless experiment pipeline intended for local runs and CI.

Evaluation is explicitly offline and decoupled from runtime-critical execution.

Standardized traces live in repository folders and should be used for repeatable
scenarios:

1. Movement traces: `movement_traces/*.json`
2. Network traces: `network_traces/*.csv`

## Matrix Dimensions

Suggested first matrix:

1. Resolution: for example `960x540`, `1280x720`
2. Sparsity level: for example `1.0`, `0.75`, `0.5`, `0.25`
3. Quantization: for example `8`, `6`, `4`, `3` bits
4. Optional runtime dimensions: codec, predictor, network profile

## Single Experiment Lifecycle

1. Load trace file and scenario metadata.
2. Select standardized movement and network traces for reproducibility.
3. Run baseline full-reference configuration for each resolution.
4. Run matrix variants through evaluation component using the same traces.
5. Compute per-frame metrics and SSIM versus reference.
6. Encode per-run video and generate tradeoff curve artifacts.

## Required Outputs Per Run

1. Raw event parquet file
2. Run manifest JSON with selected configuration
3. Aggregated summary JSON (latency, throughput, and quality-proxy stats)
4. Per-run encoded video
5. Tradeoff curve CSV and markdown summary

## KPI Suggestions

1. Motion-to-photon latency (p50, p95)
2. End-to-end frame time budget split
3. Throughput versus target bitrate tracking
4. Frame drop ratio and stall intervals
5. Predictor error in translational and rotational terms
6. SSIM proxy versus full-reference run

## CI Reduced Matrix

For pull requests, run a reduced matrix to keep runtime short:

1. Two codecs (h264 and av1)
2. Two predictors (noop and kalman)
3. One short trace
4. One medium network profile
