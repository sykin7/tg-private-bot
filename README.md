# CodexBot

CodexBot 是一个可 Docker 部署的 Telegram 私聊客服与反垃圾机器人。它支持私聊消息转发、管理员匿名回复、人机验证、广告规则拦截、第三方 AI 广告复核、黑名单、白名单、临时封禁、广播、管理员菜单、群聊入群审核、群内广告检测封禁和基础运行状态检查。

本项目维护四个 Python 文件：主脚本 `new.py`、AI 判定模块 `ai_classifier.py`、规则同步模块 `rule_sync.py` 和共享环境变量工具 `env_utils.py`。Docker 镜像构建时会把 `new.py` 复制成容器内的 `/app/bot.py` 并运行它，其余模块会一起复制进镜像。

## 当前推荐方案

- 推荐 VPS 部署目录：`/opt/codexbot`
- 推荐镜像：`ghcr.io/sykin7/spamguard-bot:latest`
- 推荐部署方式：单容器轻量版，SQLite 保存数据
- 推荐数据目录：`/opt/codexbot/data`
- 推荐日志限制：每个容器 `50MB x 5`，最多约 `250MB`
- 你的专属 VPS 文档：[VPS-DEPLOYMENT.md](VPS-DEPLOYMENT.md)

代码已移除 Redis 和 PostgreSQL 依赖，固定使用单容器 + SQLite，避免低内存 VPS 触发 `exited with code 137`。旧的 `docker-compose.bot.yml` 三容器示例仅保留作参考，不再维护。

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
| `BOT_DB_PATH` | 否 | `/app/data/bot_core.db` | SQLite 数据库路径。Docker 轻量版不要改。 |
| `REMOTE_SPAM_URL` | 否 | 空或默认规则地址 | 第三方广告规则 TXT 地址。留空时使用代码里的默认地址和内置兜底规则。 |
| `AI_ENABLED` | 否 | `false` | 是否启用第三方 AI 广告判定。留空或关闭时只走本地规则。 |
| `AI_PROVIDER` | 否 | `openai-compatible` | AI 协议：`openai-compatible`、`anthropic` 或 `gemini`。 |
| `AI_BASE_URL` | 否 | 空 | 按协议填 API 地址，例如 OpenAI 兼容 `https://api.deepseek.com/v1`、Anthropic `https://api.anthropic.com`、Gemini `https://generativelanguage.googleapis.com`。 |
| `AI_API_KEY` | 否 | 空 | 第三方模型 API Key。只填写在 VPS 的 `.env`，不要提交到 GitHub。 |
| `AI_MODEL` | 否 | `gpt-4o-mini` | 模型名称，按服务商填写，例如 `deepseek-chat`、`claude-3-5-sonnet-latest`、`gemini-2.0-flash`。 |
| `AI_MAX_TOKENS` | 否 | `300` | 单次 AI 回复最大 token 数。Anthropic 必填，其他协议也会带上。 |
| `AI_RESPONSE_FORMAT` | 否 | `false` | 是否请求模型返回 JSON。Anthropic 无标准 JSON 参数，只能靠提示词约束；默认 `false`，避免部分严格网关拒绝额外参数。 |
| `AI_TIMEOUT` | 否 | `20` | 单次 AI 请求超时秒数。 |
| `AI_MIN_SCORE` | 否 | `5` | 本地风险分达到该值时触发 AI 复核。 |
| `AI_ALWAYS_CHECK` | 否 | `false` | `true` 时所有待判定内容都请求 AI。 |
| `AI_PROFILE_CHECK` | 否 | `true` | 入群申请是否对用户资料做 AI 判定。 |
| `RULE_LEARN_ENABLED` | 否 | `true` | 是否启用广告规则学习。`false` 时不保存反馈也不同步。 |
| `RULE_AUTO_LEARN_ENABLED` | 否 | `true` | 同一广告特征重复命中达到阈值后自动确认学习。 |
| `RULE_AUTO_LEARN_THRESHOLD` | 否 | `3` | 同一特征重复命中多少次自动学习。 |
| `RULE_AUTO_LEARN_MAX_RULES` | 否 | `200000` | 学习反馈表最多保留条数，超出后按最旧优先清理。 |
| `RULE_AUTO_LEARN_RETENTION_DAYS` | 否 | `30` | 未确认学习样本保留天数。 |
| `RULE_IGNORE_RETENTION_DAYS` | 否 | `7` | 管理员忽略样本保留天数。 |
| `RULE_LEARNED_MEMORY_LIMIT` | 否 | `50000` | 最多加载进内存参与判断的学习特征条数。 |
| `RULE_EXACT_MAX_TERMS` | 否 | `200000` | 学习特征精确匹配最大条数。 |
| `RULE_REGEX_MAX_KEYWORDS` | 否 | `20000` | 第三方普通规则编译成正则的最大关键词数。 |
| `RULE_REGEX_BATCH_SIZE` | 否 | `2000` | 正则分批编译大小。 |
| `AI_KEYWORDS_LIMIT` | 否 | `2000` | 每次给 AI 的关键词上限，唯一控制项，防止提示词过长。 |
| `RULE_SYNC_GITHUB_REPO` | 否 | 空 | GitHub 规则仓库，格式 `owner/repo`。留空不同步 GitHub。 |
| `RULE_SYNC_GITHUB_PATH` | 否 | 空 | GitHub 规则文件路径，例如 `spam.txt`。 |
| `RULE_SYNC_GITHUB_BRANCH` | 否 | `main` | 写入 GitHub 规则文件的分支。 |
| `RULE_SYNC_GITHUB_TOKEN` | 否 | 空 | GitHub Personal Access Token，需规则仓库 contents 读写权限。只放 VPS 的 `.env`。 |
| `RULE_SYNC_R2_ENDPOINT` | 否 | 空 | Cloudflare R2 S3 API 端点。配置后既同步也拉取该对象参与判断。 |
| `RULE_SYNC_R2_BUCKET` | 否 | 空 | R2 存储桶名称。 |
| `RULE_SYNC_R2_KEY` | 否 | 空 | R2 对象键，例如 `spam.txt`。 |
| `RULE_SYNC_R2_REGION` | 否 | `auto` | R2 区域，默认 `auto`。 |
| `RULE_SYNC_R2_ACCESS_KEY` | 否 | 空 | R2 Access Key ID。只放 VPS 的 `.env`。 |
| `RULE_SYNC_R2_SECRET_KEY` | 否 | 空 | R2 Secret Access Key。只放 VPS 的 `.env`。 |
| `R2_USAGE_PATH` | 否 | `/app/data/r2_usage.db` | R2 用量计数 SQLite 路径。 |
| `R2_LOCAL_RULES_PATH` | 否 | 空 | 本地规则镜像 SQLite 路径。留空复用 `R2_USAGE_PATH`。 |
| `R2_FETCH_INTERVAL` | 否 | `10800` | R2 拉取缓存秒数，默认每3小时一次。 |
| `R2_MAX_STORAGE_GB` | 否 | `10` | R2 免费存储上限 GB，默认 10 GB。 |
| `R2_STORAGE_WARN_RATIO` | 否 | `0.9` | R2 存储写入硬上限比例，默认 9 GB；超过就拒绝写入并提醒。 |
| `R2_MAX_CLASS_A_MONTHLY` | 否 | `900000` | R2 Class A 每月请求上限，默认免费层 100 万次的 90%。 |
| `R2_MAX_CLASS_B_MONTHLY` | 否 | `9000000` | R2 Class B 每月请求上限，默认免费层 1000 万次的 90%。 |
| `R2_RATE_LIMIT_COOLDOWN` | 否 | `3600` | R2 收到 429/503 后暂停 R2 请求的秒数。 |
| `RULE_SYNC_R2_ENDPOINT_2` 到 `_20` | 否 | 空 | 第二到第二十个 R2 账户端点；每账户配套 `RULE_SYNC_R2_BUCKET_2`、`RULE_SYNC_R2_KEY_2`、`RULE_SYNC_R2_REGION_2`、`RULE_SYNC_R2_ACCESS_KEY_2`、`RULE_SYNC_R2_SECRET_KEY_2`。第一个账户配额满或限流后自动切换。 |
| `R2_MIRROR_INTERVAL` | 否 | `10800` | 多 R2 账户镜像同步间隔秒数，默认每3小时一次；任一账户恢复后立即补同步。 |
| `R2_SYNC_INTERVAL` | 否 | `10800` | 学习规则写入 R2 的同步间隔秒数，默认每3小时一次；学习先立即写入本地 SQLite，到点才统一推送 R2。 |
| `GROUP_ENABLED` | 否 | `true` | 是否启用群聊管理与入群审核。 |
| `GROUP_JOIN_APPROVE` | 否 | `true` | 是否接管入群申请。 |
| `GROUP_AUTO_APPROVE` | 否 | `true` | 正常申请是否自动通过。 |
| `GROUP_JOIN_REVIEW_TIMEOUT` | 否 | `600` | 进入人工审核后，管理员超时未处理时按规则自动兜底的等待秒数。广告判定自动拒绝并在该群封禁，用户仍可私聊申诉，正常判定自动通过。 |
| `GROUP_JOIN_REQUIRED_CHANNEL` | 否 | 空 | 入群前必须关注的频道，填 `@username` 或数字频道 ID。留空关闭；开启后未关注频道的申请会先被拒绝并提示。 |
| `GROUP_BAN_ON_SPAM` | 否 | `true` | 群内广告是否永久封禁发广告用户。 |
| `GROUP_DELETE_SPAM` | 否 | `true` | 群内广告是否删除原消息。 |
| `GROUP_SPAM_WARN_LIMIT` | 否 | `1` | 群内广告命中几次后永久封禁。默认 1 = 首次命中即删消息加永久封，无警告缓冲；设 2 才首次只删消息、第二次才封。强特征词任何时候直接封，不吃此计数。 |
| `GROUP_IDS` | 否 | 空 | 只管理这些群，逗号分隔整数群 ID，Telegram 群 ID 通常为负数。留空管理所有已启用群聊。 |
| `GROUP_ADMIN_IDS` | 否 | 空 | 接收群聊通知的管理员 ID，逗号分隔。留空使用 `ADMIN_ID`。Telegram 群原生管理员无需配置，会自动识别。 |
| `WELCOME_ZH` | 否 | 代码默认中文欢迎语 | 自定义中文欢迎语。留空即可。 |
| `VERIFIED_ZH` | 否 | 代码默认中文验证通过语 | 自定义中文验证通过提示。留空即可。 |
| `AUTO_REPLY_ZH` | 否 | 代码默认中文已送达提示 | 用户消息转发后，机器人给用户的中文自动回馈。留空即可。 |
| `WELCOME_EN` | 否 | 代码默认英文欢迎语 | 自定义英文欢迎语。留空即可。 |
| `VERIFIED_EN` | 否 | 代码默认英文验证通过语 | 自定义英文验证通过提示。留空即可。 |
| `AUTO_REPLY_EN` | 否 | 代码默认英文已送达提示 | 用户消息转发后，机器人给用户的英文自动回馈。留空即可。 |

你的 VPS 推荐 `.env` 最小配置：

```env
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
OWNER_ID=
BOT_DB_PATH=/app/data/bot_core.db
REMOTE_SPAM_URL=
```

一般只需要改 `BOT_TOKEN`、`ADMIN_ID`、`REMOTE_SPAM_URL` 和自定义提示语。AI 和群聊配置全部可选：未配置 `AI_ENABLED=true` 和 `AI_API_KEY` 时，本地规则照常工作；不填 `GROUP_IDS` 时群聊管理对所有已启用群生效。不要在 `.env.example` 里填写真实 token。

VPS 上一键覆盖写入 `.env`：

```bash
cat > /opt/codexbot/.env <<'EOF'
BOT_TOKEN=你的BotFatherToken
ADMIN_ID=你的Telegram数字ID
OWNER_ID=
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

- `new.py`：机器人主脚本，包含私聊客服、本地广告规则和群聊管理。
- `ai_classifier.py`：多协议第三方 AI 广告判定模块（OpenAI 兼容 / Anthropic / Gemini），可按需开关。
- `rule_sync.py`：广告规则学习后的特征提取，以及 GitHub / Cloudflare R2 同步。
- `Dockerfile`：构建镜像，把 `new.py` 复制为容器内 `/app/bot.py`，同时复制 `ai_classifier.py` 和 `rule_sync.py`。
- `requirements.txt`：Python 依赖。
- `docker-compose.bot-lite.yml`：轻量单容器部署示例。
- `docker-compose.bot.yml`：旧三容器部署参考，包含 Redis 和 PostgreSQL，当前代码已不支持，仅供历史参考。
- `env_utils.py`：共享环境变量解析工具。
- `.env.example`：中文环境变量示例，不填写真实密钥。
- `.github/workflows/docker-publish.yml`：GitHub Actions 构建并推送 GHCR 镜像。
- `VPS-DEPLOYMENT.md`：按你当前 VPS 情况整理的专属部署与维护文档。

## 功能概览

- 用户私聊机器人后，消息会转发给管理员。
- 管理员回复机器人转发来的消息，可以匿名回复用户。
- 新用户需要通过按钮人机验证。
- 每一条准备转发给管理员的普通用户消息，都会先经过广告规则过滤。
- 白名单用户会跳过广告和频率检查。
- 命中广告规则后，默认拦截并临时封禁，不再把广告原文转发给管理员。
- 广告拦截后会给管理员一个干净通知；默认直接临时封禁，仅在不封禁模式下保留“封禁用户 / 不封禁”按钮。
- 支持第三方广告规则 URL，启动和重载时会通知管理员加载状态。
- 支持 OpenAI 兼容、Anthropic Claude、Google Gemini 三类第三方 AI 接口；本地规则和网络广告词规则不明确时，AI 会按判定标准复核。
- 支持自动学习广告特征：同一特征重复命中后自动进本地知识库，管理员按钮仍可确认或忽略，并可选同步到 GitHub 规则仓库或 Cloudflare R2。
- 支持群聊入群申请审核：自动通过正常申请，拒绝疑似广告号，并通知管理员；管理员可按钮手动通过或拒绝。
- 支持群内广告检测：命中本地规则或 AI 判定的广告消息会被删除，发广告用户会被永久封禁，并通知管理员。
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
黑名单检查 -> 临时封禁检查 -> 白名单判断 -> 频率检查 -> 本地规则检查 -> AI 复核 -> 人机验证状态判断 -> 转发给管理员
```

也就是说，用户通过人机验证之后继续发广告，仍然会被广告规则拦截。真正绕过广告规则的是白名单用户。

白名单只跳过广告和频率检查，不会跳过临时封禁：用户处于 `ban_until` 封禁期内时，无论是否在白名单，私聊消息都会被忽略，直到解封或封禁到期。每条私聊或群消息只做一次完整广告判定，命中后直接复用原因和风险分去封禁、通知和写学习样本，不会重复请求 AI。

全局白名单在群里同样生效：群消息不做广告判定，入群申请直接通过，不查频道关注也不查资料广告特征。

第三方广告规则会在启动后自动加载，也可以用 `/reloadrules` 手动重载。管理员可用 `/status` 查看当前规则状态。

AI 只作为复核层：本地关键词或风险分已经明确的广告会直接拦截，不再请求 AI；只有达到 `AI_MIN_SCORE` 阈值、开启 `AI_ALWAYS_CHECK`，或入群申请需要资料判定时才调用 AI。AI 请求失败、超时或未配置时自动回退本地规则，不影响机器人运行。

## 第三方 AI 协议配置

`AI_PROVIDER` 支持三种协议，默认 `openai-compatible`，切换后机器人会自动选择请求地址、鉴权头和响应解析。

OpenAI 兼容网关（DeepSeek、硅基流动、通义、智谱、Ollama 等）：

```env
AI_PROVIDER=openai-compatible
AI_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=你的APIKey
AI_MODEL=deepseek-chat
```

Anthropic Claude 原生 Messages API：

```env
AI_PROVIDER=anthropic
AI_BASE_URL=https://api.anthropic.com
AI_API_KEY=你的APIKey
AI_MODEL=claude-3-5-sonnet-latest
AI_MAX_TOKENS=300
```

Google Gemini 原生 generateContent：

```env
AI_PROVIDER=gemini
AI_BASE_URL=https://generativelanguage.googleapis.com
AI_API_KEY=你的APIKey
AI_MODEL=gemini-2.0-flash
```

## 广告规则学习与同步

机器人拦截广告后，会先把广告里的稳定特征（域名、`t.me/` 链接、`@用户名`、联系方式、混合字母数字 token）写入本地 SQLite 的 `spam_feedback` 表。同一特征重复命中达到 `RULE_AUTO_LEARN_THRESHOLD` 次后自动确认学习并立即合并进当前广告规则；管理员通知里的“学习规则 / 不学习”按钮仍可手动确认或忽略。原始广告全文和手机号不会写入数据库。

学习后自动推送已配置的远程规则文件：

- GitHub：直接写入你指定的仓库文件，格式 `owner/repo` + 文件路径 + 分支。
- Cloudflare R2：按 S3 API 写入指定 Bucket 和对象键。

配置 R2 同步后，规则会先拉取到本地 SQLite 镜像（`R2_LOCAL_RULES_PATH`，留空复用 `R2_USAGE_PATH`），日常判定和学习只读本地，不产生 R2 请求。默认每3小时拉取一次（`R2_FETCH_INTERVAL=10800`）、每3小时写入一次学习规则（`R2_SYNC_INTERVAL=10800`）、每3小时镜像一次到多个 R2 账户（`R2_MIRROR_INTERVAL=10800`），形成“学习 -> 本地生效 -> 每3小时备份进 R2 -> 每3小时拉回本地”的闭环。R2 同步始终用 PUT 覆盖写同一个 `RULE_SYNC_R2_KEY` 对象，不会每次生成新对象。GitHub 规则 URL 和 R2 本地镜像会同时合并进判断规则。

R2 默认按 Cloudflare 免费层上限的 90% 控制：Class A 90 万次/月、Class B 900 万次/月，保留 10% 冗余。收到 429/503 限流后暂停该账户 R2 请求 1 小时，暂停期间本地广告判定、GitHub 同步和规则缓存都不受影响。

R2 免费存储同样保留 10% 冗余：默认按 10 GB 上限、90% 即约 9 GB 后停止向该 R2 写入并通知管理员。本地规则按规则文本去重分类存储，同一规则只占一行。

支持配置多个 R2 账户（旧变量为账户 1，追加 `_2` 到 `_20` 后缀即可）。每次请求前先检查该账户额度，触顶或限流时自动切换到下一个可用账户；多个账户会按 `R2_MIRROR_INTERVAL` 定时镜像同步，保持规则文本一致，任一账户恢复后立即补同步并解除暂停。

R2 触顶、存储接近上限或收到 429/503 限流时会向管理员发送一次提醒，消息带账户编号和预计恢复时间，同一自然月只提醒一次；Cloudflare 免费配额按 UTC 自然月重置，次月会自动恢复，不用手动干预。

推送失败时记录保留为“未同步”，下次启动或规则刷新周期会自动重试。同步渠道全部留空时，只做本地学习，不推送任何远程文件。`RULE_SYNC_GITHUB_TOKEN`、`RULE_SYNC_R2_ACCESS_KEY`、`RULE_SYNC_R2_SECRET_KEY` 只放在 VPS 的 `.env`，不要提交到 GitHub。

## 群聊管理

把机器人设为目标群管理员后，机器人会接管入群申请和群内广告管理：

```text
入群申请 -> 本地资料规则检查 -> AI 资料复核（可选） -> 自动通过 / 自动拒绝 / 通知管理员
群消息 / 群内编辑 -> 本地规则检查 -> AI 复核（可选） -> 删除消息 / 永久封禁 / 通知管理员
```

群内消息默认跳过机器人自己、`GROUP_ADMIN_IDS` 里的管理员和 Telegram 群原生管理员。入群申请审核通知会发到对应群聊，你设置的管理员也会私聊收到，管理员可以直接点按钮通过或拒绝。配置了 `GROUP_JOIN_REQUIRED_CHANNEL` 时，用户必须先关注指定频道，未关注的申请会先被拒绝并收到提示，关注后重新申请才会进入审核。判定为广告的申请会自动拒绝并在该群封禁，被拒绝的用户仍可私聊机器人申诉，申诉内容会先经过广告检测再转给管理员；正常申请默认自动通过；开启人工审核（`GROUP_AUTO_APPROVE=false`）时，管理员超过 `GROUP_JOIN_REVIEW_TIMEOUT` 秒未处理，机器人会按规则自动兜底，广告自动拒绝并在该群封禁，正常通过。群原生管理员只能处理本群的入群申请，学习规则、黑名单、GitHub / R2 同步等全局操作仍只归你设置的管理员。机器人至少需要群管理员的“删除消息、封禁成员、批准入群申请”权限，并加入指定频道（建议设为频道管理员）以检查关注状态，具体按 Telegram 群权限逐项勾选。

群内普通用户可用 `/id`、`/help`、`/spamtest 内容`。群管理员可在当前群使用 `/status`、`/reloadrules`、`/ban 用户ID`、`/unban 用户ID`，也可以回复对方消息后发送 `/ban`。

群级 `/ban` 会封禁当前群、写入本地 `group_bans` 记录，并同时写入全局黑名单：该用户之后申请加入任何已接管的群会被直接拒绝并封禁，在任何已接管的群发言也会被直接删除并封禁。群内自动永久封禁（命中广告规则）走同一条链路。全局白名单里的用户群管理员封不动，只有 `ADMIN_ID` 能处理。其他群执行全局黑名单时只封禁、不写 `group_bans`，所以那些群的管理员也无法用 `/unban` 把全局黑名单解掉。

群级 `/unban` 先解除当前群封禁并删除对应 `group_bans` 记录，再判断能不能动全局：只有这条全局黑名单是本群封进去的、并且该用户没有被其他群封禁，才会一起移出全局黑名单；否则只解除本群，全局保留并提示需要最高管理员处理。`ADMIN_ID` 在群里执行 `/unban` 不受该限制，一定会清掉全局黑名单。全局 `/awl`、`/abl`、`/dbl` 仍只在私聊中供 `ADMIN_ID` 使用。

群内编辑消息和普通群消息走同一套检测：编辑成广告会删除原消息、永久封禁发广告用户并通知管理员；正常编辑不动作。入群申请已被自动处理时，管理员再点通过或拒绝按钮只会收到“已处理”提示，不会重复操作或报错。

`GROUP_IDS` 留空时，机器人会处理所有它已加入且启用了 Join Requests 的群；填写群 ID 列表后只管理指定群。

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

修改以下文件后，需要推送到 `v2` 分支并等待 GitHub Actions 构建成功：

- `new.py`
- `ai_classifier.py`
- `rule_sync.py`
- `Dockerfile`
- `requirements.txt`
- `.github/workflows/docker-publish.yml`

镜像构建成功后，VPS 才能拉到新版：

```bash
docker pull ghcr.io/sykin7/spamguard-bot:latest
```

如果 VPS 拉取后功能还是旧的，用下面命令确认容器内代码：

```bash
docker exec codexbot sh -c "grep -n 'admin_menu_status\|admin_menu_resetverify\|Reset Verification\|one_time_keyboard=False\|/reloadrules\|/status' /app/bot.py | head -30"
```

## 本地检查

先做语法检查，再跑单元测试：

```bash
python -m py_compile new.py ai_classifier.py rule_sync.py
python -m unittest discover
```

测试覆盖 AI 响应解析、AI 分类器请求、群聊开关、群管理员判定、规则学习反馈和 GitHub / R2 同步。本地如果没有安装 `telebot`，测试会用轻量 stub 加载 `new.py` 的纯函数，不依赖真实 Telegram 网络。

## 快速 VPS 更新命令

你的 VPS 老版 `docker-compose` 容易遇到 `KeyError: 'ContainerConfig'`。因此实际维护时，推荐直接使用 `docker run` 重建单容器：

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

检查：

```bash
docker ps | grep codexbot
docker logs --tail=80 codexbot
docker inspect codexbot --format '{{json .HostConfig.LogConfig}}'
```
