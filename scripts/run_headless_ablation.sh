#!/usr/bin/env bash
set -euo pipefail

# Headless runtime launcher (no evaluation artifact generation).
#
# Usage:
# ./scripts/run_headless_ablation.sh <PLY_PATH> [TRACE_JSON] [RENDERER_BACKEND] [QUANT_BITS]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PLY_PATH="${1:-}"
TRACE_JSON="${2:-}"
RENDERER_BACKEND="${3:-cpu}"
QUANT_BITS="${4:-8}"

if [[ -z "${PLY_PATH}" ]]; then
	echo "error: missing PLY path"
	echo "usage: ./scripts/run_headless_ablation.sh <PLY_PATH> [TRACE_JSON] [RENDERER_BACKEND] [QUANT_BITS]"
	exit 1
fi

export PYTHONPATH="${REPO_ROOT}/src:${PYTHONPATH:-}"

CMD=(
	python -m tigas.orchestration.run_headless
	--ply-path "${PLY_PATH}"
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
