#!/bin/bash
set -e

echo "================================================"
echo "  Cloud Service Node - Multi-Protocol"
echo "  Xray + Hysteria2 + gRPC + CF Tunnel"
echo "================================================"

UUID="${UUID:-226ed049-909c-4f4e-816b-303e2a2c11e6}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-Admin@2026!}"
export UUID ADMIN_USER ADMIN_PASS

# ---- 1. TLS certs for Hysteria2 ----
echo "[1/6] Preparing TLS certificates..."
if [ ! -f /etc/hysteria/server.crt ]; then
    openssl req -x509 -nodes -newkey ec:<(openssl ecparam -name prime256v1) \
        -keyout /etc/hysteria/server.key \
        -out /etc/hysteria/server.crt \
        -subj "/CN=www.bing.com" -days 36500 2>/dev/null
    echo "    Done."
fi

# ---- 2. Start Xray ----
echo "[2/6] Starting Xray-core (WS + gRPC on :8080)..."
xray run -config /etc/xray/config.json &
XRAY_PID=$!
sleep 2
if kill -0 $XRAY_PID 2>/dev/null; then
    echo "    Xray OK (PID $XRAY_PID)"
else
    echo "    Xray FAILED - check config"
    exit 1
fi

# ---- 3. Start Hysteria2 ----
echo "[3/6] Starting Hysteria2 (QUIC :8443)..."
if command -v hysteria &>/dev/null; then
    hysteria server -c /etc/hysteria/config.yaml &
    HY_PID=$!
    sleep 2
    if kill -0 $HY_PID 2>/dev/null; then
        echo "    Hysteria2 OK (PID $HY_PID)"
    else
        echo "    Hysteria2 SKIP (not available on this arch)"
    fi
else
    echo "    Hysteria2 SKIP (binary not found)"
fi

# ---- 4. Cloudflare Tunnel ----
echo "[4/6] Starting Cloudflare Quick Tunnel..."
CF_LOG=/tmp/cf.log
cloudflared tunnel --no-autoupdate --url http://localhost:8080 >"$CF_LOG" 2>&1 &
CF_PID=$!

echo "    Waiting for tunnel URL..."
TUNNEL_URL=""
for i in $(seq 1 60); do
    TUNNEL_URL=$(grep -oP 'https://[a-z0-9]+(-[a-z0-9]+)*\.trycloudflare\.com' "$CF_LOG" 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then break; fi
    sleep 1
done

if [ -z "$TUNNEL_URL" ]; then
    echo "    WARN: No tunnel URL found after 60s"
    cat "$CF_LOG" 2>/dev/null || true
    export TUNNEL_URL=""
else
    echo "    Tunnel: $TUNNEL_URL"
    export TUNNEL_URL
fi

# ---- 5. Save initial settings ----
echo "[5/6] Writing initial settings..."
python3 -c "
import json
s = {
    'admin_user': '$ADMIN_USER',
    'admin_pass': '$ADMIN_PASS',
    'uuid': '$UUID',
    'vless_path': '/vless',
    'vmess_path': '/vmess',
    'trojan_path': '/trojan',
    'grpc_service': 'DataService'
}
with open('/tmp/node_settings.json','w') as f:
    json.dump(s, f)
print('    Settings saved.')
"

# ---- 6. Dashboard ----
echo "[6/6] Starting dashboard on :3000..."
python3 /app/server.py &

echo ""
echo "================================================"
echo "  READY!"
echo "================================================"
echo "  Dashboard:  port 3000 (Back4app URL)"
echo "  Tunnel:     $TUNNEL_URL"
echo "  Login:      $ADMIN_USER / $ADMIN_PASS"
echo "  UUID:       $UUID"
echo ""
echo "  Protocols:"
echo "    VLESS     WS+TLS   /vless"
echo "    VMess     WS+TLS   /vmess"
echo "    Trojan    WS+TLS   /trojan"
echo "    VLESS     gRPC     DataService"
echo "    Hysteria2 QUIC     :8443"
echo "================================================"

wait
