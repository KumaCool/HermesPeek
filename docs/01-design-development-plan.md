# 01 HermesPeek 设计与开发方案

**Goal:** 构建一个轻量、只读、安全的 Hermes 产物预览服务，使用户能从 Telegram 消息中的“预览”按钮打开 Mini App 浮窗，查看 Hermes 本轮修改文件的磁盘最新内容。

**Architecture:** 采用 Python 模块化单体：FastAPI 同时提供 Preview API 与原生 HTML/CSS/JS 前端；文件系统保存 Preview Registry，不引入数据库；独立 CLI 负责显式发布；Hermes 插件记录写文件工具产生的路径，Gateway Event Hook 在 `agent:end` 阶段发布并发送 Telegram 通知。应用只监听本地地址，HTTPS 和公网入口由外层网络设施提供。

**Tech Stack:** Python 3.11+、FastAPI、Uvicorn、Pydantic、httpx、原生 HTML/CSS/JS、Telegram Mini Apps API、pytest、uv。

---

## 1. 方案依据

### 1.1 产品决策来源

来源：[`docs/00-product-decisions.md`](00-product-decisions.md)

已确认约束：

- 复用当前 Hermes Telegram Bot；
- 预览磁盘实时文件，不制作完成时快照；
- 对外只暴露随机 Preview ID，不暴露绝对路径；
- 默认仅任务发起人可访问；
- 首版支持 Markdown、代码/文本、JSON/YAML/TOML、HTML、图片和 PDF；
- 先做 `hermes-peek publish`，稳定后自动接入 Hermes；
- 私聊使用 `web_app`，群组/Topic 使用 Mini App Direct Link；
- 应用入口可替换，WireGuard 仅用于受控设备测试，需要普遍访问时再使用 Cloudflare Tunnel。

### 1.2 Hermes 官方能力依据

来源：Hermes 本机官方文档与当前源码：

- `website/docs/user-guide/features/hooks.md`
- `website/docs/user-guide/features/plugins.md`
- `gateway/hooks.py`
- `gateway/run.py`

现场确认的能力边界：

1. General Plugin 的 `post_tool_call` 可取得 `tool_name`、`args`、`result`、`task_id/session_id`，适合记录 `write_file`、`patch` 等工具写入的文件路径。
2. Gateway Event Hook 的 `agent:end` 可取得 `platform`、`user_id`、`chat_id`、`thread_id`、`chat_type`、`session_id` 与截断后的最终响应，适合完成发布和 Telegram 路由。
3. `agent:end` 在 Hermes 最终普通消息发送前触发，但 Hook 不能修改最终发送参数，也不能为原消息附加 `reply_markup`。
4. 因此首个自动化版本必须发送一条独立的预览通知；把按钮合并进 Hermes 最终回复需要 Hermes 提供通用的最终消息 `reply_markup` 扩展点，不能伪装成现有能力。
5. Gateway Hook 和 Plugin 出错均不阻断主 Agent，HermesPeek 集成应保持 best-effort，失败时只记录日志。

### 1.3 当前代码状态依据

当前仓库已有最小骨架：

- `src/hermes_peek/app.py`：`/healthz`、首页、按绝对路径预览文本文件；
- `tests/test_app.py`：5 个基础测试；
- `pyproject.toml`：FastAPI、Uvicorn、pytest；
- Git 仓库尚无 commit，现有骨架处于 staged/modified 状态。

当前实现只能作为验证骨架，不能直接作为产品接口，因为 `/preview?path=<absolute-path>` 会把真实路径暴露给客户端，且尚无 Preview Registry、Telegram 鉴权与多格式渲染。

---

## 2. 总体设计

### 2.1 模块化单体结构

```text
HermesPeek/
├── pyproject.toml
├── README.md
├── docs/
│   ├── 00-product-decisions.md
│   ├── 01-design-development-plan.md
│   ├── 02-architecture.md
│   ├── 03-security.md
│   ├── 04-hermes-integration.md
│   ├── 05-operations.md
│   └── plan/
│       └── 01-implementation-task-plan.md
├── src/hermes_peek/
│   ├── __init__.py
│   ├── app.py                 # FastAPI app factory 与路由装配
│   ├── cli.py                 # hermes-peek publish/serve/revoke/inspect
│   ├── config.py              # 类型化配置
│   ├── models.py              # PreviewRecord、FileEntry、AuthSession
│   ├── registry.py            # 文件系统 Registry 与原子写入
│   ├── paths.py               # 路径解析、安全边界、文件分类
│   ├── auth.py                # Telegram initData 验证与会话签发
│   ├── service.py             # 发布、读取、撤销、过期判断
│   ├── telegram.py            # Bot API 消息与按钮构造
│   ├── renderers/
│   │   ├── base.py
│   │   ├── text.py
│   │   ├── markdown.py
│   │   ├── structured.py
│   │   ├── image.py
│   │   ├── pdf.py
│   │   └── html.py
│   ├── templates/
│   │   └── preview.html
│   └── static/
│       ├── app.css
│       └── app.js
├── integrations/hermes/
│   ├── plugin.yaml
│   ├── __init__.py            # post_tool_call 路径收集器
│   ├── collector.py
│   ├── HOOK.yaml
│   └── handler.py             # agent:end 发布/通知
└── tests/
    ├── conftest.py
    ├── unit/
    ├── integration/
    └── e2e/
```

不拆微服务，不引入 PostgreSQL、Redis、WebSocket、React/Vue 或对象存储。

### 2.2 运行时数据结构

默认状态目录：

```text
${XDG_STATE_HOME:-~/.local/state}/hermes-peek/
├── previews/
│   └── <preview_id>.json
├── sessions/
│   └── <session_hash>.json
├── collector/
│   └── <hermes_session_id>.json
└── logs/
```

每个 Preview 使用独立 JSON 文件，写入流程采用“临时文件 → `fsync` → `os.replace`”原子替换，避免一个全局 JSON 文件产生并发覆盖。

`PreviewRecord` 建议字段：

```json
{
  "schema_version": 1,
  "preview_id": "pv_<256-bit-url-safe-token>",
  "title": "HermesPeek 设计文档",
  "created_at": "ISO-8601",
  "expires_at": "ISO-8601 or null",
  "revoked_at": null,
  "owner_telegram_user_id": "<telegram-user-id>",
  "source_chat_id": "<telegram-chat-id>",
  "source_thread_id": "<telegram-thread-id-or-empty>",
  "source_session_id": "...",
  "entry": "docs/02-architecture.md",
  "files": [
    {
      "id": "f_<stable-hash>",
      "display_path": "docs/02-architecture.md",
      "absolute_path": "/resolved/server/path",
      "kind": "markdown"
    }
  ]
}
```

绝对路径只保存在服务端 Registry，任何 API 响应、HTML、日志和 Telegram URL 都不得返回它。

### 2.3 请求与认证流程

```text
Telegram 按钮
    │
    ▼
GET /p/<preview_id>                # 只返回不含文件内容的 App Shell
    │
    ▼
POST /api/auth/telegram
  - preview_id
  - Telegram.WebApp.initData
    │
    ├─ 验证 Telegram HMAC
    ├─ 检查 auth_date
    ├─ 检查 Preview owner/chat/revoked/expiry
    └─ 签发短期 HttpOnly 会话 Cookie
    │
    ▼
GET /api/previews/<preview_id>     # 文件列表与公开元数据
GET /api/previews/<id>/files/<fid> # 实时读取磁盘内容
```

安全原则：Preview ID 只用于定位记录，不作为唯一身份认证；真正文件内容必须在 Telegram `initData` 验证通过后读取。

### 2.4 实时文件语义

- 发布时保存经过解析和校验的服务端文件引用；
- 每次请求内容时重新执行 `resolve(strict=True)`、允许根检查、敏感路径检查、类型检查和大小检查；
- 文件修改后刷新页面显示最新内容；
- 文件删除、移出允许根、变成软链接逃逸目标或改成不支持类型时返回明确的不可用状态；
- 不提供编辑、保存、删除、执行代码等写接口。

### 2.5 Preview API

```text
GET    /healthz
GET    /p/{preview_id}
POST   /api/auth/telegram
POST   /api/auth/dev                 # 仅显式 development 模式可用
DELETE /api/auth/session
GET    /api/previews/{preview_id}
GET    /api/previews/{preview_id}/files/{file_id}
GET    /api/previews/{preview_id}/files/{file_id}/raw
```

管理操作只通过本机 CLI，不开放公网管理 API：

```text
hermes-peek publish [FILES...] --entry FILE --title TITLE --owner USER_ID
hermes-peek inspect PREVIEW_ID
hermes-peek revoke PREVIEW_ID
hermes-peek serve
```

### 2.6 内容渲染策略

- Markdown：服务端解析，禁用或清洗原始 HTML；代码块高亮；本地产物图片仅允许通过同一 Preview 的 `file_id` 引用。
- 代码/文本：HTML 转义、行号、长行横向滚动、复制按钮；不执行内容。
- JSON/YAML/TOML：只读解析；解析失败时降级为纯文本并显示错误，不阻断查看。
- 图片：只允许白名单 MIME；设置 `nosniff`；从鉴权 API 返回。
- PDF：浏览器内嵌预览并提供受控下载；响应必须经过同一授权检查。
- HTML：在 `<iframe sandbox="allow-scripts">` 中显示；首版不开放 `allow-same-origin`、表单、弹窗和顶层导航；只支持单文件 HTML，跨文件资源作为后续明确需求处理。

### 2.7 Telegram 按钮策略

私聊：

```json
{
  "text": "👁 预览",
  "web_app": {"url": "https://<host>/p/<preview_id>"}
}
```

群组/Topic：

```json
{
  "text": "👁 预览",
  "url": "https://t.me/<bot_username>/<app_short_name>?startapp=<preview_id>&mode=compact"
}
```

Topic 消息必须携带 `message_thread_id`。Mini App 通过 `start_param` 获取 Preview ID，但后端只信任验证后的原始 `initData`。

---

---

## 3. 测试与质量门禁

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

---

## 4. 风险与应对

| 风险 | 证据/原因 | 应对 |
|---|---|---|
| Preview ID 泄漏后被直接访问 | Telegram 消息链接可转发 | ID 只定位记录；内容读取必须验证 initData 和 owner |
| 实时文件在发布后越界或变成软链接 | 文件会继续变化 | 每次读取都重新 resolve 和执行完整安全策略 |
| HTML 预览执行恶意内容 | Agent 产物不等于可信网页 | sandbox + CSP；首版单文件；不开放 same-origin/forms/popups |
| Hook 猜错本轮文件 | `agent:end` 不含文件列表 | Plugin 精确观察 write/patch；不从响应文本或 shell 命令猜路径 |
| 自动集成影响 Hermes 正常答复 | Hook/通知属于边缘功能 | best-effort、幂等、错误隔离；无文件时静默 |
| 最终回复按钮无法合并 | 当前 Hook 无 reply_markup 注入能力 | 先发送独立消息；仅在通用上游扩展真实可用后融合 |
| WireGuard 无法满足 Telegram HTTPS | WG 只提供私网路由 | 先现场验证；失败后经授权切换独立 Cloudflare Tunnel |
| Registry 长期增长 | 每次任务可能创建记录 | 提供 expiry/revoke；后续增加显式 `gc`，不首版引入后台调度器 |
| Bot Token/签名密钥泄漏 | Telegram API 与 HMAC 必需 | 只放 secret env；日志脱敏；测试使用固定假 token |

---

## 5. 明确不做的事项

首版不做：

- 数据库、Redis、对象存储；
- WebSocket/SSE 过程直播；
- 工作区目录浏览；
- 编辑或写回文件；
- 任意绝对路径 URL；
- 猜测 `terminal` 命令修改了哪些文件；
- 多租户管理后台；
- HTML 多文件站点完整托管；
- 未获许可的 Hermes 配置修改；
- 未获许可的端口、HTTPS、反向代理、Tailscale Serve、Cloudflare Tunnel 或防火墙变更。

---

## 6. 推荐实施顺序

```text
阶段 0  基线与文档
  ↓
阶段 1  Registry + publish CLI
  ↓
阶段 2  Telegram 鉴权 + 多格式 Mini App
  ↓
阶段 3  显式 Telegram 通知闭环
  ↓
阶段 4  Hermes 自动收集 + 第二条预览消息
  ↓
阶段 5  经授权部署 HTTPS 真实入口
  ↓
阶段 6  条件满足后融合最终回复按钮
```

**第一开发目标不是自动化，而是证明安全的显式闭环：**

```text
hermes-peek publish
→ 随机 Preview ID
→ Telegram 身份验证
→ Mini App 读取磁盘最新文件
→ 用户刷新即可看到变化
```

只有该闭环真实验收通过后，才接入 Hermes Plugin 与 Gateway Hook。这样能将文件安全、Telegram 鉴权、网络入口和 Hermes 自动化四类问题分开验证，避免在一个阶段同时排查全部链路。
