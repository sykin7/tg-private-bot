# nicechat-bot (安全加固版)

部署在 Cloudflare Workers 上的 Telegram 个人双向聊天机器人。这是 [TyrEamon/nicechat-bot](https://github.com/TyrEamon/nicechat-bot) 的安全加固 fork，**100% 保留 Cloudflare 原生架构**（Workers + KV + Workers AI），通过纯代码层修复堵住原版的全部 Critical / High / Medium / Low 级问题。

## 改造原则

- ✅ **不脱离 Cloudflare 生态**：仍然是 Workers + KV + Workers AI 三件套
- ✅ **零额外服务**：不引入 Redis / PostgreSQL / VPS
- ✅ **免费层可用**：所有修复都在 Workers 免费套餐内可运行
- ✅ **代码层修复为主**：利用 KV list 操作实现近似原子计数，规避最终一致性竞态

## 📖 部署文档

| 你的情况 | 看哪份文档 |
|---------|----------|
| **完全小白，想用大白话看懂** | [DEPLOY-EASY.md](./DEPLOY-EASY.md) ⭐⭐⭐ 最推荐 |
| **不想装软件，全程网页操作** | [DEPLOY-WEB.md](./DEPLOY-WEB.md) |
| 熟悉命令行，想用 wrangler | [DEPLOY.md](./DEPLOY.md) |

### 关于部署方式的说明

这个项目是 **Cloudflare Workers** 项目（不是 Pages），所以：

- ❌ **不能**像 Pages 那样直接上传 ZIP 文件（Workers 需要构建，Pages 是静态文件）
- ✅ **最简单**：把代码传到 GitHub → Cloudflare 连接仓库 → 在网页上填密钥 → 完成
- ✅ **也可以**用 wrangler 命令行部署

**为什么还要注册 webhook？** 这是 Telegram 的规则——任何 Telegram bot 都要告诉 Telegram"消息往哪发"。这一步就一次操作，复制一条命令的事，不是 Cloudflare 的额外要求。

**最简单的方式**：看 [DEPLOY-EASY.md](./DEPLOY-EASY.md)，大白话讲解，20-30 分钟搞定。

快速部署（如果你已熟悉 Cloudflare）：

```bash
# 1. 解压项目，进入目录
cd nicechat-fixed

# 2. 安装依赖
npm install

# 3. 登录 Cloudflare
npx wrangler login

# 4. 创建 KV namespace，把输出的 id 填入 wrangler.jsonc
npm run kv:create

# 5. 设置所有 secrets（交互式）
npm run secret:setup
#   或手动:
#   wrangler secret put BOT_TOKEN
#   wrangler secret put BOT_SECRET
#   wrangler secret put ADMIN_UID
#   wrangler secret put AI_BASE_URL
#   wrangler secret put AI_API_KEY

# 6. 部署
npm run deploy

# 7. 注册 webhook（替换 WORKER_URL 和 BOT_SECRET）
curl -X POST -H "x-bot-secret: BOT_SECRET" https://WORKER_URL/registerWebhook

# 8. 设置命令菜单
curl -X POST -H "x-bot-secret: BOT_SECRET" https://WORKER_URL/setcommands
```

## 修复清单

详见 [CHANGES.md](./CHANGES.md)。摘要：

| 轮次 | 修复数 | 关键修复 |
|------|--------|---------|
| v0.2 第一轮 | 37 | 凭据泄露 / 验证码暴力 / 提示注入 / IDOR / 媒体绕过 |
| v0.3 第二轮 | 38 | /start 死循环 / 群聊锁 / 并发竞态 / 可观测性 |
| v0.4 第三轮 | 20 | CF 免费层适配 / 超时编排 / 转义边界 |
| v0.5 第四轮 | 8 | 爆破防护 / 全消息类型转发 |
| v0.6 第五轮 | 8 | 验证绕过 bug / 答案规范化 / AI 防护 |
| v0.7 第六轮 | 5 | hitRate scope / clearViolations 循环 / 草稿 try/catch |
| v0.8 第七轮 | 6 | 命令覆盖 / @bot 后缀 / 模糊测试 |
| v0.8 第八轮 | 3 | ack try/catch / 草稿顺序 / 锁泄漏 |
| v0.10 第九轮 | 2 | KV 写失败容错 / 缓存写非致命 |
| **合计** | **127** | — |

## 部署步骤

**完整详细步骤请看 [DEPLOY.md](./DEPLOY.md)**。上面已经给出快速版。

## 本地开发

详见 [DEPLOY.md 附录 D](./DEPLOY.md#附录-d本地开发)。

```bash
cp .dev.vars.example .dev.vars
# 编辑 .dev.vars 填入测试值
npm run dev
```

注意：本地开发时 `BYPASS_TG_ASN_CHECK=1`，跳过 Telegram ASN 校验。

## 隐私与安全

### 凭据保护
- 所有敏感信息（BOT_TOKEN / BOT_SECRET / ADMIN_UID / AI_BASE_URL / AI_API_KEY / SEARCH_API_KEY）都通过 `wrangler secret` 设置，不会写入仓库
- `wrangler.jsonc` 里只有非敏感配置变量

### 用户隐私保护
- 用户消息发送给 AI 中转站前会被截断（≤ 1000 字）
- 拦截记录入库前会脱敏（手机号、邮箱、身份证号、API key、银行卡号）
- 申诉内容通知管理员时也会脱敏
- 自动封禁通知不再附带用户原文

### 提示注入防御
- 代笔时把用户上下文标记为不可信 system message
- AI 输出层检测可疑内容（Telegram 链接、@用户名、加密货币关键词、转账请求等）
- 命中可疑检测时，草稿仍生成但会向管理员发出警告

### 访问控制
- 管理端点必须 POST + `x-bot-secret` header（不再支持 GET query）
- Webhook 校验使用 `X-Telegram-Bot-Api-Secret-Token` header + 常数时间比较
- 可选：通过 `request.cf.asn === 62041` 验证请求来自 Telegram 网络
- `/to <uid>` 命令限制只能发给已知用户（防 IDOR）

### 审计日志
- 所有管理操作（ban / unban / model 切换 / to 发送 / 草稿发送）都记录到 KV
- 用 `/audit` 命令查看最近 100 条审计记录
- 日志保留 90 天

## 已知局限

由于坚持纯 Cloudflare 免费层，以下问题只能做到"近似正确"：

| 局限 | 当前方案 | 残余风险 |
|------|---------|---------|
| KV 最终一致 → 限流并发 | list-based 令牌计数 | 高并发下偶发多 1-2 条通过 |
| KV 最终一致 → 违规计数 | list-based 令牌计数 | 并发拦截可能多算 1-2 次 |
| KV 最终一致 → update 去重 | 600s TTL KV key | 多区域极端情况下可能重复处理 |
| KV 最终一致 → 群聊锁 | list-based 令牌锁 + try/finally | 极端情况下锁可能短暂失效 |

如果未来流量上升需要强一致，可升级 Workers Paid（$5/月）+ Durable Objects，**仍在 Cloudflare 生态内**。

## 管理命令

仅 `ADMIN_UID` 可用：

| 命令 | 说明 |
|------|------|
| reply 用户消息 + 普通文本 | 直接回复该用户 |
| reply 用户消息 + `/ai <意向>` | 生成代笔草稿，可确认回复/重新生成/自行回复 |
| `/ai <问题>` | 与私人助理对话 |
| `/aimode on` / `/aimode off` | 开启/关闭 AI 模式 |
| `/model` | 查看当前模型 |
| `/model list` | 查询中转站可用模型 |
| `/model <模型名>` | 切换当前模型（只允许字母数字点横杠斜杠冒号，长度 ≤ 100） |
| `/model default` | 恢复默认模型 |
| `/to <uid> <内容>` | 主动给指定用户发消息（仅限已知用户） |
| `/intercepts [数量]` | 查看最近拦截记录（最多 50 条） |
| `/audit [数量]` | 查看管理员审计日志（最多 100 条） |
| `/ban <uid>` | 手动封禁用户；也可 reply 后 `/ban` |
| `/unban <uid>` | 解封用户并清空违规/申诉次数 |
| `/forgive <uid>` | 清空用户误伤/违规计数 |

被封禁用户可发送：

```
/appeal <申诉说明>
```

## 许可

继承原仓库许可。
