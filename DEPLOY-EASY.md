# 小白部署指南（人话版）

## 这个项目部署有多简单？

**一句话总结**：把代码放到 GitHub → 在 Cloudflare 网页点几下连接 → 填几个密钥 → 发一条命令告诉 Telegram"消息往哪发" → 完成。

**不用装任何软件**，全程在浏览器里操作。大概 20-30 分钟。

---

## 准备工作（5 分钟）

### 你需要准备 3 样东西

#### 1. 一个 Telegram Bot

打开 Telegram，找 `@BotFather` 这个机器人（蓝色认证勾）：

1. 给它发 `/newbot`
2. 它问你叫什么名字，随便起，比如 `我的助手`
3. 它问你 username（必须以 bot 结尾），比如 `my_helper_bot`
4. 它会给你一串 token，**复制保存下来**，长这样：
   ```
   7123456789:AAH3bB2cC1dD4eE5fF6gG7hH8iI9jJ0kK
   ```
   👆 这就是你的 **BOT_TOKEN**，等下要用

#### 2. 你自己的 Telegram ID

打开 Telegram，找 `@userinfobot`：

1. 给它发 `/start`
2. 它立刻回复你的信息，其中有一行：
   ```
   Id: 123456789
   ```
   👆 这串数字就是你的 **ADMIN_UID**，等下要用

#### 3. 一个 AI 中转站

你需要一个 OpenAI 兼容的 AI 服务（用来过滤广告、帮你代笔回复）。如果你已经有了，准备：
- 中转站地址，比如 `https://api.your-ai.com/v1` —— 这是 **AI_BASE_URL**
- API Key，比如 `sk-xxxxx` —— 这是 **AI_API_KEY**

没有的话，可以用 Cloudflare 自带的免费 AI（不用额外注册），下面会说。

---

## 开始部署

### 第 1 步：把代码放到 GitHub（5 分钟）

#### 1.1 注册 GitHub

打开 https://github.com/signup 注册账号（免费）。如果已经有了就跳过。

#### 1.2 创建仓库

1. 登录后点右上角 `+` 号 → **New repository**
2. Repository name 填：`nicechat-bot`
3. **选 Private**（私有，别人看不到你的代码）
4. 勾选 **Add a README file**
5. 点绿色的 **Create repository** 按钮

#### 1.3 上传项目代码

1. 解压你拿到的 `nicechat-bot-secured.zip` 文件
2. 回到 GitHub 仓库页面，点 **Add file** → **Upload files**
3. **把解压出来的所有东西拖进去**（用 Chrome 浏览器，可以拖整个文件夹）
4. 注意：**不要上传** `node_modules` 文件夹（如果有）
5. 拖完等它上传完，点绿色的 **Commit changes** 按钮

#### 1.4 检查

GitHub 仓库里应该能看到这些：
- `src/` 文件夹（里面 15 个 .ts 文件）
- `wrangler.jsonc` 文件
- `package.json` 文件
- `README.md`、`DEPLOY-WEB.md` 等文档

---

### 第 2 步：在 Cloudflare 连接你的 GitHub（3 分钟）

#### 2.1 注册 Cloudflare

打开 https://dash.cloudflare.com/sign-up 注册（免费）。

#### 2.2 连接 GitHub

1. 登录后，左边菜单点 **Workers & Pages**
2. 点蓝色的 **Create** 按钮
3. 选 **Connect to Git** 标签
4. 点 **Connect GitHub**，授权 Cloudflare 访问你的 GitHub
5. 选你刚创建的 `nicechat-bot` 仓库
6. 点 **Begin setup**

#### 2.3 配置（一般自动填好了）

Cloudflare 会自动检测项目配置。检查一下：

| 字段 | 应该填什么 |
|------|----------|
| Project name | `nicechat-bot`（自动填的就行） |
| Production branch | `main` |
| Build command | 留空 |
| Deploy command | `npx wrangler deploy` |

点 **Save and Deploy**。

**这时会报错**——因为还没配置密钥。**正常，不用管**，继续往下做。

---

### 第 3 步：创建数据库存储（2 分钟）

Bot 需要一个地方存用户信息、违规记录等。

#### 3.1 创建 KV

1. Cloudflare 左边菜单点 **Storage & Databases** → **KV**
2. 点 **Create a namespace**
3. Namespace name 填：`TG_BOT_KV`
4. 点 **Add**

#### 3.2 复制 ID

创建后，列表里会显示一串 ID（32 位字母数字）。**复制保存下来**，长这样：
```
a1b2c3d4e5f6789012345abcdef67890
```
等下要用。

---

### 第 4 步：连接数据库到 Worker（2 分钟）

#### 4.1 进入 Worker 设置

1. Cloudflare 左边菜单点 **Workers & Pages**
2. 点你刚创建的 `nicechat-bot`（如果没看到，等 1 分钟刷新）
3. 点 **Settings** 标签
4. 找 **Bindings** 区域（或叫 **Variables and Secrets**）

#### 4.2 添加 KV 绑定

点 **Add binding** → 选 **KV Namespace**：
- Variable name（变量名）：填 `TG_BOT_KV`
- KV namespace：下拉选 `TG_BOT_KV`（你刚创建的）
- 点 **Save**

#### 4.3 添加 AI 绑定

再点 **Add binding** → 选 **Workers AI**：
- Variable name：填 `AI`
- 点 **Save**

---

### 第 5 步：添加密钥（5 分钟）

**这一步最关键**，要填 6 个密钥。

在 Worker 的 **Settings** → **Variables and Secrets** 区域，点 **Add** → 选 **Secret**（注意选 Secret，不是 Plain text）。

逐个添加以下 6 个：

#### 密钥 1：BOT_TOKEN

| Variable name | Value |
|---------------|-------|
| `BOT_TOKEN` | 你在准备工作里拿到的 Bot Token，比如 `7123456789:AAH3bB2cC1dD4eE5fF6gG7hH8iI9jJ0kK` |

点 **Save**。

#### 密钥 2：BOT_SECRET

这是 webhook 校验密钥，自己随便生成一个长字符串。

**怎么生成？** 在浏览器任意页面按 F12 打开控制台，粘贴这行回车：
```javascript
console.log(Array.from({length:64},()=>Math.floor(Math.random()*16).toString(16)).join(''))
```

会输出一串 64 位的随机字符，比如：
```
a3f5e8b2c1d4f6a9e7b3c5d8f1a4b6e9c2d5f8a1b4c6e9d2f5a8b1c4d6e9f2a5
```

复制这串，填到：

| Variable name | Value |
|---------------|-------|
| `BOT_SECRET` | 你刚生成的那串 64 位字符 |

点 **Save**。**这串字符你自己也要保存一份**，等下注册 webhook 时要用！

#### 密钥 3：ADMIN_UID

| Variable name | Value |
|---------------|-------|
| `ADMIN_UID` | 你的 Telegram 数字 ID，比如 `123456789` |

点 **Save**。

#### 密钥 4：AI_BASE_URL

| Variable name | Value |
|---------------|-------|
| `AI_BASE_URL` | 你的 AI 中转站地址，比如 `https://api.your-ai.com/v1` |

**注意**：地址结尾是 `/v1`，不要带 `/chat/completions`。

点 **Save**。

**如果你没有 AI 中转站**：填一个空字符串 `""`，bot 会用 Cloudflare 自带的免费 AI（效果一般但能跑）。

#### 密钥 5：AI_API_KEY

| Variable name | Value |
|---------------|-------|
| `AI_API_KEY` | 你的 AI 中转站 API key，比如 `sk-xxxxxxxxxxxxx` |

点 **Save**。

**如果你没有 AI 中转站**：填一个空字符串 `""`。

#### 密钥 6：SEARCH_API_KEY（可选）

这个是联网搜索功能用的。不要搜索功能就跳过。

要的话：

| Variable name | Value |
|---------------|-------|
| `SEARCH_API_KEY` | Brave Search key（`BSA` 开头）或 Tavily key（`tvly-` 开头） |

点 **Save**。

#### 检查

添加完后，Secrets 列表应该有 5-6 项（看你是否加了 SEARCH_API_KEY）。

---

### 第 6 步：把数据库 ID 填到代码里（2 分钟）

**不做这步部署会失败。**

#### 6.1 改 GitHub 文件

1. 回到 GitHub 你的 `nicechat-bot` 仓库
2. 点 `wrangler.jsonc` 文件
3. 点右上角 ✏️ 铅笔图标编辑
4. 找到这一行（大约在第 20 行）：
   ```jsonc
   { "binding": "TG_BOT_KV", "id": "REPLACE_WITH_YOUR_KV_ID" }
   ```
5. 把 `REPLACE_WITH_YOUR_KV_ID` 替换成你在第 3 步复制的真实 KV ID，比如：
   ```jsonc
   { "binding": "TG_BOT_KV", "id": "a1b2c3d4e5f6789012345abcdef67890" }
   ```
6. 点绿色的 **Commit changes** 按钮

#### 6.2 自动重新部署

你 commit 后，Cloudflare 会自动检测到变化，重新部署。约 1-2 分钟。

#### 6.3 查看部署状态

1. Cloudflare → Workers & Pages → 你的 `nicechat-bot`
2. 点 **Deployments** 标签
3. 看最新一条状态：
   - 🟡 Building = 正在构建
   - 🟢 Success = 成功
   - 🔴 Failed = 失败（点进去看错误日志）

---

### 第 7 步：拿到你的 Worker 网址（1 分钟）

部署成功后：

1. Cloudflare → Workers & Pages → 你的 `nicechat-bot`
2. 在主页顶部能看到一个网址，类似：
   ```
   https://nicechat-bot.你的名字.workers.dev
   ```
3. **复制这个网址**，等下要用

#### 测试一下

浏览器打开 `https://nicechat-bot.你的名字.workers.dev/health`

如果看到 `ok` 两个字母，说明部署成功了！

---

### 第 8 步：注册 webhook（2 分钟）

**什么是 webhook？** 就是告诉 Telegram："有人给我发消息时，请推送到这个网址"。这一步任何 Telegram bot 都要做，不是 Cloudflare 的额外要求。

**就一次操作，复制粘贴的事。**

#### 方法 A：用浏览器控制台（最简单）

1. 打开任意网页（比如百度）
2. 按 F12 打开开发者工具
3. 点 **Console** 标签
4. 粘贴下面这段代码，**改两个地方**再回车：

```javascript
fetch('https://你的WORKER网址/registerWebhook', {
  method: 'POST',
  headers: { 'x-bot-secret': '你的BOT_SECRET值' }
}).then(r => r.text()).then(t => console.log(t))
```

**改两处**：
- `https://你的WORKER网址/registerWebhook` → 换成你第 7 步拿到的网址 + `/registerWebhook`
- `你的BOT_SECRET值` → 换成你第 5 步生成的 64 位随机字符串

回车后，控制台应该输出：
```
✅ webhook set to https://nicechat-bot.xxx.workers.dev/webhook
```

看到这个就成功了！

#### 方法 B：用在线工具

打开 https://reqbin.com/curl

填：
- Method：选 **POST**
- URL：填 `https://你的WORKER网址/registerWebhook`
- Headers：点 Add，Name 填 `x-bot-secret`，Value 填你的 BOT_SECRET
- 点 **Send**

看到 `✅ webhook set to...` 就成功了。

---

### 第 9 步：设置命令菜单（1 分钟）

让管理员在 Telegram 客户端能看到命令提示（点输入框左边的 `/` 出菜单）。

**和第 8 步一样的方法，只是 URL 换一下：**

```javascript
fetch('https://你的WORKER网址/setcommands', {
  method: 'POST',
  headers: { 'x-bot-secret': '你的BOT_SECRET值' }
}).then(r => r.text()).then(t => console.log(t))
```

回车后看到：
```
✅ commands set (public: start; admin: full menu)
```

---

### 第 10 步：测试（2 分钟）

#### 10.1 用另一个 Telegram 账号测试

**不要用管理员账号测**，要找朋友或用另一个账号。

1. 让朋友在 Telegram 搜索你的 bot username（比如 `@my_helper_bot`）
2. 点 **Start**
3. 朋友应该收到：
   ```
   你好，这是主人的私人助手...
   
   请发送【验证码】：8 加 5 = ?
   （直接发送数字答案）
   ```
4. 朋友发送正确答案（比如 `13`）
5. 朋友收到 `✅ 验证通过，请发送你的消息。`
6. 朋友发任意消息（比如"你好"）
7. **你的管理员账号**会收到转发：
   ```
   👤 朋友的名字 @朋友username (uid:朋友的ID)
   📋 UID: 朋友的ID
   
   [朋友发的消息]
   ```

#### 10.2 测试管理员命令

用你的管理员账号给 bot 发：

```
/ai 你好
```

应该收到 AI 助理的回复。

#### 10.3 测试代笔

1. 让朋友给 bot 发"你好"
2. 你收到转发后，**回复（reply）那条转发消息**，发送 `/ai 礼貌回复`
3. 你会收到 AI 生成的草稿 + 三个按钮
4. 点 **✅ 确认回复**，草稿自动发给朋友

---

## 完成！🎉

你的 bot 现在能用了。总结一下它有什么功能：

- ✅ 陌生人发消息 → 算术题验证 → 通过后转发给你
- ✅ AI 自动过滤广告/诈骗/骚扰
- ✅ 累计违规自动封禁
- ✅ 你 reply 转发消息就能回复对方
- ✅ `/ai` 让 AI 帮你代笔回复
- ✅ `/ai 问题` 直接问 AI 助理
- ✅ `/model` 切换 AI 模型
- ✅ `/ban` `/unban` `/forgive` 管理用户
- ✅ `/intercepts` 看拦截记录
- ✅ `/audit` 看操作日志

---

## 常见问题（小白版）

### Q: 部署失败，显示红色

**最常见原因**：第 6 步的 KV ID 没填。

去 GitHub 看 `wrangler.jsonc`，如果还是 `REPLACE_WITH_YOUR_KV_ID`，就是没改。改成你真实的 KV ID，commit，等 2 分钟自动重新部署。

### Q: Bot 不回消息

1. 检查第 8 步 webhook 是否注册成功
2. 浏览器打开 `https://你的WORKER网址/health`，看是否返回 `ok`
3. 检查 Cloudflare Dashboard 的 Worker Logs，看有没有错误

### Q: 验证题答对了但提示错误

确保你发的是纯数字（如 `13`），不是"十三"或"13.0"。

### Q: AI 不回复

检查第 5 步的 `AI_BASE_URL` 和 `AI_API_KEY` 是否填对。`AI_BASE_URL` 结尾是 `/v1`，不要带别的。

### Q: 怎么改欢迎语？

去 GitHub 改 `wrangler.jsonc` 里的 `WELCOME_MESSAGE`，commit，等自动部署。

### Q: 怎么改 AI 模型？

GitHub 改 `wrangler.jsonc` 里的 `AI_MODEL`，或者在 Telegram 给 bot 发 `/model list` 看可用模型，`/model 模型名` 切换。

### Q: 会不会扣钱？

**不会**。Cloudflare 免费层够个人用：
- 每天 10 万次请求
- 每天 1000 次 KV 写（约 500 条消息）
- 每天 1 万次 AI 调用

用超了才会提示升级，不会自动扣费。

### Q: 怎么删除 bot？

1. Cloudflare → Workers & Pages → 你的 Worker → Settings → 滚到底 → Delete
2. Cloudflare → KV → 你的 namespace → Delete
3. Telegram 找 @BotFather → `/deletebot`

---

## 还是不行？

按这个顺序检查：

1. **GitHub 仓库**有没有上传完整？应该有 `src/` 文件夹和 `wrangler.jsonc`
2. **Cloudflare Worker** 部署状态是不是绿色 Success？
3. **KV ID** 是不是填到 `wrangler.jsonc` 了？
4. **6 个 Secret** 是不是都填了？
5. **webhook** 是不是注册成功了？
6. 浏览器开 `https://你的WORKER网址/health` 是不是返回 `ok`？

如果都对了还不行，把 Cloudflare Worker 的 Logs 里的错误信息发出来看看。
