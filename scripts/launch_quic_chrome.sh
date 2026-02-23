#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <open-url> [force-quic-origin host:port]"
  exit 1
fi

URL="$1"
FORCE_QUIC_ORIGIN="${2:-}"

if [[ "$URL" != https://* ]]; then
  echo "URL must start with https://"
  exit 1
fi

CHROME_BIN=""
if [[ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
  CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
elif command -v google-chrome >/dev/null 2>&1; then
  CHROME_BIN="$(command -v google-chrome)"
elif command -v chromium >/dev/null 2>&1; then
  CHROME_BIN="$(command -v chromium)"
else
  echo "Chrome/Chromium binary not found"
  exit 1
fi

url_hostport="${URL#https://}"
url_hostport="${url_hostport%%/*}"

hostport="$url_hostport"
if [[ -n "$FORCE_QUIC_ORIGIN" ]]; then
  hostport="$FORCE_QUIC_ORIGIN"
fi

host=""
port=""
if [[ "$hostport" =~ ^\[(.*)\]:(.*)$ ]]; then
  host="${BASH_REMATCH[1]}"
  port="${BASH_REMATCH[2]}"
elif [[ "$hostport" =~ ^([^:]+):(.*)$ ]]; then
  host="${BASH_REMATCH[1]}"
  port="${BASH_REMATCH[2]}"
else
  host="$hostport"
  port="443"
fi

if ! [[ "$port" =~ ^[0-9]+$ ]]; then
  echo "Invalid port in URL: $URL"
  exit 1
fi

if ! lsof -nP -iUDP:"$port" >/dev/null 2>&1; then
  echo "No QUIC server detected on UDP port $port (target: $hostport)."
  echo "Start TIGAS basic mode/server first, then re-run this launcher."
  exit 2
fi

# Resolve SPKI hash for certificate trust bypass (required for QUIC)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SPKI_FILE="$REPO_ROOT/certs/spki.hash"

if [[ -f "$SPKI_FILE" ]]; then
  SPKI_HASH=$(cat "$SPKI_FILE")
elif [[ -f "$REPO_ROOT/certs/server.crt" ]]; then
  SPKI_HASH=$(openssl x509 -in "$REPO_ROOT/certs/server.crt" -pubkey -noout \
    | openssl pkey -pubin -outform der \
    | openssl dgst -sha256 -binary | base64)
else
  echo "No certificate found. Run scripts/generate_dev_cert.sh first."
  exit 3
fi

PROFILE_DIR="$(mktemp -d /tmp/tigas-quic-profile.XXXXXX)"
NETLOG_PATH="/tmp/tigas-quic-netlog-$(date +%Y%m%d-%H%M%S).json"
echo "Using Chrome profile: $PROFILE_DIR"
echo "Open URL: $URL"
echo "Forcing QUIC origin: $hostport"
echo "SPKI hash: $SPKI_HASH"
echo "Netlog: $NETLOG_PATH"

ARGS=(
  --user-data-dir="$PROFILE_DIR"
  --no-first-run
  --no-default-browser-check
  --disable-background-networking
  --disable-component-update
  --enable-quic
  --origin-to-force-quic-on="$hostport"
  --ignore-certificate-errors-spki-list="$SPKI_HASH"
  --log-net-log="$NETLOG_PATH"
  --net-log-capture-mode=Everything
  "$URL"
)

if [[ "$URL" == https://reference.dashif.org/* ]]; then
  ARGS+=(
    --disable-web-security
    --allow-running-insecure-content
  )
  echo "Applied loopback access compatibility flags for external reference player."
fi

"$CHROME_BIN" "${ARGS[@]}" >/tmp/tigas-quic-chrome.log 2>&1 &
disown
