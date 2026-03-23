#!/usr/bin/env bash
set -euo pipefail

# Network shaping helper.
#
# Usage:
# ./scripts/shape_network.sh <IFACE> <PROFILE|RATE_KBPS> [clear]
# Example:
# ./scripts/shape_network.sh eth0 lte
# ./scripts/shape_network.sh eth0 8000
# ./scripts/shape_network.sh eth0 wifi clear

IFACE="${1:-eth0}"
PROFILE="${2:-wifi}"
ACTION="${3:-apply}"

if [[ "${ACTION}" == "clear" ]]; then
	tc qdisc del dev "${IFACE}" root || true
	echo "Cleared tc qdisc on ${IFACE}"
	exit 0
fi

if [[ "${PROFILE}" =~ ^[0-9]+$ ]]; then
	tc qdisc replace dev "${IFACE}" root tbf rate "${PROFILE}kbit" burst 64kbit latency 50ms
	echo "Applied tc rate ${PROFILE} kbps on ${IFACE}"
	exit 0
fi

case "${PROFILE}" in
	wifi)
		tc qdisc replace dev "${IFACE}" root tbf rate 25000kbit burst 64kbit latency 20ms
		;;
	lte)
		tc qdisc replace dev "${IFACE}" root tbf rate 12000kbit burst 64kbit latency 40ms
		;;
	3g)
		tc qdisc replace dev "${IFACE}" root tbf rate 2000kbit burst 32kbit latency 120ms
		;;
	*)
		echo "Unsupported profile: ${PROFILE}"
		exit 1
		;;
esac

echo "Applied tc profile ${PROFILE} on ${IFACE}"
