
# 🤖 Telegram 私聊客服 & 智能反垃圾机器人

[![Version](https://img.shields.io/badge/Version-V39.2%20Persistent%20Core-crimson)](https://github.com/yourusername/yourrepository)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Database-SQLite3%20(WAL)-lightgrey)](https://www.sqlite.org/index.html)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED?logo=docker)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

这是一个基于 Python (`pyTelegramBotAPI`) 开发的高级 Telegram 机器人。它不仅可以充当**私聊转发/客服机器人**（将用户的消息转发给管理员，管理员直接回复），还内置了强大的**自动反垃圾（Anti-Spam）、人机验证（Captcha）和黑白名单系统**。

## ✨ 主要功能

  * **📨 消息转发系统**：用户发给机器人的消息（文本、图片、视频、贴纸、文件等）会自动转发给管理员。
  * **🗣️ 双向交流**：管理员直接回复转发的消息，机器人会将内容匿名发送回用户。
  * **🛡️ 多重安全防护**：
      * **人机验证**：新用户需完成数学算术验证（支持中文/数字显示）。
      * **智能反垃圾**：基于正则匹配和远程规则库（Github）自动拦截违规广告（博彩、发票、色情等）。
      * **防刷屏（Flood Control）**：限制用户短时间内的发送频率。
  * **🌐 多语言支持**：内置中文和英文，用户可自由切换，管理员回复时自动匹配语言。
  * **👮 管理员工具箱**：支持封禁、解封、黑名单、白名单、群发广播等指令。
  * **🧹 自动清理**：自动删除验证消息、菜单消息，保持聊天界面整洁；自动维护数据库体积。

-----

## 🛠️ 部署指南

### 1\. 环境要求

  * Python 3.8+
  * 依赖库：`pyTelegramBotAPI`, `requests`

### 2\. 安装依赖

创建一个 `requirements.txt` 并写入以下内容：

```text
pyTelegramBotAPI
requests
```

然后运行：

```bash
pip install -r requirements.txt
```

### 3\. 环境变量配置 (Environment Variables)

你需要通过环境变量来配置机器人，不要直接修改代码中的敏感信息。

| 变量名 | 必填 | 默认值 | 说明 |
| :--- | :---: | :--- | :--- |
| `BOT_TOKEN` | ✅ | 无 | 从 @BotFather 获取的 API Token |
| `ADMIN_ID` | ✅ | 无 | 管理员的数字 ID (可通过 @userinfobot 获取) |
| `BOT_DB_PATH` | ❌ | `/app/data/bot_core.db` | 数据库存储路径 |
| `REMOTE_SPAM_URL` | ❌ | (默认 GitHub 地址) | 远程违禁词库 TXT 文件的 URL |
| `WELCOME_ZH` | ❌ | (默认欢迎语) | 中文欢迎语 |
| `WELCOME_EN` | ❌ | (默认欢迎语) | 英文欢迎语 |

### 4\. 运行机器人

**直接运行：**

```bash
export BOT_TOKEN="你的Token"
export ADMIN_ID="你的ID"
python bot.py
```

**或者使用 Docker (推荐)：**

```bash
docker run -d \
  -e BOT_TOKEN="你的Token" \
  -e ADMIN_ID="你的ID" \
  -v $(pwd)/data:/app/data \
  --name tg-bot \
  python:3.9-slim python bot.py
```

*(注意：需要自行构建包含依赖的 Docker 镜像)*

-----

## 📖 使用说明

### 👤 对于普通用户

1.  **开始使用**：发送 `/start`，选择语言（中文/English）。
2.  **验证**：如果是第一次发消息，机器人会发送一道数学题（例如：`壹 + 3 = ?`），直接回复数字答案即可通过。
3.  **发送消息**：验证通过后，直接发送文本或媒体文件，管理员会收到通知。
4.  **防骚扰**：如果发送包含违禁词（如USDT、兼职等）的内容，会被自动封禁。

### 👑 对于管理员 (Admin)

#### 1\. 回复用户消息

当机器人转发用户的消息给你时：

  * **直接回复该消息**：你的回复内容（文字、图片等）会通过机器人发送给该用户。
  * **注意**：如果不引用（Reply）转发的消息，机器人不会知道你要发给谁。

#### 2\. 快捷管理指令 (回复模式)

在**回复**用户转发过来的消息时，发送以下指令：

| 指令 | 作用 | 说明 |
| :--- | :--- | :--- |
| `/ban` | 🚫 **封禁用户** | 封禁 30 天，期间用户无法发消息。 |
| `/unban` | 🔓 **解封用户** | 解除封禁状态。 |
| `/awl` | ⚪ **加白名单** | Add Whitelist，跳过反垃圾和频率检测。 |
| `/abl` | ⚫ **加黑名单** | Add Blacklist，永久拒收该用户消息。 |

#### 3\. 全局管理指令 (直接发送)

直接给机器人发送以下指令：

| 指令 | 作用 | 示例 |
| :--- | :--- | :--- |
| `/gb <内容>` | 📢 **全员广播** | `/gb 大家好，系统维护通知...` |
| `/awl <ID>` | ➕ **ID 加白** | `/awl 123456789` (无需回复消息) |
| `/abl <ID>` | ➖ **ID 拉黑** | `/abl 123456789` |
| `/dwl <ID>` | ❌ **移除白名单** | `/dwl 123456789` |
| `/dbl <ID>` | ❌ **移除黑名单** | `/dbl 123456789` |
| `/vlist wl` | 📋 **查看白名单** | 列出所有白名单用户 |
| `/vlist bl` | 📋 **查看黑名单** | 列出所有黑名单用户 |

-----

## ⚙️ 进阶机制说明

### 反垃圾系统 (Anti-Spam)

机器人会在三个层面拦截垃圾广告：

1.  **昵称检测**：如果用户的名字、姓氏或用户名包含违禁词（如“出U”、“跑分”），直接秒封。
2.  **内容检测**：用户发送的消息如果包含违禁词，直接秒封。
3.  **编辑检测**：即使用户先发正常消息，后来编辑成广告，机器人也能检测到并封禁，同时删除该消息。

*违禁词库每 1 小时自动从 `REMOTE_SPAM_URL` 更新一次。*

### 防刷屏 (Flood Control)

  * 如果用户在 10 秒内发送超过 6 条消息，会被判定为刷屏。
  * **惩罚**：自动禁言 15 分钟。

### 数据库自动维护

  * 数据库文件 (`.db`) 如果超过 10MB，系统会自动执行压缩 (`VACUUM`)。
  * 超过 1000 条的历史消息映射记录会自动滚动删除，防止数据库过大。
  * 超过 7 天的历史记录会自动清理。

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



