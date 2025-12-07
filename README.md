
# 🛡️ Telegram 私聊转发与主动防御机器人 (SQLite 增强版)

![Version](https://img.shields.io/badge/Version-V33.0%20SQLite%20Edition-red)
![Language](https://img.shields.io/badge/Language-Python%203-blue)
![Dependencies](https://img.shields.io/badge/Dependencies-pyTelegramBotAPI%2C%20requests-orange)
![Database](https://img.shields.io/badge/Database-SQLite3-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

这是一个面向高安全性需求的 Telegram 私聊转发机器人。相比普通转发机器人，它集成了 **SQLite 持久化存储**、**抗 OCR 验证码**、**中文数字混淆**以及**自动反垃圾**机制，确保管理员只接收有效信息，并能进行精准的封禁管理。

## ✨ 核心功能亮点

*   **🔐 智能人机验证 (Advanced Captcha)**：
    *   **混合干扰**：算术题采用**中文数字**（如：壹、贰）与阿拉伯数字混合，并注入**不可见字符**（Zero-width space）防止 OCR 自动识别。
    *   **容错机制**：新用户有 **120秒** 时间和 **3次** 回答机会。
    *   **自动惩罚**：超时或错误次数耗尽，将随机封禁用户 10~60 分钟。
*   **💾 SQLite 持久化存储**：
    *   所有用户状态、验证记录、消息映射关系均存储在本地 `bot_core.db` 数据库中。
    *   **重启不丢失**：机器人重启后，已验证的用户无需再次验证，封禁状态依然有效。
*   **🔨 管理员控制**：
    *   通过**回复**转发的消息，可以快速封禁恶意骚扰者或直接回复用户。
*   **🛡️ 深度防骚扰 (Anti-Spam)**：
    *   **正则过滤**：自动忽略空格干扰（如检测到 `U 币` 等同于 `U币`）。
    *   **特殊字符处理**：自动进行 NFKC 标准化，防止利用特殊字体绕过检测。
    *   **动态更新**：每小时自动从 GitHub 或指定 URL 同步最新的垃圾广告关键词库。
*   **🌊 防洪泛控制 (Anti-Flood)**：
    *   默认限制：10秒内最多发送 5 条消息，违规暂停服务 60秒。

## 🛠️ 部署指南

### 1. 准备工作

*   Telegram Bot Token (通过 [@BotFather](https://t.me/BotFather) 获取)。
*   你的 User ID (通过 [@userinfobot](https://t.me/userinfobot) 获取)。
*   Python 3.8+ 环境。

### 2. 安装依赖

```bash
pip install pyTelegramBotAPI requests
````

### 3\. 环境变量配置 (Environment Variables)

| 变量名 | 必填 | 默认值 | 说明 |
| :--- | :---: | :--- | :--- |
| **`BOT_TOKEN`** | ✅ | 无 | 机器人的 Token |
| **`ADMIN_ID`** | ✅ | 无 | 管理员 ID (或使用 `OWNER_ID`) |
| `REMOTE_SPAM_URL` | ❌ | (内置 GitHub URL) | 远程垃圾词库地址 (Raw Text) |
| `BOT_DB_PATH` | ❌ | `/app/data/bot_core.db` | SQLite 数据库保存路径 |

### 4\. 运行机器人

```bash
# Linux/Mac 示例
export BOT_TOKEN="123456:ABC-DEF..."
export ADMIN_ID="123456789"
python bot.py
```

## 📝 使用说明 (管理员)

### 1\. 回复用户

收到用户的消息转发后，直接**回复 (Reply)** 该条消息，机器人会自动将你的回复内容发送给该用户。支持文本、图片、贴纸、视频、文件和语音。

### 2\. 管理命令

所有命令必须通过**回复 (Reply)** 某条用户发来的消息来触发：

| 命令 | 说明 | 效果 |
| :--- | :--- | :--- |
| **`/ban`** | 封禁该用户 | 用户将被封禁 **30天**，无法发送任何消息。 |
| **`/unban`** | 解封该用户 | 立即恢复用户的发送权限。 |

> **注意**：脚本中 `/ban` 默认为固定时长（30天），不支持自定义时间。

## ⚙️ 技术细节与维护

  * **消息映射清理**：
      * 数据库会自动清理 **7天前** 的消息映射记录，保持数据库轻量化。
  * **验证码逻辑**：
      * 题目示例：`🤖 人机验证：请计算：伍 加上 3 = ?`
      * 用户需回复纯数字（如 `8`）。
  * **并发安全**：
      * 采用了 `threading.Lock()` 和 SQLite WAL 模式，支持多线程并发处理消息，防止数据库锁死。

## ⚠️ 免责声明

本项目仅供技术研究与个人安全防护使用。请勿用于非法用途。

```
```
