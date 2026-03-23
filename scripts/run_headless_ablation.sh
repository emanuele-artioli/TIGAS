#!/usr/bin/env bash
set -euo pipefail

# Headless ablation launcher.
#
# Usage:
# ./scripts/run_headless_ablation.sh <PLY_PATH> [TRACE_JSON] [OUTPUT_DIR] [RENDERER_BACKEND] [QUANT_BITS]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PLY_PATH="${1:-}"
TRACE_JSON="${2:-}"
OUTPUT_DIR="${3:-${REPO_ROOT}/outputs/headless}"
RENDERER_BACKEND="${4:-cpu}"
QUANT_BITS="${5:-8}"

if [[ -z "${PLY_PATH}" ]]; then
	echo "error: missing PLY path"
	echo "usage: ./scripts/run_headless_ablation.sh <PLY_PATH> [TRACE_JSON] [OUTPUT_DIR]"
	exit 1
fi

export PYTHONPATH="${REPO_ROOT}/src:${PYTHONPATH:-}"

CMD=(
	python -m tigas.orchestration.run_headless
	--ply-path "${PLY_PATH}"
	--output-dir "${OUTPUT_DIR}"
	--num-frames 120
	--fps 30
	--width 960
	--height 540
	--max-points 120000
	--default-lod full
	--renderer-backend "${RENDERER_BACKEND}"
	--quant-bits "${QUANT_BITS}"
)

if [[ -n "${TRACE_JSON}" ]]; then
	CMD+=(--trace-json "${TRACE_JSON}")
fi

"${CMD[@]}"
