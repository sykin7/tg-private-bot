
# 🤖 Telegram 全能群管与客服机器人使用手册

这是一个集成了**智能防广告**、**数学人机验证**、**双向私聊客服**以及**全员广播**功能的高性能 Telegram 机器人。本项目采用 Docker 部署，基于 Webhook 模式运行。

## 目录

1.  [功能特性](https://www.google.com/search?q=%23-%E5%8A%9F%E8%83%BD%E7%89%B9%E6%80%A7)
2.  [准备工作](https://www.google.com/search?q=%23-%E5%87%86%E5%A4%87%E5%B7%A5%E4%BD%9C)
3.  [核心配置详解 (Variables)](https://www.google.com/search?q=%23-%E6%A0%B8%E5%BF%83%E9%85%8D%E7%BD%AE%E8%AF%A6%E8%A7%A3-variables)
4.  [部署教程 (Docker)](https://www.google.com/search?q=%23-%E9%83%A8%E7%BD%B2%E6%95%99%E7%A8%8B-docker)
5.  [机器人操作指南](https://www.google.com/search?q=%23-%E6%9C%BA%E5%99%A8%E4%BA%BA%E6%93%8D%E4%BD%9C%E6%8C%87%E5%8D%97)
6.  [常见问题排查](https://www.google.com/search?q=%23-%E5%B8%B8%E8%A7%81%E9%97%AE%E9%A2%98%E6%8E%92%E6%9F%A5)

-----

## ✨ 功能特性

  * **🛡️ 暴力防广**：自动检测群组消息，包含违禁词（支持去符号干扰检测）立即撤回并封禁发送者。
  * **🧠 智能验证**：触发频率限制或新用户时，自动弹出数学题（如 `3 + 5 = ?`），答错或超时自动封禁。
  * **📩 客服转发**：用户私聊机器人的消息会转发给管理员，管理员回复即可通过机器人发回给用户。
  * **📢 系统广播**：管理员可一键向数据库内所有历史用户发送公告。
  * **🧹 自动维护**：定时清理系统服务消息（进群/退群提示）和过期日志，防止数据库膨胀。

-----

## 🛠 准备工作

在开始之前，你需要准备以下信息：

1.  **Bot Token**: 在 Telegram 找 [@BotFather](https://t.me/BotFather) 申请。
2.  **Admin ID**: 你自己的 Telegram 数字 ID（可找 [@userinfobot](https://t.me/userinfobot) 获取）。
3.  **Webhook 域名**: 因为脚本强制使用 `run_webhook`，你需要一个**HTTPS 域名**指向你的服务器 IP。

-----

## ⚙️ 核心配置详解 (Variables)

你的脚本依赖 `config.py` 来获取变量。请在项目根目录下新建 `config.py` 文件，并严格按照以下格式填写：

```python
# config.py - 配置文件

# 1. 基础设置
TOKEN = "123456789:ABCDefghIJKLmnOPqrstUVwxyz"  # 你的机器人 Token
ADMIN_ID = 123456789                           # 管理员的数字 ID (只有这个 ID 能使用广播和接收客服消息)

# 2. 网络设置 (Webhook)
# 注意：必须使用 HTTPS 域名，因为 TG 官方 Webhook 不支持纯 HTTP
PORT = 8080                                    # 容器内部运行端口 (与 Dockerfile EXPOSE 一致)
WEBHOOK_URL = "https://your-domain.com"        # 你的域名地址 (不要带最后的 /)

# 3. 防垃圾广告设置
# 这里填写你要屏蔽的关键词，支持部分匹配
SPAM_KEYWORDS = {
    "兼职", "刷单", "USDT", "博彩", "色情", 
    "http", ".com", "加微信", "免费领"
}

# 4. 风控与频率限制
RATE_LIMIT_WINDOW = 60    # 时间窗口 (秒)：检测多少秒内的消息
RATE_LIMIT_COUNT = 10     # 阈值：在上面时间窗口内，超过多少条消息触发人机验证
BAN_DURATION = 3600       # 封禁时长 (秒)：验证失败或发广告封禁多久 (3600秒 = 1小时)

# 5. 系统设置
LOG_RETENTION = 7         # 日志和数据库记录保留天数 (超过自动删除)
```

### 变量填写注意事项：

  * **`SPAM_KEYWORDS`**: 是一个集合（Set），里面的词只要出现在群消息里，消息就会被秒删，人会被封。
  * **`WEBHOOK_URL`**: 必须是外网可访问的 HTTPS 地址。Telegram 服务器会将消息推送到 `https://your-domain.com/YOUR_TOKEN`。

-----

## 🐳 部署教程 (Docker)

### 第一步：构建镜像

在包含 `Dockerfile` 的目录下运行：

```bash
docker build -t my-tg-bot .
```

### 第二步：运行容器

**重要**：必须挂载 `/app/data` 目录，否则你重启容器后，用户数据库和验证状态会丢失。

```bash
docker run -d \
  --name bot \
  -p 8080:8080 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  --restart always \
  my-tg-bot
```

  * `-p 8080:8080`: 将服务器的 8080 端口映射到容器。
  * `-v .../data`: 保证数据库文件 `bot.db` 持久化保存。

### 第三步：配置反向代理 (Nginx/Caddy)

因为 Docker 暴露的是 HTTP 端口，你需要用 Nginx 或 Caddy 给它加上 SSL (HTTPS) 并转发到 8080 端口。

**Nginx 示例配置块：**

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

-----

## 🎮 机器人操作指南

### 1\. 基础设置 (非常重要！)

为了让机器人能看到群里的普通消息并进行过滤，你必须：

1.  私聊 **@BotFather**。
2.  发送 `/mybots` -\> 选择你的机器人 -\> **Bot Settings**。
3.  选择 **Group Privacy** -\> 设置为 **Turn off** (关闭隐私模式)。
      * *解释：如果不关这个，机器人只能看到以 / 开头的命令，无法检测广告。*

### 2\. 群组管理 (Anti-Spam)

1.  将机器人拉入你的群组。
2.  **将机器人提升为管理员 (Admin)**。
      * 必须权限：`Delete Messages` (删除消息), `Ban Users` (封禁用户)。
3.  **效果**：
      * 任何触发 `SPAM_KEYWORDS` 的消息会被秒删。
      * 任何人刷屏（超过 `RATE_LIMIT_COUNT`）会触发数学验证题。
      * 验证失败 3 次或乱点按钮，会被踢出或禁言。

### 3\. 客服系统 (私聊)

这是脚本中很强的一个功能：

  * **用户视角**：直接私聊机器人发送 "你好，我有问题"。
  * **管理员视角**：你会收到一条消息：
    > 📩 张三 (ID: 123456):
    > 你好，我有问题
  * **回复方法**：管理员直接 **回复 (Reply)** 这条消息，输入 "请问遇到什么问题？"。
  * **结果**：机器人会把你的回复内容发给张三。

### 4\. 广播命令 (Broadcast)

只有在 `config.py` 里配置的 `ADMIN_ID` 才能使用此命令。

  * **指令**：`/gb <内容>`
  * **示例**：`/gb 各位注意，今晚服务器维护。`
  * **作用**：机器人会遍历数据库，给所有和它私聊过的用户发送这条消息。

-----

## ❓ 常见问题排查

**Q1: 机器人为什么不回复 /start？**

  * 检查 `WEBHOOK_URL` 是否配置正确，必须是 HTTPS。
  * 检查服务器防火墙是否开放了 8080 端口。
  * 查看日志：`docker logs bot` 或查看 `logs/bot.log`。

**Q2: 为什么群里发广告没反应？**

  * **BotFather 的 Group Privacy 没关**（最常见原因）。
  * 机器人不是管理员，没有删除权限。
  * 广告词没命中 `SPAM_KEYWORDS` 里的词。

**Q3: 修改了 config.py 怎么生效？**

  * 需要重启容器：`docker restart bot`。
