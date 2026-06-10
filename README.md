# CodexBot

CodexBot 是一个可 Docker 部署的 Telegram 私聊客服与反垃圾机器人。它支持私聊消息转发、管理员匿名回复、人机验证、广告规则拦截、黑名单、白名单、临时封禁、广播、管理员菜单、第三方广告规则加载状态通知和基础运行状态检查。

本项目当前只维护一个主脚本：`new.py`。Docker 镜像构建时会把 `new.py` 复制成容器内的 `/app/bot.py` 并运行它。

## 当前推荐方案

- 推荐 VPS 部署目录：`/opt/codexbot`
- 推荐镜像：`ghcr.io/sykin7/codexbot:latest`
- 推荐部署方式：单容器轻量版，SQLite 保存数据
- 推荐数据目录：`/opt/codexbot/data`
- 推荐日志限制：每个容器 `50MB x 5`，最多约 `250MB`
- 你的专属 VPS 文档：[VPS-DEPLOYMENT.md](VPS-DEPLOYMENT.md)

不建议在低内存 VPS 上默认使用 Redis + PostgreSQL 三容器版。你的 VPS 已经验证过三容器版可能触发 `exited with code 137`，单容器 SQLite 方案更稳。

## 安全原则

不要把真实密钥写进镜像、代码或 GitHub 仓库。

- `BOT_TOKEN`、`ADMIN_ID` 只放在 VPS 的 `/opt/codexbot/.env`。
- `.env.example` 只能放示例和说明，不能写真实 token。
- Docker 镜像只包含代码和依赖，不包含你的 token。
- 轻量部署不配置 `ports:`，机器人不会把数据库或内部服务暴露到公网。
- 不要执行会误删数据的清理命令，例如 `docker system prune`、`docker volume prune`，除非你清楚影响范围。

## 环境变量总表

这些是 `new.py` 当前实际会读取的变量。生产环境只在 VPS 的 `/opt/codexbot/.env` 里填写真实值，不要写进 GitHub。

| 变量名 | 必填 | 推荐值 / 默认值 | 用法说明 |
| :--- | :---: | :--- | :--- |
| `BOT_TOKEN` | 是 | 无 | BotFather 给你的 Telegram Bot Token。必须填写。 |
| `ADMIN_ID` | 是 | 无 | 管理员 Telegram 数字 ID。推荐使用这个变量。 |
| `OWNER_ID` | 否 | 空 | 备用管理员 ID。`ADMIN_ID` 为空时才会用它。 |
| `REDIS_ENABLED` | 否 | 轻量版填 `false` | 是否启用 Redis。你的 VPS 推荐 `false`，使用内存缓存即可。 |
| `BOT_DB_PATH` | 否 | `/app/data/bot_core.db` | SQLite 数据库路径。Docker 轻量版不要改。 |
| `REMOTE_SPAM_URL` | 否 | 空或默认规则地址 | 第三方广告规则 TXT 地址。留空时使用代码里的默认地址和内置兜底规则。 |
| `WELCOME_ZH` | 否 | 代码默认中文欢迎语 | 自定义中文欢迎语。留空即可。 |
| `VERIFIED_ZH` | 否 | 代码默认中文验证通过语 | 自定义中文验证通过提示。留空即可。 |
| `AUTO_REPLY_ZH` | 否 | 代码默认中文已送达提示 | 用户消息转发后，机器人给用户的中文自动回馈。留空即可。 |
| `WELCOME_EN` | 否 | 代码默认英文欢迎语 | 自定义英文欢迎语。留空即可。 |
| `VERIFIED_EN` | 否 | 代码默认英文验证通过语 | 自定义英文验证通过提示。留空即可。 |
| `AUTO_REPLY_EN` | 否 | 代码默认英文已送达提示 | 用户消息转发后，机器人给用户的英文自动回馈。留空即可。 |
| `DATABASE_URL` | 否 | 空 | PostgreSQL 连接串。轻量版不用填。 |
| `POSTGRES_DSN` | 否 | 空 | `DATABASE_URL` 的备用名称。轻量版不用填。 |
| `REDIS_URL` | 否 | 空 | Redis 连接地址。轻量版不用填。 |
| `MIGRATE_SQLITE_TO_POSTGRES` | 否 | `false` | 只有从 SQLite 迁移到 PostgreSQL 时才临时设为 `true`。你的轻量版保持 `false`。 |

你的 VPS 推荐 `.env` 最小配置：

```env
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
OWNER_ID=
REDIS_ENABLED=false
BOT_DB_PATH=/app/data/bot_core.db
REMOTE_SPAM_URL=
```

一般只需要改 `BOT_TOKEN`、`ADMIN_ID`、`REMOTE_SPAM_URL` 和自定义提示语。不要在 `.env.example` 里填写真实 token。

VPS 上一键覆盖写入 `.env`：

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

如果只是追加自定义提示语，可以用：

```bash
cat >> /opt/codexbot/.env <<'EOF'
WELCOME_ZH=👋 您好，请直接发送消息，管理员看到后会回复。
VERIFIED_ZH=✅ 验证通过，可以发送消息了。
AUTO_REPLY_ZH=✅ 已送达，管理员会尽快回复。
WELCOME_EN=👋 Hello, please send your message directly.
VERIFIED_EN=✅ Verified. You can now send messages.
AUTO_REPLY_EN=✅ Message sent. The admin will reply shortly.
EOF
```

如果要修改已经写过的变量，推荐重新执行“覆盖写入 `.env`”那段命令，避免同一个变量在 `.env` 里出现多次。

## 项目文件

- `new.py`：机器人主脚本，本项目只维护这个文件。
- `Dockerfile`：构建镜像，把 `new.py` 复制为容器内 `/app/bot.py`。
- `requirements.txt`：Python 依赖。
- `docker-compose.bot-lite.yml`：轻量单容器部署示例。
- `docker-compose.bot.yml`：进阶三容器部署示例，包含 Redis 和 PostgreSQL。
- `.env.example`：中文环境变量示例，不填写真实密钥。
- `.github/workflows/build.yml`：GitHub Actions 构建并推送 GHCR 镜像。
- `VPS-DEPLOYMENT.md`：按你当前 VPS 情况整理的专属部署与维护文档。

## 功能概览

- 用户私聊机器人后，消息会转发给管理员。
- 管理员回复机器人转发来的消息，可以匿名回复用户。
- 新用户需要通过按钮人机验证。
- 每一条准备转发给管理员的普通用户消息，都会先经过广告规则过滤。
- 白名单用户会跳过广告和频率检查。
- 命中广告规则后，默认拦截并临时封禁，不再把广告原文转发给管理员。
- 广告拦截后会给管理员一个干净通知，并提供“封禁用户 / 不封禁”按钮。
- 支持第三方广告规则 URL，启动和重载时会通知管理员加载状态。
- 支持用户编辑消息检测，编辑成广告也会拦截。
- 用户删除已发送消息后，已经转发到管理员侧的副本不会被删除。
- 支持 Telegram 官方命令菜单和右侧聊天框按钮菜单；按钮菜单可手动隐藏，点击按钮后不会自动消失。
- 菜单按管理员和普通用户分离，并支持中文 / 英文显示。

## 管理员菜单

管理员发送 `/start` 或 `/menu` 后，右侧聊天框按钮菜单应显示完整管理功能。这个菜单是 Telegram Reply Keyboard：可以手动隐藏，隐藏后可从输入框旁边的键盘按钮再次展开；点击菜单按钮后不会自动消失。

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

普通用户菜单只显示：

```text
📨 联系管理员
❓ 常见问题
🌐 切换语言
```

英文普通用户菜单：

```text
📨 Contact Admin    ❓ FAQ
🌐 Change Language
```

Telegram 官方 slash 命令菜单也会注册普通用户和管理员两套命令。注意：官方命令菜单的描述语言跟随 Telegram 客户端语言；右侧按钮菜单和机器人回复内容跟随用户在机器人里选择的语言。

如果你是管理员但仍然看到普通用户菜单，优先检查两件事：

1. `/id` 返回的 Telegram 数字 ID 是否和 VPS `/opt/codexbot/.env` 里的 `ADMIN_ID` 一致。
2. VPS 容器里的镜像是否真的是新版代码。

检查容器代码是否为新版：

```bash
docker exec codexbot sh -c "grep -n 'admin_menu_status\|admin_menu_resetverify\|Reset Verification\|one_time_keyboard=False\|/reloadrules\|/status' /app/bot.py | head -30"
```

如果没有输出，说明 VPS 当前镜像还是旧代码，需要先让 GitHub Actions 构建最新镜像，再到 VPS 拉取。

## 管理员指令

直接发送给机器人：

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

说明：

- `/status`：查看机器人、数据库、广告规则加载状态。
- `/reloadrules`：手动重新拉取第三方广告规则。
- `/spamtest 内容`：测试广告规则是否能命中，不会真的封禁用户。
- `/resetverify`：一键清空普通用户验证状态，确认后他们下次发消息需要重新完成人机验证。
- `/vlist wl`：查看白名单。
- `/vlist bl`：查看黑名单。
- `/vlist ban`：查看临时封禁名单，并支持按钮解封。
- `/awl`：加入白名单，同时清理黑名单、临时封禁和验证状态冲突。
- `/abl`：加入黑名单，同时清理白名单、临时封禁和验证状态冲突。

右侧聊天框按钮菜单里的“解除封禁、加白名单、群发广播、广告测试”等按钮是快捷入口；点击后机器人会按当前语言提示你发送对应命令和参数。

## 广告拦截逻辑

普通用户私聊机器人时，核心流程是：

```text
黑名单检查 -> 白名单判断 -> 频率检查 -> 广告规则检查 -> 人机验证状态判断 -> 转发给管理员
```

也就是说，用户通过人机验证之后继续发广告，仍然会被广告规则拦截。真正绕过广告规则的是白名单用户。

第三方广告规则会在启动后自动加载，也可以用 `/reloadrules` 手动重载。管理员可用 `/status` 查看当前规则状态。

## Docker 日志与数据限制

推荐日志限制：

```bash
--log-driver json-file \
--log-opt max-size=50m \
--log-opt max-file=5
```

含义：每个容器最多保留 5 个日志文件，每个 50MB，最多约 250MB。超过后 Docker 自动删除最旧日志。

脚本内部也有清理机制：

- 消息映射记录按数量和时间清理。
- SQLite 数据库超过限制后会触发整理压缩。
- 验证码、频率、自动回复、用户状态等运行时缓存会自动过期。
- 运行时缓存会在容器重启后清空。

注意：核心数据不能粗暴自动覆盖，例如白名单、黑名单、封禁记录、用户状态。这些数据保存在 `/opt/codexbot/data/bot_core.db`，不要删除 `/opt/codexbot/data`。

## GitHub Actions 与镜像更新

修改以下文件后，需要推送到 `codex` 分支并等待 GitHub Actions 构建成功：

- `new.py`
- `Dockerfile`
- `requirements.txt`
- `.github/workflows/build.yml`

镜像构建成功后，VPS 才能拉到新版：

```bash
docker pull ghcr.io/sykin7/codexbot:latest
```

如果 VPS 拉取后功能还是旧的，用下面命令确认容器内代码：

```bash
docker exec codexbot sh -c "grep -n 'admin_menu_status\|admin_menu_resetverify\|Reset Verification\|one_time_keyboard=False\|/reloadrules\|/status' /app/bot.py | head -30"
```

## 本地检查

至少做语法检查：

```bash
python -m py_compile new.py
```

本地如果没有安装 `telebot`，导入级运行测试可能失败，这是依赖环境问题；语法检查通过即可先确认代码没有 Python 语法错误。

## 快速 VPS 更新命令

你的 VPS 老版 `docker-compose` 容易遇到 `KeyError: 'ContainerConfig'`。因此实际维护时，推荐直接使用 `docker run` 重建单容器：

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

检查：

```bash
docker ps | grep codexbot
docker logs --tail=80 codexbot
docker inspect codexbot --format '{{json .HostConfig.LogConfig}}'
```
