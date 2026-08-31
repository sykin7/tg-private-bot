# Development Log

## 2026-08-31（群内广告分级：首次删消息+警告，再犯永久封）

### 改动范围

- `new.py`：新增 `GROUP_SPAM_WARN_LIMIT`（默认 1），新增 `should_ban_group_spam` / `get_group_spam_warn_count` / `clear_group_spam_warn` 三个函数，用 `_group_spam_warn_lock` 保护内存计数。
- 群内命中广告后：强特征词（U币等）任何时候直接永久封；普通广告首次删消息+警告，达到 `GROUP_SPAM_WARN_LIMIT` 再永久封。封禁成功后立即清除计数，避免内存堆积。
- `.env.example`：补充 `GROUP_SPAM_WARN_LIMIT=1` 及注释。

### 验证证据

- `python -m unittest tests.test_core tests.test_rule_sync`：87 tests OK。
- `new.py` 语法解析通过。

### 当前状态

- 已完成代码改动与验证，未提交。等 Boss 确认后 push 到 v2 分支触发镜像重建。

### 回滚点

- 本次改动集中在 `new.py` 群内广告封禁段落与 `.env.example`，回滚可直接还原这两个文件的对应段落。

## 2026-08-31（灰色地带交 AI 裁决，单关键词不再直接封）

### 改动范围

- `spam_risk_score`：触达信号（URL/@/电话/联系方式）各 +2，加密信号 +3；营销词按命中数 *2 封顶 6；远程规则命中仅在无营销词时补 +2，避免重复计分；收款/诱导/联系方式三类命中≥2 类再 +3；关键收敛点：只有单个营销词且既无联系方式也无加密信号时 -3，判为讨论不判广告。
- `ai_classifier.AI_MIN_SCORE` 默认 5 改 3：本地拿不准的灰色分段（达到 3 但不到封禁门槛 6）自动交 AI 裁决，不再本地硬判。
- `.env.example`：补充 `AI_MIN_SCORE` 注释，说明它是「本地拿不准就问 AI」的门槛。

### 判定分层（内容默认阈值）

- 风险分 >= 6：直接封。
- 3 <= 风险分 < 6：交 AI 裁决（AI 关闭时放行，避免误封）。
- 风险分 < 3：直接放行。
- 强特征词（U 币等）任何时候即时封，不进分段。

### 验证证据

- `python -m unittest tests.test_core tests.test_rule_sync`：87 tests OK。
- 边界样本：单关键词无联系方式「请问有兼职吗」分 0 放行；带充值/单词带链接分 3-4 交 AI；兼职刷单加微信、博彩返佣等多信号分 9-11 直接封。

### 当前状态

- 已完成代码改动与验证，未提交。等 Boss 确认后 push 到 v2。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831-211817-scorefix`

## 2026-08-31（广告加权评分治本降误封）

### 改动范围

- `new.py`：远程/学习/兜底规则命中从「一票即封」改为加权。拆出 `keyword_rule_hit`（纯命中判定），`is_spam_text` 保留强特征词即封 + 规则命中（用户名/文件名等短文本入口）。
- `spam_risk_score`：规则命中 +4 分；新增组合重罚（收款/诱导/联系方式三类信号命中≥2 类再 +3）；新增负权重（纯提问寒暄且无广告组合信号且无链接时 -3），分数下限 0。
- `classify_spam_text`：强特征词即时封，其余走风险分阈值 `SPAM_BLOCK_SCORE`（默认 6），不再让 8000+ 远程规则子串命中直接封。
- 阈值全部做成 `.env` 变量：`SPAM_BLOCK_SCORE`（内容判定门槛，默认 6）、`SPAM_PROFILE_BLOCK_SCORE`（资料/用户名/文件名门槛，默认 5，替换原写死的 5）。
- 新增 `MONEY_RE`/`LURE_RE`/`HAM_RE` 三个信号正则，仅供加权对冲使用。
- 未新增任何数据库表，学习通道与群/私聊/入群逻辑完全复用，未改行为契约。

### 验证证据

- `python -m unittest tests.test_core tests.test_rule_sync`：87 tests OK。
- 手工样本核验：正常提问/闲聊/带链接提问均判 False（分 0-3），U币硬广走强特征即封，兼职刷单/博彩/引流带联系方式均判 True（分 15-16）。

### 当前状态

- 已完成代码改动与验证，未提交。等 Boss 确认后 push 到 v2 分支触发镜像重建。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831-211817-scorefix`

## 2026-08-31（新镜像名与 v2 分支统一）

### 改动范围

- 镜像统一为 `ghcr.io/sykin7/spamguard-bot:latest`，替换 workflow、compose、README、VPS-DEPLOYMENT 中所有旧镜像名。
- GitHub Actions 触发分支从 `codex` 改为 `v2`。

### 验证证据

- `rg` 扫描确认项目内不再存在旧镜像名。
- `python -m unittest discover -s tests` 全量测试通过。

### 当前状态

- 待推送：在项目里创建 `v2` 分支并推送后，GitHub Actions 会自动构建 `ghcr.io/sykin7/spamguard-bot:latest`。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831-162553`

## 2026-08-31（GitHub 打包前审计）

### 改动范围

- `.github/workflows/docker-publish.yml`：`paths` 触发列表补上 `rule_sync.py`、`env_utils.py`，避免这两个文件改动后 GitHub Actions 不重建镜像。
- `new.py`：`/status` 和启动通知里的“入口脚本”改为动态显示 `os.path.basename(__file__)`，容器内正确显示 `bot.py`。

### 审计结果

- 全仓库扫描未发现真实 BOT_TOKEN、GitHub Token、AI Key、R2 Key 等硬编码密钥；`.gitignore` 已忽略 `.env`、数据库、data 目录。
- 密钥只走环境变量；AI、GitHub、R2 请求日志不打印密钥。
- 所有脚本和配置文件均为 LF 换行，VPS bash 可直接执行。
- R2 本地规则 SQLite、签名、额度守卫、多账户镜像逻辑经测试覆盖。
- `get_db_conn` 会自动创建数据库目录，启动时缺 BOT_TOKEN/ADMIN_ID 会直接退出，轮询崩溃后 5 秒自动重启。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py env_utils.py tests\test_core.py tests\test_rule_sync.py` 通过。
- `python -m unittest discover -s tests` 通过，86 个测试全部 OK。
- 本机无 Docker，镜像构建需在 GitHub Actions 推送后验证。

### 当前状态

- 项目可安全推送到 GitHub；推送前只需确认仓库根目录是 `codexbot-v2` 内容，分支为 `v2`（以最新条目为准）。

## 2026-08-31（移除 Redis/PostgreSQL，固定单容器 SQLite）

### 改动范围

- `new.py`：删除 Redis 连接、限流、状态上报和所有 Redis 调用，内存回退成为唯一实现；删除 PostgreSQL 分支和迁移函数，`get_db_conn`/`db_execute` 只保留 SQLite。
- `new.py`：删除死代码 `check_deep_spam`、`spam_regex_pattern`，抽出 `classify_spam_text` 供消息分析和解释复用；抽出 `_load_and_apply_remote_rules`，规则刷新共用一套拉取合并逻辑。
- `ai_classifier.py`、`rule_sync.py`：删除各自重复的环境变量解析，统一从 `env_utils.py` 导入 `env_bool/env_int/env_float`。
- `deploy.sh`、`docker-compose.bot-lite.yml`、`Dockerfile`、`requirements.txt`：默认使用轻量单容器 compose，补充 `build`、`env_file: .env`，删除 redis/psycopg 依赖和 `POSTGRES_PASSWORD` 校验。
- `.env.example`、`README.md`、`VPS-DEPLOYMENT.md`：删除 Redis/PostgreSQL 配置说明，`/status` 文案改为 SQLite。
- `tests\test_core.py`：删除已不再读取的 `REDIS_ENABLED` 测试环境变量。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py env_utils.py` 通过。
- `python -m unittest discover -s tests` 通过，86 个测试全部 OK。

### 当前状态

- 单容器 + SQLite，无 Redis/PostgreSQL 进程，适配 1C1G VPS；R2、第三方 AI、群聊管理、规则学习功能保留。
- `docker-compose.bot.yml` 保留作历史参考，不再维护。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831-143916`（本次清理前完整备份）

## 2026-08-31（群聊与私聊规则去重和冲突修复）

### 改动范围

- `new.py`：新增 `analyze_spam_message`，一次完成关键词、风险分、用户资料、文件名和 AI 判定，私聊与群聊共用，每条消息只判定一次。
- `new.py`：私聊临时封禁检查移到白名单判断之外，白名单用户处于 `ban_until` 封禁期内同样忽略消息；私聊编辑消息也补上临时封禁检查。
- `new.py`：私聊广告拦截复用已算好的判定结果，不再二次调 AI；群消息处理抽出 `process_group_spam_message`，通知直接使用判定原因和风险分。
- `new.py`：新增群内编辑消息广告检测，编辑成广告会删除消息、永久封禁并通知管理员；普通编辑不动作。
- `new.py`：群内广告封禁由 3 小时限时改为不带时间的永久封禁，与入群拒绝一致。
- `new.py`：入群审核按钮改为幂等，申请已被自动处理时重复点击只提示“已处理”。
- `analyze_spam_message` 关键词命中分支和风险分计算加异常保护，单点失败不影响整体判定。
- 测试：`GroupAndPrivateRulesTest` 覆盖白名单临时封禁、私聊只判定一次、群消息只判定一次、群编辑广告/正常消息、入群按钮幂等、私聊编辑临时封禁。
- 文档：README、VPS-DEPLOYMENT 同步上述行为。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py tests\test_core.py tests\test_rule_sync.py` 通过。
- `python -m unittest discover -s tests` 通过，86 个测试全部 OK。

### 当前状态

- 群聊与私聊的广告判定共用同一入口，无重复 AI 调用；入群拒绝只做该群 Telegram 封禁，不写全局黑名单，被拒用户仍可私聊申诉。
- 群内广告与入群拒绝都用 `ban_chat_member` 不带时间，是永久群封禁；私聊仍是 `MAX_BAN_DURATION` 临时封禁。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831134644`（本组代码改动前）
- `D:\CodexProjects\codexbot\codex-config-backup-20260831135347`（本组文档改动前）
- `D:\CodexProjects\codexbot\codex-config-backup-20260831140238`（群内广告改永久封禁前）

## 2026-08-31（入群拉黑与私聊申诉通道分离）

### 改动范围

- `new.py`：`reject_spam_join` 不再写入全局黑名单，只拒绝申请并在该群 Telegram 封禁；被拒用户仍可私聊机器人申诉。
- `new.py`：拒绝入群时向用户发送申诉提示，说明可直接私聊机器人，内容会先经过广告检测再转给管理员。
- 测试：更新 `reject_spam_join` 测试，断言拒绝、群封禁、申诉提示发送，且不再写全局黑名单。
- 文档：README、VPS-DEPLOYMENT、`.env.example` 同步说明入群封禁不阻断私聊申诉。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py tests\test_core.py tests\test_rule_sync.py` 通过。
- `python -m unittest discover -s tests` 通过，测试全部 OK。

### 当前状态

- 群拉黑只影响该群入群与群内；私聊仍走广告检测、频率检查和验证。管理员手动 `/abl` 仍可彻底封禁私聊。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831143000`

## 2026-08-31（入群前关注频道校验）

### 改动范围

- `new.py`：新增 `GROUP_JOIN_REQUIRED_CHANNEL` 环境变量，填 `@username` 或数字频道 ID 即启用，留空关闭。
- `new.py`：新增 `user_follows_required_channel`，通过 `get_chat_member` 校验用户是否已关注频道，60 秒小缓存。
- `new.py`：入群申请先做频道关注校验，未关注的申请直接拒绝并私聊提示，关注后重新申请才进入规则判定、人工审核或自动通过。
- 测试：新增未配置放行、已关注放行、未关注拦截、申请流程先校验频道的测试。
- 文档：`.env.example`、README、VPS-DEPLOYMENT 补充频道变量和 bot 需要加入频道的说明。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py tests\test_core.py tests\test_rule_sync.py` 通过。
- `python -m unittest discover -s tests` 通过，测试全部 OK。

### 当前状态

- 频道关注校验默认关闭；配置变量后生效，不影响现有自动审核流程。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831130035`（关注频道校验改动前备份）

## 2026-08-31（入群审核超时自动兜底）

### 改动范围

- `new.py`：新增 `GROUP_JOIN_REVIEW_TIMEOUT`（默认 600 秒），人工审核模式（`GROUP_AUTO_APPROVE=false`）下管理员超时未处理时按规则自动兜底。
- `new.py`：广告判定入群申请自动拒绝并拉黑：先拒绝申请，再 Telegram 封禁防止再次加入，并写入本地黑名单。
- `new.py`：新增 pending 记录和后台检查线程，超时后广告判定自动拒绝并拉黑，正常判定自动通过；管理员手动处理后立即移除 pending，避免重复操作。
- `new.py`：超时自动处理后编辑群聊通知消息，避免管理员再点已失效按钮。
- 测试：新增拒绝广告申请、pending 记录/移除、超时按规则处理测试。
- 文档：`.env.example`、README、VPS-DEPLOYMENT 补充超时兜底配置和行为说明。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py tests\test_core.py tests\test_rule_sync.py` 通过。
- `python -m unittest discover -s tests` 通过，测试全部 OK。

### 当前状态

- 默认自动通过模式行为不变；人工审核模式具备管理员超时自动兜底。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831130035`（入群审核超时兜底改动前备份）

## 2026-08-31（群原生管理员参与入群审核）

### 改动范围

- `new.py`：新增 `can_manage_group(user_id, chat_id)`，静态 `GROUP_ADMIN_IDS` 优先，再通过 `get_chat_administrators` 识别 Telegram 群原生管理员，60 秒 TTL 小缓存，API 失败时回退静态管理员。
- `new.py`：入群审核按钮先解析 `chat_id` 再校验权限，群原生管理员可处理本群入群申请，普通成员仍无权操作。
- `new.py`：入群申请审核通知同步发送到对应群聊，让群原生管理员可直接点击；你设置的管理员仍私聊收到。
- `new.py`：群内消息跳过静态管理员和当前群原生管理员，避免误删误封管理员消息。
- 测试：`StubTeleBot` 增加 `get_chat_administrators`，新增静态管理员、群原生管理员、普通成员和 API 失败回退测试。
- 文档：`.env.example`、README、VPS-DEPLOYMENT 说明群原生管理员自动识别，仅限本群入群审核，全局规则仍归你设置的管理员。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py tests\test_core.py tests\test_rule_sync.py` 通过。
- `python -m unittest discover -s tests` 通过，测试全部 OK。

### 当前状态

- 群原生管理员可参与本群入群审核，不开放学习规则、黑名单、GitHub / R2 同步等全局操作。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831130035`（群原生管理员改动前备份）

## 2026-08-31（AI 多协议通用接口）

### 改动范围

- `ai_classifier.py`：新增 `AI_PROVIDER`，支持 `openai-compatible`、`anthropic`、`gemini` 三种协议，自动切换请求地址、鉴权头、payload 和响应解析；默认仍为 `openai-compatible`，现有行为不变。
- `ai_classifier.py`：新增 `AI_MAX_TOKENS`（默认 300），Anthropic Messages API 必填；Gemini 走 `generateContent`，使用 `x-goog-api-key` 鉴权。
- `ai_classifier.py`：新增可选 `AI_RESPONSE_FORMAT`，默认关闭，避免部分严格网关拒绝 `response_format` / `responseMimeType`。
- `ai_classifier.py`：关键词上限统一到 `AI_KEYWORDS_LIMIT`（默认 2000），`AI_MAX_KEYWORDS` 保留为兼容别名，不再被 80 条二次截断。
- `ai_classifier.py`：修复 `AI_ENABLED=false` 不生效的问题，模块级分类器现在真正遵循开关；直接实例化仍默认启用，不影响测试和二次开发。
- `new.py`：`/status` 显示当前 AI 协议，例如 `openai-compatible 已启用`。
- 文档：`.env.example`、README、VPS-DEPLOYMENT 补充三种协议的配置方式和示例。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py tests\test_core.py tests\test_rule_sync.py` 通过。
- `python -m unittest discover -s tests -v` 通过，68 个测试全部 OK。
- 新增测试覆盖 OpenAI 兼容、Anthropic、Gemini 的请求地址、鉴权头、payload、响应解析，以及关键词上限、未知协议禁用和 `AI_ENABLED` 开关。

### 当前状态

- 三类主流第三方模型接口已接入：OpenAI 兼容网关、Anthropic Claude、Google Gemini。
- 未实际连接真实模型 API 和 Telegram，网络相关行为仍以单元测试 stub 验证。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831123521`（AI 多协议通用接口版备份）

## 2026-08-31（R2 复查修复）

### 改动范围

- `rule_sync.py`：`sync_r2_mirrors` 镜像同步跳过刚拉取过的源账户，避免对源账户重复 PUT，减少 Class A 消耗。
- `rule_sync.py`：`r2_merge_and_write` 和 `sync_r2_mirrors` 只在账户写入成功后清除该账户的恢复标记，避免恢复后每轮同步都重复强制推送。
- `tests/test_rule_sync.py`：镜像同步预期从 2 次 PUT 改为 1 次；恢复清除断言改为验证实际写入的账户。

### 验证证据

- `python -m unittest discover -s tests -p "test_rule_sync.py"` 通过，36 个测试全部 OK。

### 当前状态

- R2 默认配额（Class A 90 万/月、Class B 900 万/月）、9GB 写入硬上限、多账户切换、每 3 小时同步均确认正常。
- 未实际连接真实 R2 和 Telegram，网络相关行为仍以单元测试 stub 验证。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831123000`

## 2026-08-31（R2 每3小时同步 + 9GB 硬上限确认）

### 改动范围

- `R2_FETCH_INTERVAL`、`R2_MIRROR_INTERVAL`、`R2_SYNC_INTERVAL` 默认值从 `86400` 改为 `10800`（每3小时一次）。
- 每个 R2 账户每3小时最多 8 次拉取、最多 8 次学习规则写入、最多 8 次镜像写入；即使配置 20 个账户，每月请求量也在免费额度的 90% 护栏内。
- R2 同步始终 PUT 覆盖写同一个 `RULE_SYNC_R2_KEY` 对象，本地 SQLite 去重，不产生冗余对象，不会越写越臃肿。
- 存储护栏确认：默认 `R2_MAX_STORAGE_GB=10`、`R2_STORAGE_WARN_RATIO=0.9`，按十进制字节计算，即 9,000,000,000 字节（9 GB）硬上限；PUT 前先检查规则文本体积，超过就直接拒绝写入并提醒管理员。

### 验证证据

- `python -m unittest discover -v` 通过，60 个测试全部 OK。
- `python -m py_compile new.py ai_classifier.py rule_sync.py tests\test_core.py tests\test_rule_sync.py` 通过。

### 当前状态

- 默认 R2 闭环为每3小时拉取、写入、镜像一次；日常消息判定仍只读本地 SQLite，不访问 R2。
- 未实际连接真实 R2 和 Telegram，网络相关行为仍以单元测试 stub 验证。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831121218`（R2 每3小时同步 + 9GB 硬上限确认版备份）

## 2026-08-31

### 改动范围

- 在副本 `codexbot-v2` 中接入第三方 AI 广告复核模块 `ai_classifier.py`。
- 新增群聊管理：入群申请审核、管理员按钮通过/拒绝、群内广告删除与临时封禁。
- 新增规则学习：拦截通知带“学习规则 / 不学习”按钮，管理员确认后把广告特征写入本地 `spam_feedback` 表并立即生效。
- 新增 `rule_sync.py`：提取广告特征，可同步到指定 GitHub 仓库文件或 Cloudflare R2，并支持从 R2 拉回规则参与判断。
- 修复 `parse_id_list` 不识别 Telegram 负群 ID 的问题。
- 清理裸 `except`，改为捕获具体异常。
- `db_save_map` 清理 SQL 参数化。
- 更新 Dockerfile、compose、`.env.example`、README、VPS-DEPLOYMENT.md。
- 新增 `tests/test_core.py`、`tests/test_rule_sync.py`，覆盖 AI 解析、群聊开关、入群判定、反馈学习、GitHub/R2 同步。
- 广告学习反馈改为 SQLite 轻量存储，几十万条规则不会让纯文本规则文件膨胀。
- 新增自动学习：同一广告特征重复命中 `RULE_AUTO_LEARN_THRESHOLD` 次后自动确认并生效，管理员按钮仍可手动确认或忽略。
- 学习特征分批编译、精确匹配集合限流，`RULE_LEARNED_MEMORY_LIMIT` 控制低内存 VPS 占用。
- R2 免费层默认只使用 90% 配额（Class A 90 万、Class B 900 万），429/503 后冷却 1 小时，拉取失败回退缓存，限流期间本地判定和 GitHub 同步不受影响。
- R2 触顶或 429/503 限流时向管理员发送一次提醒，同一自然月只提醒一次，次月 UTC 自然月自动恢复。
- 新增多 R2 账户自动切换：支持 `_2` 到 `_20` 后缀配置，请求前检查该账户额度，触顶或限流后记录恢复时间并自动切到下一个可用账户。
- 新增 `sync_r2_mirrors`：多 R2 账户按 `R2_MIRROR_INTERVAL` 定时镜像同步，任一账户恢复后立即补同步并解除暂停；主程序已启动镜像同步后台线程。
- R2 限流提醒带上账户编号和预计恢复时间，同一自然月每个账户只提醒一次。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py tests\test_core.py tests\test_rule_sync.py` 通过。
- `python -m unittest discover -v` 通过，51 个测试全部 OK。

### 当前状态

- 代码与配置完成，未实际启动机器人（无 BOT_TOKEN、无网络环境）。
- AI 不可用或未配置时回退本地规则，不阻塞机器人运行。
- 原目录 `tg-private-bot-codex` 与 zip 未改动。
- R2 用量计数和限流状态持久化到 `R2_USAGE_PATH`，重启后继续生效。
- R2 配额触顶和限流提醒已接入主程序，`ADMIN_ID` 可收到通知。
- 多 R2 自动切换、镜像同步和恢复补同步已接入主程序，未实际启动机器人（无 BOT_TOKEN、无网络环境）。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831084924`（AI/群管基础版）
- `D:\CodexProjects\codexbot\codex-config-backup-20260831094912`（规则学习与同步收尾版）
- `D:\CodexProjects\codexbot\codex-config-backup-20260831095404`（R2 拉取闭环版）
- `D:\CodexProjects\codexbot\codex-config-backup-20260831101116`（R2 配额半成品版）
- `D:\CodexProjects\codexbot\codex-config-backup-20260831101825`（SQLite 自动学习与 R2 限流收尾版）
- `D:\CodexProjects\codexbot\codex-config-backup-20260831110809`（多 R2 自动切换与镜像同步版）

## 2026-08-31（补充：本地优先 R2 规则同步）

### 改动范围

- 新增 `LocalRuleStore`：把 R2 规则镜像进本地 SQLite（`R2_LOCAL_RULES_PATH`，默认复用 `R2_USAGE_PATH`），按规则文本去重、分类并累计命中次数。
- 日常判定和学习只读本地，不再每次请求 R2；首次拉取、每日刷新和每日镜像才访问 R2。
- `R2_FETCH_INTERVAL` 默认改为 `86400`（每天一次），`R2_MIRROR_INTERVAL` 默认改为 `86400`（每天一次）。
- 新增 `R2_MAX_STORAGE_GB`（默认 10）和 `R2_STORAGE_WARN_RATIO`（默认 0.9）：本地规则文本预计达到免费存储 90% 时暂停向该 R2 写入并提醒管理员。
- `r2_merge_and_write` 和 `sync_r2_mirrors` 改为优先用本地去重后的规则文本写入，成功后再标记本地规则已同步。
- `R2UsageStore` 新增今日用量查询，`/status` 输出每日 Class A/B 用量、本地规则条数、待同步条数和本地 DB 大小。
- 修复 `LocalRuleStore(path='')` 不能进入纯内存模式的问题。

### 验证证据

- `python -m py_compile new.py ai_classifier.py rule_sync.py tests\test_core.py tests\test_rule_sync.py` 通过。
- `python -m unittest discover -v` 通过，55 个测试全部 OK。
- 临时 SQLite 实测：100 万条短规则（12-20 字节）约 68-95 MB，即 1000 万条约 683-948 MB，1 亿条约 6.8-9.5 GB，低于 10 GB 免费上限；实际体积含 WAL、索引和碎片，可用 `VACUUM` 压缩。

### 当前状态

- R2 已改为本地优先 + 每日同步，VPS 侧不因每条群消息访问 R2。
- 未实际连接真实 R2 和 Telegram，网络相关行为仍以单元测试 stub 验证。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831113000`（本地优先 R2 规则与每日同步版）

## 2026-08-31（R2 写入每日节流修复）

### 改动范围

- 新增 `R2_SYNC_INTERVAL`（默认 `86400`）：学习规则写入 R2 改为每天最多一次。学习确认后规则先立即写入本地 SQLite 生效并保留待同步状态，到点才统一推送 R2，避免每小时刷新循环对 R2 产生额外 PUT。
- `r2_merge_and_write` 在每日节流窗口内只写本地、不调用 R2；任一 R2 账户恢复后立即打破节流补写，符合“解除限制第一时间同步”的要求。
- `sync_r2_mirrors` 成功镜像后也记录 `last_sync_at`，与学习推送共用每日节流，避免同一天重复写 R2。
- 修复首次拉取失败且无远程基础规则时可能用“仅新学习规则”覆盖 R2 原对象的问题：此时保留本地待同步状态并跳过 R2 写入，下一周期重试。
- `last_sync_at` 持久化到 `r2_meta`，机器人重启后节流状态不丢失。
- `.env.example`、README、VPS-DEPLOYMENT 补充 `R2_SYNC_INTERVAL` 说明，闭环描述与实际行为一致。

### 验证证据

- `python -m unittest discover -v` 通过，59 个测试全部 OK。
- 新增测试覆盖：每日节流内不请求 R2、超过间隔后写入、账户恢复后立即写入、无远程基础时保留 pending 且不覆盖远程对象。

### 当前状态

- R2 拉取和写入均为每日一次，日常判定和学习不访问 R2；失败样本保留 pending 并每小时重试。
- 未实际连接真实 R2 和 Telegram，网络相关行为仍以单元测试 stub 验证。

### 回滚点

- `D:\CodexProjects\codexbot\codex-config-backup-20260831115901`（R2 写入每日节流修复版备份）
