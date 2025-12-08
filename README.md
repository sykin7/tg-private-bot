
# 🛡️ Telegram 私聊转发与主动防御机器人

[![Version](https://img.shields.io/badge/Version-V39.2%20Persistent%20Core-crimson)](https://github.com/yourusername/yourrepository)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Database-SQLite3%20(WAL)-lightgrey)](https://www.sqlite.org/index.html)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED?logo=docker)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

这是一个专为高安全性需求设计的 Telegram 私聊转发机器人。它不仅仅是一个简单的转发器，更是一个集成了**企业级持久化存储**、**高强度人机验证**和**动态反垃圾网络**的主动防御系统。

引入了“不死鸟”轮询机制和自动数据目录创建功能，显著提升了在容器环境（如 Docker, Leaflow, Zeabur）下的稳定性。

## ✨ 核心功能亮点

### 🧠 智能人机验证 (Anti-OCR Captcha)

  * **混合干扰抗对抗**：采用“中文数字 + 阿拉伯数字 + 运算符 + 零宽隐形字符”混合生成算术题，有效抵御常规 OCR 脚本的自动识别。
  * **动态惩罚机制**：新用户需在 120秒 内完成验证。超时或 3次错误尝试后，将触发随机时长的临时封禁（10\~60分钟）。

### 💾 数据持久化与高可用 (SQLite WAL)

  * **状态永不丢失**：所有用户验证状态、封禁记录和消息映射关系均实时写入本地 SQLite 数据库。
  * **容器友好**：支持通过环境变量自定义数据库路径，配合 Docker 挂载卷，即使容器重建或服务器重启，机器人记忆依然在。
  * **高并发读写**：启用 SQLite WAL (Write-Ahead Logging) 模式和线程锁，确保多用户同时操作时的数据一致性和高性能。

### 🛡️ 多重防御体系

  * **动态反垃圾 (Anti-Spam)**：内置基础词库，并**每小时自动从远程 URL（如 GitHub）同步最新规则**。支持复杂的正则表达式匹配和文本标准化处理。
  * **洪水控制 (Anti-Flood)**：内置频率限制器，检测瞬时高频请求。违规者将自动暂停服务 60秒。
  * **深度内容检测**：不仅检测消息内容，还会自动扫描发送者的**昵称**、**文件名**是否包含违规推广词。

### 📨 双向无缝转发与广播

  * **管理员视角**：接收用户消息时，会自动附加用户信息尾巴（如 `👤 Name (ID: 12345)`），一眼识别发送者。
  * **便捷回复**：管理员只需**回复 (Reply)** 转发过来的消息，机器人即可将内容（支持文本、图片、文件、语音等）原路转达给对应的用户。
  * **全员广播**：内置广播系统，管理员可一键向历史所有用户发送通知。

### 🌍 智能多语言 (i18n)

  * **双语支持**：完整支持 **中文** 与 **English** 界面。
  * **自动/手动切换**：用户可在菜单中自主切换语言，机器人也会根据上下文自动适配。

### 🔄 “不死鸟”保活机制

  * 内置无限重试循环，当遇到网络波动或 Telegram API 暂时不可用导致连接中断时，机器人会自动休眠并重新连接，无需人工干预。

-----

## 🛠️ 部署指南

### 1\. 前置要求

  * 获取 Telegram Bot Token ([@BotFather](https://t.me/BotFather))
  * 获取您的数字 Admin ID ([@userinfobot](https://t.me/userinfobot))

### 2\. 环境变量配置 (Environment Variables)

| 变量名 | 必填 | 默认值 / 说明 |
| :--- | :---: | :--- |
| **`BOT_TOKEN`** | ✅ | 您的机器人 Token |
| **`ADMIN_ID`** | ✅ | 管理员的数字 ID |
| `BOT_DB_PATH` | ❌ | `/app/data/bot_core.db` <br> **强烈建议**在容器部署时指定此路径并挂载卷。 |
| `REMOTE_SPAM_URL` | ❌ | (内置 GitHub 链接) <br> 您的远程 spam 规则文件直链 (Raw Text)。 |
| `WELCOME_ZH` | ❌ | (内置欢迎语) 自定义中文欢迎消息。 |
| `WELCOME_EN` | ❌ | (内置欢迎语) 自定义英文欢迎消息。 |
| `AUTO_REPLY_ZH` | ❌ | (内置回复) 用户发送消息后的自动回执。 |

### 3\. Docker Compose 部署 (推荐)

为了确保数据持久化，请务必配置**存储卷挂载**。

```yaml
version: '3'
services:
  bot:
    image: python:3.9-slim
    container_name: secure_bot
    restart: always
    environment:
      - BOT_TOKEN=your_token_here
      - ADMIN_ID=your_admin_id
      - BOT_DB_PATH=/app/data/bot_core.db
      - TZ=Asia/Shanghai
    volumes:
      - ./bot.py:/app/bot.py
      - ./data:/app/data  # 核心：确保数据库文件持久化
    working_dir: /app
    command: sh -c "pip install pyTelegramBotAPI requests && python bot.py"
```

-----

## 📝 管理员使用手册

### 1\. 回复消息 (Reply)

收到用户的转发消息后，直接对此消息进行**回复 (Reply)**，机器人会将您的回复内容发送给该用户。

### 2\. 管理命令

所有命令必须通过**回复 (Reply)** 某条用户发来的消息（或者直接发送给机器人）来触发：

| 命令 | 功能 | 说明 |
| :--- | :--- | :--- |
| **`/ban`** | 封禁用户 | **回复消息使用**。将目标用户封禁 **30天**，期间无法交互。 |
| **`/unban`** | 解封用户 | **回复消息使用**。立即恢复目标用户的发送权限。 |
| **`/broadcast [内容]`** | 全员广播 | **直接发送使用**。向数据库中记录的所有用户群发消息。 |

-----

## 📈 发展趋势与反馈 (Feedback & Trends)

项目的持续改进离不开您的参与！

* **遇到 BUG？** 发现机器人有异常行为，请直接提交 [Issues](../../issues) 反馈，我会尽快修复。
* **有新点子？** 欢迎提出 Feature Request，让机器人变得更强大。

如果这个项目对您有帮助，欢迎点亮一颗 ⭐ Star！

[![Star History Chart](https://api.star-history.com/svg?repos=sykin7/tg-private-bot&type=Date)](https://star-history.com/#sykin7/tg-private-bot&Date)

---
## ⚠️ 免责声明

本项目仅供技术研究与个人安全防护使用。使用者应遵守当地法律法规及 Telegram 服务条款。请勿用于非法用途。



