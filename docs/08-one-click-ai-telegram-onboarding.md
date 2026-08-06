# 08 一键安装、AI 辅助安装与 Telegram 接入方案

> **文档状态：** 已评审并实施；v0.2.1 Linux Release 已发布，TASK 10.6 真实 Telegram 现场验收待独立授权。
>
> **真实性声明：** v0.2.1 使用仓库/tag `install.sh` 作为唯一安装器来源；GitHub Release 已现场确认发布匹配的 wheel、sdist 与 `SHA256SUMS`。三项公开资产已实际下载并通过 checksum 与内容复核，`main` 和 `v0.2.1` 安装器也已确认固定指向 v0.2.1 wheel。TASK 10.6 的真实 Gateway、BotFather、HTTPS 与 Telegram 验收仍未执行。

## 1. 问题

当前 README 主要面向开发者：用户需要自行克隆仓库、安装依赖、理解 Hermes profile、准备 Telegram Bot、配置 Main Mini App、提供 HTTPS 地址，再组合多个参数执行 setup。

这会造成两个直接问题：

1. “安装到 Hermes”并不等于“Telegram 中已经能使用”；
2. 用户即使把仓库链接交给 AI，也没有一段安全、可验证、不会擅自修改网络或泄漏 Token 的安装提示词。

项目必须提供三条同等受支持的入口：

- **一键交互安装**：适合普通用户；
- **AI 辅助安装**：适合已经在使用 Hermes Agent 或其他具备终端工具的 Agent 的用户；
- **完整手工安装**：适合审计、排障和高级部署。

三条入口最终必须调用同一个 `hermes-peek setup` 生命周期实现，不能各自维护不同安装逻辑。

## 2. 目标用户体验

首个正式的一键生命周期版本只支持具备 systemd user backend 的 Linux。macOS、Windows 和不具备受支持 service backend 的 Linux 仍可用于本地开发，但安装器必须在任何写入前标记为 `UNSUPPORTED/PENDING_BACKEND`；在 launchd、Windows service/Task Scheduler 与对应锁实现和验收完成前，不宣称一键安装可用。

### 2.1 一键交互安装

发布资产现场检查通过后的公开入口（当前不能仅凭仓库内容声称已发布）：

```bash
curl -fsSL https://github.com/KumaCool/HermesPeek/releases/latest/download/install.sh | sh
```

安装器必须在执行 setup 前显示解析后的 HermesPeek 版本，并只下载同一 GitHub Release 的校验文件和安装资产。需要严格固定版本时，用户把 `latest` 替换为明确的 `download/vX.Y.Z`。

更适合安全审查的等价方式：

```bash
curl -fsSLo install-hermes-peek.sh \
  https://github.com/KumaCool/HermesPeek/releases/latest/download/install.sh
less install-hermes-peek.sh
sh install-hermes-peek.sh
```

安装脚本只负责：

1. 检查受支持的操作系统、Python、`uv`、`hermes` 和 HTTPS 下载能力；
2. 从已标记 release 安装 HermesPeek CLI；
3. 校验下载产物或 release 中声明的哈希；
4. 启动交互式 `hermes-peek setup`；
5. 输出脱敏的验证结果和下一步 Telegram 操作。

安装脚本不得：

- 静默创建 Telegram Bot；
- 把 Token 放进命令行、Shell history、日志或仓库；
- 擅自建立公网入口、修改防火墙、反向代理、Tailscale Serve/Funnel 或证书；
- 修改非目标 profile，或修改目标 profile 中与 HermesPeek Plugin 启用无关的 Hermes、Telegram、审批或 Gateway 配置；setup 启用目标 profile 的 HermesPeek Plugin 属于必须预先展示并确认的受控变更；
- 在无法验证 service、Plugin、Skill 或 Telegram 前提时声称成功；
- 从正在运行的 Gateway 会话内强制重启 Gateway。

### 2.2 交互式向导

目标命令：

```bash
hermes-peek setup
```

向导按顺序完成以下发现和提问：

1. 发现 Hermes 安装及 profile；有多个 profile 时让用户明确选择；
2. 发现目标 profile 的 Telegram 配置，只显示 Bot username 和脱敏状态，不显示 Token；
3. 让用户选择允许预览的目录，拒绝 `/`、整个 home、Secret 目录和不安全 symlink；
4. 要求填写 Telegram 客户端可访问的 HTTPS Origin；
5. 在线检查 `/healthz`、TLS 和 Telegram Bot 身份；
6. 分层报告 Main Mini App 状态：Bot 身份是否验证、是否有可信配置证据、URL 匹配是否仍未验证，以及是否仍需 Telegram 客户端现场打开；不得根据 `getMe` 成功或能够构造 Direct Link 推断 BotFather 已配置完成；
7. 先显示变更计划和重启影响，再要求确认；
8. 执行事务化 setup；
9. 若 Gateway 重启必须由外部操作者完成，输出准确命令，不伪装为已激活；
10. 运行 `status`、`doctor` 和新会话发现检查。

无人值守环境继续支持显式参数，不允许用猜测替代缺失值。

## 3. AI 辅助安装

### 3.1 用户可复制的提示词

以下提示词应放在 README 的“使用 AI 安装”区，并由安装文档长期维护：

```text
请帮我安装并验证 HermesPeek：
https://github.com/KumaCool/HermesPeek

要求：
1. 先阅读仓库 README、docs/08-one-click-ai-telegram-onboarding.md、
   docs/06-installation-uninstallation.md 和最新 release 信息；
2. 先做只读检查并告诉我：目标 Hermes profile、Hermes/Gateway 状态、
   Telegram 是否已配置、还缺哪些输入；
3. 不要让我把 Telegram Bot Token、API Key 或密码直接发到聊天里；
   Secret 必须通过本机受限权限文件或 Hermes 官方配置向导输入；
4. 在任何文件写入、服务安装、Gateway 重启、Telegram 菜单修改、
   HTTPS/端口/防火墙/反向代理/Tailscale 变更前，先列出计划并征得我同意；
5. 优先使用项目提供的 install.sh 和 hermes-peek setup，
   不要自行复制插件文件或发明另一套安装流程；
6. Telegram 侧必须说明并检查：Hermes Bot、allowed users、群组隐私、
   Main Mini App、HTTPS URL 和新会话加载；
7. 安装后现场运行 hermes-peek status --json、hermes-peek doctor、
   hermes gateway status，并在 Telegram 新会话中做一次真实预览测试；
8. 严格区分“代码/离线测试通过”“已安装”“Gateway 已加载”
   和“Telegram 真实验收通过”，失败时不要声称完成。
```

### 3.2 AI 执行契约

AI 辅助安装不是“跳过确认”的无人值守模式。Agent 必须遵守：

- **先发现、后计划、再执行**；
- Secret 不进入聊天和工具参数；
- 网络入口和 Gateway 重启属于独立副作用；
- 优先调用项目 CLI，不复制内部实现；
- 每一层都用现场命令验证；
- 真实 Telegram 消息是最终验收依据，MockTransport 不能代替。

项目应额外提供机器可发现的仓库级 `AGENTS.md`，把以上边界和权威文档入口交给支持项目规则的 Agent。`AGENTS.md` 只描述操作纪律，不复制完整安装实现。

<a id="telegram-complete-configuration"></a>
<a id="telegram-完整配置"></a>

## 4. Telegram 完整配置

HermesPeek 默认**复用正在承载 Hermes Gateway 的 Telegram Bot**，不要求创建第二个 Bot。Telegram 配置分为 Hermes Bot 接入和 HermesPeek Mini App 绑定两层。

### 4.1 创建或准备 Hermes Telegram Bot

如果 Hermes 已能在 Telegram 收发消息，跳到 §4.3，并确认使用同一个 profile 和同一个 Bot。

否则：

1. 在 Telegram 打开官方 [@BotFather](https://t.me/BotFather)；
2. 发送 `/newbot`，按提示设置显示名和以 `bot` 结尾的 username；
3. 复制 Bot Token，但**不要发到聊天、Issue、命令行或截图中**；
4. 使用 Hermes 官方向导：

   ```bash
   hermes gateway setup
   ```

5. 在向导中选择 Telegram，在本机输入 Bot Token 和允许使用 Bot 的 Telegram user ID；
6. user ID 可通过 [@userinfobot](https://t.me/userinfobot) 查询；
7. 安装或启动 Gateway，并检查状态：

   ```bash
   hermes gateway install
   hermes gateway status
   ```

Hermes Telegram 配置的最新权威步骤以 [Hermes Agent Telegram 文档](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram) 为准。

### 4.2 群组和 Forum Topic

如果只在私聊使用，不需要本节。

若要在群组或 Topic 中使用：

1. 将同一个 Bot 加入目标群组；
2. 保持 BotFather Privacy Mode 时，Bot 通常只收到命令、回复和明确提及；
3. 若希望 Bot 读取普通群消息，可在 BotFather 中关闭 Privacy Mode，或将 Bot 提升为群管理员；
4. 仍需在 Hermes 中限制允许的用户，不能把群组可见性当作授权；
5. Forum Topic 请求必须由 Hermes Gateway 保留原 `chat_id + message_thread_id`，HermesPeek 不允许回退到私聊或 Home channel。

修改 Privacy Mode 或管理员权限会改变 Bot 的消息可见范围，必须由群组/Bot owner 明确决定。

### 4.3 准备 HTTPS 地址

Telegram Mini App 必须使用 Telegram 客户端可访问且证书受信任的 HTTPS Origin，例如：

```text
https://preview.example.com
```

要求：

- 只填写 Origin，不带 Token、用户名、密码、query 或 fragment；
- 手机和桌面 Telegram 都应能访问；
- HermesPeek 应继续只监听受控地址，由现有 HTTPS 入口转发；
- 安装器只验证该地址，不自动创建或修改网络入口。

如果尚无 HTTPS 地址，应先停止 HermesPeek 安装，并单独设计入口。不得为了“一键安装”静默开放公网端口。

### 4.4 绑定 Main Mini App

群组和 Forum Topic 的 Preview 使用 Mini App Direct Link，因此必须在 BotFather 为该 Bot 注册 Main Mini App。Telegram 官方仍要求 Bot owner 完成这一步，CLI 不能安全绕过。

在 [@BotFather](https://t.me/BotFather) 中：

1. 选择目标 Bot；
2. 进入 Bot Settings / Configure Mini App；
3. 选择同一个 Hermes Bot；
4. 设置 Mini App 标题和说明；
5. Web App URL 填写 §4.3 的 HermesPeek HTTPS Origin；
6. 保存后验证 Main Mini App 入口可以打开；HermesPeek 默认使用不带 short name 的 Main Mini App Direct Link：

   ```text
   https://t.me/<bot-username>?startapp=<opaque-launch-reference>
   ```

如果用户另外通过 `/newapp` 注册了**命名 Mini App**，可以把 BotFather 返回的 3–30 字符 short name 作为可选参数传给 setup：

```text
--telegram-mini-app-short-name <short-name>
```

命名 Mini App 不是 HermesPeek 群组/Topic Preview 的必需前提。BotFather 菜单文案可能变化；以 Telegram 官方 [Mini Apps 文档](https://core.telegram.org/bots/webapps) 为准。关键验收不是按钮名称，而是同一个 Bot 的 Main Mini App Direct Link 能在 Telegram 内打开 HermesPeek HTTPS 页面。

### 4.5 可选：私聊菜单按钮

HermesPeek 可以在用户明确传入 `--configure-telegram-menu` 时，通过 Bot API 把私聊菜单按钮指向 Preview 首页：

```bash
hermes-peek setup ... --configure-telegram-menu
```

这是可选便利功能：

- 不等价于 Main Mini App 注册；
- 不应作为发送单次 Preview 的前提；
- setup 必须记录旧值，失败、rollback 或 uninstall 时只恢复自己修改过且未被他人再次更改的值。

### 4.6 安装 HermesPeek 集成

当前已实现的显式参数路径如下；在一键交互向导完成前，它仍是权威安装入口：

```bash
uv run hermes-peek setup \
  --hermes-home "$HERMES_HOME" \
  --allowed-root /path/to/approved/workspace \
  --external-url https://preview.example.com \
  --telegram-bot-username <bot-username> \
  --plan
```

审核脱敏计划后，去掉 `--plan` 执行。仅当 BotFather 已配置并验证命名 Mini App 时，才额外传 `--telegram-mini-app-short-name <short-name>`。Bot Token 默认从目标 Hermes home 的 `.env` 读取，也可通过 `--telegram-env` 指向权限受限的 Secret 文件；不要把 Token 作为 CLI 参数。

### 4.7 激活与验收

安装后依次验证：

```bash
hermes-peek status --json
hermes-peek doctor --json
hermes gateway status
```

若 setup 报告 `activation_pending_gateway_restart`，必须从 Gateway 外部执行：

```bash
hermes gateway restart
```

然后在 Telegram 发送 `/new`，确保新会话重新发现 Skill 和 Plugin Tool，再发送：

```text
把 README 发我看下
```

`doctor --json` 只做只读诊断，并分层报告：Token 文件可读性与权限、`getMe`
身份、Webhook、HTTPS health、Bot username、HermesPeek 配置证据，以及 Main Mini
App Direct Link 是否可构造。`verified` 身份或可构造链接都**不能**证明 BotFather 已
注册 Main Mini App；URL 匹配保持 `unverified`，Telegram 客户端打开保持 `pending`，
直到 TASK 10.6 现场验收。缺少 `TELEGRAM_ALLOWED_USERS`（或明确的群组允许用户）时
诊断为阻塞项，请运行 `hermes gateway setup` 并遵循
[Hermes Telegram 配置](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram)，
HermesPeek 不修改 Hermes 主配置。`setChatMenuButton` 只是可选私聊入口，不是 Main
Mini App 注册证据。

setup 输出的待办清单分别保留 BotFather owner 操作、私聊、群组、Forum Topic 的
Telegram 客户端验收。群组 Privacy Mode 只提供选择建议；是否关闭、是否授予管理员，
以及变更后移除并重新加入 Bot，均由 Bot/group owner 决定。

通过标准：

- Agent 调用一次 `hermes_peek_send_preview`；
- Preview 发回请求发生的同一私聊、群组或 Topic；
- 只出现一条带 `Open preview` 的消息；
- 页面能打开并通过 Telegram 身份与 owner 授权；
- 成功后没有第二条“已发送”确认；
- 失败时返回真实、脱敏的原因，不回退到其他聊天。

## 5. 文档信息架构

README 应把普通用户路径放在开发安装之前：

1. 一句话说明用途和安全边界；
2. 一键安装；
3. 使用 AI 安装；
4. Telegram 前置条件与 BotFather 链接；
5. 安装后第一条测试消息；
6. 手工安装与排障链接；
7. 开发者安装、架构、安全和计划文档。

英文 README 是默认入口，中文 README 保持同等内容。详细 Telegram 步骤以本文为权威来源，README 只保留最短闭环和链接，避免两份长教程漂移。

## 6. 安全与失败语义

- 远程脚本安装必须固定 release 或明确展示安装版本；`main` 入口可以存在，但文档优先推荐 release URL；
- 提供下载后审查再执行的等价流程；
- 安装产物必须有可验证哈希，失败即停止；
- 不支持的平台和缺失依赖必须在副作用前失败；
- Token 只从本机 Secret 输入或受限文件读取；
- 所有计划、状态、doctor、日志和错误统一脱敏；
- 安装过程中发现网络入口缺失时只报告前提，不自动开放入口；
- 真实 Profile、service、Gateway、Telegram 菜单和 BotFather 分别记录状态，不能用一个笼统的“安装成功”覆盖。

## 7. 验收矩阵

| 层级 | 验收证据 |
|---|---|
| 安装脚本 | 干净 Linux systemd user 环境的隔离测试；固定 release 与哈希校验；其他平台在写入前准确拒绝 |
| CLI 安装 | `hermes-peek --version`、`status --json`、`doctor` |
| Hermes 集成 | 目标 profile 中 Skill/Plugin 可发现；新会话暴露 Tool |
| Service | 进程、监听和 `/healthz` 现场通过 |
| Telegram Bot | `getMe` 身份与 Hermes Gateway 收发现场通过 |
| Main Mini App | BotFather 的 Main Mini App Direct Link 可打开 HTTPS 页面；命名 short name 为可选项 |
| 私聊 | 同一私聊单消息 Preview，owner 正确 |
| 群组 | 同一群组发送，不回退私聊 |
| Forum Topic | 同一 chat 和 thread，Topic 不丢失 |
| 失败路径 | 缺 Secret、无 HTTPS、歧义文件、Telegram 失败均不伪成功 |

离线测试只能证明合同；最后四项必须使用真实 Telegram 现场证据。

## 8. 权威来源

- [Hermes Agent Telegram 配置](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram)
- [Telegram Mini Apps](https://core.telegram.org/bots/webapps)
- [`06-installation-uninstallation.md`](06-installation-uninstallation.md)
- [`07-conversational-preview-delivery.md`](07-conversational-preview-delivery.md)
- [`plan/05-one-click-ai-telegram-onboarding-rollout.md`](plan/05-one-click-ai-telegram-onboarding-rollout.md)
