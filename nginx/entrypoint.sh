#!/bin/sh
# Nginx 容器启动脚本：先生成自签证书（如果没有），再启动 Nginx

CERT_DIR="/etc/nginx/certs"
CERT_FILE="$CERT_DIR/cert.pem"
KEY_FILE="$CERT_DIR/key.pem"

# 证书中的 SAN IP 列表（可通过环境变量 SAN_IPS 覆盖）
# 改成你 NAS 的实际可达 IP（浏览器地址栏输入的 IP 必须在这个列表里）
SAN_IPS="${SAN_IPS:-IP:127.0.0.1,IP:192.168.1.100}"

# 如果证书已存在，跳过生成（避免每次重启都换新证书导致浏览器重新弹警告）
if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    echo "✔ SSL 证书已存在，跳过生成"
else
    echo "★ 生成自签名 SSL 证书..."
    echo "  SAN IP 列表: $SAN_IPS"

    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$KEY_FILE" \
        -out "$CERT_FILE" \
        -days 3650 \
        -subj "/O=CupsAutoPrinter/CN=nas-print-server" \
        -addext "subjectAltName=$SAN_IPS"

    if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
        echo "✔ 证书生成成功（有效期 10 年）"
    else
        echo "✘ 证书生成失败！"
        exit 1
    fi
fi

# 启动 Nginx（用官方镜像的默认 entrypoint）
echo "★ 启动 Nginx..."
exec /docker-entrypoint.sh nginx -g 'daemon off;'
