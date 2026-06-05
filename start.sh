#!/bin/bash
set -e

echo "================================================"
echo "  Proxy Node - Multi-Protocol"
echo "  Xray (VLESS/VMess/Trojan) + Hysteria2"
echo "================================================"

UUID="${UUID:-226ed049-909c-4f4e-816b-303e2a2c11e6}"
export UUID

# ---- Step 1: Generate self-signed TLS cert for Hysteria2 ----
echo "[1/5] Generating TLS certificates for Hysteria2..."
if [ ! -f /etc/hysteria/server.crt ]; then
    openssl req -x509 -nodes -newkey ec:<(openssl ecparam -name prime256v1) \
        -keyout /etc/hysteria/server.key \
        -out /etc/hysteria/server.crt \
        -subj "/CN=www.bing.com" -days 36500 2>/dev/null
    echo "    Certificates generated."
else
    echo "    Certificates already exist."
fi

# ---- Step 2: Start Xray ----
echo "[2/5] Starting Xray-core (VLESS + VMess + Trojan on port 8080)..."
xray run -config /etc/xray/config.json &
XRAY_PID=$!
sleep 2

if kill -0 $XRAY_PID 2>/dev/null; then
    echo "    Xray started (PID: $XRAY_PID)"
else
    echo "    ERROR: Xray failed to start!"
    exit 1
fi

# ---- Step 3: Start Hysteria2 ----
echo "[3/5] Starting Hysteria2 (QUIC on port 8443)..."
hysteria server -c /etc/hysteria/config.yaml &
HYSTERIA_PID=$!
sleep 2

if kill -0 $HYSTERIA_PID 2>/dev/null; then
    echo "    Hysteria2 started (PID: $HYSTERIA_PID)"
else
    echo "    WARNING: Hysteria2 failed to start (may not support this platform)"
fi

# ---- Step 4: Start Cloudflare Quick Tunnel ----
echo "[4/5] Starting Cloudflare Quick Tunnel..."
CF_LOG=/tmp/cloudflared.log
cloudflared tunnel --no-autoupdate --url http://localhost:8080 > "$CF_LOG" 2>&1 &
CF_PID=$!

echo "    Waiting for tunnel URL (up to 45s)..."
TUNNEL_URL=""
for i in $(seq 1 45); do
    TUNNEL_URL=$(grep -oP 'https://[a-z0-9]+(-[a-z0-9]+)*\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    sleep 1
done

if [ -z "$TUNNEL_URL" ]; then
    echo "    WARNING: Tunnel URL not detected after 45s."
    echo "    --- Cloudflare Log ---"
    cat "$CF_LOG" 2>/dev/null || true
    echo "    --- End Log ---"
    TUNNEL_URL="unknown"
else
    echo "    Tunnel URL: $TUNNEL_URL"
fi

export TUNNEL_URL

# ---- Step 5: Start Dashboard ----
echo "[5/5] Starting web dashboard on port 3000..."
python3 /app/server.py &
DASH_PID=$!
sleep 1

echo ""
echo "================================================"
echo "  ALL SERVICES STARTED!"
echo "================================================"
echo ""
echo "  Dashboard:  http://localhost:3000"
echo "  Tunnel URL: $TUNNEL_URL"
echo "  UUID:       $UUID"
echo ""
echo "  Protocols:"
echo "    VLESS    -> ws+tls  path=/vless"
echo "    VMess    -> ws+tls  path=/vmess"
echo "    Trojan   -> ws+tls  path=/trojan"
echo "    Hysteria2-> QUIC    port=8443"
echo ""
echo "  Open the Back4App URL (port 3000) to see the"
echo "  dashboard with copy-ready node links."
echo "================================================"

# Keep container running
wait
