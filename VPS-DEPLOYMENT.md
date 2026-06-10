# CodexBot 专属 VPS Docker 部署与维护方案

这份文档按你当前 VPS 的真实情况整理：Docker 已安装，推荐部署目录为 `/opt/codexbot`，镜像使用 `ghcr.io/sykin7/codexbot:latest`，运行方式推荐单容器 SQLite 轻量版。

你这台 VPS 已经验证过：三容器版 `codexbot + PostgreSQL + Redis` 容易触发 `exited with code 137`，也就是内存压力导致容器被系统杀掉。当前最稳方案是只运行一个 `codexbot` 容器，数据保存到 `/opt/codexbot/data/bot_core.db`。

## 最终推荐方案

- 只运行 `codexbot` 一个容器。
- 不运行 Redis。
- 不运行 PostgreSQL。
- 不暴露任何公网端口。
- `.env` 只放在 VPS，不上传 GitHub。
- 数据保存在 `/opt/codexbot/data`。
- Docker 日志限制为 `50MB x 5`，最多约 `250MB`。
- 后期更新优先使用 `docker run` 重建，避免老版 `docker-compose` 的兼容问题。

## 1. 停掉旧机器人

同一个 Telegram Bot Token 不能同时被两个机器人进程使用，否则会出现 `Conflict: terminated by other getUpdates request`。

如果旧容器叫 `tg-bot`，先停掉：

```bash
docker stop tg-bot 2>/dev/null || true
docker rm tg-bot 2>/dev/null || true
```

如果旧容器叫 `codexbot`，重装前也可以停掉：

```bash
docker rm -f codexbot 2>/dev/null || true
```

不要删除你的数据目录：

```text
/opt/codexbot/data
```

也不要随便执行：

```bash
docker system prune
docker volume prune
rm -rf /opt/codexbot/data
```

## 2. 创建目录

```bash
mkdir -p /opt/codexbot/data
cd /opt/codexbot
```

最终目录应类似：

```text
/opt/codexbot/.env
/opt/codexbot/data/
```

`docker-compose.yml` 可以保留作为记录，但你这台 VPS 后期推荐直接用 `docker run`。

## 3. 创建 .env

用 `cat` 创建，不需要 `nano`：

```bash
cat > /opt/codexbot/.env <<'EOF'
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
OWNER_ID=
REDIS_ENABLED=false
BOT_DB_PATH=/app/data/bot_core.db
REMOTE_SPAM_URL=
EOF
```

检查：

```bash
cat /opt/codexbot/.env
```

必须替换成真实值，例如：

```env
BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxx
ADMIN_ID=123456789
OWNER_ID=
REDIS_ENABLED=false
BOT_DB_PATH=/app/data/bot_core.db
REMOTE_SPAM_URL=
```

说明：

- `BOT_TOKEN`：从 `@BotFather` 获取。
- `ADMIN_ID`：你的 Telegram 数字 ID，可以用 `@userinfobot` 获取。
- `OWNER_ID`：可以留空，已经设置 `ADMIN_ID` 即可。
- `REDIS_ENABLED=false`：你的 VPS 推荐轻量单容器部署，不启用 Redis。
- `BOT_DB_PATH=/app/data/bot_core.db`：容器内 SQLite 数据库路径，配合 `-v /opt/codexbot/data:/app/data` 使用，不要随便改。
- `REMOTE_SPAM_URL`：可留空，留空时使用脚本内置和默认规则。

### .env 变量怎么改

常用变量：

| 变量名 | 是否建议修改 | 说明 |
| :--- | :---: | :--- |
| `BOT_TOKEN` | 必须改 | 你的 BotFather Token。换机器人时才改。 |
| `ADMIN_ID` | 必须改 | 你的 Telegram 数字 ID。管理员菜单、封禁、广播都靠它识别。 |
| `OWNER_ID` | 通常不改 | 备用管理员 ID。已经填了 `ADMIN_ID` 就可以留空。 |
| `REDIS_ENABLED` | 不建议改 | 你的轻量部署固定用 `false`。改成 `true` 但没有 Redis 容器会出问题。 |
| `BOT_DB_PATH` | 不建议改 | 固定 `/app/data/bot_core.db`，数据实际落在 VPS 的 `/opt/codexbot/data`。 |
| `REMOTE_SPAM_URL` | 可选 | 自定义第三方广告规则 TXT 地址。留空用默认规则。 |
| `WELCOME_ZH` | 可选 | 自定义中文欢迎语。不填就用默认文案。 |
| `VERIFIED_ZH` | 可选 | 自定义中文验证通过提示。不填就用默认文案。 |
| `AUTO_REPLY_ZH` | 可选 | 自定义中文“消息已送达”提示。不填就用默认文案。 |
| `WELCOME_EN` | 可选 | 自定义英文欢迎语。不填就用默认文案。 |
| `VERIFIED_EN` | 可选 | 自定义英文验证通过提示。不填就用默认文案。 |
| `AUTO_REPLY_EN` | 可选 | 自定义英文“Message sent”提示。不填就用默认文案。 |

### 一键写入 .env

第一次部署或想重新整理 `.env` 时，推荐直接覆盖写入。执行前把 `BOT_TOKEN` 和 `ADMIN_ID` 换成你的真实值：

```bash
cat > /opt/codexbot/.env <<'EOF'
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
OWNER_ID=
REDIS_ENABLED=false
BOT_DB_PATH=/app/data/bot_core.db
REMOTE_SPAM_URL=
EOF
```

如果你要同时自定义提示语，用这个完整版本覆盖写入：

```bash
cat > /opt/codexbot/.env <<'EOF'
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
OWNER_ID=
REDIS_ENABLED=false
BOT_DB_PATH=/app/data/bot_core.db
REMOTE_SPAM_URL=
WELCOME_ZH=👋 您好，请直接发送消息，管理员看到后会回复。
VERIFIED_ZH=✅ 验证通过，可以发送消息了。
AUTO_REPLY_ZH=✅ 已送达，管理员会尽快回复。
WELCOME_EN=👋 Hello, please send your message directly.
VERIFIED_EN=✅ Verified. You can now send messages.
AUTO_REPLY_EN=✅ Message sent. The admin will reply shortly.
EOF
```

如果只是临时追加新变量，可以用 `cat >>`，但不要重复追加已经存在的变量：

```bash
cat >> /opt/codexbot/.env <<'EOF'
REMOTE_SPAM_URL=https://你的广告规则地址/spam.txt
EOF
```

更稳的做法是使用上面的完整覆盖写入，让每个变量只出现一次。

修改 `.env` 后必须重建或重启容器才会生效。稳妥做法是执行本文第 11 节“更新镜像并重建”的完整 `docker run` 命令。

## 4. 一键启动或重装

推荐使用这段命令。它会删除旧 `codexbot` 容器，拉取最新镜像，然后重新启动。不会删除 `/opt/codexbot/data`。

```bash
cd /opt/codexbot

docker rm -f codexbot 2>/dev/null || true

docker pull ghcr.io/sykin7/codexbot:latest

docker run -d \
  --name codexbot \
  --restart unless-stopped \
  --env-file /opt/codexbot/.env \
  -e REDIS_ENABLED=false \
  -e BOT_DB_PATH=/app/data/bot_core.db \
  -v /opt/codexbot/data:/app/data \
  --log-driver json-file \
  --log-opt max-size=50m \
  --log-opt max-file=5 \
  ghcr.io/sykin7/codexbot:latest
```

## 5. 检查是否启动成功

```bash
docker ps | grep codexbot
docker logs --tail=80 codexbot
docker inspect codexbot --format '{{json .HostConfig.LogConfig}}'
```

正常应看到：

```text
codexbot   ghcr.io/sykin7/codexbot:latest   Up
Bot Started.
Rules Updated: 数量
```

日志限制正常应类似：

```json
{"Type":"json-file","Config":{"max-file":"5","max-size":"50m"}}
```

## 6. 确认镜像是不是新版代码

如果你发现机器人还是旧菜单、旧指令、管理员功能没有出现，马上执行：

```bash
docker exec codexbot sh -c "grep -n 'admin_menu_status\|admin_menu_resetverify\|Reset Verification\|one_time_keyboard=False\|/reloadrules\|/status' /app/bot.py | head -30"
```

如果没有任何输出，说明 VPS 当前镜像不是最新代码。原因通常是：本地代码还没推到 GitHub，或者 GitHub Actions 还没成功构建新镜像。

正确处理顺序：

1. 本地把最新 `new.py` 推到 GitHub 的 `codex` 分支。
2. 等 GitHub Actions 构建成功。
3. VPS 执行第 4 步的一键重装命令。
4. 再执行上面的 `grep` 检查。

只要 `grep` 没输出，就不是 Telegram 菜单问题，而是容器里的代码还是旧的。

## 7. Telegram 首次测试

给机器人发送：

```text
/start
/help
/id
/status
```

`/id` 返回的数字必须和 `/opt/codexbot/.env` 里的 `ADMIN_ID` 一致，否则你不会被识别为管理员。

管理员右侧聊天框按钮菜单应显示完整管理功能。这个菜单可以手动隐藏，隐藏后可从输入框旁边的键盘按钮再次展开；点击菜单按钮后不会自动消失。

中文管理员菜单：

```text
📊 机器人状态    🔄 重载广告规则
🚫 封禁名单      ⚪ 白名单        ⚫ 黑名单
✅ 解除封禁      ➕ 加白名单      ➖ 移出白名单
⛔ 加黑名单      ♻️ 移出黑名单
🧹 清空验证      📣 群发广播      🧪 广告测试
🆔 查看ID        ❓ 常见问题      🌐 切换语言
```

英文管理员菜单：

```text
📊 Bot Status       🔄 Reload Rules
🚫 Ban List         ⚪ Whitelist       ⚫ Blacklist
✅ Unban User       ➕ Add Whitelist   ➖ Remove Whitelist
⛔ Add Blacklist    ♻️ Remove Blacklist
🧹 Reset Verification   📣 Broadcast   🧪 Spam Test
🆔 Show ID          ❓ FAQ             🌐 Change Language
```

如果你还是看到普通用户菜单：

```text
📨 联系管理员
❓ 常见问题
🌐 切换语言
```

英文普通用户菜单是：

```text
📨 Contact Admin
❓ FAQ
🌐 Change Language
```

Telegram 官方 slash 命令菜单也会注册普通用户和管理员两套命令。注意：官方命令菜单的描述语言跟随 Telegram 客户端语言；右侧按钮菜单和机器人回复内容跟随用户在机器人里选择的语言。

按顺序检查：

1. `/id` 是否等于 `.env` 里的 `ADMIN_ID`。
2. 容器内代码检查命令是否有输出。
3. GitHub Actions 是否已经构建成功。

## 8. 管理员快捷指令

直接发送：

```text
/help
/id
/status
/reloadrules
/spamtest 测试内容
/gb 广播内容
/awl 用户ID
/dwl 用户ID
/abl 用户ID
/dbl 用户ID
/unban 用户ID
/resetverify
/vlist wl
/vlist bl
/vlist ban
```

回复机器人转发来的用户消息时发送：

```text
/ban
/unban
/awl
/abl
```

常用说明：

- `/status`：查看机器人、数据库和广告规则状态。
- `/reloadrules`：手动重载第三方广告规则。
- `/spamtest 内容`：测试广告规则是否会拦截，不会真的封禁。
- `/resetverify`：一键清空普通用户验证状态，确认后他们下次发消息需要重新完成人机验证。
- `/vlist ban`：查看临时封禁名单，并可按钮解封。
- `/awl`：加入白名单。白名单会跳过广告和频率检测。
- `/abl`：加入黑名单。黑名单用户消息会被拒收。
- `/ban`：临时封禁回复消息对应的用户。
- `/unban`：解封回复消息对应的用户，或 `/unban 用户ID`。

右侧聊天框按钮菜单里的“解除封禁、加白名单、群发广播、广告测试”等按钮是快捷入口；点击后机器人会按当前语言提示你发送对应命令和参数。

## 9. 广告拦截确认

普通用户每一条准备转发给管理员的消息，都会先经过广告规则过滤。流程是：

```text
黑名单检查 -> 白名单判断 -> 频率检查 -> 广告规则检查 -> 人机验证状态判断 -> 转发给管理员
```

重点：

- 通过人机验证后，仍然要经过广告规则。
- 白名单用户才会跳过广告规则。
- 命中广告后不会把广告原文转发给管理员。
- 管理员只收到干净的拦截通知和处理按钮。

测试广告规则：

```text
/spamtest u币
/spamtest u 币
/spamtest 出U
/spamtest USDT
```

查看规则状态：

```text
/status
```

手动重载规则：

```text
/reloadrules
```

如果第三方规则 URL 加载失败，机器人仍会使用内置兜底规则。你可以用 `/reloadrules` 再次尝试拉取。

## 10. 日志、缓存和数据大小

当前 Docker 日志限制：

```bash
--log-driver json-file
--log-opt max-size=50m
--log-opt max-file=5
```

含义：最多保留 5 个日志文件，每个 50MB，总计约 250MB。超过后 Docker 自动删除最旧日志。

确认是否生效：

```bash
docker inspect codexbot --format '{{json .HostConfig.LogConfig}}'
```

脚本内部清理机制：

- 消息映射记录会按时间和数量清理。
- SQLite 数据库会在超过限制后整理压缩。
- 人机验证、频率限制、自动回复、用户状态等运行时缓存会自动过期。
- 容器重启后，内存缓存会清空。

不要自动删除整个 `/opt/codexbot/data`，因为里面有白名单、黑名单、封禁记录、用户状态和消息映射数据库。

## 11. 日常维护命令

查看容器：

```bash
docker ps | grep codexbot
```

查看最近日志：

```bash
docker logs --tail=80 codexbot
```

实时查看日志：

```bash
docker logs -f codexbot
```

退出实时日志：

```text
Ctrl + C
```

重启机器人：

```bash
docker restart codexbot
```

停止机器人：

```bash
docker stop codexbot
```

重新启动已停止的机器人：

```bash
docker start codexbot
```

更新镜像并重建：

```bash
cd /opt/codexbot

docker rm -f codexbot 2>/dev/null || true
docker pull ghcr.io/sykin7/codexbot:latest

docker run -d \
  --name codexbot \
  --restart unless-stopped \
  --env-file /opt/codexbot/.env \
  -e REDIS_ENABLED=false \
  -e BOT_DB_PATH=/app/data/bot_core.db \
  -v /opt/codexbot/data:/app/data \
  --log-driver json-file \
  --log-opt max-size=50m \
  --log-opt max-file=5 \
  ghcr.io/sykin7/codexbot:latest
```

## 12. 备份和恢复

备份 SQLite 数据库：

```bash
cd /opt/codexbot
mkdir -p backup
cp -a data/bot_core.db backup/bot_core-$(date +%F-%H%M%S).db
ls -lh backup
```

恢复数据库：

```bash
cd /opt/codexbot
docker stop codexbot
cp -a backup/你的备份文件.db data/bot_core.db
docker start codexbot
```

## 13. 公网暴露检查

查看端口：

```bash
docker ps
```

正常情况下，`codexbot` 不应该出现类似：

```text
0.0.0.0:5432->5432/tcp
0.0.0.0:6379->6379/tcp
0.0.0.0:5000->5000/tcp
```

当前推荐 `docker run` 命令没有 `-p` 参数，所以不会主动暴露公网端口。

## 14. 常见问题

### docker compose up -d 报 unknown shorthand flag: 'd'

你的服务器不支持新版 `docker compose` 插件。不要用：

```bash
docker compose up -d
```

可以用旧命令：

```bash
docker-compose up -d
```

但你的 VPS 已经遇到过老版 compose 的兼容问题，所以后期更推荐本文第 4 步的 `docker run`。

### docker-compose up -d 报 KeyError: 'ContainerConfig'

这是老版 `docker-compose 1.29.2` 常见兼容问题，不是 `new.py` 写坏了。

你的实际解决方案是绕开 compose，用 `docker run` 重建：

```bash
cd /opt/codexbot
docker rm -f codexbot 2>/dev/null || true
docker pull ghcr.io/sykin7/codexbot:latest
```

然后执行第 4 步完整 `docker run` 命令。

### 容器启动了，但 Telegram 没反应

先看日志：

```bash
docker logs --tail=120 codexbot
```

常见原因：

- `BOT_TOKEN` 错误。
- `ADMIN_ID` 错误。
- 旧容器还在使用同一个 token。
- 镜像不是最新版。
- VPS 网络无法访问 Telegram。

检查旧容器：

```bash
docker ps -a
```

停掉旧 `tg-bot`：

```bash
docker stop tg-bot 2>/dev/null || true
docker rm tg-bot 2>/dev/null || true
docker restart codexbot
```

### 管理员菜单没有出现

先发：

```text
/id
```

确认返回值等于 `/opt/codexbot/.env` 里的 `ADMIN_ID`。

再检查容器代码：

```bash
docker exec codexbot sh -c "grep -n 'admin_menu_status\|admin_menu_resetverify\|Reset Verification\|one_time_keyboard=False\|/reloadrules\|/status' /app/bot.py | head -30"
```

如果没有输出，就是镜像旧，不是管理员权限问题。

### BOT_TOKEN and ADMIN_ID must be set

检查 `.env`：

```bash
cat /opt/codexbot/.env
```

至少要有：

```env
BOT_TOKEN=真实Token
ADMIN_ID=你的Telegram数字ID
```

### Unauthorized

`BOT_TOKEN` 错误，回 `@BotFather` 重新确认。

### Conflict: terminated by other getUpdates request

还有另一个容器或程序在使用同一个 Telegram Bot Token。

```bash
docker ps -a
```

停掉旧容器后重启：

```bash
docker stop tg-bot 2>/dev/null || true
docker rm tg-bot 2>/dev/null || true
docker restart codexbot
```

### codexbot exited with code 137

这是容器被系统强制杀掉，通常是内存不足。保持单容器 SQLite 轻量版，不要默认启用 Redis + PostgreSQL。

检查：

```bash
docker inspect codexbot --format '{{.State.OOMKilled}} {{.State.ExitCode}} {{.State.Error}}'
free -h
```

## 15. 后期正确更新流程

本地代码改完后：

1. 确认只维护 `new.py`，不要再恢复 `机器.py`。
2. 本地执行 `python -m py_compile new.py`。
3. 推送到 GitHub 的 `codex` 分支。
4. 等 GitHub Actions 构建 `ghcr.io/sykin7/codexbot:latest` 成功。
5. VPS 执行第 11 节“更新镜像并重建”。
6. 用第 6 节 `grep` 命令确认容器里是新版代码。
7. Telegram 发送 `/status`、`/help`、`/reloadrules` 检查功能。
