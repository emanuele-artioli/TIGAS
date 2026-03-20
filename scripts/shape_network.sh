#!/usr/bin/env bash
set -euo pipefail

# Network shaping placeholder script.
#
# Planned profile examples: 5g, lte, wifi.

IFACE="${1:-eth0}"
PROFILE="${2:-wifi}"

echo "TODO: apply tc profile ${PROFILE} on interface ${IFACE}"
