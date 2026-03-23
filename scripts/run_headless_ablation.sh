#!/usr/bin/env bash
set -euo pipefail

# Headless runtime launcher (no evaluation artifact generation).
#
# Usage:
# ./scripts/run_headless_ablation.sh <PLY_PATH> [MOVEMENT_TRACE] [NETWORK_TRACE] [RENDERER_BACKEND] [QUANT_BITS] [ABR_PROFILE] [TC_INTERFACE]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PLY_PATH="${1:-}"
MOVEMENT_TRACE="${2:-}"
NETWORK_TRACE="${3:-}"
RENDERER_BACKEND="${4:-cpu}"
QUANT_BITS="${5:-8}"
ABR_PROFILE="${6:-}"
TC_INTERFACE="${7:-}"

if [[ -z "${PLY_PATH}" ]]; then
	echo "error: missing PLY path"
	echo "usage: ./scripts/run_headless_ablation.sh <PLY_PATH> [MOVEMENT_TRACE] [NETWORK_TRACE] [RENDERER_BACKEND] [QUANT_BITS] [ABR_PROFILE] [TC_INTERFACE]"
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

if [[ -n "${MOVEMENT_TRACE}" ]]; then
	CMD+=(--movement-trace "${MOVEMENT_TRACE}")
fi

if [[ -n "${NETWORK_TRACE}" ]]; then
	CMD+=(--network-trace "${NETWORK_TRACE}")
fi

if [[ -n "${ABR_PROFILE}" ]]; then
	CMD+=(--abr-profile "${ABR_PROFILE}")
fi

if [[ -n "${TC_INTERFACE}" ]]; then
	CMD+=(--enable-tc --tc-interface "${TC_INTERFACE}")
fi

"${CMD[@]}"
