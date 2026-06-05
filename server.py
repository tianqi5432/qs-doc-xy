#!/usr/bin/env python3
"""Lightweight HTTP server for proxy node dashboard.
No external dependencies - uses only Python stdlib."""

import http.server
import json
import os
import urllib.parse

TUNNEL_URL = os.environ.get('TUNNEL_URL', '')
UUID = os.environ.get('UUID', '226ed049-909c-4f4e-816b-303e2a2c11e6')
HYSTERIA_PORT = os.environ.get('HYSTERIA_PORT', '8443')

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')


def get_api_data():
    """Return node connection data as JSON."""
    tunnel_host = TUNNEL_URL.replace('https://', '').replace('http://', '')
    return {
        "tunnel_url": TUNNEL_URL,
        "tunnel_host": tunnel_host,
        "uuid": UUID,
        "protocols": [
            {
                "name": "VLESS",
                "type": "vless",
                "link": f"vless://{UUID}@{tunnel_host}:443?encryption=none&security=tls&type=ws&host={tunnel_host}&path=%2Fvless#Back4App-VLESS" if tunnel_host else "",
                "config": {
                    "address": tunnel_host,
                    "port": 443,
                    "uuid": UUID,
                    "encryption": "none",
                    "transport": "ws",
                    "tls": "tls",
                    "ws_path": "/vless",
                    "sni": tunnel_host
                }
            },
            {
                "name": "VMess",
                "type": "vmess",
                "link": "",
                "config": {
                    "address": tunnel_host,
                    "port": 443,
                    "uuid": UUID,
                    "alterId": 0,
                    "security": "auto",
                    "transport": "ws",
                    "tls": "tls",
                    "ws_path": "/vmess",
                    "sni": tunnel_host
                }
            },
            {
                "name": "Trojan",
                "type": "trojan",
                "link": f"trojan://{UUID}@{tunnel_host}:443?security=tls&type=ws&host={tunnel_host}&path=%2Ftrojan#Back4App-Trojan" if tunnel_host else "",
                "config": {
                    "address": tunnel_host,
                    "port": 443,
                    "password": UUID,
                    "transport": "ws",
                    "tls": "tls",
                    "ws_path": "/trojan",
                    "sni": tunnel_host
                }
            },
            {
                "name": "Hysteria2",
                "type": "hysteria2",
                "link": f"hysteria2://{UUID}@{tunnel_host}:{HYSTERIA_PORT}?insecure=1&sni={tunnel_host}#Back4App-Hysteria2" if tunnel_host else "",
                "config": {
                    "address": tunnel_host,
                    "port": HYSTERIA_PORT,
                    "password": UUID,
                    "tls": "tls",
                    "insecure": True,
                    "note": "Hysteria2 使用 QUIC/UDP，需要通过 Cloudflare Tunnel 域名访问。如果连接失败，可能需要直连 IP。"
                }
            }
        ]
    }


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == '/api/nodes':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(get_api_data(), ensure_ascii=False, indent=2).encode('utf-8'))
            return

        # Serve the main dashboard page
        if path == '/' or path == '/index.html':
            try:
                with open(os.path.join(TEMPLATE_DIR, 'index.html'), 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            except FileNotFoundError:
                self.send_response(500)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Error: index.html template not found')
            return

        # Favicon
        if path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return

        self.send_response(404)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Not Found')

    def log_message(self, format, *args):
        # Suppress default logging
        pass


def main():
    port = int(os.environ.get('PORT', '3000'))
    server = http.server.HTTPServer(('0.0.0.0', port), DashboardHandler)
    print(f"[OK] Dashboard server running on port {port}")
    print(f"[OK] Access at: http://localhost:{port}")
    server.serve_forever()


if __name__ == '__main__':
    main()
