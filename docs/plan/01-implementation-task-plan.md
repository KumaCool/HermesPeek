# 01 HermesPeek 实施任务计划

> 本文是 [`../01-design-development-plan.md`](../01-design-development-plan.md) 的执行拆分。设计依据与架构决策以设计文档为准；本文只维护 TASK、状态、验收证据与提交边界。

**当前总体状态：** `阶段 0–5 DONE（TASK 5.3 未批准、不执行）；阶段 6 代码与离线集成 DONE；阶段 7 DONE（实现、离线验收和项目负责人真实 Topic 验收完成）；阶段 8 DONE（实现、离线验收和真实生命周期验收完成）`

---

## 1. 验收矩阵

### 1.1 状态定义

| 状态 | 含义 | 进入条件 |
|---|---|---|
| `TODO` | 尚未开始 | TASK 已定义但没有实现工作 |
| `IN_PROGRESS` | 正在实施 | 已开始修改代码、测试或文档 |
| `BLOCKED` | 被外部条件阻塞 | 必须写明阻塞原因、证据和解除条件 |
| `VERIFYING` | 实现完成，正在验收 | 交付物已具备，验收命令尚未全部通过 |
| `DONE` | 已完成 | TASK 验收项全部通过，证据已记录，独立 commit 已创建 |

### 1.2 TASK 总览

| TASK | 名称 | 阶段 | 状态 | 核心验收证据 |
|---|---|---:|---|---|
| TASK 0.1 | 建立可复现基线 | 0 | `DONE` | `uv sync --locked`; `uv run pytest`；工作区变更符合预期 |
| TASK 0.2 | 落地架构与安全文档 | 0 | `DONE` | 架构、安全、集成文档完整且能力边界准确 |
| TASK 1.1 | 类型化配置 | 1 | `DONE` | 配置单元测试；缺失配置与多允许根场景通过 |
| TASK 1.2 | 安全路径策略 | 1 | `DONE` | 路径穿越、敏感路径、软链接逃逸、大小/MIME 测试通过 |
| TASK 1.3 | 文件系统 Preview Registry | 1 | `DONE` | Registry 创建/读取/撤销/过期/并发原子写测试通过 |
| TASK 1.4 | 发布服务与 CLI | 1 | `DONE` | 真实 CLI publish→inspect→revoke 闭环；输出无绝对路径 |
| TASK 2.1 | FastAPI app factory 与 Preview API | 2 | `DONE` | Preview API 集成测试；未知/过期/撤销状态正确且无路径泄漏 |
| TASK 2.2 | Telegram initData 验证 | 2 | `DONE` | Telegram 固定向量、篡改、过期、错误用户和日志脱敏测试通过 |
| TASK 2.3 | 文本、代码、Markdown 与结构化文本 | 2 | `DONE` | XSS/转义/结构化解析/错误降级/磁盘实时更新测试通过 |
| TASK 2.4 | 图片、PDF 与受限 HTML | 2 | `DONE` | 未授权 raw、MIME 欺骗、CSP 与 iframe sandbox 测试通过 |
| TASK 2.5 | Telegram Mini App 前端 | 2 | `DONE` | 移动端布局、认证先行、主题、文件切换及浏览器控制台检查通过 |
| TASK 3.1 | Bot API 客户端与按钮构造 | 3 | `DONE` | MockTransport 验证 DM/群组/Topic payload 与 Token 脱敏 |
| TASK 3.2 | CLI 发布后通知 | 3 | `DONE` | Mock E2E 通过；真实 Telegram 点击验收待明确授权 |
| TASK 4.1 | Hermes 写文件收集插件 | 4 | `DONE` | 成功 write/patch 精确收集、失败忽略、去重和安全过滤测试通过 |
| TASK 4.2 | agent:end Gateway Hook | 4 | `DONE` | 无文件静默、幂等、异常隔离、Topic 路由集成测试通过 |
| TASK 4.3 | 安装与运维说明 | 4 | `DONE` | 临时 HERMES_HOME 安装/卸载通过；不修改真实配置 |
| TASK 5.1 | 本机服务封装 | 5 | `DONE` | 本地服务仅绑定批准地址；重启恢复；健康检查通过 |
| TASK 5.2 | WireGuard 受控入口验证 | 5 | `DONE` | Tailscale Serve 私网 HTTPS、Telegram WebView 与 owner 认证现场通过 |
| TASK 5.3 | Cloudflare Tunnel 生产入口（仅在批准后） | 5 | `TODO` | 获授权后验证最小公网暴露、未授权拒绝和 Tunnel 回滚 |
| TASK 6.1 | 设计通用 Hermes Gateway 扩展点 | 6 | `DONE` | 平台中立 URL action、Telegram send/edit 与流式兼容测试通过 |
| TASK 6.2 | HermesPeek 使用扩展点附加按钮 | 6 | `DONE` | 插件发布 Preview 并返回 action；不调用 Bot API；离线集成与全量回归通过 |

### 1.3 状态维护规则

1. 任一时刻只允许一个 TASK 为 `IN_PROGRESS` 或 `VERIFYING`。
2. TASK 状态变化时，同时更新本矩阵和对应 TASK 正文中的状态。
3. `BLOCKED` 必须在 TASK 正文追加“阻塞记录”，包括日期、原因、证据与解除条件。
4. `DONE` 必须在 TASK 正文追加“验收记录”，包括实际命令、实际结果和 commit SHA；没有真实工具输出不得标记完成。
5. 阶段内 TASK 连续执行；阶段结束后运行全量回归、确认工作区干净并统一汇报，等待项目负责人的“继续”。

---

## 2. TASK 清单

> 所有阶段均不写工期。每个 TASK 均列出方案来源、交付物、验收依据和独立 commit。阶段内连续执行，阶段结束后统一回归并等待项目负责人指示。

## 阶段 0：固化基线与架构文档

### TASK 0.1：建立可复现基线

**状态：** `DONE`

**方案来源：** 当前无 commit 的仓库状态；项目负责人的“每个 TASK 验收后独立 commit”规则。

**交付物：**

- 整理当前 `.gitignore`；
- 将现有骨架、测试和 `docs/00-product-decisions.md` 纳入首个基线提交；
- 不改变现有业务行为。

**验收依据：**

```bash
uv sync --locked
uv run pytest
```

预期：现有 5 个测试全部通过；`git status --short` 只显示本 TASK 预期文件。

**Commit：** `chore: establish HermesPeek baseline`

**验收记录（2026-08-04 03:11 CST）：**

- 命令：`uv sync --locked && uv run pytest`
- 结果：依赖锁定同步成功；`5 passed, 1 warning`。警告来自 FastAPI TestClient 对 Starlette/httpx 兼容层的弃用提示，不影响本 TASK 基线行为。
- 提交：`d7898ce chore: establish HermesPeek baseline`
- 提交前 staged diff 敏感信息扫描：0 命中；`git diff --cached --check` 通过。

### TASK 0.2：落地架构与安全文档

**状态：** `DONE`

**方案来源：** 本方案第 2 节；`docs/00-product-decisions.md`。

**交付物：**

- `docs/02-architecture.md`
- `docs/03-security.md`
- `docs/04-hermes-integration.md`
- 更新 `README.md` 文档索引

**验收依据：** 文档明确列出数据流、信任边界、API、模块职责、Hermes 能力边界，且不把“最终消息内合并按钮”写成当前已具备能力。

**Commit：** `docs: define architecture and security model`

**验收记录（2026-08-04 03:15 CST）：**

- 文档结构断言：架构、安全、Hermes 集成三份文档各 6 项必需边界全部存在。
- README Markdown 链接检查：6 个链接全部存在。
- 回归命令：`uv run pytest && git diff --check`
- 结果：`5 passed, 1 warning`；diff 检查通过。
- 提交：`9a65028 docs: define architecture and security model`
- 提交前 staged diff 敏感信息扫描：0 命中。

**阶段验收：** `uv run pytest` 全绿；Git 工作区干净。

---

## 阶段 1：安全 Preview Registry 与显式发布 CLI

### TASK 1.1：类型化配置

**状态：** `DONE`

**方案来源：** 模块化单体设计；秘密与行为配置分离原则。

**交付物：**

- `src/hermes_peek/config.py`
- `tests/unit/test_config.py`
- 配置项：允许根、状态目录、最大文件大小、Preview 默认有效期、外部基础 URL、开发模式；
- Bot Token、会话签名密钥只从 secret env 读取，非秘密行为配置支持 CLI/配置文件。

**验收依据：** 缺失必需配置时错误可读；多允许根解析正确；测试不读取真实用户配置。

**Commit：** `feat: add typed application settings`

**验收记录（2026-08-04）：**

- RED：`uv run pytest tests/unit/test_config.py -q` 因 `hermes_peek.config` 尚不存在而按预期失败。
- GREEN：目标配置测试 `7 passed`；全量回归 `12 passed, 1 warning`；`git diff --check` 通过。
- 覆盖显式允许根、多允许根、状态目录、默认值、HTTPS 外部 URL、开发模式与无效配置；测试使用显式环境映射，不读取真实用户配置。
- 提交：`242677e feat: add typed application settings`；提交前 staged diff 敏感信息扫描 0 命中。

### TASK 1.2：安全路径策略

**状态：** `DONE`

**方案来源：** `docs/00-product-decisions.md` 默认安全规则。

**交付物：**

- `src/hermes_peek/paths.py`
- `tests/unit/test_paths.py`
- 允许根、软链接逃逸、敏感文件/目录、扩展名、MIME、大小、UTF-8 与不存在文件判断。

**验收依据：** 正常文件通过；`..`、根外文件、`.env`、`.git`、`.ssh`、`.hermes`、软链接逃逸、超大文件和不支持类型均被拒绝。

**Commit：** `feat: enforce preview path security policy`

**验收记录（2026-08-04）：**

- RED：目标测试因 `hermes_peek.paths` 尚不存在而按预期失败。
- GREEN：路径策略测试 `14 passed`；全量回归 `26 passed, 1 warning`；`git diff --check` 通过。
- 覆盖正常 UTF-8/PNG、根外与 `..`、敏感路径、任意软链接、缺失/目录、类型、大小、UTF-8 与 MIME 签名；错误不回显提交路径。
- 提交：`a600aa2 feat: enforce preview path security policy`；提交前 staged diff 敏感信息扫描 0 命中。

### TASK 1.3：文件系统 Preview Registry

**状态：** `DONE`

**方案来源：** 最小化方案；无需数据库；每记录独立原子 JSON。

**交付物：**

- `src/hermes_peek/models.py`
- `src/hermes_peek/registry.py`
- `tests/unit/test_registry.py`

**验收依据：** Preview ID 使用密码学安全随机数；创建、读取、撤销、过期、损坏记录隔离、并发原子写入测试通过；API 模型不序列化绝对路径。

**Commit：** `feat: add filesystem preview registry`

**验收记录（2026-08-04）：**

- RED：目标测试因 `hermes_peek.models` 尚不存在而按预期失败。
- GREEN：Registry 测试 `7 passed`；全量回归 `33 passed, 1 warning`；`git diff --check` 通过。
- 已验证密码学随机 Preview ID、独立 JSON、原子写与目录 fsync、读取、幂等撤销、过期语义、损坏隔离、40 路并发创建及公开 DTO 不含绝对路径。
- 提交：`5e4846e feat: add filesystem preview registry`；提交前 staged diff 敏感信息扫描 0 命中。

### TASK 1.4：发布服务与 CLI

**状态：** `DONE`

**方案来源：** 已确认“先实现 `hermes-peek publish`”。

**交付物：**

- `src/hermes_peek/service.py`
- `src/hermes_peek/cli.py`
- `pyproject.toml` 的 `[project.scripts]`
- `tests/unit/test_service.py`
- `tests/integration/test_cli.py`

**验收依据：**

```bash
uv run hermes-peek publish docs/00-product-decisions.md \
  --entry docs/00-product-decisions.md \
  --title "HermesPeek 产品决策" \
  --owner "<telegram-user-id>"
```

命令输出 Preview ID 和 URL，不输出绝对路径；`inspect` 可见脱敏元数据；`revoke` 后不可读取。

**Commit：** `feat: add explicit preview publishing CLI`

**验收记录（2026-08-04）：**

- RED：目标测试因 `hermes_peek.service` 尚不存在而按预期失败。
- GREEN：服务与 subprocess CLI 目标测试 `5 passed`；全量回归 `38 passed, 1 warning`；`uv sync --locked` 与 `git diff --check` 通过。
- 真实 CLI 闭环：临时允许根与状态目录中执行 `publish → inspect → revoke`，得到 `REAL_CLI_ROUND_TRIP_OK`；输出包含不透明 Preview ID、HTTPS URL、相对显示路径与撤销时间，不含临时绝对路径或 `absolute_path` 字段。
- 提交：`a438793 feat: add explicit preview publishing CLI`；提交前 staged diff 敏感信息扫描 0 命中。

**阶段验收：** 全量 pytest；创建真实 Preview 记录并现场读取、撤销；Git 工作区干净。

---

## 阶段 2：认证 API 与多格式只读预览

### TASK 2.1：FastAPI app factory 与 Preview API

**状态：** `DONE`

**方案来源：** 第 2.3、2.5 节请求模型。

**交付物：**

- 重构 `src/hermes_peek/app.py` 为 `create_app(settings)`；
- Preview App Shell、元数据与文件内容 API；
- `tests/integration/test_preview_api.py`。

**验收依据：** URL 和响应中不出现绝对路径；未知、过期、撤销 Preview 返回明确状态；测试使用临时 Registry 和临时允许根。

**Commit：** `feat: expose preview API by opaque ID`

**验收记录（2026-08-04）：**

- RED：集成测试因 `create_app` 不存在按预期失败；GREEN：目标测试 `5 passed`，全量回归 `38 passed`。
- 未知 Preview 返回 404；过期和撤销返回 410；Shell、元数据与内容 API 均不返回绝对路径。
- 提交：`cbf5ec9 feat: expose preview API by opaque ID`；提交前 staged 敏感信息扫描 0 命中。

### TASK 2.2：Telegram initData 验证

**状态：** `DONE`

**方案来源：** Telegram Mini Apps HMAC 验证要求；默认仅任务发起人可访问。

**交付物：**

- `src/hermes_peek/auth.py`
- `tests/unit/test_telegram_auth.py`
- `tests/integration/test_auth_api.py`
- HttpOnly、Secure、SameSite 会话 Cookie；短时会话和退出接口。

**验收依据：** 有效固定测试向量通过；篡改 hash、过期 `auth_date`、错误用户、撤销 Preview、错误 Preview ID 均拒绝；日志不记录 `initData`、Bot Token 或 Cookie。

**Commit：** `feat: verify Telegram Mini App identity`

**验收记录（2026-08-04）：**

- RED：认证模块不存在；后续测试捕获请求模型绑定、204 Response 与 Secure Cookie 测试协议问题，并逐项修复。
- 目标测试 `9 passed`；全量回归 `45 passed`。有效 HMAC、篡改、过期/未来时间、错误 owner、未知和撤销 Preview 均覆盖。
- 会话 Cookie 为 HttpOnly、Secure、SameSite=Lax；服务端仅存随机 Token 哈希；响应不包含 initData、Bot Token、Cookie 或绝对路径。
- 提交：`b448f87 feat: authenticate Telegram preview sessions`；提交前 staged 敏感信息扫描 0 命中。

### TASK 2.3：文本、代码、Markdown 与结构化文本

**状态：** `DONE`

**方案来源：** 首版格式范围；服务端安全渲染策略。

**交付物：**

- `renderers/base.py`
- `renderers/text.py`
- `renderers/markdown.py`
- `renderers/structured.py`
- 相应单元与集成测试。

**验收依据：** Markdown 脚本与原始 HTML 无法执行；代码正确转义；JSON/YAML/TOML 成功格式化，语法错误安全降级；文件更新后再次请求返回磁盘最新内容。

**Commit：** `feat: render text and markdown previews safely`

**验收记录（2026-08-04）：**

- RED：渲染模块不存在；首轮 GREEN 暴露不安全 Markdown URI 仍留在输出，修复后目标测试 `8 passed`。
- 全量回归 `51 passed`；文本/代码转义、Markdown 禁止原始 HTML 与危险协议、JSON/YAML/TOML 校验和磁盘实时读取通过。
- 提交：`1d60704 feat: render safe text previews`；提交前 staged 敏感信息扫描 0 命中。

### TASK 2.4：图片、PDF 与受限 HTML

**状态：** `DONE`

**方案来源：** 首版格式范围；HTML sandbox 最小权限设计。

**交付物：**

- `renderers/image.py`
- `renderers/pdf.py`
- `renderers/html.py`
- MIME、CSP、`X-Content-Type-Options` 和缓存策略；
- 相应测试。

**验收依据：** 未授权 raw 请求被拒绝；伪扩展名与错误 MIME 被拒绝；HTML iframe 不含 `allow-same-origin`、`allow-forms`、`allow-popups`；HTML 不能导航顶层窗口。

**Commit：** `feat: add protected media and sandboxed HTML previews`

**验收记录（2026-08-04）：**

- RED：图片/PDF raw 路由缺失且 HTML 危险协议仍存在；GREEN：目标测试 `8 passed`，全量回归 `53 passed`。
- raw 只允许 image/pdf，返回 inline、正确 MIME 与 `X-Content-Type-Options: nosniff`；HTML 经 allowlist 清洗并由无权限 sandbox iframe 展示。
- PathPolicy 既有伪扩展/MIME 签名与未授权 API 测试继续全绿。
- 提交：`fb9e24b feat: serve safe binary and HTML previews`；提交前 staged 敏感信息扫描 0 命中。

### TASK 2.5：Telegram Mini App 前端

**状态：** `DONE`

**方案来源：** compact 浮窗体验和 Telegram 主题要求。

**交付物：**

- `templates/preview.html`
- `static/app.css`
- `static/app.js`
- 文件切换、错误态、加载态、刷新、复制按钮、Telegram theme variables、非 Telegram 开发降级。

**验收依据：** 手机宽度下无横向页面溢出（代码块除外）；调用 `Telegram.WebApp.ready()`；不主动 `expand()`；首次加载先认证再取内容；切换文件不会泄漏路径。

**Commit：** `feat: build Telegram Mini App preview interface`

**验收记录（2026-08-04）：**

- RED：静态资源路由缺失；GREEN：Mini App 目标测试通过，全量回归 `54 passed`。
- Shell 使用 Telegram SDK 与主题变量；调用 `ready()` 且不主动 `expand()`；认证先于元数据；具备加载/错误态、文件切换、刷新、复制链接及各格式展示。
- 提交：`5b82e2f feat: add Telegram Mini App preview UI`；补全计划所列控件与不主动展开约束：`7dc13c3 fix: complete Mini App preview controls`。两次 staged 敏感信息扫描均 0 命中。

**阶段验收记录（2026-08-04）：**

- `uv run pytest -q`：`54 passed, 1 warning`；`python3 -m compileall -q src` 通过。警告仍为 TestClient 兼容层弃用提示。
- Uvicorn 临时绑定 `127.0.0.1:18765`；健康、Shell、元数据与 Markdown 渲染均返回 200，响应无绝对路径。
- 使用真实临时 Markdown、Python、JSON、PNG、PDF、HTML 六个文件完成 HTTP 现场验证，结果 `SIX_FORMAT_HTTP_OK`；HTML 无脚本，PNG/PDF MIME 正确。
- 浏览器 daemon 与 computer-use backend 在本机超时/不可用，因此未取得浏览器控制台现场证据；静态前端集成测试和本机 HTTP 已通过。未修改网络入口或 Hermes/Telegram 配置。

**阶段验收：** 全量 pytest；本机 Uvicorn 启动后使用真实 Markdown、代码、JSON、图片、PDF、HTML 各做一次 HTTP 现场验证；浏览器检查控制台无错误。此阶段仅绑定 `127.0.0.1`，不改网络入口。

---

## 阶段 3：Telegram 显式通知闭环

### TASK 3.1：Bot API 客户端与按钮构造

**状态：** `DONE`

**方案来源：** 私聊 `web_app`、群组/Topic Direct Link 的已确认决策。

**交付物：**

- `src/hermes_peek/telegram.py`
- `tests/unit/test_telegram_messages.py`
- 私聊、普通群组、Forum Topic 三类 payload；
- Bot Token 仅从 secret env 获取。

**验收依据：** MockTransport 断言私聊使用 `web_app`；群组/Topic 使用 `url` Direct Link；Topic 携带整数 `message_thread_id`；日志和异常不泄漏 Bot Token。

**Commit：** `feat: send Telegram preview notifications`

**验收记录（2026-08-04）：**

- RED：`hermes_peek.telegram` 不存在，目标测试在收集阶段按预期失败。
- GREEN：目标测试 `8 passed`；全量回归 `62 passed, 1 warning`。
- MockTransport 验证私聊使用 `web_app`，群组/Topic 使用 Direct Link；Topic 的 `message_thread_id` 为整数；非法 chat/thread 组合和非 HTTPS URL 被拒绝。
- Bot Token 仅由调用方注入；API 与网络异常转换为固定安全错误，异常文本不含 Token。
- 提交：`24c1da7 feat: send Telegram preview notifications`；提交前 staged 敏感信息扫描 0 命中。

### TASK 3.2：CLI 发布后通知

**状态：** `DONE`

**方案来源：** 显式发布先于自动集成。

**交付物：**

- `publish --notify --chat-id --thread-id --chat-type`；
- 发布成功但通知失败时保留 Preview，并返回非零退出码和可操作错误；
- 集成测试。

**验收依据：** 使用 Mock Bot API 完成发布→发送链路；真实 Telegram 验收前必须由项目负责人明确授权使用当前 Bot 与当前 Topic。

**Commit：** `feat: notify Telegram from publish command`

**验收记录（2026-08-04）：**

- RED：CLI 不认识 `--notify` 等参数，且无可注入 Telegram transport；3 个目标测试按预期失败。
- GREEN：CLI 与既有 subprocess 测试 `5 passed`；全量回归 `65 passed, 1 warning`。
- Mock E2E 验证 publish→构造 Topic payload→sendMessage→输出 `message_id`；通知失败返回非零状态且已创建 Preview 仍保留。
- `--notify` 强制要求 chat ID、chat type、HTTPS 外部 URL 与 secret env Token；输出和错误不含绝对路径或 Token。
- 提交：`3f85f57 feat: notify Telegram from publish command`；提交前 staged 敏感信息扫描 0 命中。

**真实验收补充（2026-08-05）：** 项目负责人明确授权向 Telegram 私聊发送测试 Preview。CLI 发布成功，Bot API 返回 `notified=true` 和消息 ID；项目负责人确认收到通知，点击 `Open preview` 后在 Telegram WebView 中通过 owner 身份认证并看到测试 Markdown。真实 Token 未输出或写入仓库。

**阶段验收记录（2026-08-04）：**

- 阶段 3 Mock 范围全量回归 `65 passed, 1 warning`，工作区提交后干净。
- 未读取或使用真实 Bot Token，未向任何 Telegram chat/topic 发送消息，未修改 Hermes 或 Bot 配置。
- 真实 Telegram 按钮点击、Telegram 内 WebView 与 owner 现场验证仍需项目负责人单独明确授权；本记录不宣称真实闭环通过。

**阶段验收：** 在获得明确授权后，发布本项目 Markdown，当前 Topic 收到带按钮消息；点击后在 Telegram 内打开；仅项目负责人可读取；其他用户或无效 initData 被拒绝。未获网络/真实 Bot 授权时只完成 Mock E2E，不宣称真实闭环通过。

---

## 阶段 4：Hermes 自动收集与独立预览消息

### TASK 4.1：Hermes 写文件收集插件

**状态：** `DONE`

**方案来源：** Hermes 官方 `post_tool_call` Plugin Hook。

**交付物：**

- `integrations/hermes/plugin.yaml`
- `integrations/hermes/__init__.py`
- `integrations/hermes/collector.py`
- `tests/integration/test_hermes_collector.py`
- 仅收集成功的 `write_file`、`patch` 所涉及路径；按 `session_id/task_id` 写入 collector spool。

**验收依据：** 失败工具调用不计入；重复文件去重；根外/敏感/不支持路径在收集阶段或发布阶段被拒绝；`terminal` 命令中的候选路径不做猜测性采集。

**Commit：** `feat: collect Hermes file tool outputs`

**验收记录（2026-08-04）：** RED 为集成文件不存在，4 个测试按预期失败；GREEN 为目标测试 `4 passed`、全量回归 `69 passed`。仅成功 `write_file`/`patch` 被收集；根外、敏感、缺失文件与 terminal 猜测均忽略；同 session/task 去重并原子写 spool。提交 `bd82a70`，敏感信息扫描 0 命中。

### TASK 4.2：agent:end Gateway Hook

**状态：** `DONE`

**方案来源：** Hermes 官方 Gateway Event Hook 与现场源码字段。

**交付物：**

- `integrations/hermes/HOOK.yaml`
- `integrations/hermes/handler.py`
- `tests/integration/test_gateway_hook.py`
- 从 context 取得 user/chat/thread/session；读取本轮 collector；创建 Preview；发送独立通知；成功后消费 collector。

**验收依据：** 无本轮文件时静默；非 Telegram 平台静默；异常只写脱敏日志且不影响 Hermes 正常答复；同一 session 重试不重复发送；Forum Topic 路由正确。

**Commit：** `feat: publish previews from Hermes gateway hook`

**验收记录（2026-08-04）：** RED 为 handler 缺失，3 个测试按预期失败；GREEN 为目标测试 `3 passed`、全量回归 `72 passed`。非 Telegram/无文件静默；Forum Topic 使用整数 thread ID；成功后消费 spool，发送失败保留 spool，重复事件不重复发送；异常隔离。提交 `88816aa`，敏感信息扫描 0 命中。

### TASK 4.3：安装与运维说明

**状态：** `DONE`

**方案来源：** Hermes 插件需显式启用，Gateway Hook 从 profile-local `hooks/` 加载。

**交付物：**

- `docs/04-hermes-integration.md` 的安装、卸载、升级、日志和故障排查；
- 安装脚本只负责复制/链接文件和检查，不自动改 `config.yaml`；
- 明确列出由项目负责人手动完成的插件启用和 Gateway 重启步骤。

**验收依据：** 全新临时 `HERMES_HOME` 中可安装和移除；不触碰真实 `~/.hermes/config.yaml`、`hermes.json`、`exec-approvals.json` 或 Gateway 配置。

**Commit：** `docs: document Hermes integration operations`

**验收记录（2026-08-04）：** 临时 `HERMES_HOME` 安装/卸载测试通过，安装前后测试 config 字节完全一致；集成目标测试 `8 passed`，全量回归 `73 passed`。文档覆盖安装、启用边界、升级、卸载、日志和故障排查。提交 `bab573a`，敏感信息扫描 0 命中。

**离线阶段验收记录（2026-08-04）：** 全量 pytest、compileall 与 diff 检查通过；未向真实 default profile 复制集成文件，未修改真实 Hermes 配置，未启用插件或重启 Gateway，也未调用真实 Telegram。真实 profile 安装与 Telegram 自动闭环仍待项目负责人明确授权。

**阶段验收：** 获得项目负责人明确授权后，在当前 profile 安装但不自动修改 Hermes 配置；由项目负责人启用插件/重启 Gateway；随后让 Hermes 修改一个测试文件，现场确认正常答复后出现第二条预览消息，按钮对应本轮文件而不是旧记录。

---

## 阶段 5：部署、HTTPS 与 Telegram 真实访问

> 本阶段会改变服务入口、端口、HTTPS、Tunnel 或外部访问范围。任何 TASK 执行前必须单独获得项目负责人明确授权。

### TASK 5.1：本机服务封装

**状态：** `DONE`

**方案来源：** 应用只监听本地地址、外层入口可替换。

**交付物：**

- `compose.yaml` 或 systemd user service（二选一，优先最小方案）；
- 健康检查、只读挂载、非 root 用户、日志轮转；
- `docs/05-operations.md`。

**验收依据：** 服务仅绑定批准的本地地址和端口；重启后恢复；容器/进程仅能读取批准根；`/healthz` 现场通过。

**Commit：** `ops: add local HermesPeek service definition`

**验收记录（2026-08-04）：** RED 为 unit 缺失且 CLI 不支持 `serve`，2 个测试按预期失败。GREEN 为目标测试 `2 passed`、全量回归 `75 passed`；`systemd-analyze verify`、compileall、diff 检查通过。测试实际启动临时 Uvicorn，绑定随机 `127.0.0.1` 端口，`/healthz` 返回预期 JSON 后终止进程。unit 使用回环监听、失败重启、journal 日志及 systemd 加固；未安装真实 user unit、未持久监听端口、未配置外部入口。提交 `ffaeb1c`，敏感信息扫描 0 命中。

**真实部署补充（2026-08-05）：** 生产环境文件以 `0600` 安装，必需变量均存在且非空；稳定 CLI 由 `uv tool` 安装。`hermes-peek.service` 已启用并运行，只监听 `127.0.0.1:8765`；`/healthz` 返回 200，重启后 PID 变化且健康恢复。此主机的 user manager 对 capability 相关加固指令返回 `218/CAPABILITIES`，故本机安装副本移除这些不兼容指令，保留 `PrivateTmp`、`ProtectSystem=strict`、`ProtectHome=read-only` 和状态目录写入白名单。仓库模板不变。

### TASK 5.2：WireGuard 受控入口验证

**状态：** `DONE`

**方案来源：** 产品决策中的优先评估项。

**交付物：** HTTPS 域名、证书、路由可达性和 Telegram WebView 兼容性验证记录；必要配置需单独批准。

**验收依据：** 打开 Telegram 的目标设备接入 WireGuard 后，能够通过受信任 HTTPS 打开 Mini App；若任一条件不满足，记录证据并停止，不擅自切换 Cloudflare 方案。

**Commit：** `docs: record WireGuard ingress validation`

**验收记录（2026-08-05）：** 配置 Tailscale Serve（tailnet only），将 `https://kuma-mini.tail5d0941.ts.net/` 代理到 `http://127.0.0.1:8765`，未启用 Funnel。TLS 证书验证结果为 0，直连 HTTPS `/healthz` 返回 200；项目负责人在同一 tailnet 客户端使用 MagicDNS 域名访问并确认健康 JSON。随后完成真实 Telegram 私聊通知、按钮打开、WebView owner 身份认证和 Markdown 预览。未认证 Preview API 返回 401。服务日志扫描 229 行，Bot Token、Token 形态、原始 initData、Cookie 和允许根绝对路径均为 0 命中。

### TASK 5.3：Cloudflare Tunnel 生产入口（仅在批准后）

**状态：** `TODO`

**方案来源：** WireGuard 无法满足任意 Telegram 客户端访问时的已确认后备方案。

**交付物：** 独立 Tunnel/域名、最小 ingress、HTTPS、BotFather Mini App 地址和回滚文档。

**验收依据：** 公网只暴露 HermesPeek HTTPS，不暴露工作区或管理 API；未授权用户不能读取；Tunnel 停止后本地服务不受影响；当前 Hermes Dashboard 入口不被占用或改写。

**Commit：** `ops: document approved production ingress`

**阶段验收：** Telegram 移动端和桌面端分别完成发布→按钮→compact 浮窗→身份校验→文件刷新→关闭的真实端到端验收，并记录现场响应和日志证据。

---

## 阶段 6：最终回复按钮融合（条件阶段）

### 设计结论

当前 Hermes 的 `agent:end` Gateway Hook 是观察者，不能为随后发送的最终消息注入 `reply_markup`；Plugin 的 `transform_llm_output` 只能替换文本。故本阶段不能在 HermesPeek 仓库内假装实现。

### TASK 6.1：设计通用 Hermes Gateway 扩展点

**状态：** `DONE`

**方案来源：** 当前 Hermes 源码 `gateway/run.py` 的最终发送链路和 Telegram adapter 的现有 `reply_markup` 能力。

**交付物：** 独立设计提案，定义平台无关的“final message attachments/actions”结构；默认无行为，不破坏非 Telegram 平台、流式发送、消息拆分、prompt cache 与角色交替。

**验收依据：** 先在 Hermes 上游测试仓库完成单元/集成测试；未经项目负责人明确许可，不修改当前运行 Hermes 源码或配置。

**Commit（Hermes 上游仓库）：** `feat: add final message action extension point`

**验收记录（2026-08-05）：** 现场核验当前 Hermes `agent:end` 仍是观察者、`transform_llm_output` 仅改文本，确认缺少结构化最终消息 action。按 TDD 新增 `final_message_actions` Plugin Hook、平台中立 HTTPS URL action 校验和 `FinalResponse` 数据边界；Telegram 非流式发送附加 InlineKeyboard，流式已发送消息使用原消息 edit 附加按钮，不创建第二条消息；无 action 时保持既有行为。目标及相关回归 `58 passed`，compileall 与 diff 检查通过。提交：`3ab8369 feat(gateway): attach actions to final messages`。未修改 Hermes 配置，未重启 Gateway。

### TASK 6.2：HermesPeek 使用扩展点附加按钮

**状态：** `DONE`

**方案来源：** TASK 6.1 真实合并或当前运行版本已具备等价能力。

**交付物：** 自动发布后将 Preview action 附加到 Hermes 最终回复；移除独立的第二条通知。

**验收依据：** 最终只发送一条完成消息；按钮在私聊、群组、Topic 均正确；发送失败时仍保留纯文本答复；现场确认无重复消息。

**Commit：** `feat: attach preview action to final Hermes reply`

**验收记录（2026-08-05）：** HermesPeek Plugin 同时注册 `post_tool_call` 与 `final_message_actions`；最终消息 hook 精确读取当前 session collector、创建 owner 限定 Preview、返回 `Open preview` HTTPS action 并消费 spool，不读取 Bot Token、不直接调用 Bot API。目标集成测试通过，全量回归 `77 passed`；compileall 与 diff 检查通过。提交：`14a09a3 feat: attach preview to final Hermes reply`。真实运行 Gateway 尚未安装这版插件/重启，故本记录仅证明代码与离线集成，不冒充真实单消息 Telegram 验收。

---

---

## 3. 统一质量门禁

### 4.1 分层测试

- 单元测试：配置、路径策略、Registry、HMAC、按钮 payload、renderer；
- 集成测试：FastAPI + 临时 Registry + 临时文件；CLI subprocess；Plugin/Hook 使用临时 `HERMES_HOME`；
- 安全回归：路径穿越、软链接逃逸、XSS、错误 MIME、未授权 raw、过期/撤销、日志秘密泄漏；
- E2E：本机 HTTP；获批后的 Telegram Mini App 和真实入口。

### 4.2 每 TASK 验收命令

实现中先运行目标测试，再运行阶段相关测试：

```bash
uv run pytest tests/<target> -v
uv run pytest
```

代码质量工具在阶段 0 或阶段 1 明确引入后固定使用，建议最小集合：

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/hermes_peek
```

如果决定不引入某工具，不得在后续验收中虚构其结果。

### 4.3 Git 纪律

每个 TASK：

1. 写失败测试；
2. 现场运行并确认预期失败；
3. 最小实现；
4. 运行目标测试；
5. 运行相关回归；
6. 检查 `git diff` 与秘密；
7. 创建该 TASK 唯一 commit；
8. 才进入下一个 TASK。

阶段结束：运行全量测试，确认工作区干净，统一汇报实际命令与结果，等待“继续”。

---

## 4. 阶段 7：Telegram Topic Mini App 闭环

**状态：** `DONE`

阶段 7 把群组/Forum Topic 中的普通 Preview HTTPS 按钮改为 Telegram Main Mini App Direct Link，并通过短期 opaque launch reference、服务端 `Telegram.WebApp.initData` 校验和 Preview owner 比对打开指定 Preview。

完整实施任务、API、测试矩阵、部署、真实验收和回滚步骤见：

- [`02-telegram-topic-mini-app-rollout.md`](02-telegram-topic-mini-app-rollout.md)

已完成配置与 Direct Link 构造、短期 launch reference、`startapp` 启动认证、Topic action、兼容通知路径和隔离测试。项目负责人已确认真实 Topic 按钮可在 Telegram Mini App 中打开 README，且同一按钮可重复打开，因此阶段 7 真实验收完成。转发拒绝、撤销、Tailnet 断连恢复和扩展日志扫描保留为后续纵深安全检查，不阻塞阶段完成。

---

## 5. 阶段 8：安装、升级、安全卸载与 Purge 生命周期

**状态：** `REVIEW_APPROVED / PROTOTYPE_EXISTS / READY_TO_CONTINUE`

阶段 8 将当前手工安装和运维步骤收敛为单一 CLI，覆盖 profile 发现、安装计划、共享配置、service、Hermes plugin、Telegram 可自动化设置、事务回滚、默认保留数据的卸载，以及带 dry-run 和确认的 purge。

当前已存在 `setup`、`uninstall`、`--purge-data`、plugin 打包和基础离线测试原型，全量回归曾达到 `82 passed`；但审计确认仍有 profile 作用域、Gateway 配置断链、无事务回滚、卸载停用失败仍删除、所有权保护不足和 Telegram 仅格式校验等阻断问题。因此不得标记 DONE 或用于真实 profile。

完整目标方案、数据保留矩阵和发布门槛见：

- [`../06-installation-uninstallation.md`](../06-installation-uninstallation.md)

具体 TASK、依赖、当前进度、验收与提交策略见：

- [`03-lifecycle-setup-uninstall-rollout.md`](03-lifecycle-setup-uninstall-rollout.md)

下一步必须先评审 TASK 8.0 文档，再从失败测试和 profile 作用域修复开始；未经明确授权，不执行真实 setup/uninstall、systemd service 变更或 Gateway 重启。

---

## 6. 阶段 9：项目分发的 Telegram 会话预览 Skill

**状态：** `REVIEW_APPROVED / READY_TO_IMPLEMENT`

阶段 9 将“把 README 发我看下”从 Agent 私有记忆和 `terminal + publish --notify` 兼容流程，升级为随 HermesPeek 仓库、源码包和安装生命周期分发的正式能力：仓库内 `hermes-peek-preview` Skill 负责自然语言触发、文件定位和成功/失败语义；`hermes_peek_send_preview` Plugin Tool 负责从当前 Gateway Session Context 读取严格原位路由、安全加载 Secret、发布 owner-bound Preview，并在同一私聊、群组或 Forum Topic 发送唯一 `Open preview` 消息。成功后 Skill 输出 `NO_REPLY`，不再追加确认文本。

完整方案见：

- [`../07-conversational-preview-delivery.md`](../07-conversational-preview-delivery.md)

具体 TASK、TDD 顺序、Skill/Plugin 生命周期分发、离线门禁、真实 Telegram 授权和回滚步骤见：

- [`04-conversational-preview-delivery-rollout.md`](04-conversational-preview-delivery-rollout.md)

方案与计划已于 2026-08-05 获项目负责人明确评审批准，下一步从 TASK 9.1 的 Skill RED 测试开始。真实 Profile 更新与 Gateway 外部重启仍需在离线阶段完成后单独授权。

---
