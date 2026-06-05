FROM alpine:latest

# Install dependencies
RUN apk add --no-cache \
    bash \
    curl \
    wget \
    unzip \
    python3 \
    openssl \
    jq \
    sed

# Install Xray-core
RUN curl -fsSL https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip -o /tmp/xray.zip \
    && unzip /tmp/xray.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray \
    && rm -f /tmp/xray.zip \
    && xray version

# Install Hysteria2
RUN curl -fsSL https://github.com/apernet/hysteria/releases/latest/download/hysteria-linux-amd64 -o /usr/local/bin/hysteria \
    && chmod +x /usr/local/bin/hysteria \
    && hysteria version || true

# Install cloudflared for Argo Tunnel
RUN curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared \
    && cloudflared --version

# Create directories
RUN mkdir -p /etc/xray /etc/hysteria /app/templates

# Copy all config and app files
COPY xray-config.json /etc/xray/config.json
COPY hysteria-config.yaml /etc/hysteria/config.yaml
COPY server.py /app/server.py
COPY start.sh /app/start.sh
COPY templates/index.html /app/templates/index.html

# Fix Windows CRLF line endings and set permissions
RUN sed -i 's/\r$//' /app/start.sh \
    && chmod +x /app/start.sh

# Back4app main port (dashboard)
EXPOSE 3000
# Xray port
EXPOSE 8080

CMD ["/app/start.sh"]
