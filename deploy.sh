#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="docker-compose.bot-lite.yml"
SERVICE_NAME="codexbot"
OLD_CONTAINER="tg-bot"

if ! command -v docker >/dev/null 2>&1; then
  echo "错误：当前 VPS 没有 docker 命令。请先安装 Docker。"
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "错误：当前 Docker 不支持 'docker compose'。请安装 Docker Compose 插件。"
  exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "错误：找不到 $COMPOSE_FILE，请在项目目录运行本脚本。"
  exit 1
fi

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "已创建 .env，请先编辑真实 BOT_TOKEN、ADMIN_ID："
    echo "  nano .env"
    exit 1
  fi
  echo "错误：找不到 .env。"
  exit 1
fi

if grep -Eq '^BOT_TOKEN=$|^ADMIN_ID=$' .env; then
  echo "错误：.env 里还有必填项未填写：BOT_TOKEN、ADMIN_ID。"
  echo "请执行：nano .env"
  exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -Fxq "$OLD_CONTAINER"; then
  echo "检测到旧容器 $OLD_CONTAINER。"
  echo "如果旧容器和 CodexBot 使用同一个 BOT_TOKEN，必须先停止旧容器，否则 Telegram polling 会冲突。"
  echo "停止旧容器命令："
  echo "  docker stop $OLD_CONTAINER"
  echo "保留旧数据但删除旧容器命令："
  echo "  docker rm $OLD_CONTAINER"
  echo
  echo "确认处理旧容器后，再重新运行："
  echo "  ./deploy.sh"
  exit 1
fi

mkdir -p data

docker compose -f "$COMPOSE_FILE" up -d --build

echo
echo "CodexBot 已启动。常用命令："
echo "  查看状态：docker compose -f $COMPOSE_FILE ps"
echo "  查看日志：docker compose -f $COMPOSE_FILE logs -f $SERVICE_NAME"
echo "  重启：docker compose -f $COMPOSE_FILE restart $SERVICE_NAME"
echo "  更新：git pull origin codex && docker compose -f $COMPOSE_FILE up -d --build"
