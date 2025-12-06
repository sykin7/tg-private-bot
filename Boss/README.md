
# 🛡️ Telegram 私聊防火墙 & 双向通讯机器人 (V19.0)

这是一个基于 Python Flask 和 python-telegram-bot 构建的高级 Telegram 机器人。它专为个人用户设计，提供**私聊广告拦截**、**消息频率限制**以及**无缝的双向私聊回复**功能。

## ✨ 主要功能

*   **🕵️‍♂️ 智能反垃圾 (Anti-Spam)**：
    *   自动识别并拦截包含特定关键词的广告消息。
    *   支持 Unicode 变体检测（防止广告通过特殊字体绕过）。
    *   **智能封禁**：群组内发广告自动踢出，私聊发广告自动拉黑数据库。
*   **🛡️ 频率限制 (Rate Limiting)**：
    *   防止恶意用户刷屏攻击。
    *   超频自动封禁。
*   **📨 双向无缝通讯**：
    *   用户发给机器人的消息会转发给管理员。
    *   管理员**回复**转发的消息，用户会直接收到（支持文字、图片、表情、视频等）。
*   **🧹 自动维护**：
    *   自动清理旧的数据库日志。
    *   自动删除进群/退群等系统服务消息。

## 🚀 部署指南 (Docker)

### 1. 准备文件
确保你的项目目录包含以下文件：
*   `main.py` (主程序)
*   `config.py` (配置文件)
*   `database.py` (数据库逻辑)
*   `requirements.txt`

### 2. 环境变量配置
在部署 Docker 时，请设置以下环境变量：

| 变量名 | 必填 | 说明 |
| :--- | :--- | :--- |
| `TOKEN` | ✅ | Bot Token (从 @BotFather 获取) |
| `ADMIN_ID` | ✅ | 管理员的数字 ID (可通过 @userinfobot 获取) |
| `WEBHOOK_URL` | ✅ | 你的公网 HTTPS 域名 (例如 `https://bot.example.com`) |
| `PORT` | ❌ | 默认 5000，根据平台需求修改 |
| `SPAM_KEYWORDS` | ❌ | 违禁词列表，使用英文逗号分隔 |

### 3. 启动命令 (示例)

**Docker Run:**
```bash
docker run -d \
  --name tg-bot \
  -e TOKEN="你的Token" \
  -e ADMIN_ID="你的ID" \
  -e WEBHOOK_URL="[https://你的域名.com](https://你的域名.com)" \
  -p 5000:5000 \
  my-tg-bot-image
````

**Docker Compose:**

```yaml
version: '3'
services:
  bot:
    build: .
    ports:
      - "5000:5000"
    environment:
      - TOKEN=你的Token
      - ADMIN_ID=123456789
      - WEBHOOK_URL=[https://your-domain.com](https://your-domain.com)
    restart: always
```

-----

## 📖 管理员使用手册

### 1\. 如何接收消息？

  * 当普通用户给机器人发送消息时，你会收到一条格式如下的消息：
    > 📩 来自 用户名 (ID: 12345678):
    > [用户的消息内容]

### 2\. 如何回复用户？

这是本机器人最核心的功能。你不需要输入指令，只需要：

1.  在 Telegram 中，**长按** 那条由机器人转发给你的消息（带有 `ID: ...` 的那条）。
2.  选择 **“回复” (Reply)** 功能。
3.  输入你想说的话，或者发送 **图片、表情包、视频、文件**。
4.  机器人会自动将你的回复内容“克隆”一份发送给该用户。

**注意：** 必须使用“回复”功能，直接发送新消息机器人不会转发。

### 3\. 封禁机制说明

  * **私聊场景**：如果用户发广告或刷屏，机器人会在数据库中将其标记为 `BANNED`，之后该用户的消息将被静默丢弃，不会打扰管理员。
  * **群组场景**：如果机器人被拉入群组并赋予管理员权限，检测到广告会直接**删除消息并踢出用户**。

-----

## 🛠️ 技术栈

  * Python 3.9+
  * Flask (Web Server for Webhook)
  * python-telegram-bot (v20+)
  * SQLite (轻量级数据库)

<!-- end list -->

````

---

### 💡 额外提示：配套的 `config.py` 写法

为了配合上面的 Docker 变量，你的 `config.py` 应该是这样的（**确保你现在的 config.py 长这样，否则读不到变量**）：

```python
import os

# 必须从环境变量读取
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) # 默认为0防止报错，但在部署时必须设置
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "5000"))

# 其他配置
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_COUNT = 10
BAN_DURATION = 3600
LOG_RETENTION = 7

# 处理屏蔽词列表
_spam_env = os.getenv("SPAM_KEYWORDS", "加群,兼职,日结,加密货币")
SPAM_KEYWORDS = [k.strip() for k in _spam_env.split(",")]
````
