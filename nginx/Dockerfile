FROM nginx:alpine

# 安装 openssl（nginx:alpine 默认不带，需要手动装）
RUN apk add --no-cache openssl

# 复制自定义配置和启动脚本
COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh

# 给启动脚本加执行权限
RUN chmod +x /entrypoint.sh

# 创建证书目录（证书文件通过 volume 持久化，不在镜像里）
RUN mkdir -p /etc/nginx/certs

# 用自定义 entrypoint 替代官方默认的（先生成证书再启动）
ENTRYPOINT ["/entrypoint.sh"]
