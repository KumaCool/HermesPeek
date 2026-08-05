# 04 Telegram 会话预览 Skill 与单消息交付实施计划

> 本计划执行 [`../07-conversational-preview-delivery.md`](../07-conversational-preview-delivery.md)。方案与计划已经项目负责人批准；后续按 TASK 9.1–9.6 实施。更新真实 Profile 或重启 Gateway 仍需另行明确授权。

**计划状态：** `REVIEW_APPROVED / READY_TO_IMPLEMENT`

## 1. 阶段目标

把“把 README 发我看下”从 Agent 私有记忆和 Shell 兼容流程，升级为随 HermesPeek 仓库、源码包和安装生命周期分发的正式能力：

```text
仓库内 hermes-peek-preview Skill
        → 一次调用 hermes_peek_send_preview
        → 当前私聊/群组/Topic 的唯一 Preview 消息
        → 成功后 NO_REPLY
```

Skill 是自然语言入口和行为契约；Plugin Tool 是严格原位路由、Secret 加载、Preview 发布与 Telegram 发送的执行层。两者必须一起交付，不能用私人记忆或 Shell 包装替代。

## 2. 执行约束

- 本方案和计划须经项目负责人明确评审批准后，才能写 Skill、测试或代码；
- “继续下一步”不视为方案评审批准；
- 获批后按完整阶段连续实施，阶段内不中途汇报；
- 每个 TASK 现场验收后创建独立 Git commit，再进入下一 TASK；
- 每个代码 TASK 遵循 RED → GREEN → REFACTOR，必须先运行并确认预期失败；
- 不修改 Hermes 主配置、Gateway 配置、审批配置或其他 Profile；
- 不修改网络入口、端口、防火墙、反向代理或 Tailscale Serve；
- 更新当前真实 Profile 和重启 Gateway 必须另行明确授权；
- Token、Preview URL、绝对本机路径、用户 ID、chat ID、thread ID 和机器专属数据不得进入 Git；
- 验收严格区分静态/离线测试、临时 Profile 安装、当前运行态和真实 Telegram 现场结果。

## 3. 方案来源

- [`../07-conversational-preview-delivery.md`](../07-conversational-preview-delivery.md)：Skill、Tool、单消息、路由、安全、生命周期和回滚权威方案；
- [`../04-hermes-integration.md`](../04-hermes-integration.md)：既有 collector 与 `final_message_actions` 集成边界；
- [`../06-installation-uninstallation.md`](../06-installation-uninstallation.md)：Profile 作用域、transaction、owned resources、Secret 分离与安全卸载；
- Hermes Plugin `ctx.register_tool()`：第三方能力通过 Plugin Tool 暴露，不增加 Hermes core Tool；
- Hermes `gateway.session_context.get_session_env()`：当前请求路由必须来自 ContextVar-backed Session Context；
- Hermes intentional-silence 契约：完整 `NO_REPLY` 由 Gateway 抑制，不额外投递；
- 项目负责人要求：能力必须做成随项目分发的 Skill，成功后不追加确认，并严格回复到请求原位。

## 4. TASK 总览

| TASK | 名称 | 状态 | 交付物 | 核心验收依据 |
|---|---|---|---|---|
| TASK 9.0 | Skill-first 方案与计划 | `DONE` | 方案、阶段计划、总计划索引 | 文档一致、链接与敏感检查通过；负责人评审批准 |
| TASK 9.1 | 仓库内 Preview Skill | `TODO` | `SKILL.md`、reference、触发检查 | 正向/near-miss 边界、唯一/歧义文件、成功/失败语义 |
| TASK 9.2 | Plugin Tool RED 契约测试 | `TODO` | schema、路由、Secret、脱敏失败测试 | 当前实现稳定 RED；测试零真实副作用 |
| TASK 9.3 | Session Context 与 Secret 安全层 | `TODO` | context adapter、pointer schema、secret loader | 同 chat/topic、无回退、权限和 Profile 隔离 |
| TASK 9.4 | 单消息 Preview Tool | `TODO` | Tool handler、注册、MockTransport 集成 | 一次调用/一次发送、owner、脱敏、失败不伪成功 |
| TASK 9.5 | Skill + Plugin 生命周期分发 | `TODO` | setup/upgrade/rollback/uninstall、打包和文档 | 临时 Profile 闭环、owned-resource drift、wheel/sdist |
| TASK 9.6 | 全量离线与新会话验收 | `TODO` | 全量测试、构建、安装烟测、敏感扫描 | 新 Profile 可发现 Skill/Tool，完整回归通过 |
| TASK 9.7 | 真实 Telegram 单消息验收 | `BLOCKED_PENDING_APPROVAL` | 当前 Profile 与私聊/Topic 现场证据 | 需另行批准部署与 Gateway 外部重启 |

## 5. TASK 细化

### TASK 9.0：Skill-first 方案与计划

**状态：** `DONE`

**方案来源：** 项目负责人关于 Skill 分发、原位回复和成功静默的要求；现有 HermesPeek/Hermes 实现事实。

**交付物：**

- `docs/07-conversational-preview-delivery.md`；
- `docs/plan/04-conversational-preview-delivery-rollout.md`；
- `docs/plan/01-implementation-task-plan.md` 的阶段 9 索引。

**实施步骤：**

1. 将 Skill 定义为正式能力入口，不再定义为 profile-local 附属项；
2. 明确仓库源码、安装目标和 Skill/Plugin 生命周期所有权；
3. 明确 Tool 是 Skill 的执行层，Tool schema 不接受路由或凭据；
4. 明确同私聊/群组/Topic 原位路由和禁止私聊/Home 回退；
5. 明确成功 `NO_REPLY`、失败解释及 CLI 兼容边界；
6. 把后续 TASK 按 Skill → RED Tool 契约 → 安全层 → Tool → 生命周期 → 验收排序；
7. 运行文档验证并提交本 TASK。

**验收依据：**

- 三份文档互相链接且状态一致；
- 不再出现“profile-local skill”作为交付定义；
- 每个 TASK 都有关联方案来源、明确交付物和可执行验收依据；
- `git diff --check` 和 Markdown 链接检查通过；
- 新增文档敏感信息扫描 0 命中；
- staged diff 只包含本 TASK 文档；
- 项目负责人明确评审批准。

**提交边界：** 只包含上述三份文档。

**计划提交：**

```text
docs: plan project-distributed preview skill
```

**验收记录（2026-08-05）：** 项目负责人已明确评审批准。三份文档完成 Skill-first 职责、严格原位路由、成功静默、生命周期分发、TDD 顺序、真实部署授权与回滚边界整理；Markdown 本地链接、whitespace、`git diff --check` 和敏感信息模式检查通过。

### TASK 9.1：仓库内 Preview Skill

**状态：** `TODO`

**方案来源：** 方案第 3–5、8、9.1 节。

**交付物：**

```text
skills/hermes-peek-preview/SKILL.md
skills/hermes-peek-preview/references/delivery-contract.md
```

以及轻量 Skill 静态/触发测试。测试放置路径在实施前按现有测试布局确认，优先：

```text
tests/unit/test_preview_skill.py
```

**RED 步骤：**

1. 写测试断言 Skill 路径存在、frontmatter 合法、name 为 `hermes-peek-preview`；
2. 写正向触发样例：发我看下、给我看文档、预览文件、上下文唯一时给我看下；
3. 写 near-miss：修改、总结、解释、定位、复制正文；
4. 写行为断言：一次专用 Tool、成功 `NO_REPLY`、失败解释、不自动使用 terminal；
5. 运行目标测试，确认因 Skill 不存在而 RED。

**GREEN 实现：**

- 创建仓库内 Skill；
- description 明确 should-trigger 与 should-not-trigger；
- `SKILL.md` 只保留常用流程，详细 Tool/安全契约放 reference；
- 不写本机路径、Profile、Token 或真实路由；
- Tool 不可用时提示安装/升级，不自动降级 Shell。

**验收依据：**

```bash
uv run pytest tests/unit/test_preview_skill.py -v
```

并确认：

- frontmatter 从首字节 `---` 开始，name/description/body 合法；
- 正向和 near-miss 全部符合预期；
- 唯一文件不追问，多匹配/无目标才澄清；
- Skill 明确调用 `hermes_peek_send_preview` 一次；
- 成功只输出 `NO_REPLY`，失败返回简短原因；
- Skill 不指导正常路径调用 `terminal source ...`；
- Skill/reference 敏感信息扫描 0 命中。

**提交：**

```text
feat: add HermesPeek preview skill
```

### TASK 9.2：Plugin Tool RED 契约测试

**状态：** `TODO`

**方案来源：** 方案第 6、7、9.2 节。

**交付物：**

- Plugin 注册和 schema 测试；
- DM、普通群组、Forum Topic 路由测试；
- 缺 route/thread/user、非 Telegram、非法路径和 Telegram 失败测试；
- Secret symlink/mode/缺 Token 测试；
- 返回值和错误脱敏断言。

优先修改/创建：

```text
tests/integration/test_gateway_hook.py
tests/integration/test_preview_tool.py
```

**RED 步骤：**

1. 用 fake PluginContext 捕获 `register_tool`；
2. 断言工具名和 schema 仅包含 `files`、`entry`、`title`；
3. 用 ContextVar-backed fake session context 固定私聊/群组/Topic 行为；
4. 用临时 Secret 和 MockTransport 固定发送/失败契约；
5. 断言返回和异常不含输入的敏感哨兵；
6. 运行目标测试，确认因当前 Plugin 未注册 Tool 而稳定 RED。

**验收依据：**

```bash
uv run pytest tests/integration/test_preview_tool.py \
  tests/integration/test_gateway_hook.py -v
```

预期：新增契约在实现前失败；既有无关测试保持通过。测试不得读取真实 Hermes Home、真实 Secret 或发送 Telegram 请求。

**提交：**

```text
test: define preview delivery tool contract
```

### TASK 9.3：Session Context 与 Secret 安全层

**状态：** `TODO`

**方案来源：** 方案第 6.2、6.3、10 节；生命周期 Profile/Secret 所有权约束。

**交付物：**

- `integrations/hermes/preview_tool.py` 的 route/config/secret helpers；
- `src/hermes_peek/hermes_plugin/preview_tool.py` 可安装副本；
- pointer schema 增加 `env_file`；
- 临时 Profile 隔离和权限测试。

**实现要求：**

- 通过 `gateway.session_context.get_session_env()` 读取当前请求；
- 不直接以 stale `os.environ` 路由作为成功依据；
- Topic 同时要求 chat ID 和 thread ID；
- 任一必需字段缺失时零发送失败；
- 读取 pointer 指向的当前 Profile `env_file`；
- 拒绝 symlink、非普通文件和 group/other 有权限的 Secret；
- 只解析 Bot Token，不复制整个 Secret 环境；
- helper 返回稳定错误码，不泄露路径或值。

**验收依据：**

```bash
uv run pytest tests/integration/test_preview_tool.py \
  tests/integration/test_lifecycle.py -v
```

并确认 Profile A/B 不串用、Topic 缺 thread 不回退、Token 哨兵未进入输出。

**提交：**

```text
feat: load preview delivery context safely
```

### TASK 9.4：单消息 Preview Tool

**状态：** `TODO`

**方案来源：** 方案第 3、6、7 节。

**交付物：**

- `hermes_peek_send_preview` handler；
- `integrations/hermes/__init__.py` 和可安装副本的 `ctx.register_tool()`；
- 更新 `plugin.yaml` 描述/版本（若现有 Plugin 约定需要）；
- PreviewService/TelegramClient MockTransport 集成测试。

**实现要求：**

1. 校验 `files`、`entry`、`title`；
2. 复用 `PathPolicy` 与 `PreviewService`；
3. owner 使用当前 Session Context user；
4. 私聊发送 Web App 按钮，群组/Topic发送支持的 Direct Link，Topic保留 thread；
5. 一次 handler 调用最多调用一次 Telegram send；
6. 不创建 collector spool；
7. 返回结构化、脱敏的 success/failure；
8. Tool handler 异常转为失败结果，不破坏 Agent loop。

**验收依据：**

```bash
uv run pytest tests/integration/test_preview_tool.py \
  tests/integration/test_gateway_hook.py \
  tests/integration/test_cli_notify.py \
  tests/integration/test_hermes_collector.py -v
```

并确认 Tool schema 中无 token/chat/thread/owner，MockTransport 每个成功场景恰好一条消息，失败不伪成功、不产生第二条通知。

**提交：**

```text
feat: add preview delivery tool
```

### TASK 9.5：Skill + Plugin 生命周期分发

**状态：** `TODO`

**方案来源：** 方案第 4、8、10 节；阶段 8 transaction/owned-resource 机制。

**主要文件：**

```text
src/hermes_peek/lifecycle.py
src/hermes_peek/cli.py
pyproject.toml
tests/integration/test_lifecycle.py
tests/integration/test_lifecycle_e2e.py
tests/integration/test_lifecycle_ux.py
README.md
README.zh-CN.md
docs/04-hermes-integration.md
docs/06-installation-uninstallation.md
```

**RED 步骤：**

1. 断言 setup 计划和 manifest 包含 Skill owned resources；
2. 断言 setup 安装 Skill/Plugin/pointer，pointer 包含 `config_file` 与 `env_file`；
3. 断言 upgrade 备份并更新 Skill；
4. 断言 rollback 恢复旧 Skill/Plugin/pointer；
5. 断言 uninstall 删除未漂移 owned Skill，但拒绝删除用户修改的 Skill；
6. 断言 Profile A/B 隔离；
7. 断言 wheel/sdist 包含 Skill 和 Plugin 文件；
8. 运行目标测试确认 RED。

**GREEN 实现：**

- 为 `InstallPaths`/manifest/plan 增加目标 Profile Skill 目录和 owned-resource 记录；
- 源 Skill 从仓库/包资源安装，不从当前用户 `~/.hermes/skills` 复制；
- 复用 transaction backup/rollback 和 hash drift 保护；
- 不修改 Hermes 主配置；
- README 中英文说明完整能力依赖 Skill + Plugin Tool + Service；
- 文档说明新 Session/Gateway 重启生效边界。

**验收依据：**

```bash
uv run pytest tests/integration/test_lifecycle.py \
  tests/integration/test_lifecycle_e2e.py \
  tests/integration/test_lifecycle_ux.py -v
uv build
```

并检查 wheel/sdist 文件清单、setup→upgrade→rollback→uninstall 临时 Profile 闭环和 owned Skill drift 行为。

**提交：**

```text
feat: distribute preview skill with HermesPeek
```

### TASK 9.6：全量离线与新会话验收

**状态：** `TODO`

**方案来源：** 方案第 8、9 节；项目统一质量门禁。

**交付物：**

- 全量测试和编译构建结果；
- wheel 临时环境安装烟测；
- 临时 Hermes Profile 的 Skill/Tool 发现证据；
- Markdown 链接与 staged diff 敏感扫描结果；
- 阶段文档离线状态更新。

**验收命令：**

```bash
uv sync --locked
uv run pytest
uv run python -m compileall -q src integrations tests
uv build
git diff --check
```

另需现场验证：

1. 从 wheel 安装到临时 venv；
2. 对临时 `HERMES_HOME` 执行 setup；
3. 启动新的 Hermes 进程/会话，确认 Skill 可发现、Plugin Tool 已注册；
4. 不使用真实 Telegram，使用 MockTransport 完成新会话调用；
5. 检查 wheel/sdist 内 Skill/reference/Plugin 完整；
6. 检查 Markdown 本地链接；
7. 检查 staged diff 中密码、Token、私钥、个人 chat/user/thread ID 和机器专属路径 0 命中；
8. 确认 Git 工作区只含阶段预期文件。

**提交：**

```text
test: verify packaged preview skill integration
```

### TASK 9.7：真实 Telegram 单消息验收

**状态：** `BLOCKED_PENDING_APPROVAL`

**方案来源：** 方案第 9.3、10 节。

**阻塞原因：** 更新当前 Profile 的 Skill/Plugin 和从 Gateway 外重启均属于真实运行态变更，必须在离线阶段完成后单独获得项目负责人明确授权。

**交付物：**

- 当前 Profile 安装/升级记录；
- Gateway 外部重启后的 Skill/Tool/Service 状态；
- 私聊和当前 Forum Topic 的真实消息验收；
- 路由缺失失败测试；
- 必要时 transaction rollback 记录。

**真实验收步骤：**

1. 先展示脱敏升级计划；
2. 获得明确授权后更新当前 Profile；
3. 由 Gateway 外部重启 Gateway；
4. 创建新会话，确认 Skill 和 Tool 生效；
5. 私聊执行一次“把 README 发我看下”；
6. 当前 Topic 执行一次同类请求；
7. 确认每次工具进度只有一个 HermesPeek 专用 Tool；
8. 确认只收到一条带按钮的 Preview，无追加“已发送……”；
9. 点击按钮，确认 owner 授权和内容；
10. 构造路由缺失，确认报错且未改发私聊/Home；
11. 检查脱敏 Gateway/Service 日志无重复通知和敏感泄露。

**验收依据：** 真实 Telegram 观测，不得以 Mock、代码状态或用户自报替代现场复验。

**解除阻塞条件：** 项目负责人在 TASK 9.6 完成后明确批准真实 Profile 更新和 Gateway 外部重启。

**提交：** 仅当需要同步真实验收文档时创建：

```text
docs: record preview skill acceptance
```

不得为纯状态变化制造空提交。

## 6. 阶段完成条件

阶段 9 只有在以下条件全部满足后才可标记 `DONE`：

1. TASK 9.0–9.6 均有独立 commit 和现场离线验收证据；
2. TASK 9.7 获授权并完成真实私聊、Topic 和失败路由验收；
3. Skill 是仓库/包内权威源码，能力不依赖 Agent 私有记忆；
4. setup/upgrade/rollback/uninstall 正确管理 Skill 与 Plugin owned resources；
5. 全量测试、compileall、构建、临时安装、链接和敏感检查通过；
6. 当前运行态文档严格区分离线、临时 Profile 和真实 Telegram 证据；
7. 工作区干净，无未提交实现或敏感数据。
