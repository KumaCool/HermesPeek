# 03 HermesPeek 安全模型

## 1. 安全目标

HermesPeek 的安全目标是：**只读、最小暴露、显式授权、失败关闭**。

受保护资产包括：

- 允许根之外的文件；
- 允许根内的 Secret、凭据、私钥、Cookie 和配置；
- Telegram Bot Token、会话签名密钥和 `initData`；
- 服务器绝对路径和内部部署信息；
- Preview owner、chat、topic 和 Hermes session 等关联元数据；
- 预览页面所在 Telegram WebView 的执行环境。

## 2. 信任边界

```text
不可信：URL、Preview ID、文件内容、文件扩展名、MIME 声明、initDataUnsafe、浏览器输入
    │
    ▼
HermesPeek：身份验证 + Preview 状态 + 路径策略 + 安全渲染
    │
    ▼
受信任但最小化：Registry、允许根、运行时 Secret
```

即使文件由 Hermes 生成，也按不可信内容处理。Preview ID 可被转发或泄漏，因此不能单独作为身份认证。

## 3. 文件访问策略

每次发布和每次读取都执行完整检查：

1. `Path.resolve(strict=True)`；
2. 确认目标是普通文件；
3. 确认解析后的路径仍在至少一个允许根内；
4. 拒绝软链接逃逸；
5. 拒绝敏感目录和文件名；
6. 检查扩展名、实际 MIME、文件大小和必要的 UTF-8 解码；
7. 读取前后错误均安全失败，不返回内部异常和绝对路径。

默认拒绝至少包括：

- `.env`、环境 Secret 文件；
- `.git`、`.ssh`、`.hermes`；
- 私钥、证书密钥、credential、cookie、token 文件；
- 浏览器 profile、依赖目录和缓存；
- 设备文件、目录、FIFO 和 socket；
- 超过配置上限或类型不在白名单的文件。

允许根必须显式配置。生产模式不得把 `/`、用户整个主目录或 Hermes 状态目录作为允许根。

## 4. 身份与授权

服务端验证 Telegram Mini App 原始 `initData`：

- 按 Telegram 规范计算和比较 HMAC；
- 使用常量时间比较；
- 检查 `auth_date` 最大年龄；
- 解析并校验 Telegram user ID；
- 确认 user ID 与 Preview owner 一致；
- 确认 Preview 未过期、未撤销；
- 必要时校验来源 chat/topic 约束。

`initDataUnsafe` 只能用于前端展示，不得作为授权依据。

验证成功后签发短时随机会话，Cookie 使用：

- `HttpOnly`；
- `Secure`（非 development）；
- 合适的 `SameSite`；
- 明确过期；
- `Path` 固定为已配置外部 HTTPS 基址的 Base Path（根部署为 `/`）；
- 服务端保存哈希，不保存可直接复用的明文 Token。

默认授权模式是仅任务发起人。群组其他成员即使拿到按钮 URL 也不能读取文件。

## 5. Preview 生命周期

Preview ID 使用密码学安全随机数，不使用顺序 ID、路径哈希或可预测 session ID。记录具有：

- 创建时间；
- 可选过期时间；
- 可选撤销时间；
- owner；
- 来源上下文；
- 文件公开 ID 与服务端路径映射。

过期和撤销应立即阻止新的元数据、内容和 raw 请求。不存在、过期和撤销可返回语义明确的状态，但响应不得泄漏真实路径或 Secret。

## 6. 内容安全

### 文本、代码和结构化数据

- 始终 HTML 转义；
- 不执行代码；
- JSON/YAML/TOML 解析失败时降级为转义纯文本；
- 错误信息不包含文件绝对路径或完整敏感内容。

### Markdown

- 禁用或清洗原始 HTML；
- 禁止 `javascript:` 等危险 URL；
- 本地资源只能映射到同一 Preview 已授权 file ID；
- Mermaid 等可执行扩展不作为默认能力。

### 图片与 PDF

- 不能只相信扩展名；校验允许 MIME；
- 设置 `X-Content-Type-Options: nosniff`；
- raw/下载路径执行同一身份、Preview 状态和文件策略检查。

### HTML

HTML 在隔离 iframe 中展示，首版只允许最小 sandbox。不得默认开放：

- `allow-same-origin`；
- `allow-forms`；
- `allow-popups`；
- 顶层导航。

响应设置限制性 CSP。首版仅支持单文件 HTML，不承诺完整托管多文件应用。

## 7. Web 安全头与缓存

按响应类型至少评估并测试：

- Content Security Policy；
- `X-Content-Type-Options: nosniff`；
- `Referrer-Policy: no-referrer`；
- `frame-ancestors` 与 Mini App 使用方式的兼容约束；
- 认证内容使用 `Cache-Control: no-store`；
- 不在 URL query、Referer 或日志中携带 `initData`、Bot Token、Cookie。

## 8. Secret 与日志

Bot Token、会话签名密钥和其他 Secret 只从 secret env 注入，不写入普通配置、仓库、Preview Registry、CLI 参数回显或测试夹具。

日志采用结构化最小字段，允许记录：Preview ID 的短哈希、结果分类、状态码和时间；禁止记录：

- 原始 `initData`；
- Bot Token、Cookie、Authorization header；
- 文件内容；
- 服务器绝对路径；
- 未脱敏异常响应正文。

异常发送和 HTTP 客户端错误必须先脱敏再记录或显示。

## 9. 网络与部署

应用不自行配置端口暴露、TLS、反向代理、Tailscale Serve、WireGuard、Cloudflare Tunnel、防火墙或 BotFather。默认仅监听批准的本地地址；任何外部访问范围变化都需要独立授权和现场验证。

生产入口必须使用受信任 HTTPS。公网只暴露读取与认证所需路径，不暴露工作区、Registry、管理 CLI 或目录索引。

外部 HTTPS 基址可包含经过严格校验的 ASCII 路径前缀；拒绝凭据、query、fragment、路径穿越、反斜杠、percent-encoded 或 Unicode 路径。路径前缀只来自本地已提交配置，不信任 `X-Forwarded-Prefix` 或其他客户端可伪造请求头。代理必须剥离公开前缀后再转发到回环上游；Cookie Path、静态资源、API、Preview 与外部健康检查必须使用同一规范化基址。

HermesPeek 不拥有外层代理规则。setup、update、rollback 和 uninstall 均不得创建、修改或删除 Nginx、Tailscale Serve、Tunnel、DNS、证书或防火墙配置。

## 10. 关键安全回归

必须自动化覆盖：

- `..` 路径穿越和根外绝对路径；
- 软链接从允许根逃逸；
- `.env`、`.git`、`.ssh`、`.hermes` 等敏感路径；
- 扩展名/MIME 欺骗、超大文件、非 UTF-8；
- 未知、过期、撤销 Preview；
- 篡改/过期 `initData` 和错误 owner；
- XSS、危险 Markdown URL、HTML sandbox/CSP；
- 未授权 raw 和缓存；
- root 与多级 Base Path 下的 URL、Cookie 和剥离前缀代理契约；
- 日志与 API 响应中的 Secret/绝对路径泄漏。

真实 Telegram、HTTPS 或外部入口验收不能由 Mock 或离线测试替代；未执行时必须明确写为未验收。
