# 05 一键安装、AI 辅助安装与 Telegram 接入实施计划

> 本计划执行 [`../08-one-click-ai-telegram-onboarding.md`](../08-one-click-ai-telegram-onboarding.md)。
>
> **评审状态：** `REVIEW_APPROVED`。项目负责人于 2026-08-06 明确要求“落地方案”，授权 TASK 10.1–10.5 按本计划连续实施；TASK 10.6 的真实环境、Gateway 重启、BotFather 与 Telegram 现场验收仍需独立授权。

**计划状态：** `RELEASE_PUBLISHED / TASK_10.6_BLOCKED_PENDING_APPROVAL`

## 1. 阶段目标

把当前开发者参数式安装升级为普通用户可完成的闭环：

```text
一键脚本或 AI 提示词
        → 同一个 hermes-peek setup 生命周期
        → Hermes Skill + Plugin + Service
        → Telegram Bot + Main Mini App 前提检查
        → 新会话真实 Preview 验收
```

## 2. 执行约束

- 方案和本计划须经项目负责人明确评审批准后，才能写测试或代码；
- 获批后按完整阶段连续实施，阶段内不中途汇报；
- 每个 TASK 按 `RED → GREEN → REFACTOR` 实施，现场验收后创建独立 Git commit；
- 不把 Token、用户 ID、chat ID、thread ID、机器路径、内部域名或真实 Preview URL提交到 Git；
- 不修改非目标 profile，也不修改目标 profile 中与 HermesPeek Plugin 启用无关的 Hermes、Telegram、审批或 Gateway 配置；启用目标 profile 的 HermesPeek Plugin 必须作为已披露、需确认且可回滚的 setup 变更；
- 不自动修改 HTTPS、端口、防火墙、反向代理、Tailscale Serve/Funnel 或证书；
- 真实 profile、service、Gateway 重启、Telegram 菜单与真实消息验收需要独立部署授权；
- BotFather Main Mini App owner 流程只能引导和验证，不能宣称自动绕过；
- 首版一键生命周期只支持已有 systemd user backend 的 Linux；macOS、Windows 保持 `UNSUPPORTED/PENDING_BACKEND`，在各自 service backend、锁和完整生命周期验收完成前不得发布对应安装入口。

## 3. 方案来源

- [`../08-one-click-ai-telegram-onboarding.md`](../08-one-click-ai-telegram-onboarding.md)：用户体验、AI 契约、Telegram 完整接入与验收矩阵；
- [`../06-installation-uninstallation.md`](../06-installation-uninstallation.md)：事务、profile、service、Secret、rollback、uninstall 权威边界；
- [`../07-conversational-preview-delivery.md`](../07-conversational-preview-delivery.md)：Skill、Plugin Tool、原位单消息和真实 Telegram 验收；
- [Hermes Agent Telegram 文档](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram)：Hermes Bot Token、allowed users、Gateway 和群组配置；
- [Telegram Mini Apps 文档](https://core.telegram.org/bots/webapps)：Main Mini App 与 Direct Link 官方边界。

## 4. TASK 总览

| TASK | 名称 | 状态 | 交付物 | 核心验收依据 |
|---|---|---|---|---|
| TASK 10.0 | 方案、计划与 README 入口 | `DONE` | 方案、计划、双语 README 导航 | 负责人已批准；文档链接与命令依据通过 |
| TASK 10.1 | Setup 交互式向导 | `DONE` | 无必填参数的 `hermes-peek setup` | 多 profile、缺 HTTPS、Secret 文件均有测试；默认流程直接执行并显示阶段进度，显式 `--plan` 保留只读 JSON |
| TASK 10.2 | 固定 Release Linux 一键安装脚本 | `DONE` | `install.sh`、哈希验证、平台门禁 | 11 项隔离安装器测试和全量 192 tests 通过 |
| TASK 10.3 | AI 安装契约与仓库 Agent 指引 | `DONE` | README 提示词、`AGENTS.md`、静态契约测试、验证清单 | Agent 先计划、Secret 不进聊天、副作用有确认；目标和全量门禁通过 |
| TASK 10.4 | Telegram onboarding 与诊断 | `DONE` | Bot/Main Mini App 检查和结构化 doctor | getMe、allowed users 指引、HTTPS、可选 short name、菜单边界 |
| TASK 10.5 | Linux 打包、发布与离线验收 | `DONE_PUBLISHED_V0.2.1` | 仓库/tag 安装器、Release 包资产、checksum、Linux CI | Linux fresh-profile fake transport 闭环；公开三项资产下载校验通过 |
| TASK 10.6 | 真实端到端安装验收 | `BLOCKED_PENDING_APPROVAL` | 新环境安装及私聊/群组/Topic 证据 | 真实 Gateway、BotFather、HTTPS 和 Telegram 现场结果 |

## 5. TASK 细化

### TASK 10.0：方案、计划与 README 入口

**状态：** `DONE`（2026-08-06，提交 `f8f81fc`）

**方案来源：** 方案全文；用户关于一键安装、AI 提示词和 Telegram 配置缺失的反馈。

**交付物：**

- `docs/08-one-click-ai-telegram-onboarding.md`；
- `docs/plan/05-one-click-ai-telegram-onboarding-rollout.md`；
- `README.md`、`README.zh-CN.md` 的普通用户入口与文档索引。

**验收依据：**

- 当前能力和目标能力明确分开；
- README 不把 `install.sh` 描述为已经存在；
- Telegram 步骤覆盖 Bot、allowed users、群组隐私、HTTPS、Main Mini App、可选命名 short name、Gateway 新会话和真实测试；
- AI 提示词禁止 Secret 进入聊天，所有副作用先计划再确认；
- `git diff --check`、Markdown 相对链接、敏感信息扫描通过；
- 项目负责人明确评审批准。

**提交：**

```text
docs: design one-click Telegram onboarding
```

### TASK 10.1：Setup 交互式向导

**状态：** `DONE`（2026-08-06，提交 `581c25e`）

**方案来源：** 方案 §2.2、§4、§6。

**交付物：**

- `hermes-peek setup` 无必填参数交互模式；
- profile、Telegram、allowed root、HTTPS、Main Mini App 前提发现；
- 脱敏 plan 与确认；
- 保留现有显式参数无人值守模式。

**RED 验收场景：**

1. 单 profile 自动选择，多 profile 必须明确选择；
2. 非 TTY 环境缺参数时失败，不挂起；
3. Token 只从受限 Secret 文件或安全提示输入；
4. allowed root 不安全时在副作用前失败；
5. HTTPS Origin 不合法或不可达时停止；
6. setup 先展示 plan，拒绝确认时零写入；
7. Gateway 内调用返回待外部重启，不自杀式重启；
8. 所有输出不含 Secret 和部署敏感信息。

**验收命令：** `uv run pytest tests/unit/test_setup_wizard.py -q`；`uv run pytest -q`。

**验收结果：** 向导目标测试通过（7 项行为测试）；全量通过（181 tests，1 条既有 Starlette/httpx 弃用警告）。

**提交：**

```text
feat: add interactive setup wizard
```

### TASK 10.2：固定 Release Linux 一键安装脚本

**状态：** `DONE`（2026-08-06，提交 `e678a16`）

**方案来源：** 方案 §2.1、§6。

**交付物：**

- Linux `install.sh`；
- Release wheel 或平台资产；
- SHA-256 checksum 文件和校验逻辑；
- `--version`、`--non-interactive`、`--dry-run` 或等价可测试入口。

**RED 验收场景：**

1. 固定版本成功安装并调用同一个 setup；
2. checksum 不匹配时零执行；
3. 网络中断不留下半安装状态；
4. 已安装同版本保持幂等；
5. 版本升级调用 lifecycle upgrade/transaction，不直接覆盖；
6. 缺 Hermes 或缺受支持 Python 时给出准确引导；
7. 不使用 `sudo`，不静默修改网络或 Gateway；
8. 从 `main` 安装时明确标记开发通道，README 默认推荐 release。
9. macOS、Windows 和非 systemd Linux 在任何写入前以 `UNSUPPORTED/PENDING_BACKEND` 失败，不提供只有下载能力却无法完成生命周期的伪安装器。

**验收命令：** `sh -n install.sh`；`uv run pytest tests/integration/test_release_installer.py -q`；`uv run pytest -q`。

**验收结果：** Shell 语法检查通过；安装器 11 项隔离测试通过；全量 192 tests 通过（1 条既有 Starlette/httpx 弃用警告）。

**提交：**

```text
feat: add verified one-command installer
```

### TASK 10.3：AI 安装契约与仓库 Agent 指引

**状态：** `DONE`（2026-08-06）

**方案来源：** 方案 §3、§5。

**交付物：**

- 英文和中文 README 的可复制提示词；
- 仓库级 `AGENTS.md`；
- 提示词/规则静态测试；
- AI 安装验证清单。

**验收依据：**

- Agent 必须先读权威文档、现场发现、输出计划；
- Secret 不允许由用户发进聊天；
- Gateway、Telegram 菜单和任何网络变更必须单独确认；
- Agent 优先使用 installer/setup，不复制内部文件；
- 完成定义明确区分安装、加载和真实 Telegram 验收；
- `AGENTS.md` 不包含机器专属值或用户个人规则。

**验收结果：** 双语提示词、仓库 Agent 规则、三层完成定义和验证清单已由 `tests/test_ai_install_contract.py` 静态约束；目标测试、Markdown 相对链接、敏感/机器专属模式扫描和全量测试通过。当前 Release 仍无 `install.sh` 与 checksum 资产，因此文档只提供发布后入口判定，不把无效远程命令写成当前可用。

**提交：**

```text
docs: add AI-assisted installation contract
```

### TASK 10.4：Telegram onboarding 与诊断

**状态：** `DONE`（2026-08-06）

**方案来源：** 方案 §4、§7；Telegram/Hermes 官方文档。

**交付物：**

- `doctor --json` 或等价结构化检查：Bot Token 可读、`getMe`、Webhook 状态、HTTPS、Bot username、可构造的 Main Mini App Direct Link，以及可选的命名 Mini App short name；状态必须区分身份已验证、可靠配置证据、URL 匹配未验证和 Telegram 客户端现场打开待验收；
- setup 完成后的 BotFather 待办清单；
- 私聊菜单修改继续保持显式 opt-in 和可回滚；
- 文档中的私聊/群组/Topic 验收命令。

**RED 验收场景：**

1. 同一个 Hermes Bot 身份一致；
2. 缺 allowed users 时阻塞并链接 Hermes 配置，不擅自改主配置；
3. 群组 Privacy Mode 只给出可选方案，不自动修改；
4. short name 为空时使用 Main Mini App Direct Link；非空值必须按 Telegram 官方实际 short-name 规则校验，代码、测试和文档共享同一 3–30 字符契约；只有配置了命名 Mini App 时才验证带 short name 的链接；
5. `setChatMenuButton` 不被误报为 Main Mini App 已注册；
6. Telegram API 错误完全脱敏；
7. rollback 不覆盖用户在安装后做的新菜单修改。

**验收结果：** `doctor --json` 已提供只读分层 Telegram onboarding 证据；所有 Bot API
测试均使用 fake transport；目标测试 37 项与全量 199 项通过。未执行真实 Telegram、
BotFather、Gateway/service/profile 或网络写入，Telegram 客户端验收保持 pending。

**提交：**

```text
feat: diagnose Telegram onboarding readiness
```

### TASK 10.5：Linux 打包、发布与离线验收

**状态：** `DONE_PUBLISHED_V0.2.1`（2026-08-06）

**方案来源：** 方案 §6、§7。

**交付物：**

- 发布工作流与 checksum；
- wheel/sdist/installer 资产验证；
- Linux systemd user 环境 CI；
- fresh HOME/profile + fake systemd/Hermes/Telegram transport 的安装/升级/卸载/rollback 离线验收；
- 双语 README 准确记录“资产可构建但尚未发布”，不提前启用远程一键入口。

**验收依据：**

- Linux 从发布资产安装，不从工作区隐式导入；
- 新 profile 可发现 Skill 和 Tool；
- setup、status、doctor、upgrade、rollback、uninstall 闭环；
- installer 固定的版本与 release 资产一致；
- 敏感信息扫描、构建、全量测试和文档链接通过；
- README 中不再以开发安装作为普通用户第一入口。
- macOS、Windows 与不受支持的 Linux backend 在 README 和 installer 中保持 `UNSUPPORTED/PENDING_BACKEND`，不声明可用。

**验收结果：** `scripts/build_release_assets.py` 生成名称一致的 wheel、sdist 与 checksum；仓库/tag `install.sh` 是安装器唯一来源，并固定下载匹配 Release wheel。本地 verifier 检查完整资产集合、版本/tag/安装器契约、wheel/sdist 内容和 checksum roundtrip；Linux workflow 对 main/PR/手工运行只上传 CI artifact，仅明确 `v*` tag 才进入 GitHub Release 上传步骤。离线验收使用 fresh HOME/profile 及 fake systemd、Hermes、setup/Telegram transport，未接触真实 profile、service、Gateway、BotFather、Telegram 或网络。v0.2.1 tag、GitHub Actions 和三项公开资产已在发布后复核。

**提交：**

```text
build: package verified Linux release assets
```

### TASK 10.6：真实端到端安装验收

**状态：** `BLOCKED_PENDING_APPROVAL`

**方案来源：** 方案 §7；既有真实部署授权边界。

**交付物：**

- 一台干净授权环境的一键安装记录；
- Hermes profile、service、Gateway、BotFather Main Mini App 的脱敏证据；
- 私聊、普通群组、Forum Topic 单消息 Preview 现场结果；
- 失败、rollback 和 uninstall 现场结果；
- README 中准确的生产就绪声明或剩余限制。

**验收矩阵：**

| 场景 | 状态 |
|---|---|
| 一键脚本安装 CLI | `NOT_RUN` |
| 交互 setup 安装 profile/service | `NOT_RUN` |
| Gateway 外部重启与新会话发现 | `NOT_RUN` |
| BotFather Main Mini App Direct Link | `NOT_RUN` |
| 私聊单消息 Preview | `NOT_RUN` |
| 普通群组原位 Preview | `NOT_RUN` |
| Forum Topic 原 thread Preview | `NOT_RUN` |
| 无 HTTPS/缺 Secret 安全失败 | `NOT_RUN` |
| rollback 恢复 | `NOT_RUN` |
| 默认 uninstall 保留数据 | `NOT_RUN` |

未逐项获得现场证据前，项目只能声明“安装器离线验证通过”，不能声明“普通用户一键即可使用 Telegram”。

**提交：**

```text
test: record end-to-end onboarding acceptance
```

## 6. 阶段完成门槛

只有同时满足以下条件，阶段 10 才能标记完成：

1. 负责人明确批准方案与计划；
2. TASK 10.1–10.5 每项独立提交且全量门禁通过；
3. 发布资产可从干净环境安装并校验；
4. README 默认入口已切换到可实际运行的一键安装；
5. AI 提示词经过真实 Agent 安装演练，不要求用户把 Secret 发进聊天；
6. Telegram Bot、Main Mini App、私聊、群组和 Topic 的完整步骤均可执行；
7. TASK 10.6 获得独立授权并完成真实现场验收；
8. 未验证平台、入口或 Telegram 场景均保持精确的 pending/unsupported 状态。
