# HermesPeek

[English](README.md) | **简体中文**

> 安全、只读地预览 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 创建的文件，并通过 Telegram 打开。

HermesPeek 是一个小型 Python 服务和命令行工具，用于在受保护的 Telegram Mini App 中查看指定本地文件的最新内容。它适合个人工作区、自托管部署，以及希望以清晰、可审计方式查看 Hermes 产物的开发者。

HermesPeek **不会**编辑、执行、上传或删除预览工作区中的文件。

## 工作方式

```text
文件被创建或修改
        ↓
HermesPeek 验证路径并发布 Preview
        ↓
Telegram 收到 Open preview 按钮
        ↓
Mini App 验证 Telegram 用户身份
        ↓
Mini App 从磁盘读取文件的当前内容
```

Preview 保存的是文件引用，而不是文件内容的静态副本。刷新页面时，HermesPeek 会重新执行安全检查并读取文件当前内容。如果文件已被删除、移到允许目录之外或变得不再安全，该文件将无法继续预览。

## 功能特性

- 使用不透明 Preview ID，通过 CLI 显式发布 Preview；
- 支持以下只读预览格式：
  - Markdown；
  - 源代码和纯文本；
  - JSON、YAML 和 TOML；
  - PNG、JPEG、GIF 和 WebP 图片；
  - PDF；
  - 受限制、沙箱化的 HTML；
- 使用签名的 Telegram `initData` 验证 Mini App 用户身份；
- Preview owner 授权和短期会话；
- 支持 Telegram 私聊按钮以及群组/Topic Mini App Direct Link；
- 可选的 Hermes 插件集成：
  - 收集成功执行的 `write_file` 和 `patch` 结果；
  - 安装并启用集成后，可在 Hermes 最终回复中添加 `Open preview` 操作；
- 安全路径处理：
  - 显式配置允许根目录；
  - 防止目录穿越和符号链接逃逸；
  - 拒绝敏感文件和敏感目录；
  - 限制文件大小和类型；
  - 每次读取时重新执行安全检查；
- 基于文件系统的 Registry，支持原子写入、过期、撤销和具备回滚能力的生命周期管理；
- 本地健康检查端点：`GET /healthz`。

## 安全边界

HermesPeek 只应通过经过批准的 HTTPS 入口对外提供服务。在完成威胁模型和部署配置审查前，请勿将其直接暴露到公共互联网。

不要把整个用户主目录、系统根目录 `/`、Hermes 状态目录或包含凭据的目录配置为允许根目录。

以下内容不适合作为 Preview 输入：

- `.env` 文件、Token、Cookie、密码、私钥和证书；
- `.git`、`.ssh`、`.hermes`、浏览器配置、缓存和依赖目录；
- 配置的允许根目录之外的文件；
- 超过文件大小限制的文件。

Preview ID 不是授权凭据。用户仍需通过有效的 Telegram 身份验证和 owner 授权。请勿将 Bot Token、Cookie、私钥、个人聊天 ID 或机器专属部署数据提交到仓库。

详细安全模型请参阅 [`docs/03-security.md`](docs/03-security.md)。

## 环境要求

- Python 3.11 或更高版本；
- [uv](https://docs.astral.sh/uv/)；
- 本地开发支持 Linux、macOS 或 Windows；
- 如需使用 Telegram Mini App，需要一个 Telegram 客户端可以访问的 HTTPS 地址；
- 只有在需要 Telegram 通知或 Mini App 集成时才需要 Telegram Bot。

## 开发环境安装

克隆仓库并安装锁定的开发依赖：

```bash
git clone https://github.com/<your-account>/HermesPeek.git
cd HermesPeek
uv sync --locked
```

运行 CLI 帮助，确认安装成功：

```bash
uv run hermes-peek --help
```

项目目前尚未发布为 PyPI 软件包。开发时请在仓库目录中使用 `uv run`，或者构建 wheel 后将其安装到独立环境。

## 启动本地预览服务

选择一个专门用于预览且不包含敏感信息的安全工作区。允许根目录属于当前部署环境配置，不应提交到仓库。

```bash
export HERMES_PEEK_ALLOWED_ROOTS="$PWD/example-workspace"
export HERMES_PEEK_STATE_DIR="$PWD/.hermes-peek-state"

uv run hermes-peek serve --host 127.0.0.1 --port 8765
```

服务只监听本机回环地址。在另一个终端中验证健康状态：

```bash
curl -fsS http://127.0.0.1:8765/healthz
```

预期响应：

```json
{"status":"ok","service":"hermes-peek"}
```

项目首页位于 <http://127.0.0.1:8765/>。文件必须先发布为 Preview 才能打开；旧版 `preview?path=...` 直接路径访问方式不再受支持。

如需配置多个允许根目录，Linux/macOS 使用 `:` 分隔，Windows 使用 `;` 分隔。

## 使用 CLI 发布 Preview

如果 Preview 需要由其他设备或 Telegram 打开，请配置 HTTPS 外部地址：

```bash
export HERMES_PEEK_EXTERNAL_BASE_URL="https://preview.example.test"
```

发布一个或多个文件。入口文件必须包含在发布的文件列表中：

```bash
uv run hermes-peek publish \
  README.md docs/03-security.md \
  --entry README.md \
  --title "HermesPeek documentation" \
  --owner <telegram-user-id>
```

命令会输出 JSON，其中包含不透明 Preview ID；如果配置了外部地址，还会包含公开 HTTPS URL。输出不会泄漏服务器上的文件绝对路径。

查看公开元数据：

```bash
uv run hermes-peek inspect <preview-id>
```

不再需要某个 Preview 时，可以将其撤销：

```bash
uv run hermes-peek revoke <preview-id>
```

撤销操作是幂等的，不会删除工作区中的原始文件。

## 发送 Telegram 通知

Telegram 发送是可选功能。请通过 Secret 环境文件或运行时环境配置 Bot Token；不要把 Token 放入命令行、源代码或提交到仓库的文件中。

```bash
export HERMES_PEEK_TELEGRAM_BOT_TOKEN="<bot-token>"
export HERMES_PEEK_TELEGRAM_BOT_USERNAME="<bot-username>"

uv run hermes-peek publish \
  README.md \
  --entry README.md \
  --title "HermesPeek README" \
  --owner <telegram-user-id> \
  --notify \
  --chat-id <chat-id> \
  --chat-type private
```

发送到群组或 Forum Topic：

```bash
uv run hermes-peek publish \
  README.md \
  --entry README.md \
  --title "HermesPeek README" \
  --owner <telegram-user-id> \
  --notify \
  --chat-id <supergroup-chat-id> \
  --chat-type supergroup \
  --thread-id <topic-thread-id>
```

私聊使用 Telegram Web App 按钮；群组和 Topic 使用 Telegram Mini App Direct Link。Telegram 客户端必须能够访问配置的 HTTPS 地址，例如通过私有 Tailscale 网络访问。

## Hermes 集成

可选集成位于 [`integrations/hermes/`](integrations/hermes/)。集成采用 best-effort 策略：Preview 发布失败不能阻止 Hermes 正常发送最终回复。

集成只观察成功执行的文件写入工具调用，并将收集到的路径限定在当前 Hermes 会话中。它不会根据 Shell 命令、文件时间戳、Git diff 或最终回复文本推断文件。

### 离线集成检查

仓库测试使用临时目录、Fake Runner 和模拟 Telegram Transport 验证集成契约，不会修改真实 Hermes profile，也不会发送真实 Telegram 消息。

### 安装到 Hermes profile

CLI 提供完整生命周期管理。首先查看脱敏后的只读计划；该命令不应写入文件或启动服务：

```bash
uv run hermes-peek setup \
  --hermes-home "$HERMES_HOME" \
  --allowed-root /path/to/approved/workspace \
  --external-url https://preview.example.test \
  --telegram-bot-username <bot-username> \
  --plan
```

审核计划后，在目标环境执行安装：

```bash
uv run hermes-peek setup \
  --hermes-home "$HERMES_HOME" \
  --allowed-root /path/to/approved/workspace \
  --external-url https://preview.example.test \
  --telegram-bot-username <bot-username>
```

只有在明确希望 setup 修改 Bot 菜单时才使用 `--configure-telegram-menu`。Telegram Main Mini App 的首次绑定仍需 Bot owner 在 BotFather 中完成，无法仅依靠本仓库安全地自动配置。

检查安装状态：

```bash
uv run hermes-peek status --json
uv run hermes-peek doctor
```

真实 Hermes profile 和 Gateway 是部署目标，不是测试夹具。在修改真实 profile 或重启 Gateway 前，请审核生成的计划并取得所需授权。

## 卸载、回滚与 Purge

默认卸载会删除 HermesPeek 集成资源，但保留 Preview 数据：

```bash
uv run hermes-peek uninstall --hermes-home "$HERMES_HOME"
```

检查生命周期状态和诊断信息：

```bash
uv run hermes-peek status --json
uv run hermes-peek doctor
```

使用 transaction ID 回滚已提交的 setup transaction：

```bash
uv run hermes-peek rollback \
  --hermes-home "$HERMES_HOME" \
  <transaction-id>
```

Purge 是破坏性操作。请使用一次性测试状态，先审核删除清单；确认范围前，不要对生产 Preview 数据执行 Purge：

```bash
uv run hermes-peek uninstall \
  --hermes-home "$HERMES_HOME" \
  --purge \
  --dry-run

uv run hermes-peek uninstall \
  --hermes-home "$HERMES_HOME" \
  --purge \
  --yes
```

## 配置参考

常用配置以环境变量提供：

| 环境变量 | 是否必需 | 用途 | 默认值 |
|---|---:|---|---|
| `HERMES_PEEK_ALLOWED_ROOTS` | 是 | 使用 `os.pathsep` 分隔的允许预览目录 | — |
| `HERMES_PEEK_STATE_DIR` | 否 | Registry、会话、launch reference 和日志目录 | XDG 状态目录 |
| `HERMES_PEEK_EXTERNAL_BASE_URL` | 否 | 用于生成 Preview URL 的 HTTPS Origin | — |
| `HERMES_PEEK_MAX_FILE_BYTES` | 否 | 可预览文件的最大大小 | 2 MiB |
| `HERMES_PEEK_DEFAULT_TTL_SECONDS` | 否 | Preview 有效期 | 7 天 |
| `HERMES_PEEK_TELEGRAM_BOT_TOKEN` | Telegram 必需 | Bot API 凭据 | — |
| `HERMES_PEEK_TELEGRAM_BOT_USERNAME` | Mini App 必需 | 用于生成 Direct Link 的 Bot 用户名 | — |
| `HERMES_PEEK_TELEGRAM_MINI_APP_SHORT_NAME` | 否 | 可选的具名 Mini App short name | — |
| `HERMES_PEEK_TELEGRAM_MINI_APP_MODE` | 否 | Mini App 显示模式 | `compact` |
| `HERMES_PEEK_DEVELOPMENT` | 否 | 在支持的位置启用仅用于开发的行为 | `false` |

对于由生命周期 CLI 管理的安装，`HERMES_PEEK_CONFIG_FILE` 指向生成的非敏感配置文件；Secret 值存储在单独的运行时 Secret 文件中。

## 开发与验证

运行测试和质量检查：

```bash
uv sync --locked
uv run pytest
uv run python -m compileall -q src integrations tests
uv build
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pre-commit run --all-files
```

测试默认保持离线，不需要真实 Telegram 凭据、真实 Hermes profile 或外部 Preview 地址。

## 项目文档

- [产品决策](docs/00-product-decisions.md)
- [设计与开发方案](docs/01-design-development-plan.md)
- [系统架构](docs/02-architecture.md)
- [安全模型](docs/03-security.md)
- [Hermes 集成](docs/04-hermes-integration.md)
- [服务运维](docs/05-operations.md)
- [安装、升级、卸载与 Purge](docs/06-installation-uninstallation.md)
- [实施任务计划](docs/plan/01-implementation-task-plan.md)
- [Telegram Topic Mini App 落地方案](docs/plan/02-telegram-topic-mini-app-rollout.md)
- [生命周期 Setup/Uninstall 实施计划](docs/plan/03-lifecycle-setup-uninstall-rollout.md)

## 参与贡献

提交 Issue 或 Pull Request 前：

1. 说明变更影响的用户行为或安全边界；
2. 行为变更必须添加或更新测试；
3. 保持默认测试离线且结果可复现；
4. 不绕过允许根目录、Telegram 身份验证、owner 授权或只读边界；
5. 不提交 Bot Token、API Key、密码、Cookie、私钥、个人 ID、内部域名或部署 Secret；
6. 涉及文件访问、身份验证、Telegram 操作或网络暴露的变更必须附带安全分析。

请让每个 Pull Request 聚焦一个明确变更。Bug 报告应包含安全的复现步骤、预期行为、实际行为和经过脱敏的相关日志。不要在公开 Issue 中发布凭据或漏洞利用细节。

## 许可证

HermesPeek 使用 [MIT License](LICENSE) 发布。
