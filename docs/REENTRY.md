# Re-entry Playbook

This document is the fastest way to resume TIGAS development after a break.

## 1. Current Reality Snapshot

As of March 2026, the validated path is:

1. Headless runtime execution (`tigas.orchestration.run_headless`).
2. Offline evaluation sweeps (`tigas.evaluation.run_evaluation`).
3. ABR comparison via profile files (`throughput`, `bola`, `robustmpc`).

Partially implemented or scaffold-level areas:

1. Browser interactive path and full MoQ pipeline integration.
2. Transport-level throughput feedback loop for ABR.

## 2. Environment Re-check

Use the project conda environment when available.

```bash
cd /home/itec/emanuele/TIGAS
conda activate tigas
pip install -r requirements.txt
pytest -q
```

Expected baseline: tests pass.

## 3. 10-Minute Smoke Validation

Run a short runtime pass:

```bash
PYTHONPATH=src python -m tigas.orchestration.run_headless \
  --ply-path "/path/to/scene.ply" \
  --movement-trace Circular \
  --network-trace lte_steps \
  --abr-profile throughput \
  --num-frames 60 \
  --renderer-backend cpu
```

Run a short evaluation sweep:

```bash
PYTHONPATH=src python -m tigas.evaluation.run_evaluation \
  --ply-path "/path/to/scene.ply" \
  --movement-trace Circular \
  --network-trace lte_steps \
  --abr-profile throughput \
  --renderer-backend cpu \
  --num-frames 60 \
  --output-dir outputs/evaluation_resume_check
```

## 4. ABR Comparison Reproduction

Use the helper script for consistent algorithm comparison:

```bash
bash ./scripts/run_abr_comparison.sh \
  "/path/to/scene.ply" Circular lte_steps outputs/abr_comparison
```

Primary artifacts to inspect:

1. `outputs/abr_comparison/*/tradeoff_curve.csv`
2. `outputs/abr_comparison/*/tradeoff_curve.md`
3. Per-run `summary.json`

## 5. Files You Should Read First

1. `README.md`
2. `docs/blueprint.md`
3. `docs/ARCHITECTURE.md`
4. `docs/ABLATION_WORKFLOW.md`
5. `src/tigas/orchestration/ablation_runner.py`
6. `src/tigas/intelligence/abr_client.py`

## 6. Open Work (Priority Order)

1. Transport-coupled ABR measurement (replace payload-size proxy with transport telemetry).
2. End-to-end interactive MoQ runtime path validation.
3. Expanded ABR regression tests for step-up and step-down traces.
4. Optional: tighter `tc` orchestration workflows where host privileges allow.

## 7. Re-entry Definition of Done

After resuming, consider the workspace healthy when:

1. `pytest -q` passes.
2. One runtime headless run completes and prints summary JSON.
3. One evaluation sweep writes tradeoff and video artifacts.
4. One 3-way ABR comparison run completes for the same movement/network traces.
