
# 🤖 Telegram 私聊转发与防骚扰机器人 (PM Forwarder Bot)

> **版本**: V16.4 Complete Edition
> **语言**: Python 3
> **依赖**: pyTelegramBotAPI, requests

这是一个高效、稳定的 Telegram 机器人，用于将用户发送给机器人的私聊消息自动转发给管理员。它不仅支持双向回复，还内置了强大的**垃圾广告过滤系统 (Anti-Spam)** 和 **防刷屏机制 (Anti-Flood)**。

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## ✨ 功能特性

*   **📨 双向转发**：
    *   **用户 -> 管理员**：转发文本、照片、视频、文档、语音、贴纸、**GIF 动图**等。
    *   **管理员 -> 用户**：管理员只需**回复**转发过来的消息，即可匿名回复用户。
*   **🛡️ 智能防骚扰 (Anti-Spam)**：
    *   **本地词库**：内置常见黑产、博彩、诈骗关键词。
    *   **云端更新**：每小时自动同步远程垃圾词库（GitHub 源），无需重启。
    *   **静默拦截**：检测到违规词直接丢弃，不给对方任何反馈，防止被探测。
*   **🌊 防刷屏控制**：
    *   限制每个用户在短时间内的发送频率（默认 10秒内最多5条），防止恶意轰炸。
*   **🦾 健壮性设计**：
    *   **多线程更新**：规则更新不阻塞主线程。
    *   **异常捕获**：防止因单个消息格式错误导致机器人崩溃。
    *   **未知类型兜底**：遇到无法解析的消息类型会通知管理员，防止漏单。

## 🛠️ 部署指南

### 1. 准备工作

*   一个 Telegram Bot Token (通过 [@BotFather](https://t.me/BotFather) 获取)。
*   你的 Telegram User ID (通过 [@userinfobot](https://t.me/userinfobot) 获取)。
*   Python 3.8 或以上环境。

### 2. 安装依赖

请注意，本脚本使用的是 `pyTelegramBotAPI`，**请勿**安装名为 `telebot` 的旧包。

```bash
pip install pyTelegramBotAPI requests
````

### 3\. 环境变量配置 (Environment Variables)

本项目完全通过环境变量配置，方便在 VPS、Docker 或 PaaS 平台（如 Zeabur, Railway, Heroku）上部署。

| 变量名 | 必填 | 默认值 | 说明 |
| :--- | :---: | :--- | :--- |
| `BOT_TOKEN` | ✅ | 无 | 你的 Telegram 机器人 Token |
| `ADMIN_ID/OWNER_ID` | ✅ | 无 | 管理员的数字 ID (例如 `123456789`) |
| `REMOTE_SPAM_URL` | ❌ | (内置 GitHub URL) | 自定义远程垃圾词库的 URL (Raw Text 格式) |
| `CUSTOM_SPAM_KEYWORDS` | ❌ | 无 | 额外的自定义拦截词，用英文逗号 `,` 分隔 |

### 4\. 运行机器人

#### 方式 A: 直接运行 (Linux/Windows/Mac)

```bash
# 设置环境变量 (Linux/Mac 示例)
export BOT_TOKEN="你的_TOKEN"
export ADMIN_ID="你的_ID"

# 启动脚本
python bot.py
```

#### 方式 B: 使用 Docker (推荐)

如果你有 Docker 环境，可以使用以下 `Dockerfile` 构建：

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir pyTelegramBotAPI requests

CMD ["python", "bot.py"]
```

构建并运行：

```bash
docker build -t pm-bot .
docker run -d \
  --name pm-bot \
  -e BOT_TOKEN="你的_TOKEN" \
  -e ADMIN_ID="你的_ID" \
  --restart unless-stopped \
  pm-bot
```

## 📝 使用说明

### 对于普通用户

直接给机器人发送消息即可。支持文字、图片、视频、文件、表情包等。

### 对于管理员

1.  **接收消息**：你会收到格式如下的消息：

    > 消息内容...

    > 

    > -----

    > 👤 Username | 🆔 ID: 123456789

2.  **回复消息**：

      * 直接**回复 (Reply)** 这条消息，你的回复内容会被机器人发送给该用户。
      * ⚠️ **注意**：如果用户发来的是**贴纸 (Sticker)**，你会收到一张贴纸和一条带 ID 的文字提示。**请回复那条带 ID 的文字消息**，回复贴纸本身会导致发送失败。

## 🧩 垃圾词库说明

机器人启动时会加载内置关键词，并启动一个后台线程。

  * **更新频率**：每 3600 秒（1小时）自动拉取一次远程 URL。
  * **扩展词库**：你可以 Fork 默认的词库仓库，修改 `REMOTE_SPAM_URL` 变量指向你自己的 `raw` 地址，实现个性化过滤。

## ⚠️ 免责声明

本项目仅供学习和技术研究使用。请勿用于发送垃圾邮件或进行骚扰。使用者需遵守 Telegram 服务条款及当地法律法规。

````

***

### 💡 额外建议：创建 `requirements.txt`

为了让别人（或你自己以后）能更方便地安装依赖，建议你在代码同级目录下创建一个 `requirements.txt` 文件，内容如下：

```text
pyTelegramBotAPI
requests
````
