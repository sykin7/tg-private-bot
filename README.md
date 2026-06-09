# CodexBot

CodexBot 是一个可独立部署的 Telegram 私聊客服/反垃圾机器人。项目包含 Dockerfile、Docker Compose、Redis、PostgreSQL 和 GitHub Actions 镜像构建配置，可以部署到 VPS 的 Docker 环境长期运行。

## 重要安全说明

不要把真实 `BOT_TOKEN`、`POSTGRES_PASSWORD`、GitHub Token 或其他密码写进镜像，也不要提交到 GitHub。

本项目的正确做法是：

- 镜像只包含代码和 Python 依赖。
- `.env.example` 只放示例和说明，可以提交。
- 真实 `.env` 只放在 VPS 本机，不提交，不打包进镜像。
- `docker-compose.bot.yml` 在容器启动时从 VPS 的 `.env` 读取变量，再传给容器运行时。

项目已经加入：

- `.gitignore`: 防止 `.env` 被误提交。
- `.dockerignore`: 防止 `.env` 被发送到 Docker 构建上下文。

所以你在 VPS 上部署时，应当复制 `.env.example` 为 `.env`，然后只在 `.env` 里填写真实密钥。

## 项目文件

- `new.py`: Docker 默认运行入口，内容应与 `机器.py` 保持一致。
- `机器.py`: 机器人主脚本，方便本地阅读或运行。
- `requirements.txt`: Python 依赖。
- `Dockerfile`: 构建 CodexBot 镜像。
- `docker-compose.bot.yml`: 运行 CodexBot、Redis、PostgreSQL。
- `.env.example`: 中文环境变量示例，不填写真实密钥。
- `.github/workflows/build.yml`: 自动构建并发布镜像到 GHCR。

## 准备工作

1. 创建 Telegram 机器人。
   在 Telegram 找 `@BotFather` 创建 bot，拿到 `BOT_TOKEN`。

2. 获取你的 Telegram 数字 ID。
   可以找 `@userinfobot` 获取，填到 `ADMIN_ID`。

3. 准备一台 VPS。
   VPS 需要安装 Docker 和 Docker Compose。

## 已有旧 tg-bot 容器时的一键部署

如果你的 VPS 以前按下面这种方式部署过旧项目：

```bash
docker run -d --name tg-bot --restart always \
  -e BOT_TOKEN="..." \
  -e ADMIN_ID="..." \
  -v /root/tg-bot-data:/app/data \
  ghcr.io/sykin7/testrobot:sha-xxxx
```

并且新旧项目使用同一个 `BOT_TOKEN`，需要先停止旧容器。Telegram bot polling 同一时间只能由一个进程使用，同一个 token 同时跑两个容器会冲突。

推荐先保留旧数据，只停止并删除旧容器：

```bash
docker stop tg-bot
docker rm tg-bot
```

如果想备份旧 SQLite 数据：

```bash
mkdir -p /root/tg-bot-backup
cp -a /root/tg-bot-data /root/tg-bot-backup/tg-bot-data-$(date +%F-%H%M%S)
```

然后部署 CodexBot：

```bash
cd /opt
git clone -b codex https://github.com/sykin7/codexbot.git
cd codexbot
cp .env.example .env
nano .env
chmod +x deploy.sh
./deploy.sh
```

`.env` 至少填写：

```env
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
POSTGRES_PASSWORD=你的强密码
```

部署后看日志：

```bash
docker compose -f docker-compose.bot.yml logs -f codexbot
```

后期更新：

```bash
cd /opt/codexbot
git pull origin codex
docker compose -f docker-compose.bot.yml up -d --build
```

重启：

```bash
docker compose -f docker-compose.bot.yml restart codexbot
```

停止：

```bash
docker compose -f docker-compose.bot.yml down
```

## 配置 .env

在 VPS 项目目录里执行：

```bash
cp .env.example .env
nano .env
```

至少填写：

```env
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
POSTGRES_PASSWORD=换成强密码
CAPTCHA_TEXT_FALLBACK=false
```

注意：`.env` 只留在 VPS，不要提交到 GitHub。

## 方式一：VPS 使用源码构建部署

适合第一次部署，简单直接。

```bash
git clone -b codex https://github.com/sykin7/codexbot.git
cd codexbot
cp .env.example .env
nano .env
docker compose -f docker-compose.bot.yml up -d --build
```

查看日志：

```bash
docker compose -f docker-compose.bot.yml logs -f codexbot
```

查看状态：

```bash
docker compose -f docker-compose.bot.yml ps
```

停止服务：

```bash
docker compose -f docker-compose.bot.yml down
```

更新代码并重新部署：

```bash
git pull
docker compose -f docker-compose.bot.yml up -d --build
```

## 方式二：VPS 使用 GitHub Actions 构建好的镜像

GitHub Actions 会发布镜像到：

```text
ghcr.io/sykin7/codexbot:latest
ghcr.io/sykin7/codexbot:sha-<commit>
```

如果镜像是公开的，VPS 可以直接拉取：

```bash
docker pull ghcr.io/sykin7/codexbot:latest
```

如果镜像是私有的，先登录 GHCR：

```bash
echo YOUR_GITHUB_TOKEN | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
docker pull ghcr.io/sykin7/codexbot:latest
```

`YOUR_GITHUB_TOKEN` 需要有读取 package 的权限。

如果要直接使用 GHCR 镜像，把 `docker-compose.bot.yml` 里的 CodexBot 服务从：

```yaml
build:
  context: .
  dockerfile: Dockerfile
```

改成：

```yaml
image: ghcr.io/sykin7/codexbot:latest
```

然后部署：

```bash
docker compose -f docker-compose.bot.yml pull
docker compose -f docker-compose.bot.yml up -d
```

这个方式同样不会把 `.env` 写进镜像。镜像启动时才会从 VPS 本机 `.env` 读取真实变量。

## 推荐 VPS 目录

```bash
mkdir -p /opt/codexbot
cd /opt/codexbot
```

如果使用源码构建，目录里需要：

```text
Dockerfile
new.py
requirements.txt
docker-compose.bot.yml
.env
```

如果使用 GHCR 镜像，目录里只需要：

```text
docker-compose.bot.yml
.env
```

## 服务和数据

Compose 会启动三个服务：

- `codexbot`: Telegram 机器人。
- `redis`: 限流、验证码冷却等临时状态。
- `postgres`: 持久化数据。

数据保存在 Docker volumes：

- `bot_data`
- `bot_redis_data`
- `bot_postgres_data`

Redis 和 PostgreSQL 默认不暴露公网端口，只在 Docker 内部网络给 CodexBot 使用。

## 从 SQLite 迁移到 PostgreSQL

如果你以前有旧的 SQLite 数据库 `/app/data/bot_core.db`，第一次启动时设置：

```env
MIGRATE_SQLITE_TO_POSTGRES=true
```

确认日志显示迁移完成后，改回：

```env
MIGRATE_SQLITE_TO_POSTGRES=false
```

然后重启：

```bash
docker compose -f docker-compose.bot.yml restart codexbot
```

## 常用命令

查看日志：

```bash
docker compose -f docker-compose.bot.yml logs -f codexbot
```

重启 bot：

```bash
docker compose -f docker-compose.bot.yml restart codexbot
```

更新镜像并重启：

```bash
docker compose -f docker-compose.bot.yml pull
docker compose -f docker-compose.bot.yml up -d
```

备份 PostgreSQL：

```bash
docker compose -f docker-compose.bot.yml exec postgres pg_dump -U bot_user bot_db > bot_db_backup.sql
```

## GitHub Actions

workflow 文件在 `.github/workflows/build.yml`。

触发条件：

- 推送到 `codex` 分支。
- 修改了 `new.py`、`Dockerfile`、`requirements.txt` 或 workflow 文件。
- 手动点击 GitHub Actions 的 `Run workflow`。

镜像名：

```text
ghcr.io/sykin7/codexbot:latest
```

如果 Actions 页面出现 Node.js 20 deprecated 警告，通常是某个 action 版本还没有完全切到 Node.js 24。构建成功时不影响使用。本项目已使用 `docker/build-push-action@v6`。

## 安全检查清单

- `.env` 不提交到 GitHub。
- `.env` 不进入 Docker 镜像。
- `POSTGRES_PASSWORD` 使用强密码。
- 私有 GHCR 镜像需要在 VPS 上登录后才能拉取。
- 不需要开放 Redis/PostgreSQL 公网端口。
