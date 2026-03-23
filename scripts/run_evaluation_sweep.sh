#!/usr/bin/env bash
set -euo pipefail

# Offline evaluation sweep launcher.
#
# Usage:
# ./scripts/run_evaluation_sweep.sh <PLY_PATH> [TRACE_JSON] [OUTPUT_DIR]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PLY_PATH="${1:-}"
TRACE_JSON="${2:-}"
OUTPUT_DIR="${3:-${REPO_ROOT}/outputs/evaluation}"

if [[ -z "${PLY_PATH}" ]]; then
	echo "error: missing PLY path"
	echo "usage: ./scripts/run_evaluation_sweep.sh <PLY_PATH> [TRACE_JSON] [OUTPUT_DIR]"
	exit 1
fi

export PYTHONPATH="${REPO_ROOT}/src:${PYTHONPATH:-}"

CMD=(
	python -m tigas.evaluation.run_evaluation
	--ply-path "${PLY_PATH}"
	--output-dir "${OUTPUT_DIR}"
	--renderer-backend gsplat_cuda
	--num-frames 120
	--fps 30
	--max-points 300000
	--sparsity-levels "1.0,0.75,0.5,0.25"
	--resolutions "960x540,1280x720"
	--quant-bits-list "8,6,4,3"
)

if [[ -n "${TRACE_JSON}" ]]; then
	CMD+=(--trace-json "${TRACE_JSON}")
fi

"${CMD[@]}"
