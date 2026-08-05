# Telegram Topic Mini App 落地方案

## 1. 目的

本方案把 HermesPeek 在 Telegram 群组和 Forum Topic 中的 `Open preview` 按钮，从普通 HTTPS URL 改造为 Telegram Main Mini App Direct Link。目标链路为：

```text
Hermes 最终回复（同一条消息携带按钮）
        ↓
https://t.me/<bot_username>?startapp=<launch_ref>&mode=compact
        ↓
Telegram Mini App 容器
        ↓
服务端验证 Telegram.WebApp.initData
        ↓
短期 launch_ref 解析为 Preview
        ↓
验证 Preview owner 后显示文件
```

本文是阶段 7 的实施、测试、部署、现场验收和回滚依据。本文不授权修改真实 Hermes profile、Gateway 配置或重启 Gateway；这些操作必须在离线验收完成后另行获得项目负责人明确批准。

## 2. 当前状态与已验证前提

截至 2026-08-05：

- Telegram Bot 已配置 Main Mini App；
- Main Mini App 入口 `https://t.me/<bot_username>?startapp` 已由项目负责人在 Telegram 客户端实测成功；
- HermesPeek 已实现 Preview Registry、Telegram `initData` 签名验证、owner 鉴权、短期会话和受控文件读取；
- Hermes 已实现 `final_message_actions`，Telegram adapter 可在最终回复的新发送或原消息 edit 路径附加 URL 按钮；
- HermesPeek 插件已能收集本轮成功写入的文件并创建最终消息 action；
- 群组/Topic action 已改为 Main Mini App Direct Link，并使用短期 `launch_ref`；
- `/` 已从 `start_param` 进入服务端 launch auth，再跳转到受保护 Preview；
- 当前真实 Hermes profile 已完成受控插件与服务升级，Topic 核心链路已由项目负责人确认可用；完整真实安全场景仍待验收。

Mini App 仍是 Telegram 内的网页容器。它不会把 Preview 内容直接渲染进 Topic 消息正文；如需正文原生展示，必须另行发送文本、Markdown 或附件。

## 3. 决策

### 3.1 使用 Main Mini App Direct Link

群组和 Topic 使用已经现场验证的 Main Mini App 形式：

```text
https://t.me/<bot_username>?startapp=<launch_ref>&mode=compact
```

命名 Mini App 可使用：

```text
https://t.me/<bot_username>/<app_short_name>?startapp=<launch_ref>&mode=compact
```

首版不依赖 `app_short_name`。只有在 BotFather 中已明确配置并现场验证命名 Mini App 时，才启用该形式。Main Mini App 入口无需虚构 short name。

### 3.2 `startapp` 使用短期 opaque launch reference

`startapp` 不直接携带：

- 文件路径；
- Telegram user/chat/topic ID；
- Bot Token、Cookie 或 `initData`；
- 完整 Preview 能力型 URL；
- 可长期复用的授权信息。

服务端为一次 Preview 创建短期、不可猜测的 `launch_ref`，并保存：

```text
launch_ref -> preview_id, owner_telegram_user_id, created_at, expires_at, consumed/revoked state
```

`launch_ref` 只负责定位，不能替代 Telegram 身份认证。建议沿用高熵 URL-safe 随机值，限制长度和字符集，并使其有效期不超过对应 Preview。首版允许同一 owner 在有效期内重复打开，以兼容刷新和重新进入；Preview 撤销或过期时 reference 同步失效。

### 3.3 服务端以原始 `initData` 为信任边界

浏览器端的 `Telegram.WebApp.initDataUnsafe` 只能用于界面启动提示，不作为身份凭据。服务端必须：

1. 接收原始 `Telegram.WebApp.initData`；
2. 使用 Bot Token 验证 Telegram 签名；
3. 检查 `auth_date` 时效；
4. 从验证后的 `user.id` 获取身份；
5. 解析 `launch_ref`；
6. 比对 launch owner 与 Preview owner；
7. 创建短期、HttpOnly、Secure 会话；
8. 后续每次读取仍检查 Preview 是否存在、过期或撤销。

客户端提交的 user ID、owner ID、chat ID 或 `initDataUnsafe.user.id` 一律不可信。

### 3.4 私聊和 Topic 的入口策略

- 私聊：保留 Telegram `web_app` InlineKeyboard 按钮，URL 可指向 HermesPeek 启动页并携带受控 launch reference；
- 群组/Topic：使用 `url` InlineKeyboard 按钮，其值必须是 `t.me` Main Mini App Direct Link；
- `final_message_actions`：根据 Telegram chat metadata 选择私聊 `web_app` 或群组/Topic Direct Link；如果平台中立 action 无法表达该差异，应在 Hermes Telegram adapter 中增加经过验证的 Telegram Mini App action 类型，而不是让插件直接调用 Bot API；
- Topic 的 `message_thread_id` 继续由 Hermes 现有路由 metadata 处理，HermesPeek 不手工发送第二条消息。

## 4. 目标配置

新增配置前必须先写配置测试并更新无敏感值模板。建议字段：

```text
HERMES_PEEK_TELEGRAM_BOT_USERNAME=<bot_username>
HERMES_PEEK_TELEGRAM_MINI_APP_SHORT_NAME=
HERMES_PEEK_TELEGRAM_MINI_APP_MODE=compact
HERMES_PEEK_LAUNCH_REF_TTL_SECONDS=900
```

约束：

- Bot username 去掉 `@` 后保存，按 Telegram username 字符规则校验；
- short name 为空表示 Main Mini App；非空时严格校验并生成命名 Mini App 链接；
- mode 首版仅允许 `compact` 或空；
- launch reference TTL 必须为正数，且解析时取 `min(reference expiry, preview expiry)`；
- Bot Token 继续只通过 Secret 环境变量注入，不写入文档、URL、Registry 日志或客户端代码；
- 外部地址仍使用 Tailnet 内 MagicDNS HTTPS；点击设备必须连接同一 Tailnet。

降级策略：

- 未配置 Bot username：不生成错误的 `t.me` 链接；保留纯文本最终回复，或在明确批准的兼容模式下使用普通 Preview HTTPS URL；
- short name 为空：使用 Main Mini App 链接，不报错；
- launch reference 创建失败：返回 `None`，不阻断 Hermes 最终文本；
- Mini App 认证失败：显示通用错误，不降级为未认证内容读取。

## 5. 路由与 API 设计

### 5.1 启动页

`GET /` 返回包含 Telegram Web App SDK 的启动 shell。客户端读取：

```javascript
Telegram.WebApp.initDataUnsafe?.start_param
```

并可用 URL 中的 `tgWebAppStartParam` 作为启动兼容值。两者不一致时不得自行选择并继续授权；应把原始 `initData` 和候选 `launch_ref` 提交服务端，由服务端验证关联关系。无启动参数时显示 HermesPeek 介绍或安全的“请从 Preview 按钮打开”提示。

禁止通过前端把 `launch_ref` 改写成任意 `/p/<preview_id>` 后绕过认证。前端只提交 reference 和原始 `initData`。

### 5.2 启动认证 API

建议新增：

```http
POST /api/auth/telegram/launch
Content-Type: application/json

{
  "launch_ref": "<opaque-reference>",
  "init_data": "<Telegram.WebApp.initData>"
}
```

成功返回：

```http
204 No Content
Set-Cookie: hermes_peek_session=...; HttpOnly; Secure; SameSite=Lax
```

会话服务端状态保存解析后的 `preview_id` 和验证后的 Telegram user ID。客户端认证成功后，由响应头、安全的固定格式响应或单独的受会话保护端点获得内部 Preview 路由；不得把绝对路径或凭据返回客户端。

错误语义：

- `400`：reference 格式非法；
- `401`：`initData` 缺失、签名错误或超过允许时效；
- `403`：验证后的 Telegram 用户不是 owner；
- `404`：reference 不存在；
- `410`：reference/Preview 已过期或撤销；
- `503`：Telegram 认证配置不可用。

面向用户的页面使用通用错误文案；服务端日志只记录错误类别和请求关联 ID，不记录 reference、原始 `initData`、Cookie、Preview ID 或文件路径。

### 5.3 受保护 Preview

现有 `/api/previews/{preview_id}` 和文件接口继续依赖短期会话。必须保留：

- session 与 Preview 精确绑定；
- owner 二次比对；
- 每次读取重新检查 Preview 的 revoke/expiry；
- 每次读取重新执行路径策略；
- HTML sandbox、CSP、安全 MIME 和文件大小限制。

## 6. 分任务实施

### TASK 7.1：配置和 Direct Link 构造器

**状态：** `DONE`

交付物：

- 扩展 `Settings`；
- 新增独立的 Direct Link 构造函数；
- 对 username、short name、mode、reference 做严格校验和 URL 编码；
- 配置缺失时 fail-open 为纯文本，不产生畸形按钮。

目标测试：

- Main Mini App 链接；
- 命名 Mini App 链接；
- compact/默认模式；
- 非法 username、short name、reference；
- 不允许额外 query 注入；
- 输出不包含 Bot Token、路径和 owner ID。

建议提交：

```text
feat: add Telegram Mini App direct links
```

### TASK 7.2：短期 launch reference Registry

**状态：** `DONE`

交付物：

- 独立于 Preview record 的 reference 存储；
- 原子创建、解析、撤销和过期检查；
- 高熵 URL-safe reference；
- Preview 撤销/过期联动失效；
- 并发和损坏记录安全失败。

不得把文件路径、Bot Token 或原始 `initData` 存入 reference record。

建议提交：

```text
feat: add expiring Mini App launch references
```

### TASK 7.3：Mini App 启动路由和认证

**状态：** `DONE`

交付物：

- `/` 加载 Telegram SDK 和启动状态；
- 读取 `start_param`/`tgWebAppStartParam`；
- 新增 launch auth API；
- 服务端签名、时效、owner、reference 和 Preview 联合校验；
- 成功后进入现有 Preview UI；
- loading、缺参、非法、未授权、过期和网络错误状态。

现有直接 `/p/<preview_id>` 路由不得在生产模式下绕过认证。是否保留为认证后的内部路由由实现测试决定。

建议提交：

```text
feat: open previews from Telegram startapp
```

### TASK 7.4：最终消息与显式通知按钮改造

**状态：** `DONE`

交付物：

- `publish_action(...)` 创建 launch reference；
- Topic/群组最终 action 指向 `t.me?...startapp=`；
- 私聊继续使用 Telegram `web_app`；
- 旧 `TelegramClient.send_preview` 兼容路径同步采用相同策略；
- action 构造失败时保留 Hermes 正常文本；
- 不创建第二条消息。

如果 Hermes 当前 action schema 只能表达普通 HTTPS URL，先在 Hermes 上游测试仓库扩展通用 action 或 Telegram adapter 映射，并证明其他平台行为不变。不得从 HermesPeek 插件直接绕过 Gateway 发送最终按钮。

建议提交：

```text
feat: route Telegram topic previews through Mini App
```

### TASK 7.5：文档和离线验收

**状态：** `DONE`

更新：

- `README.md`；
- `docs/01-design-development-plan.md`；
- `docs/03-security.md`；
- `docs/04-hermes-integration.md`；
- `docs/05-operations.md`；
- `docs/plan/01-implementation-task-plan.md`；
- 本文的 TASK 状态与实际验收记录。

只有真实执行通过后才能记录命令结果，不预填测试数量。

建议提交：

```text
docs: document Telegram Topic Mini App rollout
```

### TASK 7.6：真实部署与 Topic 验收

**状态：** `PARTIAL_REAL_ACCEPTANCE`

前置条件：

- TASK 7.1～7.5 完成；
- Hermes 与 HermesPeek 全量测试通过；
- 工作区干净、提交完整；
- Tailnet 设备可访问 MagicDNS HTTPS；
- 项目负责人明确授权安装、配置变更和 Gateway 重启；
- 已准备回滚版本和维护窗口。

项目负责人已在当前 Telegram Topic 明确要求继续验证。已完成的真实验收包括：

- BotFather Main Mini App 已启用，Main Mini App Direct Link 可用；
- 当前 profile 的 HermesPeek 插件与服务完成受控升级，服务 `/healthz` 正常；
- Topic 中发送的按钮为 `t.me/<bot>?startapp=lr_...`，不再是普通 Preview HTTPS URL；
- 项目负责人确认 README 在 Telegram Mini App 容器中成功打开；
- 同一按钮可重复打开；Topic Direct Link 每次显示 Telegram 平台确认页属于平台预期行为；
- 私聊 `web_app` 按钮仍可用；
- 真实验收期间未执行 uninstall 或 purge。

尚未完成：从 Gateway 新会话自动触发最终消息 action 的重启后验收、他人转发拒绝、Preview revoke、Tailnet 断连恢复和完整生产日志脱敏扫描。因此阶段状态不得记为全部真实验收完成。

### 实施与验收记录（2026-08-05）

- `087d954 feat: open topic previews as Telegram Mini Apps`：Direct Link、短期 launch reference、启动认证和 Topic action；
- `888de90 fix: align lifecycle activation with live Hermes`：真实 Hermes 生命周期兼容修复；
- 隔离全量回归：147 tests passed；
- 提交后 Mini App/Gateway 定向回归：22 tests passed；
- `compileall`、`git diff --check` 和 staged Secret 扫描通过；
- Telegram Topic 真实消息成功发送并由项目负责人确认可用；能力型 URL、Preview ID、用户/聊天/Topic 标识和私有域名不写入仓库验收记录。

## 7. 测试矩阵

### 7.1 单元测试

- 配置解析与边界；
- Direct Link 的 Main/命名两种格式；
- launch reference 熵、格式、碰撞、过期、撤销；
- Telegram `initData` 正确签名、错误签名、过期 `auth_date`；
- owner 匹配和不匹配；
- 安全日志与错误文案。

### 7.2 集成测试

- 发布 Preview 后生成 reference 和 Direct Link；
- 从启动 auth API 建立会话并读取 Preview；
- 未认证 API 返回 401；
- 他人打开转发链接返回 403；
- reference 不存在返回 404；
- reference/Preview 过期或撤销返回 410；
- 私聊 `web_app`、群组/Topic `url` payload 正确；
- `final_message_actions` 在同一条发送/edit 消息附加按钮；
- action 失败时仍发送纯文本且无第二条消息；
- 临时 `HERMES_HOME` 安装测试不触碰真实 profile。

### 7.3 安全回归

- query 注入和 URL 编码绕过；
- reference 枚举和时序差异；
- 伪造客户端 user ID；
- `initDataUnsafe` 替代原始 `initData`；
- 路径穿越、软链接逃逸、敏感文件名；
- Session 固定、跨 Preview Cookie 复用；
- 日志和响应泄露 reference、Preview ID、Bot Token、Cookie、绝对路径；
- XSS、HTML sandbox、错误 MIME 和未授权 raw 文件。

### 7.4 每个 TASK 的质量门禁

```bash
uv run pytest tests/<target> -v
uv run pytest
uv run python -m compileall -q src integrations tests
git diff --check
```

同时执行仓库已采用的静态检查和敏感信息扫描。检查 staged 与 unstaged diff；不得把真实 Token、用户 ID、聊天 ID、Topic ID、私有域名、能力型标识或本机绝对部署路径提交到仓库。

## 8. 部署步骤（获得授权后）

以下仅为操作模板，不表示已执行。

### 8.1 部署前检查

```bash
cd /path/to/HermesPeek
uv sync --locked
uv run pytest
```

确认：

- HermesPeek 服务和 Gateway 使用同一 state directory；
- 服务端可读取 Bot Token，最终消息插件不需要读取 Token；
- Bot username 与 Main Mini App Bot 一致；
- external base URL 是 Telegram 客户端可访问的 Tailnet HTTPS 地址；
- 没有同时启用旧 `agent:end` 独立通知 Hook。

### 8.2 更新服务

1. 备份非敏感配置结构和当前插件版本；
2. 部署 HermesPeek 新代码；
3. 增加 Bot username、Mini App mode 和 launch TTL 配置；
4. 保持 Bot Token 仅在服务 Secret 中；
5. 重启 HermesPeek 服务；
6. 验证本机 `/healthz` 和 Tailnet HTTPS `/healthz`；
7. 用测试 Registry 完成一次签名认证，不输出真实凭据。

### 8.3 更新 Hermes 插件

1. 复制已验收的插件文件到**当前获批 profile**；
2. 核对插件列表；
3. 经再次确认后启用插件；
4. 在维护窗口重启 Gateway；
5. 查看脱敏日志，确认无插件加载错误。

不得修改其他 profile。

## 9. 真实验收清单

在真实 Telegram 私聊、群组和当前 Forum Topic 分别执行：

1. 让 Hermes 用 `write_file` 或 `patch` 创建一个无敏感内容的测试 Markdown；
2. 等待 Hermes 最终答复；
3. 确认只有一条最终完成消息；
4. 确认 `Open preview` 按钮在同一条消息；
5. Topic 按钮 URL 为 `t.me` Main Mini App Direct Link，而不是普通 Preview HTTPS URL；
6. 点击后在当前 Telegram 内打开 Mini App 容器；
7. 确认显示的是本轮 Preview，不是首页或旧 Preview；
8. 刷新和重新进入仍能在有效期内访问；
9. 将按钮转发给另一 Telegram 用户，确认对方无法读取；
10. 撤销 Preview 后确认返回失效状态；
11. 断开点击设备的 Tailnet 后确认内容不可达，重新连接后恢复；
12. 模拟 action 创建失败，确认 Hermes 纯文本最终答复仍正常；
13. 检查日志中没有原始 `initData`、Token、Cookie、reference、Preview ID 或文件路径。

验收记录必须包括场景、时间、软件版本、实际结果和失败项；凭据及能力型值必须脱敏。

## 10. 回滚

出现认证绕过、内容泄露、重复消息、Gateway 不稳定或 Mini App 无法打开时：

1. 立即禁用 HermesPeek 插件；
2. 经授权重启 Gateway，恢复纯文本回复；
3. 回滚 HermesPeek 服务到上一已验收版本；
4. 撤销本轮测试 Preview 和 launch references；
5. 不删除 Registry 作为问题分析的唯一动作，先保护权限并保存脱敏证据；
6. 若怀疑 Bot Token 泄露，立即通过 BotFather 轮换 Token，并更新服务 Secret；
7. 分析完成前不启用普通 HTTPS 未认证降级。

回滚成功标准：Hermes Telegram 正常回复、没有 Preview 按钮或第二条消息、Gateway 日志无持续错误、旧 Preview 不产生越权访问。

## 11. 完成定义

只有同时满足以下条件，阶段 7 才能标记 `DONE`：

- Main Mini App Direct Link 生成和解析已实现；
- `startapp` 使用短期 opaque reference；
- 服务端验证原始 `initData`、时效和 owner；
- 私聊、群组、Topic 按钮策略符合 Telegram 限制；
- Topic 最终回复与按钮在同一条消息；
- 无重复独立通知；
- 全量、集成和安全回归实际通过；
- 经授权完成真实 Gateway 部署；
- 当前 Topic 现场验收通过；
- 文档记录实际结果和回滚点，工作区干净。

在真实部署与 Topic 验收完成前，只能声明“阶段 7 方案/代码/离线验证完成”中的对应部分，不能声明 Telegram Topic Mini App 闭环已经上线。
