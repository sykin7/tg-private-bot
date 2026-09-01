# CodexBot 专属 VPS Docker 部署与维护方案

这份文档按你当前 VPS 的真实情况整理：Docker 已安装，推荐部署目录为 `/opt/codexbot`，镜像使用 `ghcr.io/sykin7/spamguard-bot:latest`，运行方式推荐单容器 SQLite 轻量版。

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
BOT_DB_PATH=/app/data/bot_core.db
REMOTE_SPAM_URL=
```

说明：

- `BOT_TOKEN`：从 `@BotFather` 获取。
- `ADMIN_ID`：你的 Telegram 数字 ID，可以用 `@userinfobot` 获取。
- `OWNER_ID`：可以留空，已经设置 `ADMIN_ID` 即可。
- `BOT_DB_PATH=/app/data/bot_core.db`：容器内 SQLite 数据库路径，配合 `-v /opt/codexbot/data:/app/data` 使用，不要随便改。
- `REMOTE_SPAM_URL`：可留空，留空时使用脚本内置和默认规则。
- `AI_ENABLED`：可选，默认 `false`。要启用第三方 AI 广告判定时改成 `true`，并配置 `AI_PROVIDER`、`AI_BASE_URL`、`AI_API_KEY`、`AI_MODEL`。
- `RULE_LEARN_ENABLED`：可选，默认 `true`。同一广告特征重复命中达到阈值后自动学习，管理员按钮仍可确认或忽略。
- `GROUP_ENABLED`：可选，默认 `true`。机器人加入群并被设为管理员后，自动接管入群审核和群内广告检测。

### .env 变量怎么改

常用变量：

| 变量名 | 是否建议修改 | 说明 |
| :--- | :---: | :--- |
| `BOT_TOKEN` | 必须改 | 你的 BotFather Token。换机器人时才改。 |
| `ADMIN_ID` | 必须改 | 你的 Telegram 数字 ID。管理员菜单、封禁、广播都靠它识别。 |
| `OWNER_ID` | 通常不改 | 备用管理员 ID。已经填了 `ADMIN_ID` 就可以留空。 |
| `BOT_DB_PATH` | 不建议改 | 固定 `/app/data/bot_core.db`，数据实际落在 VPS 的 `/opt/codexbot/data`。 |
| `REMOTE_SPAM_URL` | 可选 | 自定义第三方广告规则 TXT 地址。留空用默认规则。 |
| `AI_ENABLED` | 可选 | 是否启用第三方 AI 广告判定。默认 `false`，不填不影响本地规则。 |
| `AI_PROVIDER` | 可选 | AI 协议：`openai-compatible`、`anthropic` 或 `gemini`。默认 `openai-compatible`。 |
| `AI_BASE_URL` | 可选 | 按协议填 API 地址。OpenAI 兼容例如 `https://api.deepseek.com/v1`；Anthropic 用 `https://api.anthropic.com`；Gemini 用 `https://generativelanguage.googleapis.com`。 |
| `AI_API_KEY` | 可选 | 第三方模型 API Key。只放 VPS 的 `.env`，不要上传 GitHub。 |
| `AI_MODEL` | 可选 | 模型名称，按服务商填写。默认 `gpt-4o-mini`，例如 `deepseek-chat`、`claude-3-5-sonnet-latest`、`gemini-2.0-flash`。 |
| `AI_MAX_TOKENS` | 可选 | 单次 AI 回复最大 token 数。默认 `300`，Anthropic 必填。 |
| `AI_RESPONSE_FORMAT` | 可选 | 是否请求模型返回 JSON。Anthropic 无标准 JSON 参数，只能靠提示词约束；默认 `false`，避免部分严格网关拒绝额外参数。 |
| `AI_MIN_SCORE` | 可选 | 本地风险分达到该值时触发 AI 复核。默认 `5`。 |
| `AI_ALWAYS_CHECK` | 可选 | `true` 时所有待判定内容都请求 AI。默认 `false`。 |
| `AI_PROFILE_CHECK` | 可选 | 入群申请是否对用户资料做 AI 判定。默认 `true`。 |
| `RULE_LEARN_ENABLED` | 可选 | 是否启用广告规则学习。默认 `true`，`false` 时完全不保存反馈。 |
| `RULE_AUTO_LEARN_ENABLED` | 可选 | 是否启用自动学习。默认 `true`。 |
| `RULE_AUTO_LEARN_THRESHOLD` | 可选 | 同一特征重复命中多少次自动学习。默认 `3`。 |
| `RULE_AUTO_LEARN_MAX_RULES` | 可选 | 学习反馈表最多保留条数。默认 `200000`，超出后按最旧优先清理。 |
| `RULE_AUTO_LEARN_RETENTION_DAYS` | 可选 | 未确认样本保留天数。默认 `30`。 |
| `RULE_IGNORE_RETENTION_DAYS` | 可选 | 管理员忽略样本保留天数。默认 `7`。 |
| `RULE_LEARNED_MEMORY_LIMIT` | 可选 | 加载进内存参与判断的学习特征上限。默认 `50000`，控制低内存 VPS 占用。 |
| `RULE_EXACT_MAX_TERMS` | 可选 | 学习特征精确匹配最大条数。默认 `200000`。 |
| `RULE_REGEX_MAX_KEYWORDS` | 可选 | 第三方普通规则编译成正则的最大关键词数。默认 `20000`。 |
| `RULE_REGEX_BATCH_SIZE` | 可选 | 正则分批编译大小。默认 `2000`。 |
| `AI_KEYWORDS_LIMIT` | 可选 | 每次给 AI 的关键词上限，唯一控制项。默认 `2000`。 |
| `RULE_SYNC_GITHUB_REPO` | 可选 | GitHub 规则仓库，格式 `owner/repo`。留空不同步 GitHub。 |
| `RULE_SYNC_GITHUB_PATH` | 可选 | GitHub 规则文件路径，例如 `spam.txt`。 |
| `RULE_SYNC_GITHUB_BRANCH` | 可选 | 写入 GitHub 规则文件的分支。默认 `main`。 |
| `RULE_SYNC_GITHUB_TOKEN` | 可选 | GitHub Personal Access Token，需规则仓库 contents 读写权限。只放 VPS 的 `.env`。 |
| `RULE_SYNC_R2_ENDPOINT` | 可选 | Cloudflare R2 S3 API 端点，例如 `https://你的账号ID.r2.cloudflarestorage.com`。配置后既同步也拉取该对象。 |
| `RULE_SYNC_R2_BUCKET` | 可选 | R2 存储桶名称。 |
| `RULE_SYNC_R2_KEY` | 可选 | R2 对象键，例如 `spam.txt`。 |
| `RULE_SYNC_R2_REGION` | 可选 | R2 区域。默认 `auto`。 |
| `RULE_SYNC_R2_ACCESS_KEY` | 可选 | R2 Access Key ID。只放 VPS 的 `.env`。 |
| `RULE_SYNC_R2_SECRET_KEY` | 可选 | R2 Secret Access Key。只放 VPS 的 `.env`。 |
| `R2_USAGE_PATH` | 可选 | R2 用量计数 SQLite 路径。默认 `/app/data/r2_usage.db`。 |
| `R2_LOCAL_RULES_PATH` | 可选 | 本地规则镜像 SQLite 路径。留空复用 `R2_USAGE_PATH`。 |
| `R2_FETCH_INTERVAL` | 可选 | R2 拉取缓存秒数。默认 `10800`（每3小时一次）。 |
| `R2_MAX_STORAGE_GB` | 可选 | R2 免费存储上限 GB。默认 `10`。 |
| `R2_STORAGE_WARN_RATIO` | 可选 | R2 存储写入硬上限比例。默认 `0.9`，即 9 GB，超过就拒绝写入并提醒。 |
| `R2_MAX_CLASS_A_MONTHLY` | 可选 | R2 Class A 每月请求上限。默认 `900000`，免费层 100 万次的 90%。 |
| `R2_MAX_CLASS_B_MONTHLY` | 可选 | R2 Class B 每月请求上限。默认 `9000000`，免费层 1000 万次的 90%。 |
| `R2_RATE_LIMIT_COOLDOWN` | 可选 | R2 429/503 限流后的暂停秒数。默认 `3600`。 |
| `RULE_SYNC_R2_ENDPOINT_2` 到 `_20` | 可选 | 第二到第二十个 R2 账户端点；每账户配套 `RULE_SYNC_R2_BUCKET_2`、`RULE_SYNC_R2_KEY_2`、`RULE_SYNC_R2_REGION_2`、`RULE_SYNC_R2_ACCESS_KEY_2`、`RULE_SYNC_R2_SECRET_KEY_2`。第一个账户配额满或限流后自动切换。 |
| `R2_MIRROR_INTERVAL` | 可选 | 多 R2 账户镜像同步间隔秒数。默认 `10800`（每3小时一次）；任一账户恢复后立即补同步。 |
| `R2_SYNC_INTERVAL` | 可选 | 学习规则写入 R2 的同步间隔秒数。默认 `10800`（每3小时一次）；学习先写入本地 SQLite 生效，到点统一推送 R2。 |
| `GROUP_ENABLED` | 可选 | 是否启用群聊管理。默认 `true`。 |
| `GROUP_JOIN_APPROVE` | 可选 | 是否接管入群申请。默认 `true`。 |
| `GROUP_AUTO_APPROVE` | 可选 | 正常申请是否自动通过。默认 `true`。 |
| `GROUP_JOIN_REVIEW_TIMEOUT` | 可选 | 人工审核超时兜底等待秒数。默认 `600`（10 分钟）：广告判定自动拒绝并在该群封禁，用户仍可私聊申诉，正常判定自动通过。 |
| `GROUP_JOIN_REQUIRED_CHANNEL` | 可选 | 入群前必须关注的频道，填 `@username` 或数字频道 ID。留空关闭；开启后未关注的申请先拒绝并提示。 |
| `GROUP_BAN_ON_SPAM` | 可选 | 群内广告是否永久封禁发广告用户。默认 `true`。 |
| `GROUP_DELETE_SPAM` | 可选 | 群内广告是否删除原消息。默认 `true`。 |
| `GROUP_SPAM_WARN_LIMIT` | 可选 | 群内广告命中几次后永久封禁。默认 `1`：首次命中即删消息加永久封，无警告缓冲；设 `2` 才首次只删消息，第二次命中才封。这个值是「第几次命中就封」，不是「警告几次」。强特征词任何时候直接封，不吃此计数。 |
| `GROUP_IDS` | 可选 | 只管理指定群，逗号分隔整数群 ID，Telegram 群 ID 通常为负数。留空管理所有已启用群聊。 |
| `GROUP_ADMIN_IDS` | 可选 | 接收群聊通知的管理员 ID，逗号分隔。留空使用 `ADMIN_ID`。Telegram 群原生管理员无需配置，会自动识别。 |
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

可选功能只在你需要时追加。例如启用第三方 AI 广告判定：

```bash
cat >> /opt/codexbot/.env <<'EOF'
AI_ENABLED=true
AI_PROVIDER=openai-compatible
AI_BASE_URL=https://你的模型网关/v1
AI_API_KEY=你的模型APIKey
AI_MODEL=deepseek-chat
EOF
```

用 Anthropic Claude 原生接口：

```bash
cat >> /opt/codexbot/.env <<'EOF'
AI_ENABLED=true
AI_PROVIDER=anthropic
AI_BASE_URL=https://api.anthropic.com
AI_API_KEY=你的AnthropicAPIKey
AI_MODEL=claude-3-5-sonnet-latest
AI_MAX_TOKENS=300
EOF
```

用 Google Gemini 原生接口：

```bash
cat >> /opt/codexbot/.env <<'EOF'
AI_ENABLED=true
AI_PROVIDER=gemini
AI_BASE_URL=https://generativelanguage.googleapis.com
AI_API_KEY=你的GeminiAPIKey
AI_MODEL=gemini-2.0-flash
EOF
```

如果你要把学习到的广告规则写回自己的 GitHub 规则仓库，追加：

```bash
cat >> /opt/codexbot/.env <<'EOF'
RULE_SYNC_GITHUB_REPO=你的GitHub用户名/规则仓库名
RULE_SYNC_GITHUB_PATH=spam.txt
RULE_SYNC_GITHUB_BRANCH=main
RULE_SYNC_GITHUB_TOKEN=你的GitHubPersonalAccessToken
EOF
```

如果你要把学习到的广告规则备份到 Cloudflare R2，追加：

```bash
cat >> /opt/codexbot/.env <<'EOF'
RULE_SYNC_R2_ENDPOINT=https://你的账号ID.r2.cloudflarestorage.com
RULE_SYNC_R2_BUCKET=你的存储桶名
RULE_SYNC_R2_KEY=spam.txt
RULE_SYNC_R2_REGION=auto
RULE_SYNC_R2_ACCESS_KEY=你的R2AccessKeyID
RULE_SYNC_R2_SECRET_KEY=你的R2SecretAccessKey
EOF
```

要配置第二个及以上 R2 账户，把上面的变量复制成 `RULE_SYNC_R2_ENDPOINT_2`、`RULE_SYNC_R2_BUCKET_2` 等 `_2` 到 `_20` 后缀即可。第一个账户配额用满或限流时会自动切换下一个可用账户，多账户数据保持同步。

GitHub 和 R2 可以同时配置。全部留空时只做本地学习，不推送远程规则文件。

群聊管理默认已启用。要限制只管理指定群，追加 `GROUP_IDS`：

```bash
cat >> /opt/codexbot/.env <<'EOF'
GROUP_IDS=-1001234567890,-1009876543210
EOF
```

机器人必须被设为目标群的管理员，群入群审核和广告封禁才有效。

群内编辑消息和普通群消息共用同一套广告检测：编辑成广告会删除原消息、永久封禁发广告用户并通知管理员，正常编辑不动作。入群申请已被自动处理时，管理员再点通过或拒绝按钮只会收到“已处理”提示，不会重复操作。

修改 `.env` 后必须重建或重启容器才会生效。稳妥做法是执行本文第 11 节“更新镜像并重建”的完整 `docker run` 命令。

## 4. 一键启动或重装

推荐使用这段命令。它会删除旧 `codexbot` 容器，拉取最新镜像，然后重新启动。不会删除 `/opt/codexbot/data`。

```bash
cd /opt/codexbot

docker rm -f codexbot 2>/dev/null || true

docker pull ghcr.io/sykin7/spamguard-bot:latest

docker run -d \
  --name codexbot \
  --restart unless-stopped \
  --env-file /opt/codexbot/.env \
  -e BOT_DB_PATH=/app/data/bot_core.db \
  -v /opt/codexbot/data:/app/data \
  --log-driver json-file \
  --log-opt max-size=50m \
  --log-opt max-file=5 \
  ghcr.io/sykin7/spamguard-bot:latest
```

## 5. 检查是否启动成功

```bash
docker ps | grep codexbot
docker logs --tail=80 codexbot
docker inspect codexbot --format '{{json .HostConfig.LogConfig}}'
```

正常应看到：

```text
codexbot   ghcr.io/sykin7/spamguard-bot:latest   Up
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

1. 本地把最新 `new.py` 推到 GitHub 的 `v2` 分支。
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

`/status` 会显示 SQLite、AI 广告识别和群聊管理是否启用。

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

群内权限是分开的：普通成员可用 `/id`、`/help`、`/spamtest`；群管理员可用 `/status`、`/reloadrules`、`/ban`、`/unban`。

群级 `/ban` 和群内自动永久封禁都会写入全局黑名单，被封用户申请加入其他已接管的群会被直接拒绝并封禁；全局白名单用户群管理员封不动。群级 `/unban` 只有在这条全局黑名单是本群封进去的、且该用户没被其他群封禁时，才会一起移出全局黑名单，否则只解除本群。`ADMIN_ID` 不受此限制；全局 `/abl`、`/dbl` 仍只允许 `ADMIN_ID` 私聊使用。

右侧聊天框按钮菜单里的“解除封禁、加白名单、群发广播、广告测试”等按钮是快捷入口；点击后机器人会按当前语言提示你发送对应命令和参数。

## 9. 广告拦截确认

普通用户每一条准备转发给管理员的消息，都会先经过广告规则过滤。流程是：

```text
黑名单检查 -> 临时封禁检查 -> 白名单判断 -> 频率检查 -> 广告规则检查 -> 人机验证状态判断 -> 转发给管理员
```

重点：

- 通过人机验证后，仍然要经过广告规则。
- 白名单用户才会跳过广告规则。
- 白名单不跳过临时封禁：`ban_until` 封禁期内，私聊消息同样被忽略，直到解封或到期。
- 全局白名单在群里同样免检：群消息不做广告判定，入群申请直接通过，不查频道关注。
- 命中广告后不会把广告原文转发给管理员。
- 管理员只收到干净的拦截通知和处理按钮。
- 每条私聊或群消息只做一次完整广告判定，不会重复请求 AI。

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

## 广告规则学习与同步

机器人拦截私聊广告、群聊广告或编辑消息广告后，会先把样本写入本地 `spam_feedback` 表。同一特征重复命中达到 `RULE_AUTO_LEARN_THRESHOLD` 次后自动确认学习并立即合并进当前规则；管理员通知里的“学习规则 / 不学习”按钮仍可手动确认或忽略。

保存的不是原始广告全文，而是提取后的稳定特征：域名、`t.me/` 链接、`@用户名`、联系方式、混合字母数字 token。手机号等敏感内容不会进数据库，日志也不打印这些特征。

学习成功后自动推送已配置渠道：

- GitHub：直接写入 `RULE_SYNC_GITHUB_REPO` 仓库的 `RULE_SYNC_GITHUB_PATH` 文件，使用 `RULE_SYNC_GITHUB_BRANCH` 分支。
- Cloudflare R2：按 S3 API 写入 `RULE_SYNC_R2_BUCKET` 桶的 `RULE_SYNC_R2_KEY` 对象。

配置 R2 后，规则会先拉取到本地 SQLite 镜像（`R2_LOCAL_RULES_PATH`，留空复用 `R2_USAGE_PATH`），日常判定和学习只读本地，不产生 R2 请求。默认每3小时拉取一次（`R2_FETCH_INTERVAL=10800`）、每3小时写入一次学习规则（`R2_SYNC_INTERVAL=10800`）、每3小时镜像一次到多个 R2 账户（`R2_MIRROR_INTERVAL=10800`），形成“学习 -> 本地生效 -> 每3小时备份进 R2 -> 每3小时拉回本地”的闭环。R2 同步始终用 PUT 覆盖写同一个 `RULE_SYNC_R2_KEY` 对象，不会每次生成新对象。`REMOTE_SPAM_URL` 指向的 GitHub 规则和 R2 本地镜像会合并使用。

R2 默认按 Cloudflare 免费层上限的 90% 控制：Class A 90 万次/月、Class B 900 万次/月，保留 10% 冗余。收到 429/503 限流后暂停该账户 R2 请求 1 小时，暂停期间本地广告判定、GitHub 同步和规则缓存都不受影响。

R2 免费存储同样保留 10% 冗余：默认按 10 GB 上限、90% 即约 9 GB 后停止向该 R2 写入并通知管理员。本地规则按规则文本去重分类存储，同一规则只占一行。

支持配置多个 R2 账户：旧变量为账户 1，追加 `_2` 到 `_20` 后缀即可添加更多账户。每次请求前先检查该账户额度，触顶或限流时自动切换下一个可用账户；多个账户按 `R2_MIRROR_INTERVAL` 定时镜像同步，保持规则文本一致，镜像会跳过刚拉取过的源账户避免重复写入，任一账户恢复后立即补同步，写入成功才解除该账户的恢复标记。

R2 触顶、存储接近上限或收到 429/503 限流时会向管理员发送一次提醒，消息带账户编号和预计恢复时间，同一自然月只提醒一次；Cloudflare 免费配额按 UTC 自然月重置，次月会自动恢复，不用手动干预。

推送失败时样本保留为未同步，机器人启动和规则刷新周期会重试。`/status` 会显示当前已学习规则条数和已配置的同步渠道。

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
docker pull ghcr.io/sykin7/spamguard-bot:latest

docker run -d \
  --name codexbot \
  --restart unless-stopped \
  --env-file /opt/codexbot/.env \
  -e BOT_DB_PATH=/app/data/bot_core.db \
  -v /opt/codexbot/data:/app/data \
  --log-driver json-file \
  --log-opt max-size=50m \
  --log-opt max-file=5 \
  ghcr.io/sykin7/spamguard-bot:latest
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
docker pull ghcr.io/sykin7/spamguard-bot:latest
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
2. 本地执行 `python -m py_compile new.py ai_classifier.py rule_sync.py` 和 `python -m unittest discover -v`。
3. 推送到 GitHub 的 `v2` 分支。
4. 等 GitHub Actions 构建 `ghcr.io/sykin7/spamguard-bot:latest` 成功。
5. VPS 执行第 11 节“更新镜像并重建”。
6. 用第 6 节 `grep` 命令确认容器里是新版代码。
7. Telegram 发送 `/status`、`/help`、`/reloadrules` 检查功能。
