#!/usr/bin/env bash
set -euo pipefail

# Run evaluation sweeps for multiple ABR profiles and keep outputs separated.
#
# Usage:
# ./scripts/run_abr_comparison.sh <PLY_PATH> [MOVEMENT_TRACE] [NETWORK_TRACE] [OUTPUT_ROOT]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PLY_PATH="${1:-}"
MOVEMENT_TRACE="${2:-}"
NETWORK_TRACE="${3:-}"
OUTPUT_ROOT="${4:-${REPO_ROOT}/outputs/abr_comparison}"

if [[ -z "${PLY_PATH}" ]]; then
  echo "error: missing PLY path"
  echo "usage: ./scripts/run_abr_comparison.sh <PLY_PATH> [MOVEMENT_TRACE] [NETWORK_TRACE] [OUTPUT_ROOT]"
  exit 1
fi

ABR_PROFILES=(throughput bola robustmpc)

for PROFILE in "${ABR_PROFILES[@]}"; do
  PROFILE_OUTPUT="${OUTPUT_ROOT}/${PROFILE}"
  mkdir -p "${PROFILE_OUTPUT}"
  "${SCRIPT_DIR}/run_evaluation_sweep.sh" \
    "${PLY_PATH}" \
    "${MOVEMENT_TRACE}" \
    "${NETWORK_TRACE}" \
    "${PROFILE_OUTPUT}" \
    "${PROFILE}"
done

echo "ABR comparison completed under: ${OUTPUT_ROOT}"
