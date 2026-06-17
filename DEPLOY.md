# nicechat-bot 保姆级部署文档

本文档从零开始，详细到每一个按钮、每一条命令、每一个变量。跟着做就能部署成功。

**总耗时**：约 30-60 分钟（看你对 Telegram / Cloudflare / 命令行的熟悉程度）
**总成本**：0 元（全程 Cloudflare 免费层 + Telegram 免费 + 你的 AI 中转站费用）

---

## 目录

1. [前置准备](#1-前置准备)
2. [创建 Telegram Bot](#2-创建-telegram-bot)
3. [获取你的 Telegram UID](#3-获取你的-telegram-uid)
4. [注册 Cloudflare 账号](#4-注册-cloudflare-账号)
5. [安装 Node.js 和 Wrangler](#5-安装-nodejs-和-wrangler)
6. [下载项目代码](#6-下载项目代码)
7. [创建 KV Namespace](#7-创建-kv-namespace)
8. [配置 Secrets（敏感信息）](#8-配置-secrets敏感信息)
9. [配置 Vars（非敏感配置）](#9-配置-vars非敏感配置)
10. [部署到 Cloudflare Workers](#10-部署到-cloudflare-workers)
11. [注册 Webhook](#11-注册-webhook)
12. [设置命令菜单](#12-设置命令菜单)
13. [验证部署](#13-验证部署)
14. [日常使用](#14-日常使用)
15. [故障排查](#15-故障排查)
16. [升级到付费层（可选）](#16-升级到付费层可选)

---

## 1. 前置准备

### 1.1 你需要准备的东西

| 项目 | 用途 | 获取方式 |
|------|------|---------|
| Telegram 账号 | 创建 Bot、接收消息 | https://telegram.org 下载 |
| Cloudflare 账号 | 部署 Worker | https://dash.cloudflare.com/sign-up 注册 |
| Node.js 18+ | 运行 wrangler CLI | https://nodejs.org 下载 LTS 版 |
| AI 中转站 API Key | AI 过滤、代笔、助理 | 你已有的 OpenAI 兼容中转站 |
| （可选）搜索 API Key | 联网搜索功能 | Brave Search 或 Tavily |

### 1.2 检查 Node.js 是否安装

打开终端（Windows: PowerShell / macOS: Terminal），输入：

```bash
node --version
```

应该看到类似 `v20.11.0` 的输出。如果报错"command not found"，去 https://nodejs.org 下载 LTS 版安装。

### 1.3 检查 npm 是否可用

```bash
npm --version
```

应该看到类似 `10.2.4` 的输出。

---

## 2. 创建 Telegram Bot

### 2.1 找到 BotFather

1. 打开 Telegram 客户端
2. 搜索 `@BotFather`（蓝色认证勾 ✓）
3. 点开对话，点 **Start**

### 2.2 创建新 Bot

1. 发送：`/newbot`
2. BotFather 问名字（display name，可中文）：输入你想要的名字，例如 `我的私人助手`
3. BotFather 问 username（必须以 `bot` 结尾，全英文）：输入例如 `my_personal_assistant_bot`
4. BotFather 返回一段消息，里面有一行类似：
   ```
   Use this token to access the HTTP API:
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567890
   ```
5. **复制这个 token** — 这就是你的 `BOT_TOKEN`，后面要用

### 2.3 安全提示

- **BOT_TOKEN 是密钥**，泄露了任何人都能控制你的 bot
- 不要发到任何群、不要提交到 GitHub
- 如果泄露，立即找 BotFather 用 `/revoke` 重新生成

---

## 3. 获取你的 Telegram UID

你需要自己的 Telegram 数字 UID，作为 `ADMIN_UID`（管理员标识）。

### 3.1 方法一：用 userinfobot

1. 在 Telegram 搜索 `@userinfobot`
2. 点开对话，点 **Start**
3. 它会立刻回复你的信息，其中 `Id: 123456789` 就是你的 UID
4. **复制这个数字** — 这就是你的 `ADMIN_UID`

### 3.2 方法二：用 getidsbot

1. 搜索 `@getidsbot`
2. 发送 `/start`
3. 它会回复你的 `Your user ID: 123456789`

### 3.3 注意

- UID 是纯数字，不是用户名
- UID 不会变，记下来一次永久使用
- 别人知道你的 UID 不算泄露（不像 token），但仍建议保密

---

## 4. 注册 Cloudflare 账号

### 4.1 注册

1. 打开 https://dash.cloudflare.com/sign-up
2. 输入邮箱和密码
3. 邮箱验证
4. 选 "Free" 计划（免费层够用）

### 4.2 验证邮箱

Cloudflare 会发验证邮件，点击邮件里的链接验证。

### 4.3 进入 Dashboard

登录后看到 Dashboard 主页，左侧有 Workers & Pages、KV、R2 等。我们主要用 **Workers & Pages** 和 **KV**。

---

## 5. 安装 Node.js 和 Wrangler

### 5.1 安装 Wrangler（Cloudflare CLI）

在终端执行：

```bash
npm install -g wrangler
```

### 5.2 验证安装

```bash
wrangler --version
```

应该看到类似 `wrangler 3.78.0` 的输出。

### 5.3 登录 Cloudflare

```bash
wrangler login
```

会自动打开浏览器，跳到 Cloudflare 授权页面。点 **Allow** 即可。

### 5.4 验证登录成功

```bash
wrangler whoami
```

应该看到你的账号邮箱和 account id。

---

## 6. 下载项目代码

### 6.1 解压项目 ZIP

把你拿到的 `nicechat-bot-secured.zip` 解压到任意目录，例如：

- Windows: `C:\projects\nicechat-fixed`
- macOS/Linux: `~/projects/nicechat-fixed`

### 6.2 进入项目目录

```bash
cd /path/to/nicechat-fixed
```

### 6.3 安装依赖

```bash
npm install
```

会安装 `wrangler`、`typescript`、`vitest` 等开发依赖。等几分钟。

### 6.4 验证项目结构

执行 `ls`（Windows 用 `dir`），应该看到：

```
.dev.vars.example
CHANGES.md
README.md
package.json
package-lock.json
scripts/
src/
test/
tsconfig.json
wrangler.jsonc
```

---

## 7. 创建 KV Namespace

KV 是 Cloudflare 的键值存储，bot 用它存用户信息、违规计数、上下文等。

### 7.1 用 wrangler 创建 KV

在项目目录执行：

```bash
npm run kv:create
```

这等价于 `wrangler kv namespace create TG_BOT_KV`。

### 7.2 复制 KV ID

命令执行后，输出类似：

```
🌀 Creating namespace with title "nicechat-bot-TG_BOT_KV"
✨ Success!
Add the following to your configuration file in your kv_namespaces array:
{
  "binding": "TG_BOT_KV",
  "id": "abcdef1234567890abcdef1234567890"
}
```

**复制那个 `id` 值**（32 位十六进制字符串）。

### 7.3 更新 wrangler.jsonc

打开 `wrangler.jsonc`，找到这一段：

```jsonc
"kv_namespaces": [
  { "binding": "TG_BOT_KV", "id": "REPLACE_WITH_YOUR_KV_ID" }
],
```

把 `REPLACE_WITH_YOUR_KV_ID` 替换成你刚才复制的 id：

```jsonc
"kv_namespaces": [
  { "binding": "TG_BOT_KV", "id": "abcdef1234567890abcdef1234567890" }
],
```

保存文件。

---

## 8. 配置 Secrets（敏感信息）

Secrets 是加密存储的环境变量，不会写入代码仓库。**所有密钥都必须用 Secret 设置**。

### 8.1 设置 BOT_TOKEN

```bash
wrangler secret put BOT_TOKEN
```

命令会提示输入值，粘贴你在 [第 2 步](#2-创建-telegram-bot) 拿到的 Bot Token：

```
🌐 Enter the secret value you'd like to assign to variable "BOT_TOKEN".
```

粘贴：`1234567890:ABCdefGHIjklMNOpqrsTUVwxyz1234567890`（你的真实 token）

按回车。看到 `✨ Success!` 表示成功。

### 8.2 设置 BOT_SECRET

这是 webhook 校验密钥，自己生成一个长随机字符串。

**生成随机字符串**（任选一种方式）：

```bash
# macOS / Linux
openssl rand -hex 32

# 或用 Node.js
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"

# 或用 Python
python -c "import secrets; print(secrets.token_hex(32))"
```

会输出类似：`a3f5e8b2c1d4f6a9e7b3c5d8f1a4b6e9c2d5f8a1b4c6e9d2f5a8b1c4d6e9f2a5`

**复制这个字符串**，然后：

```bash
wrangler secret put BOT_SECRET
```

粘贴刚才的随机字符串，回车。

⚠️ **这个字符串你要自己保存一份**，后面注册 webhook 时要用！

### 8.3 设置 ADMIN_UID

```bash
wrangler secret put ADMIN_UID
```

粘贴你在 [第 3 步](#3-获取你的-telegram-uid) 拿到的纯数字 UID，例如 `123456789`，回车。

### 8.4 设置 AI_BASE_URL

这是你的 OpenAI 兼容中转站地址，**不要带 `/chat/completions` 后缀**。

例如你的中转站是 `https://cliproxy.mtcacg.top/v1`，就填这个。

```bash
wrangler secret put AI_BASE_URL
```

粘贴：`https://your-relay.example.com/v1`（你的真实地址），回车。

### 8.5 设置 AI_API_KEY

你的中转站 API key，通常是 `sk-` 开头。

```bash
wrangler secret put AI_API_KEY
```

粘贴：`sk-xxxxxxxxxxxx`（你的真实 key），回车。

### 8.6 （可选）设置 SEARCH_API_KEY

如果你要启用联网搜索功能，需要 Brave Search 或 Tavily 的 API key。不用就跳过。

**获取 Brave Search API key**：
1. 打开 https://brave.com/search/api/
2. 注册账号
3. 选 Free 计划（每月 2000 次免费）
4. 拿到 `BSA` 开头的 API key

**获取 Tavily API key**：
1. 打开 https://tavily.com
2. 注册账号
3. 拿到 `tvly-` 开头的 API key

设置：

```bash
wrangler secret put SEARCH_API_KEY
```

粘贴你的搜索 API key，回车。不填则搜索功能关闭。

### 8.7 验证所有 Secrets

```bash
wrangler secret list
```

应该看到：

```
AI_API_KEY
AI_BASE_URL
ADMIN_UID
BOT_SECRET
BOT_TOKEN
SEARCH_API_KEY  # 如果你设置了
```

---

## 9. 配置 Vars（非敏感配置）

Vars 是非敏感配置，写在 `wrangler.jsonc` 的 `vars` 字段里。默认值已经能跑，但建议按需调整。

### 9.1 必须检查的配置

打开 `wrangler.jsonc`，找到 `"vars": { ... }` 块。以下是需要确认的项：

#### 9.1.1 AI_MODEL

默认：`"gpt-4o-mini"`

改成你中转站支持的模型名。常见选择：
- `gpt-4o-mini`（便宜快）
- `gpt-4o`（贵但好）
- `claude-3-5-sonnet-20241022`（如果你中转站支持）
- `deepseek-chat`（DeepSeek V3）

#### 9.1.2 AI_TIMEOUT_MS

默认：`"25000"`（25 秒）

⚠️ **不要改大！** Cloudflare 免费层 `ctx.waitUntil` 最多 30 秒。25 秒留 5 秒给清理。如果你升级到 Workers Paid，可以改成 `"60000"`。

#### 9.1.3 AI_CLASSIFY_TIMEOUT_MS

默认：`"10000"`（10 秒）

过滤分类用的超时，比完整 chat 短。一般不用改。

#### 9.1.4 AI_PROVIDER

默认：`"relay"`

可选值：
- `"relay"` — 只用你的中转站
- `"workers_ai"` — 只用 Cloudflare Workers AI（免费但模型弱）
- `"auto"` — 优先中转站，失败回落 Workers AI

建议保持 `"relay"`。如果你中转站不稳定，改成 `"auto"`。

#### 9.1.5 FILTER_ENABLED

默认：`"true"`

是否启用 AI 过滤。设 `"false"` 则所有消息直接转发不过滤。

#### 9.1.6 FILTER_THRESHOLD

默认：`"0.75"`

AI 判定广告/诈骗/骚扰的置信度阈值。越低越严格（拦截更多但误杀多），越高越宽松（放过更多但漏拦多）。范围 0-1。

- `"0.5"` — 激进（拦截多）
- `"0.75"` — 平衡（推荐）
- `"0.9"` — 保守（少误杀）

#### 9.1.7 AUTO_BAN_THRESHOLD

默认：`"3"`

累计违规多少次自动封禁。设 `"0"` 关闭自动封禁。

#### 9.1.8 VERIFY_MODE

默认：`"math"`

可选值：
- `"math"` — 算术题验证（默认）
- `"quiz"` — 自定义问答（需配合 `VERIFY_QUESTION` 和 `VERIFY_ANSWER`）

如果用 quiz，在 vars 里加：

```jsonc
"VERIFY_MODE": "quiz",
"VERIFY_QUESTION": "你最喜欢的颜色是什么？（请填具体颜色）",
"VERIFY_ANSWER": "蓝色",
```

⚠️ **如果用 quiz，VERIFY_ANSWER 应该用 secret 设置**（避免泄露到仓库）：

```bash
wrangler secret put VERIFY_ANSWER
```

然后 wrangler.jsonc 里 `VERIFY_ANSWER` 留空字符串 `""`。

#### 9.1.9 WELCOME_MESSAGE

默认：`"你好，这是主人的私人助手。为了挡住广告机器人，请先回答一道简单的算术题完成验证。"`

用户 `/start` 时看到的欢迎语。可改成你喜欢的，例如：

```jsonc
"WELCOME_MESSAGE": "喵～你好！我是主人的私人小助手，请先回答一道算术题完成验证，然后就可以留言啦～",
```

#### 9.1.10 AUTO_GREETING

默认：`"你好！你的消息已经收到并转达给主人，请稍等回复。"`

陌生人验证通过后收到的自动问候。可改成：

```jsonc
"AUTO_GREETING": "你的消息已收到～主人会尽快回复你哦！",
```

留空字符串 `""` 则不发问候。

#### 9.1.11 GROUP_AI_ENABLED

默认：`"false"`

是否开启群聊 AI（群里 @bot 提问）。建议保持 `"false"` 除非你需要。

#### 9.1.12 BYPASS_TG_ASN_CHECK

默认：`""`（空）

留空则启用 Telegram IP 白名单校验（推荐）。只在本地开发时设 `"1"` 旁路。

#### 9.1.13 WEBHOOK_URL_OVERRIDE

默认：`""`（空）

留空则自动用 Worker 自身域名。只在本地开发用 ngrok/cloudflared 隧道时填隧道地址。

### 9.2 完整默认配置参考

```jsonc
"vars": {
  "RELAY_MODE": "private",
  "ADMIN_GROUP_ID": "",

  "AI_MODEL": "gpt-4o-mini",
  "AI_TIMEOUT_MS": "25000",
  "AI_CLASSIFY_TIMEOUT_MS": "10000",
  "AI_PROVIDER": "relay",
  "AI_FALLBACK_TO_CF": "true",
  "CF_AI_MODEL": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",

  "FILTER_ENABLED": "true",
  "FILTER_THRESHOLD": "0.75",
  "BLOCK_KEYWORDS": "",

  "VERIFY_MODE": "math",
  "VERIFY_QUESTION": "",
  "VERIFY_ANSWER": "",

  "WELCOME_MESSAGE": "你好，这是主人的私人助手。为了挡住广告机器人，请先回答一道简单的算术题完成验证。",
  "AUTO_GREETING": "你好！你的消息已经收到并转达给主人，请稍等回复。",
  "AI_REPLY_PREVIEW": "preview",
  "AI_CONTEXT_ROUNDS": "6",

  "AUTO_BAN_THRESHOLD": "3",
  "BAN_MESSAGE": "你已因多次发送广告或骚扰信息被系统封禁。如需申诉，请发送 /appeal <申诉说明>。",
  "APPEAL_MAX_ATTEMPTS": "2",
  "APPEAL_MESSAGE": "申诉已收到，管理员会视情况处理。请勿重复发送无关内容。",

  "AUTO_SEARCH_ENABLED": "true",
  "SEARCH_PROVIDER": "brave",
  "SEARCH_MAX_RESULTS": "5",
  "SEARCH_DECISION_MODEL": "",

  "BOT_USERNAME": "",
  "GROUP_AI_ENABLED": "false",
  "GROUP_AI_MAX_CONCURRENCY": "1",
  "GROUP_AI_LOCK_TTL_SECONDS": "120",
  "GROUP_USER_COOLDOWN_SECONDS": "30",
  "GROUP_AI_CONTEXT_ROUNDS": "4",
  "GROUP_AI_MAX_INPUT_CHARS": "1200",
  "GROUP_AI_MAX_OUTPUT_CHARS": "1800",

  "BYPASS_TG_ASN_CHECK": "",
  "WEBHOOK_URL_OVERRIDE": ""
}
```

---

## 10. 部署到 Cloudflare Workers

### 10.1 检查配置

部署前最后检查：

```bash
# 验证 wrangler.jsonc 格式正确
cat wrangler.jsonc

# 验证 secrets 已设置
wrangler secret list

# 验证 KV id 已填入
grep "TG_BOT_KV" wrangler.jsonc
```

### 10.2 类型检查（可选但推荐）

```bash
npm run typecheck
```

应该无输出（表示 0 错误）。

### 10.3 跑测试（可选但推荐）

```bash
npm test
```

应该看到 `185 passed`。

### 10.4 部署

```bash
npm run deploy
```

这等价于 `wrangler deploy`。输出类似：

```
Total Upload: 45.27 KiB / gzip: 11.23 KiB
Worker Startup Time: 12 ms
Uploaded nicechat-bot (3.45 sec)
Published nicechat-bot (0.89 sec)
  https://nicechat-bot.<your-subdomain>.workers.dev
```

**复制那个 `https://nicechat-bot.<your-subdomain>.workers.dev`** — 这是你的 Worker URL，后面要用。

### 10.5 验证部署

浏览器打开 `https://nicechat-bot.<your-subdomain>.workers.dev/health`

应该看到纯文本 `ok`。

---

## 11. 注册 Webhook

让 Telegram 把用户消息推到你的 Worker。

### 11.1 准备 BOT_SECRET

你需要在 [第 8.2 步](#82-设置-bot_secret) 保存的那个 BOT_SECRET 字符串。

### 11.2 调用注册接口

注意：v0.10 之后**只支持 POST + header**（不再支持 GET ?secret=）。

在终端用 curl：

```bash
curl -X POST \
  -H "x-bot-secret: 你的BOT_SECRET字符串" \
  https://nicechat-bot.<your-subdomain>.workers.dev/registerWebhook
```

把 `你的BOT_SECRET字符串` 和 Worker URL 替换成你的真实值。

成功输出：

```
✅ webhook set to https://nicechat-bot.<your-subdomain>.workers.dev/webhook
```

### 11.3 验证 webhook 注册成功

```bash
curl -X POST \
  -H "x-bot-secret: 你的BOT_SECRET" \
  https://nicechat-bot.<your-subdomain>.workers.dev/stats
```

返回 JSON：

```json
{
  "ok": true,
  "time": "2026-06-17T04:25:00.000Z",
  "has_intercepts": false,
  "has_audit": false,
  "admin_uid_configured": true,
  "ai_base_url_configured": true,
  "ai_api_key_configured": true,
  "search_api_key_configured": false,
  "filter_enabled": true,
  "group_ai_enabled": false,
  "active_model": "gpt-4o-mini",
  "admin_ai_mode": false
}
```

确认 `admin_uid_configured`、`ai_base_url_configured`、`ai_api_key_configured` 都是 `true`。

---

## 12. 设置命令菜单

让管理员在 Telegram 客户端看到命令提示。

### 12.1 调用 setcommands

```bash
curl -X POST \
  -H "x-bot-secret: 你的BOT_SECRET" \
  https://nicechat-bot.<your-subdomain>.workers.dev/setcommands
```

成功输出：

```
✅ commands set (public: start; admin: full menu)
```

### 12.2 验证

在 Telegram 打开和 bot 的对话，点输入框左边的 `/` 按钮，应该看到：
- 普通用户只看到 `start` 命令
- 管理员（你的 UID）看到 `ai`、`model`、`aimode`、`to`、`intercepts`、`audit`、`ban`、`unban`、`forgive` 等命令

---

## 13. 验证部署

### 13.1 用小号测试

用另一个 Telegram 账号（不是你的管理员账号）给 bot 发消息：

1. 搜索你的 bot username
2. 点 Start
3. 应该收到欢迎语 + 算术题，例如：
   ```
   你好，这是主人的私人助手...
   
   请发送【验证码】：8 加 5 = ?
   （直接发送数字答案）
   ```
4. 发送正确答案（如 `13`）
5. 应该收到 `✅ 验证通过，请发送你的消息。`
6. 发送任意消息（如"你好"）
7. 管理员（你）应该收到转发：
   ```
   👤 用户名 @username (uid:123456)
   📋 UID: 123456
   
   [实际转发的消息内容]
   ```

### 13.2 测试管理员命令

用你的管理员账号给 bot 发：

```
/ai 你好
```

应该收到 AI 助理回复。

### 13.3 测试代笔

1. 用小号给 bot 发"你好"
2. 管理员收到转发后，**reply 那条转发消息**，发送 `/ai 礼貌回复`
3. 应该收到 AI 生成的草稿 + 三个按钮（确认回复 / 重新生成 / 自行回复）
4. 点"✅ 确认回复"，草稿发给小号

### 13.4 测试封禁

1. 用管理员账号发 `/ban <小号UID>`（UID 在转发消息里能看到）
2. 应该收到 `已拉黑 uid:xxx`
3. 小号再发消息，收到封禁提示
4. 小号发 `/appeal 我是误封的`，管理员收到申诉通知
5. 管理员发 `/unban <小号UID>` 解封

### 13.5 检查审计日志

管理员发 `/audit`，看到最近的操作记录。

### 13.6 检查拦截记录

管理员发 `/intercepts`，看到最近拦截的广告/诈骗消息。

---

## 14. 日常使用

### 14.1 管理员命令速查

| 命令 | 作用 |
|------|------|
| `/ai <问题>` | 与 AI 助理对话 |
| reply 转发消息 + `/ai <意向>` | 让 AI 代笔回复用户 |
| reply 转发消息 + 普通文本 | 直接回复用户 |
| `/aimode on` / `/aimode off` | 开启/关闭 AI 模式（普通消息直接进助理） |
| `/model` | 查看当前模型 |
| `/model list` | 列出中转站可用模型 |
| `/model <模型名>` | 切换模型 |
| `/model default` | 恢复默认模型 |
| `/to <uid> <内容>` | 主动给指定用户发消息 |
| `/intercepts [n]` | 查看最近 n 条拦截记录（默认 10，最大 50） |
| `/audit [n]` | 查看最近 n 条管理操作日志 |
| `/ban <uid>` 或 reply + `/ban` | 封禁用户 |
| `/unban <uid>` 或 reply + `/unban` | 解封用户 |
| `/forgive <uid>` 或 reply + `/forgive` | 清空用户违规计数 |

### 14.2 用户视角

- 陌生人发 `/start` → 收到欢迎语 + 算术题
- 答对 → 收到"验证通过"
- 发消息 → 被转发给管理员
- 管理员 reply → 陌生人收到回复
- 被封 → 收到封禁提示，可 `/appeal <说明>` 申诉

### 14.3 修改配置后重新部署

如果你改了 `wrangler.jsonc` 里的 vars：

```bash
npm run deploy
```

立即生效，无需重新注册 webhook。

### 14.4 修改 secret

```bash
wrangler secret put BOT_TOKEN   # 重新设置会覆盖
```

立即生效。

### 14.5 查看日志

如果你在 wrangler.jsonc 里启用了 `observability`（默认已启用），可以在 Cloudflare Dashboard 看：

1. https://dash.cloudflare.com → Workers & Pages → 你的 Worker
2. 点 **Logs** 标签
3. 实时查看请求日志和 console.error/warn 输出

---

## 15. 故障排查

### 15.1 部署失败

**错误**：`wrangler deploy` 报 "KV namespace not found"

**解决**：检查 wrangler.jsonc 里的 `kv_namespaces[0].id` 是否填了真实的 KV id。

---

**错误**：`wrangler deploy` 报 "Authentication failed"

**解决**：重新登录 `wrangler login`。

---

**错误**：`wrangler deploy` 报 "Script exceeds size limit"

**解决**：免费层 Worker 上限 1MB（压缩后 3MB）。你的代码远低于此，不应该出现。检查是否意外打包了大文件。

### 15.2 Webhook 注册失败

**错误**：curl 调用 registerWebhook 返回 403 forbidden

**解决**：
1. 检查 `x-bot-secret` header 是否正确
2. 检查 BOT_SECRET 是否设置成功：`wrangler secret list`
3. 重新设置：`wrangler secret put BOT_SECRET`

---

**错误**：curl 返回 405 method not allowed

**解决**：必须用 POST，不能用 GET。命令里要有 `-X POST`。

---

**错误**：curl 返回 `Telegram setWebhook failed: Unauthorized`

**解决**：BOT_TOKEN 错了。重新设置：
```bash
wrangler secret put BOT_TOKEN
```

### 15.3 Bot 不响应消息

**症状**：给 bot 发消息，bot 无反应。

**排查步骤**：

1. 检查 webhook 是否注册成功：
   ```bash
   curl -X POST -H "x-bot-secret: 你的SECRET" https://你的worker/stats
   ```
   确认 `admin_uid_configured` 等都是 true。

2. 检查 Cloudflare Dashboard 的 Workers Logs，看 webhook 是否收到请求。

3. 如果 Logs 里没请求，说明 Telegram 没推过来：
   - 用 Telegram API 直接查 webhook 状态：
     ```bash
     curl https://api.telegram.org/bot你的BOT_TOKEN/getWebhookInfo
     ```
   - 看 `url` 字段是否正确，`last_error_message` 是否有错。

4. 如果 Logs 里有请求但返回 500，看错误日志。

### 15.4 验证不通过

**症状**：用户答对了算术题但收到"答案不对"。

**排查**：
- 确认用户发的是纯数字（如 `13`），不是"十三"或"13.0"
- v0.10 的 `normalizeAnswer` 支持 "40"/" 40 "/"40.0"/"４０"（全角），但不支持中文数字

### 15.5 AI 不工作

**症状**：`/ai 你好` 没响应或报错。

**排查**：
1. 检查 AI_BASE_URL 是否正确（不带 `/chat/completions` 后缀）
2. 检查 AI_API_KEY 是否有效
3. 检查 AI_MODEL 是否是中转站支持的模型
4. 在 Workers Logs 看 `chatComplete` 的错误日志

**测试中转站是否通**：
```bash
curl -X POST https://你的中转站/v1/chat/completions \
  -H "Authorization: Bearer 你的AI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}'
```

应该返回 JSON 含 `choices`。

### 15.6 KV 写额度耗尽

**症状**：消息能转发但上下文丢失，AI 回复变傻。

**原因**：CF 免费层 KV 写限制 1000/天。代码已有写预算保护（超 800 写/天跳过非关键写）。

**解决**：
1. 升级到 Workers Paid（$5/月，KV 写无限）
2. 或者降低 `AI_CONTEXT_ROUNDS`（减少上下文保存）
3. 或者设置 `FILTER_ENABLED=false`（不过滤，省 AI 调用——但会失去广告过滤）

### 15.7 被自己封了

**症状**：管理员不小心被自动封禁（不太可能，但如果 ADMIN_UID 配错）。

**解决**：管理员路径**不受封禁检查**，所以管理员不会被真正封。如果你用小号测试被误封：
1. 用管理员账号发 `/unban <小号UID>`

### 15.8 速率限制

**症状**：用户发消息没反应（静默丢弃）。

**原因**：v0.6 之后限流静默丢弃（不回复"太快了"）。

**解决**：等 1 分钟再发。管理员路径不限流。

---

## 16. 升级到付费层（可选）

如果免费层不够用（KV 写 1000/天、Workers AI 10000/天耗尽），升级 Workers Paid $5/月。

### 16.1 升级步骤

1. https://dash.cloudflare.com → 右上角 → **Change Plan**
2. 选 Workers Paid ($5/month)
3. 付费

### 16.2 升级后可调整的配置

编辑 `wrangler.jsonc`：

```jsonc
"AI_TIMEOUT_MS": "60000",  // 25s → 60s（paid 层 ctx.waitUntil 上限更高）
```

重新部署：
```bash
npm run deploy
```

### 16.3 升级 Durable Objects（强一致，可选）

如果你需要强一致并发（高流量场景），可以加 Durable Objects。这超出本文档范围，参考 Cloudflare 官方文档：https://developers.cloudflare.com/durable-objects/

### 16.4 用 D1 存审计日志（可选）

免费层 KV 写 1000/天可能不够存审计日志。可以改用 D1（SQLite）：

1. https://dash.cloudflare.com → Workers & Pages → D1
2. 创建数据库
3. 在 wrangler.jsonc 加 binding：
   ```jsonc
   "d1_databases": [
     { "binding": "DB", "database_name": "nicechat-bot", "database_id": "你的D1-id" }
   ]
   ```
4. 改 `store.ts` 的 `logAdminAction` 用 D1 而非 KV（需自行编码）

---

## 附录 A：所有环境变量速查

### Secrets（用 `wrangler secret put` 设置）

| 变量名 | 必填 | 说明 | 示例 |
|--------|------|------|------|
| `BOT_TOKEN` | ✅ | Telegram bot token | `123456:ABC-DEF...` |
| `BOT_SECRET` | ✅ | webhook 校验密钥（自己生成 32 字节随机） | `a3f5e8b2...` |
| `ADMIN_UID` | ✅ | 你的 Telegram 数字 UID | `123456789` |
| `AI_BASE_URL` | ✅ | OpenAI 兼容中转站 URL（不带 /chat/completions） | `https://your-relay.com/v1` |
| `AI_API_KEY` | ✅ | 中转站 API key | `sk-xxxx` |
| `SEARCH_API_KEY` | ❌ | Brave/Tavily 搜索 key（不填则无搜索） | `BSAxxxx` 或 `tvly-xxxx` |

### Vars（在 wrangler.jsonc 的 vars 字段）

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `AI_MODEL` | `gpt-4o-mini` | 默认 AI 模型名 |
| `AI_TIMEOUT_MS` | `25000` | AI chat 超时（免费层最大 25s） |
| `AI_CLASSIFY_TIMEOUT_MS` | `10000` | AI 分类超时 |
| `AI_PROVIDER` | `relay` | `relay`/`workers_ai`/`auto` |
| `AI_FALLBACK_TO_CF` | `true` | 中转站失败时是否回落 Workers AI |
| `CF_AI_MODEL` | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Workers AI 模型 |
| `FILTER_ENABLED` | `true` | 是否启用 AI 过滤 |
| `FILTER_THRESHOLD` | `0.75` | 拦截置信度阈值（0-1） |
| `BLOCK_KEYWORDS` | 空 | 硬拦截关键词（`\|` 或换行或逗号分隔） |
| `VERIFY_MODE` | `math` | `math`/`quiz` |
| `VERIFY_QUESTION` | 空 | quiz 模式问题 |
| `VERIFY_ANSWER` | 空 | quiz 模式答案（建议用 secret） |
| `WELCOME_MESSAGE` | 见默认 | /start 欢迎语 |
| `AUTO_GREETING` | 见默认 | 验证通过后自动问候（空则不发） |
| `AI_CONTEXT_ROUNDS` | `6` | 助理上下文保留轮数 |
| `AUTO_BAN_THRESHOLD` | `3` | 违规几次自动封禁（0 关闭） |
| `BAN_MESSAGE` | 见默认 | 封禁提示语 |
| `APPEAL_MAX_ATTEMPTS` | `2` | 申诉次数上限 |
| `APPEAL_MESSAGE` | 见默认 | 申诉收到提示语 |
| `AUTO_SEARCH_ENABLED` | `true` | 是否启用自动搜索 |
| `SEARCH_PROVIDER` | `brave` | `brave`/`tavily` |
| `SEARCH_MAX_RESULTS` | `5` | 搜索结果数量（1-8） |
| `SEARCH_DECISION_MODEL` | 空 | 搜索决策模型（空则用当前模型） |
| `BOT_USERNAME` | 空 | bot 用户名（不带@，空则自动 getMe） |
| `GROUP_AI_ENABLED` | `false` | 是否开启群聊 AI |
| `GROUP_AI_MAX_CONCURRENCY` | `1` | 单群并发 AI 请求数 |
| `GROUP_AI_LOCK_TTL_SECONDS` | `120` | 群聊锁 TTL |
| `GROUP_USER_COOLDOWN_SECONDS` | `30` | 群聊用户冷却 |
| `GROUP_AI_CONTEXT_ROUNDS` | `4` | 群聊上下文轮数 |
| `GROUP_AI_MAX_INPUT_CHARS` | `1200` | 群聊单次输入上限 |
| `GROUP_AI_MAX_OUTPUT_CHARS` | `1800` | 群聊 AI 输出上限 |
| `BYPASS_TG_ASN_CHECK` | 空 | 开发模式旁路 ASN 检查（设 `1`） |
| `WEBHOOK_URL_OVERRIDE` | 空 | 本地开发 webhook URL 覆盖 |

---

## 附录 B：一键脚本

如果你嫌手动设置 secret 麻烦，可以用项目自带的脚本：

```bash
npm run secret:setup
```

会交互式提示你输入每个 secret 的值，自动调用 `wrangler secret put`。

---

## 附录 C：常用 curl 命令

把下面的 `WORKER_URL` 和 `BOT_SECRET` 替换成你的真实值。

```bash
# 健康检查
curl https://WORKER_URL/health

# 配置状态
curl -X POST -H "x-bot-secret: BOT_SECRET" https://WORKER_URL/stats

# 注册 webhook
curl -X POST -H "x-bot-secret: BOT_SECRET" https://WORKER_URL/registerWebhook

# 注销 webhook
curl -X POST -H "x-bot-secret: BOT_SECRET" https://WORKER_URL/unregisterWebhook

# 设置命令菜单
curl -X POST -H "x-bot-secret: BOT_SECRET" https://WORKER_URL/setcommands

# 查看 Telegram webhook 状态
curl https://api.telegram.org/botBOT_TOKEN/getWebhookInfo
```

---

## 附录 D：本地开发

### D.1 安装依赖

```bash
npm install
```

### D.2 配置 .dev.vars

```bash
cp .dev.vars.example .dev.vars
```

编辑 `.dev.vars`，填入测试值：

```bash
BOT_TOKEN=123456:ABC...
BOT_SECRET=随便一个字符串用于本地
ADMIN_UID=你的UID
AI_BASE_URL=https://your-relay.com/v1
AI_API_KEY=sk-xxx
SEARCH_API_KEY=
BYPASS_TG_ASN_CHECK=1
```

⚠️ `.dev.vars` 不要提交到 git（已在 .gitignore）。

### D.3 启动本地 wrangler dev

```bash
npm run dev
```

会启动本地 dev server，通常在 `http://localhost:8787`。

### D.4 用 ngrok 暴露到公网

Telegram webhook 需要公网 URL。用 ngrok：

```bash
# 安装 ngrok（如果没装）
# https://ngrok.com/download

ngrok http 8787
```

会得到类似 `https://abc123.ngrok.io` 的公网地址。

### D.5 配置 webhook 指向本地

编辑 `.dev.vars`，加：

```bash
WEBHOOK_URL_OVERRIDE=https://abc123.ngrok.io
```

重启 `npm run dev`。

### D.6 注册 webhook

```bash
curl -X POST \
  -H "x-bot-secret: 你的BOT_SECRET" \
  https://abc123.ngrok.io/registerWebhook
```

现在 Telegram 消息会推到你的本地 dev server。

### D.7 改代码后自动重载

wrangler dev 会监视文件变化自动重载。改完代码保存即可，无需重启。

---

## 完成

部署完成后，你的 bot 应该能：
- ✅ 自动验证陌生人（算术题）
- ✅ AI 过滤广告/诈骗/骚扰
- ✅ 自动封禁违规用户
- ✅ 转发所有消息类型（文字/图片/视频/语音/文件等）给管理员
- ✅ 管理员 reply 直接回复用户
- ✅ AI 代笔草稿（带确认/重生成/自行回复按钮）
- ✅ AI 私人助理（/ai 命令）
- ✅ 联网搜索（如配置了 SEARCH_API_KEY）
- ✅ 审计日志和拦截记录查询
- ✅ 用户申诉流程

有任何问题，先看 [故障排查](#15-故障排查) 章节。祝使用愉快！
