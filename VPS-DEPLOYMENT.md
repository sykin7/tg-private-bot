# CodexBot 专属 VPS Docker 部署与维护方案

这份文档按你当前 VPS 的真实情况整理：已经安装 Docker，使用旧版 `docker-compose` 命令，部署目录固定为 `/opt/codexbot`，镜像使用 `ghcr.io/sykin7/codexbot:latest`。

最终确认：你的 VPS 使用轻量版部署最合适。之前三容器版 `codexbot + PostgreSQL + Redis` 会让 `codexbot` 很快 `exited with code 137`，也就是被系统强制杀掉，Telegram 看起来就会“没反应”。轻量版只运行一个 `codexbot` 容器，使用 SQLite 保存数据，已经验证能立即恢复正常。

## 当前推荐方案

- 只运行 `codexbot` 一个容器。
- 不运行 PostgreSQL。
- 不运行 Redis。
- 数据保存到 `/opt/codexbot/data/bot_core.db`。
- `.env` 只保存在 VPS，不上传 GitHub，不进入 Docker 镜像。
- compose 文件不写真实 token 和密码，只从 `.env` 读取。
- 没有 `ports:` 配置，所以 CodexBot 不会暴露公网端口。

## 1. 停止旧项目

如果旧机器人容器 `tg-bot` 还在运行，先停止并删除旧容器。同一个 `BOT_TOKEN` 不能同时被两个 bot 进程使用，否则 Telegram 会冲突。

```bash
docker stop tg-bot
docker rm tg-bot
```

这只删除容器，不会删除旧数据目录 `/root/tg-bot-data`。

建议备份旧数据：

```bash
mkdir -p /root/tg-bot-backup
cp -a /root/tg-bot-data /root/tg-bot-backup/tg-bot-data-$(date +%F-%H%M%S)
```

不要执行：

```bash
docker volume prune
docker system prune
rm -rf /root/tg-bot-data
```

VPS 上的 `subconverter` 容器和 CodexBot 无关，不要动它。

## 2. 创建目录

```bash
mkdir -p /opt/codexbot
cd /opt/codexbot
mkdir -p data
```

最终目录结构：

```text
/opt/codexbot/.env
/opt/codexbot/docker-compose.yml
/opt/codexbot/data/
```

## 3. 创建 .env

你的 VPS 没有 `nano`，所以直接用 `cat` 创建：

```bash
cat > /opt/codexbot/.env <<'EOF'
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
OWNER_ID=
CAPTCHA_TEXT_FALLBACK=false
EOF
```

然后检查：

```bash
cat /opt/codexbot/.env
```

必须替换成真实值：

```env
BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxx
ADMIN_ID=123456789
OWNER_ID=
CAPTCHA_TEXT_FALLBACK=false
```

说明：

- `BOT_TOKEN` 从 `@BotFather` 获取。
- `ADMIN_ID` 是你的 Telegram 数字 ID，可以用 `@userinfobot` 获取。
- `OWNER_ID` 可以留空，因为已经设置 `ADMIN_ID`。
- `.env` 只放 VPS 本机，不要上传 GitHub，不要发给别人。

## 4. 创建轻量版 docker-compose.yml

直接复制执行：

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

检查文件：

```bash
cat /opt/codexbot/docker-compose.yml
```

确认里面没有真实 token，真实 token 只应该在 `/opt/codexbot/.env`。

## 5. 启动 CodexBot

```bash
cd /opt/codexbot
docker-compose pull
docker-compose up -d
docker-compose ps
docker-compose logs -f codexbot
```

正常应该看到：

```text
codexbot   Up
```

日志正常类似：

```text
Bot Started.
Rules Updated.
```

退出日志查看：

```text
Ctrl + C
```

## 6. Telegram 测试

给机器人发送：

```text
/start
/help
/id
```

`/id` 会返回你的 Telegram 数字 ID。这个 ID 必须和 `/opt/codexbot/.env` 里的 `ADMIN_ID` 一样，否则你不会被识别为管理员。

## 7. 管理员快捷指令

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

回复用户转发消息时发送：

```text
/ban
/unban
/awl
/abl
```

说明：

- `/ban`：封禁该用户 30 天。
- `/unban`：解封该用户。
- `/awl`：加入白名单；白名单用户会跳过广告和刷屏检查。
- `/abl`：加入黑名单。
- `/gb`：广播给已记录用户。
- `/vlist wl`：查看白名单。
- `/vlist bl`：查看黑名单。
- `/spamtest 内容`：测试广告规则是否命中，不会真的封人，回复里不会回显广告原文。例如 `/spamtest u币`、`/spamtest u 币`、`/spamtest 出U`。

## 8. 广告屏蔽排查

这个机器人不是“通过验证后就不查广告”。普通用户私聊消息的处理顺序是：黑名单检查 -> 白名单判断 -> 刷屏检查 -> 广告检查 -> 验证码/已验证判断 -> 转发给管理员。

所以，通过验证码的用户继续发广告，正常也会被广告规则拦截并封禁。真正会绕过广告检查的是白名单用户。

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

日志里看到 `Bot Started.` 后，再用另一个 Telegram 账号给机器人发送测试内容。

## 9. 日常维护

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

重启机器人：

```bash
docker-compose restart codexbot
```

停止机器人：

```bash
docker-compose down
```

重新启动：

```bash
docker-compose up -d
```

更新最新镜像：

```bash
cd /opt/codexbot
docker-compose pull
docker-compose up -d
docker-compose logs -f codexbot
```

## 10. 备份和恢复

轻量版数据文件在：

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

恢复时先停 bot，再替换数据库：

```bash
cd /opt/codexbot
docker-compose down
cp -a backup/你的备份文件.db data/bot_core.db
docker-compose up -d
```

## 11. 安全确认

查看端口：

```bash
docker ps
```

CodexBot 不应该出现类似：

```text
0.0.0.0:5432->5432/tcp
0.0.0.0:6379->6379/tcp
```

轻量版没有 PostgreSQL 和 Redis，也没有 `ports:`，所以默认不会暴露公网。

## 12. 常见问题

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

你的 VPS 没装 `nano`。用本文档里的 `cat > 文件 <<'EOF'` 方式创建文件即可。

### codexbot exited with code 137

这表示容器被系统强制杀掉，常见原因是内存不足。你已经验证轻量版可以解决这个问题。

确认当前只运行一个 bot 容器：

```bash
cd /opt/codexbot
docker-compose ps
```

如果还看到 `codexbot-postgres` 或 `codexbot-redis`，说明还在用三容器旧 compose。执行：

```bash
cd /opt/codexbot
docker-compose down
```

然后按本文档第 4 步重新写入轻量版 `docker-compose.yml`。

### BOT_TOKEN and ADMIN_ID must be set

检查 `.env`：

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

## 13. 进阶：什么时候才需要 PostgreSQL 和 Redis

只有这些情况才建议使用三容器版：

- VPS 内存足够。
- 需要更强的数据持久化和迁移能力。
- 未来计划多实例或更复杂的部署。

你当前这个 VPS 已经出现过 `code 137`，所以不要默认使用 PostgreSQL + Redis 方案。保持轻量版更稳。
