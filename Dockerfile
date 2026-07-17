FROM python:3.11-slim

# 安装 cups-client，提供 lp / lpstat 命令
RUN apt-get update \
    && apt-get install -y --no-install-recommends cups-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 创建上传目录
RUN mkdir -p /tmp/print_uploads

EXPOSE 5000

CMD ["python", "app.py"]
