# 使用官方轻量级 Python 镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 防止 Python 生成 .pyc 文件，并让日志直接输出到控制台
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 1. 先复制依赖文件 (利用 Docker 缓存机制加速构建)
COPY requirements.txt .

# 2. 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 3. 复制其余的所有代码文件 (main.py, config.py, database.py 等)
COPY . .

# 暴露端口 (对应 config.py 里的默认端口)
EXPOSE 8080

# 定义数据卷挂载点 (重要！为了让 defense.db 数据持久化)
VOLUME /app/data

# 启动命令
CMD ["python", "main.py"]
