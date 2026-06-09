# CodexBot

CodexBot 是一个可独立部署的 Telegram 私聊客服 / 反垃圾机器人。它支持私聊转发、管理员回复、验证码、黑白名单、广播、基础反垃圾规则和 Docker 部署。

普通 VPS 或低内存 VPS 推荐使用轻量版：只运行一个 `codexbot` 容器，使用 SQLite 保存数据。你当前 VPS 已经验证过，三容器版 `codexbot + PostgreSQL + Redis` 会触发 `exited with code 137`，轻量版可以正常运行。

## 重要结论

- 推荐部署文件：`docker-compose.bot-lite.yml`
- 进阶部署文件：`docker-compose.bot.yml`
- 推荐镜像：`ghcr.io/sykin7/codexbot:latest`
- 推荐 VPS 目录：`/opt/codexbot`
- 你的专属部署文档：[VPS-DEPLOYMENT.md](VPS-DEPLOYMENT.md)

## 安全说明

不要把真实 `BOT_TOKEN`、`ADMIN_ID`、数据库密码、GitHub Token 或其他密码写进镜像，也不要提交到 GitHub。

正确做法：

- 镜像只包含代码和 Python 依赖。
- `.env.example` 只放示例和中文说明，可以提交。
- 真实 `.env` 只放在 VPS 本机。
- `docker-compose.yml` 启动时从 VPS 的 `.env` 读取变量。
- `.gitignore` 已排除 `.env`。
- `.dockerignore` 已防止 `.env` 进入 Docker 构建上下文。

## 项目文件

- `new.py`: Docker 镜像默认运行入口，内容应与 `机器.py` 保持一致。
- `机器.py`: 机器人主脚本，方便本地阅读或运行。
- `requirements.txt`: Python 依赖。
- `Dockerfile`: 构建 CodexBot 镜像。
- `docker-compose.bot-lite.yml`: 推荐部署方式，只运行 CodexBot，使用 SQLite。
- `docker-compose.bot.yml`: 进阶部署方式，运行 CodexBot、Redis、PostgreSQL。
- `.env.example`: 中文环境变量示例，不填写真实密钥。
- `.github/workflows/build.yml`: 自动构建并发布镜像到 GHCR。
- `VPS-DEPLOYMENT.md`: 按你当前 VPS 情况写好的专属部署维护文档。

## 准备工作

1. 在 Telegram 找 `@BotFather` 创建机器人，拿到 `BOT_TOKEN`。
2. 找 `@userinfobot` 获取你的 Telegram 数字 ID，填到 `ADMIN_ID`。
3. VPS 已安装 Docker 和旧版 `docker-compose`。
4. 如果旧容器 `tg-bot` 还在使用同一个 token，必须先停止它。

停止旧容器：

```bash
docker stop tg-bot
docker rm tg-bot
```

## 推荐部署：轻量版

适合普通 VPS、低内存 VPS、单机器人长期运行。

在 VPS 执行：

```bash
mkdir -p /opt/codexbot
cd /opt/codexbot
mkdir -p data
```

创建 `.env`：

```bash
cat > /opt/codexbot/.env <<'EOF'
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
OWNER_ID=
CAPTCHA_TEXT_FALLBACK=false
EOF
```

创建 `docker-compose.yml`：

```bash
cat > /opt/codexbot/docker-compose.yml <<'EOF'
version: '3.8'

services:
  codexbot:
    image: ghcr.io/sykin7/codexbot:latest
    container_name: codexbot
    restart: unless-stopped
    environment:
      BOT_TOKEN: ${BOT_TOKEN:?请在 .env 中填写 BOT_TOKEN}
      ADMIN_ID: ${ADMIN_ID:-}
      OWNER_ID: ${OWNER_ID:-}
      REDIS_ENABLED: "false"
      BOT_DB_PATH: /app/data/bot_core.db
      CAPTCHA_TEXT_FALLBACK: ${CAPTCHA_TEXT_FALLBACK:-false}
      WELCOME_ZH: ${WELCOME_ZH:-}
      VERIFIED_ZH: ${VERIFIED_ZH:-}
      AUTO_REPLY_ZH: ${AUTO_REPLY_ZH:-}
      WELCOME_EN: ${WELCOME_EN:-}
      VERIFIED_EN: ${VERIFIED_EN:-}
      AUTO_REPLY_EN: ${AUTO_REPLY_EN:-}
      REMOTE_SPAM_URL: ${REMOTE_SPAM_URL:-}
    volumes:
      - ./data:/app/data
    networks:
      - bot-network

networks:
  bot-network:
    driver: bridge
EOF
```

启动：

```bash
cd /opt/codexbot
docker-compose pull
docker-compose up -d
docker-compose ps
docker-compose logs -f codexbot
```

正常状态：

```text
codexbot   Up
```

正常日志：

```text
Bot Started.
Rules Updated.
```

退出日志查看：`Ctrl + C`。

## Telegram 测试

给机器人发送：

```text
/start
/help
/id
```

`/id` 返回的数字 ID 必须和 `.env` 里的 `ADMIN_ID` 一致，否则你不会被识别为管理员。

## 管理员快捷指令

直接发送：

```text
/help
/id
/gb 要广播的内容
/awl 用户ID
/dwl 用户ID
/abl 用户ID
/dbl 用户ID
/vlist wl
/vlist bl
/spamtest 要测试的内容
```

回复机器人转发来的用户消息时发送：

```text
/ban
/unban
/awl
/abl
```

常用说明：

- `/ban`：封禁该用户 30 天。
- `/unban`：解封该用户。
- `/awl`：加入白名单；白名单用户会跳过广告和刷屏检查。
- `/abl`：加入黑名单。
- `/gb`：广播给已记录用户。
- `/vlist wl`：查看白名单。
- `/vlist bl`：查看黑名单。
- `/spamtest 内容`：管理员测试广告规则是否命中，不会真的封人，回复里不会回显广告原文。例如 `/spamtest u币`、`/spamtest u 币`、`/spamtest 出U`。

## 广告屏蔽排查

普通用户私聊机器人时，处理顺序是：黑名单检查 -> 白名单判断 -> 刷屏检查 -> 广告检查 -> 验证码/已验证判断 -> 转发给管理员。

也就是说，用户通过验证码以后继续发消息，仍然会经过广告屏蔽。真正会绕过广告检查的是白名单用户。

广告命中后会直接封禁并停止转发，管理员只收到干净的拦截结果，不会再收到广告原文。如果你看到广告还能发到管理员这里，按这个顺序查：

1. 看他是不是白名单：

```text
/vlist wl
```

2. 测试当前规则是否命中：

```text
/spamtest u币
/spamtest u 币
/spamtest 出U
```

3. 确认 VPS 已经拉到新镜像：

```bash
cd /opt/codexbot
docker-compose pull
docker-compose up -d
docker-compose logs -f codexbot
```

## 日常维护

进入目录：

```bash
cd /opt/codexbot
```

查看状态：

```bash
docker-compose ps
```

查看日志：

```bash
docker-compose logs -f codexbot
```

重启：

```bash
docker-compose restart codexbot
```

停止：

```bash
docker-compose down
```

更新镜像：

```bash
docker-compose pull
docker-compose up -d
docker-compose logs -f codexbot
```

## 备份数据

轻量版数据文件：

```text
/opt/codexbot/data/bot_core.db
```

备份：

```bash
cd /opt/codexbot
mkdir -p backup
cp -a data/bot_core.db backup/bot_core-$(date +%F-%H%M%S).db
ls -lh backup
```

恢复：

```bash
cd /opt/codexbot
docker-compose down
cp -a backup/你的备份文件.db data/bot_core.db
docker-compose up -d
```

## code 137 说明

如果日志出现：

```text
codexbot exited with code 137
```

说明容器被系统强制杀掉，通常是 VPS 内存不足。你当前 VPS 的实际情况就是三容器版资源压力过大，所以应保持轻量版部署。

确认当前只运行一个 bot 容器：

```bash
cd /opt/codexbot
docker-compose ps
```

如果看到 `codexbot-postgres` 或 `codexbot-redis`，说明还在用三容器旧配置。执行：

```bash
docker-compose down
```

然后重新写入轻量版 `docker-compose.yml`。

## 公网暴露说明

轻量版没有 `ports:` 配置，不会把 bot、SQLite 或任何内部服务暴露到公网。

检查：

```bash
docker ps
```

CodexBot 不应该出现类似：

```text
0.0.0.0:5432->5432/tcp
0.0.0.0:6379->6379/tcp
```

## 进阶部署

`docker-compose.bot.yml` 会启动：

- `codexbot`
- `redis`
- `postgres`

只有在 VPS 内存足够、需要 PostgreSQL 持久化或未来计划复杂部署时才建议使用。你当前 VPS 已经验证过三容器版会触发 `code 137`，所以不要默认使用它。

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

## 常见问题

### docker: unknown command: docker compose

你的 VPS 使用旧版 Compose，命令是：

```bash
docker-compose up -d
```

不是：

```bash
docker compose up -d
```

### nano: command not found

你的 VPS 没装 `nano`。用本文档里的 `cat > 文件 <<'EOF'` 方式创建文件。

### BOT_TOKEN and ADMIN_ID must be set

检查：

```bash
cd /opt/codexbot
cat .env
```

确认至少有：

```env
BOT_TOKEN=你的真实Token
ADMIN_ID=你的Telegram数字ID
```

### Unauthorized

`BOT_TOKEN` 错了，重新去 `@BotFather` 检查。

### Conflict: terminated by other getUpdates request

还有另一个容器或程序在用同一个 bot token。

检查：

```bash
docker ps -a
```

停掉旧容器：

```bash
docker stop tg-bot
docker rm tg-bot
docker-compose restart codexbot
```
