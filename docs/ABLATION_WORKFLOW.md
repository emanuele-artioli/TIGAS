# Ablation Workflow

This document defines a repeatable headless experiment pipeline intended for local runs and CI.

## Matrix Dimensions

Suggested first matrix:

1. Codec: `h264_nvenc`, `av1_nvenc`, `libx264`
2. Predictor: `noop`, `kalman`
3. LOD policy: `fixed_full`, `fixed_50`, `adaptive`
4. Network profile: `5g`, `lte`, `wifi`

## Single Experiment Lifecycle

1. Load trace file and scenario metadata.
2. Apply network profile (Linux tc).
3. Launch orchestrator with selected module set.
4. Run for fixed duration or fixed frame count.
5. Drain metrics to parquet and summarize KPIs.

## Required Outputs Per Run

1. Raw event parquet file
2. Run manifest JSON with selected configuration
3. Aggregated summary JSON (latency and throughput stats)
4. Optional rendered output sample for sanity checks

## KPI Suggestions

1. Motion-to-photon latency (p50, p95)
2. End-to-end frame time budget split
3. Throughput versus target bitrate tracking
4. Frame drop ratio and stall intervals
5. Predictor error in translational and rotational terms

## CI Reduced Matrix

For pull requests, run a reduced matrix to keep runtime short:

1. Two codecs (h264 and av1)
2. Two predictors (noop and kalman)
3. One short trace
4. One medium network profile
