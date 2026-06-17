# nicechat-bot 网页端部署（最简方式）

## ⚠️ 先澄清一个概念

### Workers ≠ Pages

| 特性 | Cloudflare Pages | Cloudflare Workers |
|------|-----------------|-------------------|
| 用途 | 静态网站（HTML/CSS/JS） | 服务端代码（接收 webhook、调 API） |
| 上传 ZIP | ✅ 支持拖拽上传 | ❌ 不支持 |
| 这个项目 | ❌ 不适合 | ✅ 适合 |

**这个项目是 Workers 项目**（要接收 Telegram webhook、调 AI API、读写 KV），**不能用 Pages 部署**。Workers 不支持直接上传 ZIP。

### Workers 的 3 种部署方式

| 方式 | 难度 | 适合 |
|------|------|------|
| **① 连接 GitHub 仓库**（推荐） | ⭐ 最简单 | 所有人 |
| ② Dashboard 编辑器手动粘贴 | ⭐⭐ 繁琐 | 改几行代码试试 |
| ③ wrangler 命令行 | ⭐⭐⭐ | 开发者 |

下面详细讲**方式 ①**——全程网页操作，不用装任何东西。

---

## 方式 ①：连接 GitHub 仓库部署（推荐）

### 总览

1. 把项目代码上传到 GitHub
2. Cloudflare 连接这个仓库
3. 在网页上添加 KV / Secrets / Vars
4. 点部署
5. 注册 webhook

**全程不用装 Node.js、不用装 wrangler、不用命令行。**

---

### 步骤 1：准备 Telegram Bot

1. 打开 Telegram，找 `@BotFather`
2. 发 `/newbot`
3. 按提示设置名字和 username
4. **保存返回的 BOT_TOKEN**（形如 `1234567890:ABCdef...`）

### 步骤 2：获取你的 Telegram UID

1. Telegram 搜索 `@userinfobot`
2. 发 `/start`
3. **保存返回的数字 UID**（如 `123456789`）

### 步骤 3：把项目代码上传到 GitHub

#### 3.1 注册 GitHub 账号（如果没有）

https://github.com/signup

#### 3.2 创建新仓库

1. 点右上角 `+` → **New repository**
2. Repository name 填 `nicechat-bot`
3. 选 **Private**（重要！私有仓库，别公开）
4. 勾选 **Add a README file**
5. 点 **Create repository**

#### 3.3 上传项目文件

1. 解压你拿到的 `nicechat-bot-secured.zip`
2. 在 GitHub 仓库页面点 **Add file** → **Upload files**
3. 把解压出来的所有文件拖进去（包括 `src/` 文件夹、`wrangler.jsonc`、`package.json` 等）
4. 注意：**不要上传** `node_modules/`、`.wrangler/`、`.dev.vars`、`package-lock.json`
5. 点 **Commit changes**

⚠️ **重要**：`src/` 是文件夹，GitHub 网页端上传文件夹需要用 Chrome 浏览器，拖拽整个文件夹进去。

如果网页端上传文件夹有问题，用 GitHub Desktop 客户端更稳：https://desktop.github.com/

#### 3.4 验证上传成功

仓库里应该有这些文件：

```
src/
  admin.ts
  ai-filter.ts
  assistant.ts
  ... (15 个 .ts 文件)
test/
  ... (10 个测试文件)
scripts/
  setup-secrets.sh
wrangler.jsonc
package.json
tsconfig.json
.dev.vars.example
README.md
DEPLOY.md
CHANGES.md
```

---

### 步骤 4：在 Cloudflare 连接仓库

#### 4.1 进入 Workers & Pages

1. 登录 https://dash.cloudflare.com
2. 左侧菜单点 **Workers & Pages**
3. 点 **Create**

#### 4.2 连接 Git

1. 选 **Connect to Git** 标签
2. 点 **Connect GitHub**
3. 授权 Cloudflare 访问你的 GitHub
4. 选你刚创建的 `nicechat-bot` 仓库
5. 点 **Begin setup**

#### 4.3 配置构建

Cloudflare 会自动检测 `wrangler.jsonc`，填写：

| 字段 | 值 |
|------|-----|
| Project name | `nicechat-bot`（或你喜欢的名字） |
| Production branch | `main` |
| Framework preset | None |
| Build command | 留空 |
| Deploy command | `npx wrangler deploy` |

如果 Cloudflare 没自动填 Deploy command，手动填 `npx wrangler deploy`。

#### 4.4 点 Save and Deploy

此时会报错——因为还没配置 KV 和 Secrets。**这是正常的**，先不管，继续下一步。

---

### 步骤 5：创建 KV Namespace

#### 5.1 进入 KV 管理

1. Cloudflare Dashboard 左侧菜单点 **Storage & Databases** → **KV**
2. 点 **Create a namespace**
3. Namespace name 填 `TG_BOT_KV`
4. 点 **Add**

#### 5.2 复制 KV ID

创建后，KV namespace 列表里会显示 ID（一串十六进制字符）。**复制这个 ID**。

---

### 步骤 6：配置 Worker 的 KV 绑定

#### 6.1 进入 Worker 设置

1. Cloudflare Dashboard → **Workers & Pages**
2. 点你刚创建的 `nicechat-bot` Worker
3. 点 **Settings** 标签

#### 6.2 添加 KV 绑定

1. 找 **Bindings** 区域（或 **Variables and Secrets** → **KV Namespace Bindings**）
2. 点 **Add binding** → 选 **KV Namespace**
3. 填：
   - Variable name: `TG_BOT_KV`
   - KV namespace: 选 `TG_BOT_KV`（你刚创建的）
4. 点 **Save** 或 **Deploy**

---

### 步骤 7：添加 Workers AI 绑定

1. 在同一个 **Bindings** 区域
2. 点 **Add binding** → 选 **Workers AI**
3. Variable name 填 `AI`
4. 点 **Save**

---

### 步骤 8：添加 Secrets（密钥）

#### 8.1 进入 Secrets 设置

1. Worker 的 **Settings** 标签
2. 找 **Variables and Secrets** 区域
3. 点 **Add** → 选 **Secret**（注意选 Secret 不是 Plain text）

#### 8.2 逐个添加以下 Secrets

| Variable name | Value | 说明 |
|---------------|-------|------|
| `BOT_TOKEN` | 你的 Bot Token | 步骤 1 拿到的 |
| `BOT_SECRET` | 自己生成的随机字符串 | 见下方"生成 BOT_SECRET" |
| `ADMIN_UID` | 你的数字 UID | 步骤 2 拿到的 |
| `AI_BASE_URL` | `https://your-relay.com/v1` | 你的 AI 中转站地址（不带 /chat/completions） |
| `AI_API_KEY` | `sk-xxx` | 你的中转站 API key |
| `SEARCH_API_KEY` | （可选） | Brave/Tavily key，不用就不填 |

#### 生成 BOT_SECRET

在任意终端（或在线工具 https://generate-random.org/api-key-generator）生成一个 64 字符随机字符串。

或者浏览器控制台（F12）执行：
```javascript
console.log(Array.from({length:64},()=>Math.floor(Math.random()*16).toString(16)).join(''))
```

复制输出，填入 `BOT_SECRET` 的 Value。

#### 8.3 保存每个 Secret

每个 Secret 填完后点 **Save**。**注意**：Secret 值保存后不可查看，只能更新。

---

### 步骤 9：添加 Vars（非敏感配置）

Vars 在 `wrangler.jsonc` 文件里已经配好默认值了，Cloudflare 连接仓库时会自动读取。**一般不用手动改。**

如果你想改某个 Var（比如 `AI_MODEL`），有两种方式：

#### 方式 A：改 GitHub 仓库的 wrangler.jsonc（推荐）

1. 在 GitHub 仓库点 `wrangler.jsonc`
2. 点 ✏️ 编辑
3. 找到 `"AI_MODEL": "gpt-4o-mini"`，改成你想要的模型
4. Commit changes
5. Cloudflare 会自动重新部署

#### 方式 B：在 Cloudflare Dashboard 加环境变量

1. Worker → Settings → Variables and Secrets
2. Add → Plain text
3. 填 Variable name 和 Value
4. Save

⚠️ 注意：Dashboard 里的 Plain text 变量会**覆盖** wrangler.jsonc 里的同名变量。

---

### 步骤 10：更新 wrangler.jsonc 的 KV ID

**这一步必须做**，否则部署会失败。

#### 10.1 获取你的 KV ID

Cloudflare Dashboard → Storage & Databases → KV → 你的 `TG_BOT_KV` → 复制 ID

#### 10.2 改 GitHub 仓库的 wrangler.jsonc

1. GitHub 仓库点 `wrangler.jsonc`
2. 点 ✏️ 编辑
3. 找到这一行：
   ```jsonc
   { "binding": "TG_BOT_KV", "id": "REPLACE_WITH_YOUR_KV_ID" }
   ```
4. 把 `REPLACE_WITH_YOUR_KV_ID` 替换成你的真实 KV ID
5. Commit changes

---

### 步骤 11：触发部署

#### 11.1 手动触发

1. Cloudflare Dashboard → Workers & Pages → 你的 `nicechat-bot`
2. 点 **Deployments** 标签
3. 点最新的 deployment → **Retry deployment**
4. 或者在 GitHub 仓库随便改一下 README（加个空格再删除），commit，Cloudflare 会自动部署

#### 11.2 查看部署状态

1. Worker → **Deployments** 标签
2. 看最新 deployment 的状态：
   - 🟡 Building — 正在构建
   - 🟢 Success — 部署成功
   - 🔴 Failed — 部署失败（点进去看日志）

#### 11.3 部署失败排查

如果失败，点进 deployment 看日志。常见原因：
- KV ID 没改（步骤 10 没做）
- wrangler.jsonc 格式错误（JSON 语法错）
- 代码有 TypeScript 错误（不太可能，已经测试过）

---

### 步骤 12：获取 Worker URL

部署成功后：

1. Worker 主页顶部会显示 URL，类似：
   ```
   https://nicechat-bot.<你的子域名>.workers.dev
   ```
2. **复制这个 URL**

---

### 步骤 13：验证部署

浏览器打开：
```
https://nicechat-bot.<你的子域名>.workers.dev/health
```

应该看到纯文本 `ok`。

---

### 步骤 14：注册 Webhook

**这一步必须用命令行或在线工具发 POST 请求**（浏览器地址栏只能发 GET）。

#### 方式 A：用在线 curl 工具

打开 https://reqbin.com/curl 或 https://hoppscotch.io

发送：
- Method: `POST`
- URL: `https://nicechat-bot.<你的子域名>.workers.dev/registerWebhook`
- Headers: `x-bot-secret: 你的BOT_SECRET值`

点 Send，应该返回：
```
✅ webhook set to https://nicechat-bot.xxx.workers.dev/webhook
```

#### 方式 B：用浏览器开发者工具

1. 打开任意网页
2. F12 打开控制台
3. 粘贴执行：
```javascript
fetch('https://你的WORKER_URL/registerWebhook', {
  method: 'POST',
  headers: { 'x-bot-secret': '你的BOT_SECRET值' }
}).then(r => r.text()).then(t => console.log(t))
```

---

### 步骤 15：设置命令菜单

同样发 POST 请求：

- Method: `POST`
- URL: `https://nicechat-bot.<你的子域名>.workers.dev/setcommands`
- Headers: `x-bot-secret: 你的BOT_SECRET值`

返回：
```
✅ commands set (public: start; admin: full menu)
```

---

### 步骤 16：测试

1. 用另一个 Telegram 账号（不是管理员）给 bot 发消息
2. 应该收到欢迎语 + 算术题
3. 答对后发消息，管理员收到转发
4. 管理员 reply 转发消息回复用户

🎉 **部署完成！**

---

## 方式 ②：Dashboard 编辑器手动粘贴（不推荐）

如果不想用 GitHub，可以在 Cloudflare Dashboard 手动创建文件。但**项目有 15 个源文件**，手动粘贴很痛苦。

### 步骤

1. Cloudflare Dashboard → Workers & Pages → Create → Create Worker
2. 起名 `nicechat-bot`，点 Deploy
3. 部署后点 **Edit code**
4. 在左侧文件树手动创建每个文件：
   - 点 `+` 新建文件，文件名如 `src/index.ts`
   - 粘贴对应文件内容
   - 重复 15 次（每个 .ts 文件一次）
5. 点右上角 **Deploy**
6. 然后回到 Worker Settings，按方式 ① 的步骤 5-15 配置 KV/Secrets/Vars/webhook

⚠️ **不推荐**：15 个文件手动粘贴容易出错，且后续更新代码要重复粘贴。**强烈建议用方式 ① GitHub 连接**。

---

## 方式 ③：wrangler 命令行（开发者用）

详见 [DEPLOY.md](./DEPLOY.md)。适合已经装了 Node.js、熟悉命令行的开发者。

---

## 常见问题

### Q: 为什么不能像 Pages 一样上传 ZIP？

A: Cloudflare Workers 的部署模型和 Pages 不同。Workers 需要构建 + 上传 Wasm bundle，这个过程要么通过 wrangler CLI，要么通过 Git 连接自动构建。Pages 是纯静态文件，所以能直接拖拽上传。

### Q: 我没有 GitHub 账号怎么办？

A: 注册一个（免费）。GitHub 是最方便的代码托管平台，Cloudflare 的 Git 集成最稳。或者用方式 ② 手动粘贴。

### Q: 可以用 GitLab 或 Bitbucket 吗？

A: Cloudflare 目前只支持 GitHub 和 GitLab。Bitbucket 不支持。

### Q: 部署后怎么改代码？

A: 在 GitHub 仓库改代码 → commit → Cloudflare 自动重新部署。约 1-2 分钟生效。

### Q: 怎么改 Secrets？

A: Worker → Settings → Variables and Secrets → 对应 Secret 点 Edit → 输入新值 → Save。立即生效。

### Q: 怎么改 Vars（非敏感配置）？

A: 改 GitHub 仓库的 `wrangler.jsonc` → commit → 自动部署。或者在 Dashboard 加 Plain text 变量覆盖。

### Q: 怎么看日志？

A: Worker → Logs 标签 → 实时查看。或 wrangler tail。

### Q: 部署失败怎么办？

A: Worker → Deployments → 点失败的 deployment → 看构建日志。常见原因：
- KV ID 没填（wrangler.jsonc 里还是 `REPLACE_WITH_YOUR_KV_ID`）
- JSON 格式错误
- 代码语法错误（不太可能）

### Q: 免费够用吗？

A: 个人用够用。免费层限制：
- 100,000 请求/天
- KV 1,000 写/天（约 500 消息/天）
- Workers AI 10,000 次/天

如果不够，升级 Workers Paid $5/月。

---

## 总结

| 步骤 | 操作 | 在哪做 |
|------|------|--------|
| 1 | 创建 Telegram Bot | Telegram |
| 2 | 获取 UID | Telegram |
| 3 | 上传代码到 GitHub | GitHub |
| 4 | 连接仓库 | Cloudflare Dashboard |
| 5 | 创建 KV | Cloudflare Dashboard |
| 6 | 绑定 KV | Worker Settings |
| 7 | 绑定 Workers AI | Worker Settings |
| 8 | 添加 6 个 Secrets | Worker Settings |
| 9 | 改 wrangler.jsonc 的 KV ID | GitHub |
| 10 | 触发部署 | Cloudflare Dashboard |
| 11 | 注册 webhook | POST 请求 |
| 12 | 设置命令菜单 | POST 请求 |

**全程不用装任何软件**（除了注册 GitHub 账号），所有操作都在浏览器里完成。
