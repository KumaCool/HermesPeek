# HermesPeek Base Path 改造方案

> **状态：** 待评审；本文件仅为方案，不实施代码、服务、Gateway、Telegram 或网络变更。
>
> **For Hermes:** 方案获明确批准后，再按阶段实施；每个 TASK 现场验收后创建独立 Git commit。

**目标：** 允许 HermesPeek 部署在共享 HTTPS 域名的子路径下，例如 `https://example.test/hermespeek`，同时保留现有根路径部署 `https://example.test` 和本机回环服务接口。

**架构：** 将 `external_base_url` 从“仅 HTTPS Origin”提升为“HTTPS 公共基址”，其 path 即 Base Path。反向代理负责把公共前缀剥离后转发给仍运行在 `/` 的本地应用；HermesPeek 统一从公共基址生成 Preview URL、外部健康检查 URL、前端资源/API URL及 Cookie Path。本机 `127.0.0.1:8765/healthz` 不改变。

**技术栈：** Python 3.11+、FastAPI/Starlette、Uvicorn、原生 HTML/CSS/JS、pytest/httpx、现有事务化 setup 生命周期。

---

## 1. 现状与问题证据

现场只读检查显示：

1. `src/hermes_peek/service.py:106-110` 已能把 `external_base_url` 中的 path 保留到 Preview URL，例如已有测试期望 `https://preview.example.test/root/p/<id>`。
2. `src/hermes_peek/setup_wizard.py:37-50` 明确拒绝任何 path；README 也要求 `--external-url` 不带路径，因此正式 setup 无法提交 Base Path。
3. `src/hermes_peek/app.py` 与 `src/hermes_peek/static/app.js` 使用根绝对路径：`/static/*`、`/api/*`、`/p/*`。即使绕过 setup 配置，浏览器也会跳出 Base Path。
4. Session Cookie 的 `path="/"`，Base Path 部署时授权 Cookie 暴露范围过宽；登出删除也只按 `/` 处理。
5. 外部健康探测大多以 `base.rstrip('/') + '/healthz'` 拼接，基本可保留 path，但实现分散，存在重复拼接和回归风险。
6. `SystemdUserBackend` 的本地健康检查固定为 `http://127.0.0.1:8765/healthz`。这是正确的本地运行态契约，不应随公共 Base Path 改变。

## 2. 需求边界

### 2.1 必须支持

| 场景 | 公共基址 | 公共入口示例 | 本地上游 |
|---|---|---|---|
| 现有根部署 | `https://example.test` | `/healthz`、`/p/<id>` | `/healthz`、`/p/<id>` |
| Base Path 部署 | `https://example.test/hermespeek` | `/hermespeek/healthz`、`/hermespeek/p/<id>` | `/healthz`、`/p/<id>` |
| 多级 Base Path | `https://example.test/apps/hermespeek` | `/apps/hermespeek/...` | `/...` |

### 2.2 明确不做

- 不新增独立 `--base-path` 配置；Base Path 直接取自 `--external-url` 的 path，避免双配置漂移。
- 不改变本地监听地址、端口或内部路由。
- 不自动创建或修改 Tailscale Serve、Nginx、Caddy、Traefik、Cloudflare、DNS、TLS 或防火墙规则。
- 不同时支持“代理保留前缀”和“代理剥离前缀”两种上游语义；首版只支持并记录**剥离公共前缀后转发到上游根路径**。
- 不信任请求头动态决定 Base Path，避免伪造 `X-Forwarded-Prefix` 影响 URL/Cookie 安全边界。
- 不迁移 Preview Registry；Preview 记录不含固定 URL，配置变更后新旧 Preview ID 均按新基址访问。

## 3. 核心设计决策

### 3.1 单一配置源

保留字段和 CLI 名称：

```text
external_base_url = https://example.test/hermespeek/
--external-url https://example.test/hermespeek
HERMES_PEEK_EXTERNAL_BASE_URL=https://example.test/hermespeek/
```

配置提交时统一规范化为：

- 必须为 `https`；
- 必须有 hostname；
- 禁止 username/password、query、fragment；
- root 规范化为 `/`；
- 非 root Base Path 规范化为一个前导 `/` 和一个结尾 `/`；
- 拒绝 `//`、`.`、`..`、反斜杠和百分号编码路径，首版仅接受 URL-safe ASCII path segment（`A-Z a-z 0-9 - . _ ~`，但 segment 不得等于 `.`/`..`）。

示例：

```text
https://example.test                    -> https://example.test/
https://example.test/hermespeek         -> https://example.test/hermespeek/
https://example.test/apps/hermespeek/   -> 原样规范化保存
```

建议在 `src/hermes_peek/urls.py` 新增小型纯函数，集中承担：

```python
normalize_external_base_url(value: str) -> str
external_base_path(value: str) -> str        # "/" 或 "/hermespeek"
external_url(value: str, relative: str) -> str
```

`setup_wizard.py`、`lifecycle.py`、`service.py`、`lifecycle_ux.py` 和 CLI 外部验证均复用它，避免各自 `rstrip('/')`。

### 3.2 代理契约：公共前缀剥离

Base Path 部署的唯一支持契约：

```text
客户端:  GET https://example.test/hermespeek/p/pv_xxx
代理:    匹配 /hermespeek/*，移除 /hermespeek
上游:    GET http://127.0.0.1:8765/p/pv_xxx
```

原因：

- 保留现有 FastAPI 路由及本地运维接口；
- 无需把同一批路由 mount 两次；
- 根路径部署保持完全兼容；
- Tailscale/Nginx/Caddy 等代理差异收敛在部署层文档和验收，不进入应用路由逻辑。

FastAPI `root_path` 只描述被代理剥离的公共前缀，并不会自动重写硬编码 URL；因此本方案不会只设置 `root_path` 就宣称完成，而是同时修复 HTML、JS、Cookie 和探测 URL。

### 3.3 前端 URL 生成

服务端在页面中注入经过 HTML 转义的规范化 Base Path，例如：

```html
<body data-base-path="/hermespeek">
```

前端新增唯一 helper：

```javascript
function appUrl(path) {
  return `${basePath}${path.startsWith('/') ? path : `/${path}`}`;
}
```

所有以下位置必须改用 helper 或服务端生成 URL：

- launch auth：`/api/auth/telegram/launch`；
- Preview 跳转：`/p/<id>`；
- Preview auth、metadata、file、raw API；
- CSS 与 JS 静态资源 URL。

建议 HTML 静态资源和跳转由服务端基于 `base_path` 生成，`app.js` 的运行时 API/raw URL 使用 `appUrl()`；不依赖 `<base>` 标签，避免相对 URL 与当前 `/p/<id>` 路径组合产生歧义。

### 3.4 Cookie 范围

Session Cookie 的 Path 设置为规范化 Base Path：

```text
根部署:       Path=/
Base Path:    Path=/hermespeek
```

设置和删除必须使用同一个值。这样 Cookie 不会发送给共享域名上的无关应用。Cookie 名称、Secure、HttpOnly、SameSite 和 15 分钟有效期不改变。

### 3.5 公共 URL 与健康检查

所有公共 URL 从同一 helper 生成：

```text
Preview:  <external_base_url>/p/<preview_id>
Health:   <external_base_url>/healthz
Menu:     <external_base_url>（Mini App landing page）
```

本地服务健康检查仍为：

```text
http://127.0.0.1:8765/healthz
```

`status` / `doctor` 的 HTTPS 检查必须探测 Base Path 下的 `/healthz`；MagicDNS fallback 也必须保留完整 path。错误文案由 “HTTPS origin” 改为 “external HTTPS base URL”，避免继续暗示只接受 Origin。

### 3.6 兼容与升级

- 配置 schema 继续使用 `schema_version: 1`：字段类型未变，旧值是新约束的合法子集，不需要迁移。
- 根部署输出 URL 与路由保持不变。
- Patch-style setup 继续遵循显式参数 > 已提交配置 > 交互输入；只修改 allowed roots 时必须保留现有含 Base Path 的 URL。
- `update` 重新应用现有配置时不得截断 path。
- 改变 `--external-url` 会引起服务配置重写和既有生命周期激活流程；真实环境是否同时改代理规则属于独立网络变更，必须另行批准。

## 4. API 与部署契约

### 4.1 应用内部路由（不变）

```text
GET    /healthz
GET    /
GET    /p/{preview_id}
POST   /api/auth/telegram
POST   /api/auth/telegram/launch
DELETE /api/auth/session
GET    /api/previews/{preview_id}
GET    /api/previews/{preview_id}/files/{file_id}
GET    /api/previews/{preview_id}/files/{file_id}/raw
GET    /static/*
```

### 4.2 公共路由

若 Base Path 为 `/hermespeek`，对应为：

```text
GET    /hermespeek/healthz
GET    /hermespeek/
GET    /hermespeek/p/{preview_id}
POST   /hermespeek/api/auth/telegram
...
GET    /hermespeek/static/*
```

### 4.3 代理验收条件

代理配置不归 HermesPeek 生命周期所有，但文档必须要求现场证明：

1. 公共 `/hermespeek/healthz` 返回 HermesPeek health JSON；
2. 公共 `/healthz` 不被 HermesPeek 占用（共享域名隔离成立）；
3. 公共 Preview shell 引用 `/hermespeek/static/*`；
4. 浏览器实际 API 请求全部位于 `/hermespeek/api/*`；
5. 上游仍只监听 loopback；
6. 未修改 Funnel/公网范围，除非另有明确批准。

## 5. 实施阶段与任务

> 每个 TASK 的“来源”均指本方案相应章节；无方案来源的事项不得进入实施。

### 阶段 1：公共基址模型与生命周期输入

#### 阶段 1 验收记录

- [x] `TASK 1.1` 集中规范化公共基址
  - Status: ✅ 已验收
  - Implementation: 新增统一 URL helper；setup/lifecycle 接受并规范化 root、单级及多级 Base Path，拒绝不安全或歧义路径。
  - Acceptance command: `uv run pytest tests/unit/test_urls.py tests/unit/test_setup_wizard.py tests/integration/test_lifecycle.py -q`
  - Acceptance result: 74 passed
  - Commit: `a07a061`
  - Updated: 2026-08-08 20:59 CST
- [x] `TASK 1.2` 统一 Preview URL 与外部健康探测
  - Status: ✅ 已验收
  - Implementation: Preview、setup preflight/final verify、status/doctor 与 MagicDNS fallback 统一保留 Base Path；本地 loopback health 未改。
  - Acceptance command: `uv run pytest tests/unit/test_service.py tests/integration/test_lifecycle_ux.py tests/unit/test_setup_wizard.py -q`
  - Acceptance result: 47 passed
  - Commit: `b7b5eab`
  - Updated: 2026-08-08 20:59 CST

#### TASK 1.1：集中规范化公共基址

**来源：** §3.1、§3.5
**交付物：**

- Create: `src/hermes_peek/urls.py`
- Create: `tests/unit/test_urls.py`
- Modify: `src/hermes_peek/setup_wizard.py`
- Modify: `src/hermes_peek/lifecycle.py`
- Modify: `tests/unit/test_setup_wizard.py`
- Modify: `tests/integration/test_lifecycle.py`

**RED 验收：** 新测试证明当前实现拒绝合法 Base Path，并覆盖 root、多级 path、规范化及非法 path。
**GREEN 验收：** `uv run pytest tests/unit/test_urls.py tests/unit/test_setup_wizard.py tests/integration/test_lifecycle.py -q` 全部通过。
**Commit：** `feat: accept external base URLs with path prefixes`

#### TASK 1.2：统一 Preview URL 与外部健康探测

**来源：** §3.5
**交付物：**

- Modify: `src/hermes_peek/service.py`
- Modify: `src/hermes_peek/lifecycle_ux.py`
- Modify: `src/hermes_peek/cli.py`
- Modify: `tests/unit/test_service.py`
- Modify: `tests/integration/test_lifecycle_ux.py`
- Modify: `tests/unit/test_setup_wizard.py`

**验收依据：** root 和多级 Base Path 的 Preview URL、普通 HTTPS probe、MagicDNS fallback path、setup preflight/final verify 均命中唯一正确的 `<base>/healthz`，没有双斜杠或 path 丢失。
**命令：** `uv run pytest tests/unit/test_service.py tests/integration/test_lifecycle_ux.py tests/unit/test_setup_wizard.py -q`
**Commit：** `fix: preserve base paths in public URL probes`

### 阶段 2：Web 应用 Base Path 感知

#### TASK 2.1：修复 HTML、静态资源与 launch 跳转

**来源：** §3.2、§3.3
**交付物：**

- Modify: `src/hermes_peek/app.py`
- Modify: `tests/integration/test_mini_app.py`
- Modify: `tests/test_app.py`

**验收依据：** 对 Base Path 配置创建 app 后，home/Preview shell 中的静态资源、launch auth 和跳转均带 `/hermespeek`；根部署仍输出现有根路径。HTML 不泄漏本地绝对路径。
**命令：** `uv run pytest tests/test_app.py tests/integration/test_mini_app.py -q`
**Commit：** `feat: render base-path-aware preview shells`

#### TASK 2.2：修复前端 API 与 raw 文件 URL

**来源：** §3.3
**交付物：**

- Modify: `src/hermes_peek/static/app.js`
- Modify: `tests/integration/test_mini_app.py`
- 如现有静态断言不足，Create: `tests/integration/test_base_path_web.py`

**验收依据：** auth、metadata、文本文件、图片/PDF raw 请求全部通过统一 `appUrl()` 生成；无残留 `fetch('/api`、``fetch(`/api``、`src = '/api`；根部署兼容。
**命令：** `uv run pytest tests/integration/test_mini_app.py tests/integration/test_base_path_web.py -q`（若新文件创建）
**Commit：** `feat: route preview frontend requests through base path`

#### TASK 2.3：收窄 Session Cookie Path

**来源：** §3.4
**交付物：**

- Modify: `src/hermes_peek/app.py`
- Modify: `tests/integration/test_auth_api.py`
- Modify: `tests/integration/test_launch_auth_api.py`（按仓库实际文件名定位）

**验收依据：** 两个登录入口的 `Set-Cookie` 均为 `Path=/hermespeek`；logout 使用相同 Path 删除；根部署仍为 `Path=/`。
**命令：** 运行所有 auth/launch API 定向测试。
**Commit：** `fix: scope preview sessions to the configured base path`

### 阶段 3：端到端回归与生命周期兼容

#### TASK 3.1：增加剥离前缀代理契约集成测试

**来源：** §3.2、§4
**交付物：**

- Create: `tests/integration/test_base_path_proxy.py`
- 必要时 Modify: `tests/integration/test_local_service.py`

**测试方式：** 使用 ASGI 测试代理或最小本地测试代理模拟 `/hermespeek/* -> /*` 剥离，不依赖真实网络配置。

**验收依据：** 完整链路覆盖公共 health、home、Preview shell、static、launch auth、metadata、file/raw；同时断言内部 `/healthz` 继续可用，公共生成 URL 始终包含 Base Path。
**命令：** `uv run pytest tests/integration/test_base_path_proxy.py tests/integration/test_local_service.py -q`
**Commit：** `test: cover stripped-prefix base path deployment`

#### TASK 3.2：验证 setup/reconfigure/update 配置保真

**来源：** §3.6
**交付物：**

- Modify: `tests/integration/test_lifecycle_reconfigure.py`
- Modify: `tests/integration/test_lifecycle.py`
- Modify: `tests/integration/test_lifecycle_ux.py`
- Modify: `tests/integration/test_release_installer.py`（仅当 fixture 对 URL path 有假设）

**验收依据：** fresh setup、单字段重配、重复 setup、update reapply 都保留规范化 Base Path；事务失败回滚恢复旧基址；`--plan` 仍只读且脱敏。
**命令：** `uv run pytest tests/integration/test_lifecycle_reconfigure.py tests/integration/test_lifecycle.py tests/integration/test_lifecycle_ux.py tests/integration/test_release_installer.py -q`
**Commit：** `test: preserve base paths across lifecycle operations`

### 阶段 4：文档与全量验收

#### TASK 4.1：同步架构、安全和普通用户文档

**来源：** §2、§4
**交付物：**

- Modify: `docs/02-architecture.md`
- Modify: `docs/03-security.md`
- Modify: `docs/05-operations.md`
- Modify: `docs/06-installation-uninstallation.md`
- Modify: `docs/08-one-click-ai-telegram-onboarding.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

**文档要求：**

- 将 “HTTPS Origin / 不带路径” 改为 “External HTTPS base URL / 可选 path prefix”；
- 明确代理必须剥离前缀；
- 给出 root 与 Base Path 两类配置和验证示例；
- Tailscale Serve 示例必须以当前 CLI 能力为准，且只作为用户明确执行的网络配置示例；
- 说明 HermesPeek 不接管代理规则，更新/卸载不会删除它；
- 英文与简中内容同步、自包含。

**验收依据：** 搜索仓库，不再存在与新契约冲突的 “without a path / 不能包含路径 / 不带路径” 指令；保留合理的“不要附加 `/healthz`”说明。
**Commit：** `docs: document base path deployments`

#### TASK 4.2：全量回归和发布前检查

**来源：** 全方案
**交付物：** 现场命令输出与 staged diff 审查；此 TASK 不自动发布 Release。

**验收命令：**

```bash
uv run pytest -q
uv run python -m compileall -q src integrations
uv build
```

随后：

- 检查 wheel/sdist 中包含新增模块和更新后的静态资源；
- 检查 `git diff --check`；
- 检查 staged diff 不含 Secret、Token、个人标识或本机路径；
- 根路径回归与 Base Path 代理集成测试均现场通过；
- 不改版本号、不打 tag、不推送 Release，除非另获发布批准。

**Commit：** 若仅验收无文件变化则不创建空 commit；若构建/打包修复产生变更，使用独立 `build:` commit 并重新全量验收。

## 6. 测试矩阵

| 维度 | 用例 |
|---|---|
| 基址 | root、单级 path、多级 path、尾斜杠输入 |
| 非法 URL | HTTP、凭据、query、fragment、`//`、`.`、`..`、反斜杠、percent-encoded path |
| URL 生成 | Preview、health、home/menu、static、auth、metadata、file、raw |
| Cookie | root Path、Base Path、登录、launch 登录、logout 删除 |
| 代理 | 剥离前缀后成功；未剥离属于明确不支持的部署错误 |
| 生命周期 | fresh setup、patch reconfigure、plan、rollback、update reapply |
| 兼容性 | 旧 root 配置无迁移、内部 loopback health 不变 |
| 安全 | 不信任 forwarded prefix；公共 `/healthz` 不误指向共享域名根；无本机路径/Secret 泄漏 |

## 7. 风险与控制

| 风险 | 后果 | 控制 |
|---|---|---|
| 代理未剥离前缀 | 上游 404 | 文档固定单一代理契约；离线代理集成测试；真实部署单独验收 |
| 只改 Preview URL，遗漏前端绝对路径 | 页面能开但资源/API 404 | HTML、JS 和端到端矩阵同时覆盖；搜索残留根绝对路径 |
| Cookie 仍为 `/` | 共享域名 Cookie 范围过宽 | Base Path 驱动 set/delete cookie；专门回归 |
| Base URL 规范化不一致 | 双斜杠、path 丢失、探测假失败 | 单一 `urls.py` helper，禁止散落字符串拼接 |
| 动态代理头被伪造 | URL/Cookie 前缀被攻击者影响 | Base Path 只来自已提交配置，不读取 forwarded-prefix header |
| 真实网络改动混入代码实施 | 影响现有 Dashboard/Serve 路由 | 本方案只做仓库改造；任何 Tailscale/代理变更独立申请授权 |

## 8. 评审决策点

建议批准以下默认选择：

1. **配置面：** 继续只用 `--external-url`，允许它包含 Base Path，不新增 `--base-path`。
2. **代理语义：** 只支持“公共前缀剥离后转发上游根路径”。
3. **路径字符集：** 首版只支持 URL-safe ASCII segment，不支持 percent-encoded 或 Unicode path。
4. **兼容策略：** 配置 schema 保持 v1，旧 root 配置零迁移。
5. **实施边界：** 本轮仅改仓库代码、测试和文档；不修改真实 HermesPeek 配置、Gateway、Telegram、Tailscale Serve 或其他网络入口。

## 9. 完成定义

只有同时满足以下条件，才可称“Base Path 代码能力完成”：

- root 与 Base Path 自动化测试现场通过；
- 公开 URL、HTML、JS、Cookie、外部 health 全部使用同一基址语义；
- 本地 loopback service health 不变；
- setup/reconfigure/update/rollback 保留 path；
- README 英文与简中以及架构/运维文档已同步；
- 全量测试、compileall、构建和包内容检查通过；
- staged diff 已完成隐私与 Secret 检查。

“真实部署验收完成”是更高一级状态，必须另获网络变更授权，并在实际代理与 Telegram 客户端上完成 `/hermespeek/healthz`、Preview 打开、认证、静态资源/API、Cookie Path 和共享域名隔离验证；自动化测试不能替代该现场验收。
