# CupsAutoPrinter - NAS 远程打印 Web 服务

把 NAS 变成打印服务器，手机/电脑打开网页就能打印。不用装驱动，不用插 U 盘，不用把文件传来传去。

## 这是什么

一个跑在 NAS Docker 上的轻量 Web 应用，对接同 NAS 上的 CUPS 打印服务。浏览器打开页面，选文件，点打印，完事。

**适合谁用：**
- NAS 上已经跑着 CUPS 打印服务的人
- 想用手机直接打印 NAS 里文件的人
- 受够了"传文件到电脑 → 连数据线 → 打印"这条老路的人

## 功能

- **上传打印**：从手机/电脑上传文件，直接打印
- **NAS 本地文件打印**：浏览 NAS 目录，选文件直接打印，不用上传
- **PDF 缩略图预览**：上传的 PDF 用 pdf.js 客户端渲染，NAS 本地 PDF 用 PyMuPDF 后端渲染
- **全屏灯箱查看**：点缩略图放大查看，支持触摸滑动翻页
- **页码范围打印**：指定打印哪几页（如 `1-3,5,8-10`）
- **打印选项**：份数、单双面、纸张大小（A4/A3/A5/Letter/Legal 等）
- **打印状态查询**：实时查看打印机状态和打印队列
- **取消打印任务**：一键取消队列中的任务
- **iPhone HTTPS 支持**：自签证书 + Nginx 反代，解决 iOS Safari 强制 HTTPS 升级问题

**支持的文件格式：**
PDF、PNG、JPG、JPEG、GIF、BMP、TIFF、TXT、PS、EPS、WebP

## 截图

![主界面](screenshots/main.png)

> 主界面：深色主题、拖拽上传、打印设置一目了然。

## 快速开始

### 前置条件

1. **NAS 上已部署 CUPS**，且打印机已添加（能通过 `lp` 命令打印）
2. **Docker + Docker Compose** 已安装
3. CUPS 容器和本服务需要能通过 `localhost:631` 通信（都用 `network_mode: host` 最简单）

### 部署步骤

```bash
# 1. 克隆项目
git clone https://github.com/simble-wang/webcupsprinter.git
cd Cupsautoprinter

# 2. 改配置（必改三项）
vi docker-compose.yml
```

**必须修改的配置：**

| 配置项 | 位置 | 说明 |
|--------|------|------|
| `/your/nas/path` | docker-compose.yml volumes | 改成你 NAS 上要浏览的文件目录 |
| `YourPrinterName` | docker-compose.yml environment | 改成 CUPS 里的打印机名（`lpstat -p` 查看） |
| `SAN_IPS` | docker-compose.yml environment | 改成你 NAS 的 IP 地址（所有你打算用来访问的 IP） |

**SAN_IPS 示例：**
```yaml
# 局域网访问
- SAN_IPS=IP:127.0.0.1,IP:192.168.1.100

# 局域网 + Tailscale 远程访问
- SAN_IPS=IP:127.0.0.1,IP:192.168.1.100,IP:100.x.x.x
```

```bash
# 3. 启动
docker compose up -d --build

# 4. 验证
curl http://localhost:5000/          # Flask 直连
curl -k https://localhost:8443/      # Nginx HTTPS
```

浏览器打开 `http://你的NAS_IP:5000` 即可使用。

## 访问方式

| 平台 | 推荐访问方式 | 说明 |
|------|-------------|------|
| Mac / Windows / Linux | `http://NAS_IP:5000` | HTTP 直连 Flask |
| Android | `http://NAS_IP:5000` | HTTP 直连 Flask |
| iPhone / iPad | `https://NAS_IP:8443` | **必须走 HTTPS**（iOS Safari 会强制升级） |

### 为什么 iPhone 必须走 HTTPS？

iOS Safari 对 IP 地址会自动尝试 HTTPS 升级。如果只提供 HTTP 服务，Safari 会把页面当成文件下载（出现"下载 document"的怪事）。所以专门用 Nginx 反代套了一层 HTTPS。

## iPhone HTTPS 证书信任设置（重要！）

Nginx 使用自签名证书，iPhone 需要手动信任。**证书必须包含 `CA:TRUE` 扩展**，否则 iOS 系统级信任不生效（本项目已处理好此问题）。

### 步骤

1. **下载证书**
   Safari 打开：`https://你的NAS_IP:8443/api/download-cert`

2. **安装描述文件**
   设置 → 通用 → VPN与设备管理 → 已下载描述文件 → 安装

3. **开启信任（最容易漏的一步！）**
   设置 → 通用 → 关于本机 → 证书信任设置 → 把开关打开

4. **访问**
   Safari 打开 `https://你的NAS_IP:8443`

> 如果之前装过旧证书，先在"VPN与设备管理"里删掉旧的，再装新的。
> 如果 Safari 缓存了旧的拒绝状态，去 设置 → Safari → 清除历史记录与网站数据。

## 架构

```
                    ┌─────────────┐
  浏览器/手机  ────→ │   Nginx     │ :8443 (HTTPS, 自签证书)
                    │  (反代+SSL)  │
                    └──────┬───────┘
                           │ proxy_pass
                    ┌──────▼───────┐
                    │   Flask App  │ :5000 (HTTP)
                    │  (打印逻辑)   │
                    └──────┬───────┘
                           │ lp / lpstat 命令
                    ┌──────▼───────┐
                    │    CUPS      │ :631
                    │  (打印服务)   │
                    └──────────────┘
```

**两个容器：**
- `print-web`：Flask 应用，处理打印逻辑、文件浏览、缩略图渲染
- `print-proxy`：Nginx 反向代理，提供 HTTPS（主要给 iPhone 用）

两个容器都用 `network_mode: host`，所以 Nginx 能直连 `localhost:5000`，Flask 能直连 `localhost:631`。

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PRINTER_NAME` | YourPrinterName | CUPS 中的打印机名 |
| `CUPS_SERVER` | localhost:631 | CUPS 服务地址 |
| `LOCAL_FILES_DIR` | /nas_files | 容器内 NAS 文件挂载路径 |
| `SAN_IPS` | IP:127.0.0.1,... | SSL 证书的 SAN IP 列表 |
| `UPLOAD_DIR` | /tmp/print_uploads | 上传文件临时目录 |
| `SSL_CERT_PATH` | /tmp/certs/cert.pem | SSL 证书路径（供 iPhone 下载） |

### 文件清理

上传的文件会在 1 小时后自动删除，每 10 分钟扫描一次，不会撑爆硬盘。

## 更新证书

如果 NAS IP 变了，或需要重新生成证书：

```bash
# 1. 改 docker-compose.yml 里的 SAN_IPS
# 2. 删旧证书
rm -rf certs/*
# 3. 重建 nginx 容器
docker compose up -d --force-recreate nginx
# 4. iPhone 重新下载安装证书
```

## 常见问题

**Q: 打印机连不上？**
确认 CUPS 容器在跑：`docker ps | grep cups`，确认 `lpstat -h localhost:631 -p` 能看到打印机。

**Q: iPhone 提示"无法连接到服务器"？**
1. 确认 Tailscale/网络通了
2. 确认证书信任开关打开了（设置 → 通用 → 关于本机 → 证书信任设置）
3. 清除 Safari 缓存重试

**Q: iPhone 访问 HTTP 下载了 document 文件？**
这是 iOS Safari 的 HTTPS 强制升级机制。iPhone 上只用 `https://NAS_IP:8443`，别用 HTTP。

**Q: Mac/安卓提示证书不安全？**
自签证书正常现象。Mac 上点"高级"→"继续访问"即可；安卓点"详细信息"→"继续访问"。

**Q: 缩略图加载慢？**
大 PDF 渲染需要时间。上传模式用 pdf.js 客户端渲染（不占服务器资源），NAS 本地文件用 PyMuPDF 后端渲染。

**Q: 想改端口？**
改 `nginx/nginx.conf` 里的 `listen 8443` 和 `docker-compose.yml` 里对应的配置。

## 技术栈

- **后端**：Flask 3.1.1 + PyMuPDF（PDF 渲染）
- **前端**：pdf.js 3.11.174（CDN）+ 原生 JS
- **打印**：CUPS（lp / lpstat / cancel 命令行工具）
- **HTTPS**：Nginx（nginx:alpine）+ OpenSSL 自签证书
- **Docker**：python:3.11-slim + nginx:alpine

## 限制

- 无用户认证（**不要暴露到公网**，仅限内网/Tailscale 使用）
- 上传文件最大 50MB
- 路径穿越防护（无法通过 `../../../` 访问 NAS 挂载目录之外的文件）

## License

MIT
