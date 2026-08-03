# 02 HermesPeek 架构

## 1. 目标与边界

HermesPeek 是轻量、只读的模块化单体，用于把经过显式选择的本地文件发布为不透明 Preview，并在 Telegram Mini App 中读取磁盘最新内容。

首版包含：

- 本地 `hermes-peek publish/inspect/revoke/serve` CLI；
- 文件系统 Preview Registry；
- FastAPI Preview API 与原生 HTML/CSS/JS 前端；
- Telegram `initData` 身份验证；
- 显式 Telegram 通知；
- 稳定后通过 Hermes Plugin 与 Gateway Hook 自动收集并发送独立预览消息。

首版不包含数据库、对象存储、工作区浏览、文件写回、过程直播或任意路径公开访问。当前 Hermes 也不具备让 `agent:end` Hook 给随后发送的最终回复附加按钮的能力；按钮融合属于条件阶段，不是当前能力。

## 2. 组件与职责

```text
CLI / Hermes integration
        │ publish(files, owner, context)
        ▼
Preview service ── Path policy
        │
        ▼
Filesystem registry
        │ preview_id
        ▼
FastAPI app ── Telegram auth ── Renderers ── Live filesystem read
        │
        ▼
Telegram Mini App
```

| 组件 | 职责 | 不负责 |
|---|---|---|
| `config.py` | 类型化行为配置和 Secret 引用 | 保存真实 Secret |
| `paths.py` | 允许根、敏感路径、类型、MIME、大小和软链接检查 | 用户身份认证 |
| `models.py` | 内部记录和公开 DTO | 文件 I/O |
| `registry.py` | 每条记录独立 JSON、原子写入、读取、撤销和过期 | 内容渲染 |
| `service.py` | 发布与读取用例编排 | HTTP/Telegram 细节 |
| `auth.py` | 校验 Telegram `initData`、owner 和短时会话 | 信任 `initDataUnsafe` |
| `renderers/` | 安全只读渲染 | 执行或修改产物 |
| `telegram.py` | Bot API payload 与通知 | 猜测本轮文件 |
| `app.py` | App factory、API 和前端装配 | 公网 TLS/路由 |
| Hermes 集成 | 精确收集成功写文件工具输出，并在 `agent:end` 发布 | 修改 Hermes 最终回复参数 |

## 3. 运行时数据

默认状态目录为 `${XDG_STATE_HOME:-~/.local/state}/hermes-peek/`：

```text
previews/<preview_id>.json
sessions/<session_hash>.json
collector/<hermes_session_id>.json
logs/
```

Preview ID 使用密码学安全的 URL-safe 随机值。Registry 中可保存服务端绝对路径，但 API、HTML、日志、CLI 默认输出和 Telegram URL 不得包含绝对路径。

记录采用临时文件写入、`fsync`、`os.replace` 的原子替换流程。损坏记录应被隔离为单条不可用，不得阻断其他 Preview。

## 4. 发布数据流

1. CLI 或 Hermes 集成提交文件、入口、标题、owner 与来源上下文。
2. Path policy 对每个文件执行 `resolve(strict=True)` 和完整安全校验。
3. Service 生成 Preview ID 和稳定的公开 file ID。
4. Registry 原子写入 PreviewRecord。
5. CLI 返回 Preview ID 和公开 URL，不输出真实路径。
6. 可选通知层发送 Telegram 按钮；通知失败不删除已经成功创建的 Preview。

Hermes 自动集成只观察成功的 `write_file`、`patch` 等明确文件工具结果。它不从最终答复、Shell 命令或文件时间戳猜测变更路径。

## 5. 读取与认证数据流

```text
GET /p/{preview_id}
  → 只返回不含文件内容的 App Shell
POST /api/auth/telegram
  → 验证原始 initData HMAC、auth_date、Preview 状态和 owner
  → 签发短时 HttpOnly/Secure/SameSite 会话
GET /api/previews/{preview_id}
  → 返回公开元数据与 file ID
GET /api/previews/{preview_id}/files/{file_id}
  → 再次执行路径安全检查
  → 读取磁盘最新内容
  → 安全渲染或返回受保护 raw 响应
```

Preview ID 只用于定位记录，不是访问凭据。前端可以读取 `initDataUnsafe` 用于界面便利，但服务端只信任经过 HMAC 校验的原始 `initData`。

## 6. 实时文件语义

HermesPeek 不制作完成时快照。每次内容请求都重新：

1. 解析真实路径；
2. 确认仍位于允许根；
3. 检查敏感路径、软链接、类型、MIME 和大小；
4. 读取磁盘当前内容。

文件删除、移出允许根、变成逃逸软链接或改成不支持类型后，Preview 返回明确的不可用状态，不回退到旧副本。

## 7. API 边界

公开读取接口：

```text
GET    /healthz
GET    /p/{preview_id}
POST   /api/auth/telegram
DELETE /api/auth/session
GET    /api/previews/{preview_id}
GET    /api/previews/{preview_id}/files/{file_id}
GET    /api/previews/{preview_id}/files/{file_id}/raw
```

`POST /api/auth/dev` 仅在显式 development 模式下存在。发布、检查、撤销和服务启动属于本机 CLI，不开放公网管理 API。

## 8. Telegram 与 Hermes 边界

- 私聊按钮使用 `web_app` HTTPS URL。
- 群组和 Forum Topic 使用 Mini App Direct Link；Topic 通知保留 `message_thread_id`。
- `agent:end` Hook 负责读取 collector、发布并发送独立通知；无文件时静默。
- Plugin/Hook 是 best-effort，异常不能阻断 Hermes 正常答复。
- 当前 Hook 不能修改最终消息的 `reply_markup`。只有 Hermes 上游提供通用 final-message action 扩展点后，才实施单消息按钮融合。

## 9. 部署边界

应用默认只绑定经批准的本地地址。TLS、域名、WireGuard、Cloudflare Tunnel、反向代理、防火墙和 BotFather 配置属于外层网络设施，均不由应用启动时自动修改，实施前需要单独授权。
