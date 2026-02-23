#!/usr/bin/env bash
set -euo pipefail

OUT_DIR=${1:-certs}
mkdir -p "$OUT_DIR"

CA_KEY="$OUT_DIR/dev-ca.key"
CA_CRT="$OUT_DIR/dev-ca.crt"
SERVER_KEY="$OUT_DIR/server.key"
SERVER_CSR="$OUT_DIR/server.csr"
SERVER_CRT="$OUT_DIR/server.crt"
CHAIN_CRT="$OUT_DIR/server-chain.crt"

if [[ ! -f "$CA_KEY" || ! -f "$CA_CRT" ]]; then
  openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout "$CA_KEY" \
    -out "$CA_CRT" \
    -subj "/CN=TIGAS Local Dev CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:1" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
fi

SERVER_CNF="$(mktemp)"
cat > "$SERVER_CNF" <<'EOF'
[req]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = req_ext

[dn]
CN = localhost

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
EOF

SIGN_CNF="$(mktemp)"
cat > "$SIGN_CNF" <<'EOF'
[v3_server]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
EOF

openssl req -new -newkey rsa:2048 -nodes \
  -keyout "$SERVER_KEY" \
  -out "$SERVER_CSR" \
  -config "$SERVER_CNF"

openssl x509 -req -in "$SERVER_CSR" -sha256 -days 825 \
  -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
  -out "$SERVER_CRT" \
  -extfile "$SIGN_CNF" -extensions v3_server

cat "$SERVER_CRT" "$CA_CRT" > "$CHAIN_CRT"

rm -f "$SERVER_CNF" "$SIGN_CNF" "$SERVER_CSR"

# Compute and save the SPKI hash for Chrome's --ignore-certificate-errors-spki-list
SPKI_HASH=$(openssl x509 -in "$SERVER_CRT" -pubkey -noout \
  | openssl pkey -pubin -outform der \
  | openssl dgst -sha256 -binary | base64)
echo "$SPKI_HASH" > "$OUT_DIR/spki.hash"

echo "generated: $SERVER_KEY, $SERVER_CRT, $CHAIN_CRT, $CA_CRT"
echo "SPKI hash:  $SPKI_HASH  (saved to $OUT_DIR/spki.hash)"
echo ""
echo "Launch Chrome with:"
echo "  --ignore-certificate-errors-spki-list=$SPKI_HASH"
