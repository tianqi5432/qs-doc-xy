#!/usr/bin/env python3
"""
Proxy Node Dashboard Server
- Admin login with cookie session
- Dynamic config: change UUID/password via UI
- API: /api/login, /api/logout, /api/nodes, /api/settings, /api/restart
- Serves masquerade page for unauthorized visitors
"""

import http.server
import json
import os
import hashlib
import secrets
import subprocess
import signal
import time
import urllib.parse
import base64

# ============================================================
# Configuration (overridable via environment variables)
# ============================================================
SETTINGS_FILE = '/tmp/node_settings.json'

DEFAULT_SETTINGS = {
    'admin_user': os.environ.get('ADMIN_USER', 'admin'),
    'admin_pass': os.environ.get('ADMIN_PASS', 'Admin@2026!'),
    'uuid': os.environ.get('UUID', '226ed049-909c-4f4e-816b-303e2a2c11e6'),
    'vless_path': '/vless',
    'vmess_path': '/vmess',
    'trojan_path': '/trojan',
    'grpc_service': 'DataService',
}

SESSION_SECRET = secrets.token_hex(32)
ACTIVE_SESSIONS = {}  # token -> expiry timestamp

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')


def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            saved = json.load(f)
            merged = {**DEFAULT_SETTINGS, **saved}
            return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(s):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(s, f, indent=2)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def create_session():
    token = secrets.token_hex(32)
    ACTIVE_SESSIONS[token] = time.time() + 86400  # 24h expiry
    return token


def check_session(token):
    if not token:
        return False
    expiry = ACTIVE_SESSIONS.get(token, 0)
    if time.time() > expiry:
        ACTIVE_SESSIONS.pop(token, None)
        return False
    return True


def get_cookie_token(headers):
    cookie = headers.get('Cookie', '')
    for part in cookie.split(';'):
        part = part.strip()
        if part.startswith('session='):
            return part[8:]
    return None


def write_xray_config(settings):
    """Dynamically generate Xray config from settings."""
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "vless-ws", "listen": "0.0.0.0", "port": 8080,
                "protocol": "vless",
                "settings": {"clients": [{"id": settings['uuid'], "flow": ""}], "decryption": "none"},
                "streamSettings": {"network": "ws", "security": "none", "wsSettings": {"path": settings['vless_path']}},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            },
            {
                "tag": "vmess-ws", "listen": "0.0.0.0", "port": 8080,
                "protocol": "vmess",
                "settings": {"clients": [{"id": settings['uuid'], "alterId": 0, "security": "auto"}]},
                "streamSettings": {"network": "ws", "security": "none", "wsSettings": {"path": settings['vmess_path']}},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            },
            {
                "tag": "trojan-ws", "listen": "0.0.0.0", "port": 8080,
                "protocol": "trojan",
                "settings": {"clients": [{"password": settings['uuid']}]},
                "streamSettings": {"network": "ws", "security": "none", "wsSettings": {"path": settings['trojan_path']}},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            },
            {
                "tag": "vless-grpc", "listen": "0.0.0.0", "port": 8080,
                "protocol": "vless",
                "settings": {"clients": [{"id": settings['uuid']}], "decryption": "none"},
                "streamSettings": {
                    "network": "grpc",
                    "security": "none",
                    "grpcSettings": {"serviceName": settings['grpc_service'], "multiMode": False}
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            }
        ],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct", "settings": {}},
            {"protocol": "blackhole", "tag": "block", "settings": {}}
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "block"}]
        }
    }
    with open('/etc/xray/config.json', 'w') as f:
        json.dump(config, f, indent=2)


def restart_services():
    """Restart Xray with new config."""
    try:
        subprocess.run(['pkill', '-f', 'xray run'], timeout=5)
        time.sleep(1)
        settings = load_settings()
        write_xray_config(settings)
        subprocess.Popen(
            ['xray', 'run', '-config', '/etc/xray/config.json'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print("[OK] Services restarted with new config")
        return True
    except Exception as e:
        print(f"[ERROR] Restart failed: {e}")
        return False


def get_node_data():
    settings = load_settings()
    tunnel_url = os.environ.get('TUNNEL_URL', '')
    tunnel_host = tunnel_url.replace('https://', '').replace('http://', '')
    uuid = settings['uuid']

    # Generate VMess link
    vmess_obj = {
        "v": "2", "ps": "Node-VMess", "add": tunnel_host, "port": "443",
        "id": uuid, "aid": "0", "scy": "auto", "net": "ws", "type": "none",
        "host": tunnel_host, "path": settings['vmess_path'], "tls": "tls", "sni": tunnel_host
    }
    vmess_link = 'vmess://' + base64.b64encode(json.dumps(vmess_obj).encode()).decode() if tunnel_host else ''

    protocols = [
        {
            "name": "VLESS", "type": "vless", "transport": "WebSocket",
            "link": f"vless://{uuid}@{tunnel_host}:443?encryption=none&security=tls&type=ws&host={tunnel_host}&path={urllib.parse.quote(settings['vless_path'])}#Node-VLESS" if tunnel_host else "",
            "config": {"address": tunnel_host, "port": 443, "uuid": uuid, "encryption": "none",
                       "transport": "ws", "tls": "tls", "ws_path": settings['vless_path'], "sni": tunnel_host}
        },
        {
            "name": "VMess", "type": "vmess", "transport": "WebSocket",
            "link": vmess_link,
            "config": {"address": tunnel_host, "port": 443, "uuid": uuid, "alterId": 0,
                       "security": "auto", "transport": "ws", "tls": "tls", "ws_path": settings['vmess_path'], "sni": tunnel_host}
        },
        {
            "name": "Trojan", "type": "trojan", "transport": "WebSocket",
            "link": f"trojan://{uuid}@{tunnel_host}:443?security=tls&type=ws&host={tunnel_host}&path={urllib.parse.quote(settings['trojan_path'])}#Node-Trojan" if tunnel_host else "",
            "config": {"address": tunnel_host, "port": 443, "password": uuid,
                       "transport": "ws", "tls": "tls", "ws_path": settings['trojan_path'], "sni": tunnel_host}
        },
        {
            "name": "VLESS-gRPC", "type": "vless-grpc", "transport": "gRPC",
            "link": f"vless://{uuid}@{tunnel_host}:443?encryption=none&security=tls&type=grpc&host={tunnel_host}&serviceName={settings['grpc_service']}&mode=gun#Node-gRPC" if tunnel_host else "",
            "config": {"address": tunnel_host, "port": 443, "uuid": uuid, "encryption": "none",
                       "transport": "grpc", "tls": "tls", "serviceName": settings['grpc_service'], "sni": tunnel_host}
        },
        {
            "name": "Hysteria2", "type": "hysteria2", "transport": "QUIC",
            "link": f"hysteria2://{uuid}@{tunnel_host}:8443?insecure=1&sni={tunnel_host}#Node-Hysteria2" if tunnel_host else "",
            "config": {"address": tunnel_host, "port": 8443, "password": uuid, "tls": "tls", "insecure": True}
        }
    ]

    return {
        "tunnel_url": tunnel_url, "tunnel_host": tunnel_host,
        "uuid": uuid, "protocols": protocols
    }


class AppHandler(http.server.BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, filename, status=200):
        try:
            with open(os.path.join(TEMPLATE_DIR, filename), 'r', encoding='utf-8') as f:
                content = f.read().encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'Template not found')

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 0:
            return json.loads(self.rfile.read(length))
        return {}

    def _is_auth(self):
        token = get_cookie_token(self.headers)
        return check_session(token)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == '/api/check':
            return self._send_json({"auth": self._is_auth()})

        if path == '/api/nodes':
            if not self._is_auth():
                return self._send_json({"error": "unauthorized"}, 401)
            return self._send_json(get_node_data())

        if path == '/api/settings':
            if not self._is_auth():
                return self._send_json({"error": "unauthorized"}, 401)
            s = load_settings()
            return self._send_json({
                "admin_user": s['admin_user'],
                "uuid": s['uuid'],
                "vless_path": s['vless_path'],
                "vmess_path": s['vmess_path'],
                "trojan_path": s['trojan_path'],
                "grpc_service": s['grpc_service'],
            })

        if path == '/dashboard':
            if not self._is_auth():
                return self._send_html('index.html')
            return self._send_html('index.html')

        # Public pages
        if path == '/' or path == '/index.html':
            return self._send_html('index.html')

        if path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'Not Found')

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path

        if path == '/api/login':
            data = self._read_body()
            s = load_settings()
            if data.get('user') == s['admin_user'] and data.get('pass') == s['admin_pass']:
                token = create_session()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Set-Cookie', f'session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400')
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode())
                return
            return self._send_json({"error": "Invalid credentials"}, 401)

        if path == '/api/logout':
            token = get_cookie_token(self.headers)
            ACTIVE_SESSIONS.pop(token, None)
            self.send_response(200)
            self.send_header('Set-Cookie', 'session=; Path=/; HttpOnly; Max-Age=0')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        # Protected endpoints
        if not self._is_auth():
            return self._send_json({"error": "unauthorized"}, 401)

        if path == '/api/settings':
            data = self._read_body()
            s = load_settings()
            for key in ['admin_user', 'admin_pass', 'uuid', 'vless_path', 'vmess_path', 'trojan_path', 'grpc_service']:
                if key in data and data[key]:
                    s[key] = data[key]
            save_settings(s)
            return self._send_json({"ok": True, "message": "Settings saved"})

        if path == '/api/restart':
            ok = restart_services()
            return self._send_json({"ok": ok, "message": "Services restarted" if ok else "Restart failed"})

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    port = int(os.environ.get('PORT', '3000'))
    server = http.server.HTTPServer(('0.0.0.0', port), AppHandler)
    print(f"[OK] Server running on port {port}")
    print(f"[OK] Default login: admin / Admin@2026!")
    server.serve_forever()


if __name__ == '__main__':
    main()
