# 03 HermesPeek 生命周期 Setup/Uninstall 实施计划

> 本计划执行 [`../06-installation-uninstallation.md`](../06-installation-uninstallation.md)。本文维护任务、依赖、当前代码进度、验收命令、回滚门槛和提交边界。

**计划状态（2026-08-05）：** `REVIEW_APPROVED / PROTOTYPE_EXISTS / READY_TO_CONTINUE`

**执行约束：**

- 先评审方案和计划，再继续修改生命周期代码；
- 当前原型不进入真实 Hermes profile，不重启真实 Gateway；
- 每个 TASK 独立提交并记录真实验收证据；
- 任一时刻只允许一个 TASK 为 `IN_PROGRESS` 或 `VERIFYING`；
- 所有 Secret、能力型 Preview 标识和连接密钥在文档/日志中写为 `[REDACTED]`。

## 1. 当前开发基线

### 1.1 已存在但尚未提交的原型

| 文件 | 当前内容 | 评估 |
|---|---|---|
| `src/hermes_peek/lifecycle.py` | InstallPaths、setup/uninstall、env/unit/manifest 生成、基础哈希 | 原型；存在 P0/P1 缺口 |
| `src/hermes_peek/cli.py` | `setup`、`uninstall` 参数和调用入口 | 原型；命令面未达到最终方案 |
| `src/hermes_peek/hermes_plugin/` | Wheel 内置 plugin 四文件 | 基础打包已验证 |
| `tests/integration/test_lifecycle.py` | 临时目录 setup/uninstall/purge 基础往返 | 覆盖不足，不能证明安全上线 |
| `pyproject.toml` | Hatch wheel/sdist 打包声明 | 已成功构建过 wheel/sdist |
| `docs/06-installation-uninstallation.md` | 生命周期总体方案 | 本轮重构为目标方案与差距说明 |

### 1.2 已验证证据

- 生命周期定向测试：`6 passed`；
- 全量回归：`82 passed`，1 条 Starlette/httpx 弃用警告；
- `compileall` 通过；
- `uv build` 成功生成 sdist 和 wheel；
- Wheel 中确认包含 4 个 Hermes plugin 文件；
- Markdown 本地链接和新增 diff 敏感值扫描曾通过；
- 未执行真实 profile setup/uninstall，未因本阶段重启真实 Gateway。

### 1.3 审计发现的阻断问题

1. **P0 profile 作用域错误风险：** 插件文件可写到 `--hermes-home`，但裸 `hermes plugins/gateway` 子命令可能作用于 default profile。
2. **P0 配置断链：** service env 已写入，但 Gateway plugin 不一定获得 allowed roots/state/external URL，可能健康却不收集。
3. **P0 无事务回滚：** 中途失败会留下部分 unit、plugin、env 或启用状态。
4. **P0 卸载停用失败仍删文件：** 当前 best-effort 路径可能留下仍加载的旧进程。
5. **P1 所有权不足：** manifest 哈希未用于卸载，修改过或非本工具创建的目录可能被递归删除。
6. **P1 缺少 Telegram 在线校验：** 只有 Token 格式检查，没有 `getMe`、Bot identity 和设置回滚。
7. **P1 缺少产品命令：** 尚无 `--plan`、`status`、`doctor`、service、rollback、purge dry-run。
8. **环境阻塞：** 当前机器观察到 systemd user bus 不可用，真实 setup 必须阻塞或使用未来受支持 backend。

## 2. TASK 总览

| TASK | 名称 | 状态 | 依赖 | 发布门槛 |
|---|---|---|---|---|
| TASK 8.0 | 方案、计划与进度同步 | `DONE` | 无 | 2026-08-05 评审通过 |
| TASK 8.1 | 原型基线冻结与失败测试 | `DONE` | 8.0 | 风险测试已转为正式回归测试 |
| TASK 8.2 | Hermes target/profile 作用域 | `DONE` | 8.1 | `HERMES_HOME` 明确绑定、target identity 入 manifest |
| TASK 8.3 | 共享配置与 Secret 分离 | `DONE` | 8.2 | `config.json` + `secrets.env` |
| TASK 8.4 | Setup transaction、备份与 rollback | `DONE_OFFLINE` | 8.3 | 文件与 service/plugin/Gateway 状态可恢复；显式 transaction rollback 已实现 |
| TASK 8.5 | Service backend、健康检查与激活策略 | `DONE_OFFLINE` | 8.4 | bus/端口 preflight 与 loopback health、PID、监听验证已用 fake 验收 |
| TASK 8.6 | 安全 uninstall 与资源所有权 | `DONE_OFFLINE` | 8.5 | schema v2 记录全文件 ownership/hash/transaction；target/path/symlink 校验与漂移备份已验收 |
| TASK 8.7 | Purge、dry-run 和恢复 | `DONE_OFFLINE` | 8.6 | CLI `--purge/--dry-run/--yes`、交互确认、先卸载及越界保护已用临时目录验收 |
| TASK 8.8 | Telegram 检测与可回滚自动配置 | `DONE_OFFLINE` | 8.3 | getMe/webhook/menu 已接入 setup transaction，变更 journal 化并条件回滚；仅 fake 验收 |
| TASK 8.9 | status、doctor、service UX | `PARTIAL` | 8.5/8.8 | 基础命令已实现；完整 schema 与探测矩阵待增强 |
| TASK 8.10 | 打包、文档与隔离 E2E | `IN_PROGRESS` | 8.2–8.9 | 现场 103 tests、compileall/build/wheel smoke 通过 |
| TASK 8.11 | 真实安装/卸载/purge 验收 | `BLOCKED_PENDING_APPROVAL` | 8.10 | Release |

## 3. TASK 细化

### TASK 8.0：方案、计划与进度同步

**状态：** `DONE_UNCOMMITTED`

**交付物：**

- `docs/06-installation-uninstallation.md`；
- `docs/plan/03-lifecycle-setup-uninstall-rollout.md`；
- README、Hermes 集成和运维文档的能力状态同步；
- 总任务计划加入阶段 8 索引。

**验收：**

- 文档明确区分目标方案、当前原型、已验证证据与阻断缺口；
- 不把原型描述为生产就绪；
- Telegram Bot API 和 BotFather 边界准确；
- 默认卸载保留数据，purge 显式且有 dry-run/确认/备份；
- 真实 profile/Gateway 操作保持未执行；
- Markdown 本地链接、`git diff --check`、敏感值扫描通过。

**提交边界：** 仅文档；是否将已有原型代码另行冻结提交由项目负责人评审后决定。

### TASK 8.1：原型基线冻结与失败测试

**状态：** `DONE_UNCOMMITTED`

**目标：** 在继续实现前把审计发现转成可复现失败测试，避免直接修代码掩盖风险。

**交付物：**

- 原型代码边界说明；
- profile A/B 隔离失败测试；
- Gateway plugin 共享配置失败测试；
- 激活步骤故障注入和 rollback 失败测试；
- service stop/Gateway restart 失败时不得删文件测试；
- manifest 丢失、哈希漂移和 symlink 删除保护测试。

**验收：** 每个 P0/P1 风险至少有一个能在当前原型上稳定失败的测试，并记录失败原因；不接触真实 profile。

**验收记录（2026-08-05）：**

```bash
uv run pytest tests/integration/test_lifecycle.py -q -rxX
```

结果：`4 passed, 5 xfailed`。5 个 `strict=True` xfail 分别稳定捕获：Hermes 命令未绑定目标 home、Gateway plugin 无法读取 setup 的 service-only env、plugin enable 失败后文件未回滚、service stop 失败后仍删除资源、无 manifest/哈希所有权仍递归删除 plugin 目录。若后续实现意外绕过断言会产生 XPASS 并令测试失败。测试只使用临时目录和 recording/failing runner，未接触真实 profile、systemd 或 Gateway。

**提交：** 尚未创建；当前工作区混有此前原型和阶段 7 变更，提交前必须按 TASK 边界暂存并复核。

### TASK 8.2：Hermes target/profile 作用域

**状态：** `TODO`

**目标：** 保证文件、CLI、Gateway 和 manifest 始终作用于同一目标 profile。

**实现建议：**

- 新增 `HermesTarget`；
- CLI 首选 `--profile NAME`；
- 探测 Hermes CLI 的准确 profile 参数或为 subprocess 注入明确作用域；
- 所有 Hermes 子命令经过统一 runner，不允许裸命令散落；
- setup/uninstall/status/rollback 都验证 target identity。

**验收：**

- profile A 安装不会修改 default/B；
- profile A 卸载不会禁用 default/B 插件；
- home/profile 不一致在副作用前失败；
- manifest 记录稳定 target identity。

**回滚门槛：** 任一 cross-profile 测试失败，不进入下一 TASK。

### TASK 8.3：共享配置与 Secret 分离

**状态：** `TODO`

**目标：** service 和 Gateway plugin 使用同一非敏感配置，Token 独立保存。

**交付物：**

- versioned `config.json` schema；
- `secrets.env`；
- `Settings.from_file_and_env()` 或等价加载层；
- plugin 配置加载器；
- 原 env 兼容迁移与回滚。

**验收：**

- service 与 plugin 得到相同 allowed roots/state/external URL；
- plugin 不需要读取 Bot Token 即可创建 final action；
- Secret 不出现在 config、manifest、status、doctor 和错误日志；
- profile A/B 配置隔离。

### TASK 8.4：Setup transaction、备份与 rollback

**状态：** `TODO`

**目标：** 所有 setup/upgrade 副作用可追踪、可逆、可恢复。

**交付物：**

- install lock；
- transaction journal；
- staging 目录；
- 原文件与状态备份；
- `commit()`/`rollback()`；
- `hermes-peek rollback [ID]`；
- 中断后 `--resume` 或安全恢复策略。

**故障注入点：** 写 config、安装 unit、daemon-reload、启动 service、健康检查、安装 plugin、enable plugin、Gateway restart、Telegram 设置。

**验收：** 每个故障点失败后，旧版本、旧启用状态、旧 service 状态和旧 Telegram 设置均恢复；无法恢复时报告 transaction ID 和精确残留，不返回成功。

### TASK 8.5：Service backend、健康检查与激活策略

**状态：** `TODO`

**目标：** 不把“文件已写”误报为“服务已安装并激活”。

**交付物：**

- systemd user backend interface；
- bus preflight；
- start/stop/status/logs；
- loopback `/healthz`、PID 和端口验证；
- 当前会话来自 Gateway 时的 `activation_pending_gateway_restart`；
- 非 systemd 平台明确不支持或实现正式 backend。

**验收：**

- bus 不可用时零副作用失败；
- 端口被无关进程占用时失败；
- 启动后仅 loopback 监听；
- stop 后 PID/端口均退出；
- 不使用不受管理的 `nohup` 降级。

### TASK 8.6：安全 uninstall 与资源所有权

**状态：** `TODO`

**目标：** 先可靠解除运行态，再删除且只删除 installer-owned 资源。

**交付物：**

- committed manifest 校验；
- owned resources 和安装后哈希；
- 修改文件自动备份；
- symlink 与目录边界保护；
- `deactivation_pending` 状态；
- 幂等卸载报告。

**验收：**

- service stop 失败时不删 unit/env/plugin；
- Gateway restart 失败时保留仍加载 plugin 所需文件；
- 修改过的 plugin/config 被备份；
- 无 manifest 默认拒绝递归删除；
- 其他 plugin/profile/systemd unit 不受影响；
- 重复卸载安全且状态准确。

### TASK 8.7：Purge、dry-run 和恢复

**状态：** `TODO`

**目标：** 永久删除必须显式、可预览、可确认且不触及原始文件。

**交付物：**

- `uninstall --purge --dry-run`；
- 删除清单与大小统计；
- 交互二次确认、无人值守 `--yes`；
- 可选 purge 前备份；
- 恢复说明和脱敏报告。

**验收：**

- 未完成默认停用时拒绝 purge；
- dry-run 零副作用；
- 不删除 allowed roots 中的原始文件；
- root/home/越界路径保护；
- 默认 uninstall 保留数据，purge 才删除 state/config/log/backups。

### TASK 8.8：Telegram 检测与可回滚自动配置

**状态：** `TODO`

**目标：** 自动处理公开 Bot API 能力，并诚实暴露 BotFather 限制。

**交付物：**

- `getMe` 验证与 identity 比对；
- `getWebhookInfo` 只读检查；
- 可选 `setChatMenuButton`/commands；
- 旧值记录、rollback/uninstall 恢复；
- Main Mini App 前提检测与最短官方引导；
- API 错误脱敏。

**验收：** invalid/revoked/wrong-bot Token 在副作用前失败；不删除 webhook；Telegram 设置只恢复本工具修改的值；测试输出不含 Token。

### TASK 8.9：status、doctor、service UX

**状态：** `TODO`

**目标：** 用户不需要读取多个日志或手工执行 systemctl/Hermes 命令。

**交付物：**

- `status [--json]`；
- `doctor`；
- `service start|stop|restart|logs`；
- config drift、health、profile、plugin、Gateway、Telegram 和 HTTPS 检查。

**验收：** JSON schema 稳定；只读命令零副作用；输出无 Token、Preview ID、内部连接密钥和文件内容。

### TASK 8.10：打包、文档与隔离 E2E

**状态：** `TODO`

**目标：** 形成可进入真实验收的 Release Candidate。

**验收命令：**

```bash
uv sync --locked
uv run pytest
uv run python -m compileall -q src integrations tests
uv build
git diff --check
```

另需：

- 从 wheel 安装到临时 venv；
- 检查 plugin/config schema 资源；
- 临时 profile A/B 全生命周期；
- 隔离 Gateway final action E2E；
- Markdown 链接和 Secret 扫描；
- 文档与 `--help` 一致；
- 回滚和卸载安全矩阵全部通过。

### TASK 8.11：真实安装、卸载与 Purge 验收

**状态：** `BLOCKED_PENDING_APPROVAL`

**阻塞原因：** 会修改真实 Hermes profile、启停 service、重启 Gateway，并可能改变 Telegram Bot 菜单设置。

**解除条件：**

- TASK 8.1–8.10 全部 `DONE`；
- 项目负责人审核 `setup --plan` 和 `uninstall --purge --dry-run`；
- 明确提供测试 profile、维护窗口、Telegram 测试范围和回滚责任人；
- 所有真实标识在记录中脱敏。

**现场验收：** setup、status、doctor、Telegram 私聊/群组/Topic、默认卸载、重装恢复、专用测试状态 purge、rollback 和紧急隔离。

## 4. 提交策略

建议提交顺序：

1. `docs: define lifecycle setup and safe uninstall plan`（TASK 8.0，仅文档）；
2. `test: capture lifecycle safety gaps`；
3. `feat: scope lifecycle operations to hermes target`；
4. `feat: share lifecycle configuration safely`；
5. `feat: add transactional setup rollback`；
6. `feat: manage and verify local service lifecycle`；
7. `feat: enforce owned-resource uninstall`；
8. `feat: add explicit purge planning and recovery`；
9. `feat: validate and configure telegram lifecycle`；
10. `feat: add lifecycle status and doctor commands`；
11. `docs: finalize lifecycle operations and release evidence`。

当前未提交的原型代码不得混入 TASK 8.0 文档提交。评审后应选择：

- 将原型单独冻结为明确的 `prototype` commit，再从失败测试推进；或
- 保留工作区原型但只暂存 TASK 8.0 文档；或
- 经负责人指示撤销原型，从测试重新实现。

## 5. 完成定义

阶段 8 只有在以下条件全部满足时才可标记 `DONE`：

- 所有 P0/P1 gap 关闭；
- setup/upgrade/uninstall/purge/rollback 幂等且有事务证据；
- profile 隔离与资源所有权测试通过；
- 默认卸载保留数据，purge 不删除原始文件；
- Telegram 自动化与 BotFather 边界准确；
- systemd bus 不可用场景行为明确；
- Wheel、全量测试、隔离 E2E 和安全检查通过；
- 真实环境验收经授权通过；
- 文档、CLI help、代码行为和验收记录一致；
- 独立 commits 已创建且工作区干净。
