FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/knifez/ug-videokeeper"
LABEL org.opencontainers.image.description="UGREEN NAS 媒体库双向同步工具"

WORKDIR /app

# 安装系统依赖（psycopg2-binary 含编译好的二进制，无需 libpq-dev）
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码（不含 .dockerignore 中排除的目录）
COPY . .

# 确保 data 目录存在（即使未挂载外部卷）
RUN mkdir -p data

# 默认启动同步模式
CMD ["python", "main.py"]
