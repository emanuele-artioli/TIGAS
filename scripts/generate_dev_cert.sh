#!/usr/bin/env bash
set -euo pipefail

OUT_DIR=${1:-certs}
mkdir -p "$OUT_DIR"

openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
  -keyout "$OUT_DIR/server.key" \
  -out "$OUT_DIR/server.crt" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo "generated $OUT_DIR/server.crt and $OUT_DIR/server.key"
