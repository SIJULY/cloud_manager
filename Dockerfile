# 文件名: Dockerfile

# 使用非精简版的 Debian Buster 基础镜像
FROM python:3.8-bullseye

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 设置工作目录
WORKDIR /app

# 在安装 Python 包之前，先安装系统级的编译依赖
RUN apt-get update && apt-get install -y gcc python3-dev && rm -rf /var/lib/apt/lists/*

# 为了利用 Docker 的层缓存，先复制并安装依赖
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir "gevent==21.12.0"

# 复制项目的所有代码到工作目录
COPY . .

# 创建一个非 root 用户来运行应用，增加安全性
RUN useradd --create-home appuser
# 将数据文件的所有权交给新用户
RUN chown -R appuser:appuser /app
USER appuser

# Gunicorn 将通过 docker-compose 启动
