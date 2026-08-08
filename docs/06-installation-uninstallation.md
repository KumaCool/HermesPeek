# HermesPeek 生命周期方案：安装、升级、安全卸载与 Purge

> **文档状态：** 方案已于 2026-08-05 经项目负责人评审通过。当前仓库已有离线验收通过的实现，并在独立授权下完成过一个记录在案的 Linux profile 真实生命周期验收；单环境验收不等于通用生产发布。
>
> **当前实现状态（2026-08-05）：** `RECORDED LINUX REAL-ENV ACCEPTANCE / NOT GENERAL RELEASE`。profile 作用域、共享配置、事务回滚、service 健康验证、所有权卸载、purge、Telegram 条件回滚和诊断 UX 已完成隔离测试；TASK 8.11 另记录了一个获授权 Linux profile 的真实 setup/uninstall/purge/rollback、systemd、Gateway 与 Telegram 验收。该证据不覆盖全新用户 onboarding、BotFather Main Mini App、跨平台 backend 或 Release 一键安装。新 Skill/Tool 仍仅在新 Hermes Session 中发现，之后对任何真实 profile 的变更和活跃 Gateway 重启都需独立授权。

## 1. 目标与非目标

### 1.1 目标

HermesPeek 最终应由单一 CLI 管理完整生命周期，普通用户不需要：

- 复制多个插件或 Hook 文件；
- 手工编辑 systemd unit、环境文件或 Hermes 配置；
- 逐条执行启用插件、启停服务和重启 Gateway 命令；
- 在卸载时猜测哪些目录可以删除；
- 为每次升级重复进入 Telegram Bot 设置。

目标命令面：

```text
hermes-peek setup [--profile NAME] [--plan] [--non-interactive ...]
hermes-peek status [--profile NAME]
hermes-peek doctor [--profile NAME]
hermes-peek service start|stop|restart|logs
hermes-peek upgrade [--profile NAME]
hermes-peek uninstall [--profile NAME] [--purge]
hermes-peek rollback [TRANSACTION_ID]
```

默认卸载必须非破坏性：解除 Hermes 集成、停止服务并移除安装器自有文件，同时保留 Preview Registry、collector spool、日志和备份。永久删除必须显式使用 `--purge`，支持删除计划、确认和恢复说明。

默认交互式 `setup` 在必要输入验证通过后直接执行，按真实事务阶段刷新进度，并以 `HermesPeek <version> installed successfully` 结束；内部 plan/result JSON 不面向普通用户。显式 `setup --plan` 仍是无副作用的机器可读审计接口。Purge 的破坏性确认规则不受此 UX 调整影响。

### 1.2 当前 v0.3.0 CLI 接口

本节记录当前 Release 已实现的命令。后文标为“目标”的 `--profile` 等接口属于设计方向，不应当作现有语法使用。已安装版本的最终权威来源是：

```bash
hermes-peek --help
hermes-peek <command> --help
```

#### 安装

Linux 且 systemd user manager 正常运行时，使用仓库安装器：

```bash
curl -fsSL https://raw.githubusercontent.com/KumaCool/HermesPeek/main/install.sh | sh
```

固定安装 v0.3.0：

```bash
curl -fsSL https://raw.githubusercontent.com/KumaCool/HermesPeek/v0.3.0/install.sh | sh
```

无人交互安装时，将 `setup` 参数放在 `sh -s --` 后：

```bash
curl -fsSL https://raw.githubusercontent.com/KumaCool/HermesPeek/main/install.sh | sh -s -- \
  --hermes-home "$HERMES_HOME" \
  --allowed-root /path/to/approved/workspace \
  --external-url https://preview.example.test \
  --telegram-env /path/to/restricted/secrets.env
```

安装器参数：

| 参数 | 作用 |
|---|---|
| `--version` | 输出安装器版本并退出 |
| `--dry-run` | 只输出安装动作，不下载或修改内容 |
| `--non-interactive` | 禁用交互向导；必须提供完整 setup 输入 |
| `--` | 后续参数全部转交给 `hermes-peek setup` |

`setup` 参数：

| 参数 | 作用 |
|---|---|
| `--allowed-root PATH` | 添加允许预览的根目录；可重复传入 |
| `--external-url HTTPS_BASE_URL` | Telegram 客户端可达的外部 HTTPS 基址，可包含代理路径前缀 |
| `--telegram-bot-username NAME` | Telegram Bot username |
| `--telegram-mini-app-short-name NAME` | 可选 Mini App short name |
| `--telegram-mini-app-mode compact` | Mini App 显示模式；当前仅支持 `compact` |
| `--telegram-env PATH` | 包含 `TELEGRAM_BOT_TOKEN` 的受限权限文件 |
| `--configure-telegram-menu` | 明确授权修改 Bot 私聊菜单按钮 |
| `--hermes-home PATH` | 指定目标 Hermes profile home |
| `--no-activate` | 不启动服务、不启用 Plugin、不重启 Gateway |
| `--plan` | 输出只读、脱敏 JSON 计划，不产生副作用 |

<a id="tailscale-serve-https"></a>

#### 使用 Tailscale Serve 获取外部 HTTPS 基址

如果没有现成的 HTTPS 域名，可以把 HermesPeek 只监听在本机的服务（`127.0.0.1:8765`）通过 [Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve) 发布到自己的 tailnet：

```bash
# 前提：本机已安装并登录 Tailscale，tailnet 已启用 MagicDNS/HTTPS
tailscale status
tailscale serve --bg http://127.0.0.1:8765
tailscale serve status
```

首次启用 Serve 时，Tailscale 可能要求在浏览器中确认 HTTPS。命令会显示类似下面的 URL：

```text
https://your-device.your-tailnet.ts.net
```

把该 URL 作为根路径外部 HTTPS 基址（不要附加 `/healthz`）填入交互向导，或传给：

```bash
hermes-peek setup \
  --allowed-root /path/to/approved/workspace \
  --external-url https://your-device.your-tailnet.ts.net
```

setup 完成、HermesPeek 服务启动后验证：

```bash
curl -fsS https://your-device.your-tailnet.ts.net/healthz
```

如果共享 HTTPS 域名已由 Nginx 等反向代理管理，也可以使用路径基址：

```bash
hermes-peek setup \
  --allowed-root /path/to/approved/workspace \
  --external-url https://example.test/apps/hermespeek/
```

代理必须匹配并剥离 `/apps/hermespeek`，再把余下路径转发到 `http://127.0.0.1:8765`。因此公共 `/apps/hermespeek/healthz` 到达上游时必须是 `/healthz`。内部探活保持不变：

```bash
curl -fsS http://127.0.0.1:8765/healthz
curl -fsS https://example.test/apps/hermespeek/healthz
```

HermesPeek 不支持让代理保留该前缀，也不根据 `X-Forwarded-Prefix` 动态改变行为。setup、update 和 uninstall 只保留应用配置，不创建、修改或删除代理规则。

重要边界：

- **Tailscale Serve 只在 tailnet 内可达。** 打开 Preview 的手机或桌面 Telegram 客户端所在设备也必须登录并连接同一个 tailnet；否则应使用你自己的反向代理/域名，或在理解公网暴露风险后另行配置 Tailscale Funnel。
- 不要把 `http://127.0.0.1:8765` 作为 `--external-url`；它只是 Serve/代理的本地上游，不是 Telegram 使用的外部 HTTPS 基址。
- HermesPeek 不会创建、接管或删除现有 Tailscale 规则。以上命令会修改本机 Tailscale Serve 配置，应由设备所有者明确执行。
- 不再使用时先查看现有规则，再删除；`reset` 会清除本机的**全部** Serve 配置，不应在共享配置的设备上盲目执行：

  ```bash
  tailscale serve status
  tailscale serve reset
  ```

#### 更新

```bash
hermes-peek update --check
hermes-peek update --plan
hermes-peek update
hermes-peek update --version 0.3.0 --yes
```

`upgrade` 是 `update` 的别名。自动更新仅支持仓库 `install.sh` 创建并带有效所有权元数据的 curl 安装。它会校验 Release 资产、原子切换 CLI、重新应用集成，并执行 `status` 和 `doctor`；失败时恢复上一版本。

| 参数 | 作用 |
|---|---|
| `--check` | 检查最新版本并输出 JSON，不执行更新 |
| `--plan` | 输出只读更新计划 |
| `--version VERSION` | 指定目标 Release |
| `--yes` | 跳过交互确认；无人交互执行时必需 |

#### 默认卸载与 Purge

默认卸载会从安装清单读取 Hermes profile，停用并删除 HermesPeek 集成和受管 CLI，同时保留 Preview 数据：

```bash
hermes-peek uninstall
```

先查看永久删除计划，再确认 Purge：

```bash
hermes-peek uninstall --purge --dry-run
hermes-peek uninstall --purge --yes
```

| 参数 | 作用 |
|---|---|
| `--hermes-home PATH` | 高级覆盖：仅允许显式指定与安装清单一致的 Hermes profile；通常应省略 |
| `--purge` / `--purge-data` | 同时永久删除 HermesPeek 数据 |
| `--dry-run` | 与 `--purge` 一起输出删除计划，不执行删除 |
| `--yes` | 无人交互确认 Purge |
| `--no-deactivate` | 跳过服务、Plugin 和 Gateway 停用，仅用于受控恢复 |

Purge 不删除允许根目录中的原始项目文件。默认 `uv tool` 安装无法安全自删除时，CLI 会明确提示执行 `uv tool uninstall hermes-peek`。

#### 状态、诊断、服务与回滚

```bash
hermes-peek status
hermes-peek doctor
hermes-peek service start|stop|restart|logs
hermes-peek rollback <transaction-id>
```

### 1.3 非目标

生命周期工具不得：

- 删除用户原始项目文件；
- 删除整个 Hermes profile、其他插件、Gateway 配置或 Telegram webhook；
- 修改其他 Hermes profile；
- 删除用户已有的 Tailscale 配置、证书或 Serve/Funnel 规则，除非 manifest 能证明该资源由 HermesPeek 独占创建；
- 绕过 Telegram 的 Bot owner 确认或 BotFather 官方限制；
- 把失败的停服、插件禁用或 Gateway 激活伪装成成功。

## 2. 当前原型与目标能力差距

| 能力 | 当前原型 | 目标状态 | 当前结论 |
|---|---|---|---|
| `setup` CLI | 已有 `--allowed-root`、`--external-url`、`--telegram-env`、`--hermes-home`、`--no-activate` | 自动发现 profile，交互/无人值守双模式 | `PARTIAL` |
| 插件打包 | Wheel 内已包含 4 个 plugin 文件 | 带版本、签名/哈希和原子目录切换 | `PARTIAL` |
| service unit | 可生成绝对 `ExecStart` 的 hardened user unit | backend 预检、健康检查、失败回滚 | `PARTIAL` |
| Hermes profile 作用域 | 文件可写到指定 home，但 Hermes 子命令未绑定同一目标 | 所有命令明确绑定同一 profile/home | `P0 GAP` |
| Gateway/插件配置 | service env 已生成 | 插件与 service 读取同一非敏感配置 | `P0 GAP` |
| Telegram Token | 可从 `.env` 读取并做格式检查 | `getMe` 在线验证、日志脱敏、配置变更可回滚 | `P1 GAP` |
| 安装事务 | 原子写单个文件，有 manifest | stage/apply/verify/commit/rollback journal | `P0 GAP` |
| 默认卸载 | 初版保留 state | 必须先确认停服、插件卸载和 Gateway 状态 | `P0 GAP` |
| Purge | 初版 `--purge-data` | `--dry-run`、删除清单、确认、备份与恢复说明 | `P1 GAP` |
| 所有权保护 | manifest 记录插件哈希，但卸载未使用 | 哈希校验；修改文件先备份；无 manifest 拒绝递归删除 | `P1 GAP` |
| `status`/`doctor` | 未实现 | 诊断 profile、service、端口、插件、Telegram、HTTPS | `TODO` |
| 真实安装/卸载验收 | 未执行 | 临时环境、隔离 Gateway、真实授权环境分层验收 | `BLOCKED_PENDING_APPROVAL` |

当前原型已经证明 CLI、打包和基础文件生命周期可实现，但不能据此宣称“一键安装/卸载已完成”。在本方案的 P0/P1 门槛通过前，README 和运维文档只能称其为开发原型。

## 3. 单一配置与 Secret 模型

服务和 Hermes Gateway 插件必须共享同一份**非敏感配置**，避免 service 健康但插件因缺少环境变量而静默不工作。

建议文件：

```text
~/.config/hermes-peek/config.json       # 0644 或 0600，非敏感行为配置
~/.config/hermes-peek/secrets.env       # 0600，只保存 Token 等 Secret
~/.config/hermes-peek/install.json      # 0600，资源所有权与事务状态
~/.local/state/hermes-peek/             # 0700，Registry/spool/备份/journal
```

`config.json` 至少包含：

- schema version；
- 明确的目标 Hermes profile/home；
- allowed roots；
- state directory；
- external HTTPS origin；
- service backend 和监听地址；
- Telegram 集成模式，但不含 Token。

`secrets.env` 只保存运行服务必须的 Secret。插件通过共享 config 文件读取 allowed roots、state dir 和 external URL，不要求把行为配置写进 Hermes `.env`。日志、manifest、status 和 doctor 输出统一使用 `[REDACTED]`。

## 4. Hermes profile 作用域

`--profile NAME` 应是首选用户接口，`--hermes-home PATH` 仅保留为高级或测试参数。安装器内部建立单一目标对象：

```text
HermesTarget(profile, hermes_home, subprocess_env, config_path)
```

以下所有操作必须引用同一目标：

- 插件复制位置；
- Token 读取位置；
- `hermes plugins list/enable/disable`；
- `hermes gateway status/restart`；
- install manifest；
- 卸载和 rollback。

任何 profile/home 不一致都必须在产生副作用前失败。安装前后运行目标 profile 的插件列表与 Gateway 状态验证，禁止出现“文件安装到 A、配置修改 B”的情况。

## 5. Telegram 自动化边界

### 5.1 可自动化能力

在已有合法 Bot Token 的前提下，CLI 可以：

- 从目标 Hermes profile 发现 `TELEGRAM_BOT_TOKEN`；
- 调用 `getMe` 验证 Token、Bot ID 和 username；
- 只读检查 `getWebhookInfo`，不得擅自破坏 Hermes polling/webhook 模式；
- 在明确启用后调用 `setChatMenuButton` 配置普通私聊菜单 Web App；
- 配置项目自有 Bot commands；
- 记录变更前值，在 rollback/uninstall 时只恢复 HermesPeek 修改的设置。

API 错误不得打印 Token 或完整敏感响应。

### 5.2 Telegram 官方硬限制

普通 Bot API 不能让本地 CLI 静默创建任意普通 Bot，也不能替代所有 BotFather 所有者流程。

Telegram Main Mini App 的首次注册、命名和 URL 绑定仍有 BotFather/Telegram UI 边界。`setChatMenuButton` 只配置菜单 Web App，不等价于 Main Mini App 元数据和 `startapp` Direct Link 所需配置。因此：

1. 项目维护者可以预配置官方 Bot，普通用户不再接触 BotFather；
2. 自托管且自带 Bot 的用户首次仍需完成一次 Telegram 官方确认；
3. CLI 负责自动检测前提、给出最短引导并在条件不满足时安全阻塞；
4. 文档不得承诺绕过 BotFather。

Managed Bots 也需要 manager bot 和 Telegram UI 的用户确认，首版不作为默认安装路径。

## 6. Setup 目标流程

### 6.1 Discover 与 plan

`hermes-peek setup --plan` 只读输出：

- 目标 Hermes profile/home；
- Hermes 和 HermesPeek 版本；
- plugin、Gateway、systemd user manager 当前状态；
- 将创建、替换、保留和重启的资源；
- Telegram 检测结果与 BotFather 前提；
- 风险、阻塞和回滚点；
- 所有 Secret 均显示为 `[REDACTED]`。

交互模式自动发现安全默认值，只询问无法可靠推导的信息。无人值守模式要求所有不可推导参数显式提供，缺失即失败。

### 6.2 Preflight

产生副作用前必须验证：

1. 目标 profile 唯一且一致；
2. Hermes 支持 `final_message_actions`；
3. systemd user bus 可用，或存在经支持的替代 backend；
4. executable 是稳定绝对路径；
5. allowed roots 存在且不是 `/`、整个 home、Secret 目录或 symlink 逃逸；
6. external URL 是无凭据、query、fragment 的 HTTPS origin；
7. Token 格式与 `getMe` 在线校验通过；
8. 端口不被无关进程占用；
9. 磁盘空间、目录权限和安装锁正常。

当前机器已观察到 `systemctl --user` bus 不可用的情况，因此 backend 检查必须是硬门槛，不能启动不受管理的 `nohup` 进程后声称安装成功。

### 6.3 Stage、apply 与 verify

所有文件先写事务 staging 目录并校验 YAML/JSON、权限、plugin import 和 unit。事务至少备份：

- 原 plugin 目录；
- 旧兼容 Hook；
- 原 unit、config、secrets、manifest；
- 插件启用状态；
- service enabled/active 状态；
- Gateway 原状态；
- Telegram 被修改设置的旧值。

应用顺序：

1. 获取安装锁并创建 transaction journal；
2. 原子安装共享配置和 Secret；
3. 原子安装 service unit，reload/start；
4. 验证 loopback `/healthz` 和进程状态；
5. 原子安装目标 profile plugin；
6. 对准确 profile 启用插件，拒绝工具覆盖；
7. 在安全场景重启 Gateway；若调用来自当前 Gateway 会话，则返回 `activation_pending_gateway_restart`，不得自杀式重启；
8. 验证插件、Gateway 和 collector 配置；
9. 可选配置 Telegram Bot API 能力并验证；
10. 全部通过后将 journal 标记 committed。

任何步骤失败都按 journal 逆序恢复。不能完成自动回滚时输出明确的 transaction ID、残留资源和恢复命令，不得输出“安装成功”。

## 7. Upgrade 目标流程

升级复用 setup 事务，而不是覆盖安装：

1. `--plan` 显示版本、迁移和重启影响；
2. 备份当前 committed 安装；
3. 在 staging 中构建新 plugin/config/unit；
4. 运行 schema migration 和离线验证；
5. 原子切换；
6. 健康检查、Gateway 验证和 Telegram smoke test；
7. 失败自动恢复旧版本和旧配置；
8. Preview Registry 默认原地保留，任何破坏性 migration 必须有独立备份。

## 8. 安全卸载与 Purge

### 8.1 默认卸载

目标命令：

```bash
hermes-peek uninstall --profile NAME
```

顺序必须是：

1. 获取安装锁并验证 committed manifest；
2. 输出将停止、删除和保留的资源；
3. 停止 HermesPeek service，并确认进程与监听端口已退出；
4. 禁用准确 profile 的 plugin；
5. 重启/重载准确 Gateway，并确认插件不再加载；
6. 只有完成停用确认后才删除 installer-owned plugin、unit 和 secrets；
7. `daemon-reload` 并做负向健康检查；
8. 保留 Registry、spool、日志、journal 和卸载备份；
9. 写入脱敏卸载报告。

停服、插件禁用或 Gateway 激活失败是硬失败：保留仍被加载所需的文件，并报告 `deactivation_pending`，不能继续删文件后返回成功。

### 8.2 资源所有权

manifest 记录每个 owned path 的类型、安装前状态、安装后哈希和归属 transaction。卸载前重新计算哈希：

- 未修改的 owned 文件可以删除；
- 已修改的文件默认移动到 `uninstall-backups/<transaction-id>/`；
- 无 manifest 时默认拒绝递归删除；
- 不跟随 symlink；
- 每个目标必须重新验证位于批准目录内；
- 绝不按模糊 glob 删除 Hermes、systemd 或用户目录。

### 8.3 Purge

目标命令：

```bash
hermes-peek uninstall --purge --dry-run
hermes-peek uninstall --purge
```

`--dry-run` 必须列出：

- Preview Registry；
- collector spool；
- 配置、Secret、日志、journal 和备份；
- 每项路径、类型、大小、所有权证据和是否可恢复；
- 明确声明原始项目文件不在删除范围。

交互模式要求输入安装 ID 或等价二次确认；无人值守模式要求显式 `--yes`。先完成默认卸载和停用验证，才允许 purge。Purge 前可选创建离线备份，结果报告保留备份路径和恢复方式。

## 9. Status、Doctor 与服务管理

`status` 提供稳定机器可读状态：

- profile/home；
- manifest 和 transaction 状态；
- service enabled/active/health；
- plugin installed/enabled/loaded；
- Gateway 状态；
- Telegram `getMe` 和 Main Mini App 前提；
- external URL 可达性；
- 配置漂移和 owned file 哈希；
- 数据目录存在性和大小，不泄露 Preview ID。

`doctor` 执行只读诊断并给出修复建议。`service` 子命令封装 start/stop/restart/logs，用户不需要记忆 systemctl 命令；非 systemd backend 必须有明确实现，不能默默降级。

## 10. 数据保留矩阵

| 资源 | Setup/Upgrade | 默认 uninstall | `--purge` | 说明 |
|---|---|---|---|---|
| 原始项目文件 | 只读引用 | 保留 | 保留 | 永不属于安装器 |
| Preview Registry | 保留/迁移 | 保留 | 删除 | Purge 前可备份 |
| collector spool | 保留/兼容迁移 | 保留 | 删除 | 可包含路径元数据，权限 0700 |
| plugin 文件 | 安装/升级 | 删除或备份修改版 | 删除 | 仅 manifest-owned |
| legacy Hook | 先备份再停用 | 删除或恢复旧状态 | 删除 HermesPeek-owned | 防止双通知 |
| service unit | 安装/升级 | 删除 | 删除 | 必须先停服 |
| 非敏感 config | 更新 | 默认保留或按选项保留 | 删除 | 支持快速重装 |
| Secret | 更新 | 默认删除 | 删除 | 降低 Token 残留风险 |
| manifest/journal | 更新 | 保留卸载报告 | 删除 | 审计与恢复用途 |
| 日志/备份 | 轮转 | 保留 | 删除 | Purge 前明确列出 |
| Hermes 其他配置 | 不修改 | 不修改 | 不修改 | profile 隔离 |
| Telegram Bot/Main Mini App | 记录本工具变更 | 仅恢复本工具变更 | 不删除 Bot | 共享资产保护 |
| Tailscale 规则 | 仅明确接管时记录 | 仅撤销 owned rule | 同左 | 不碰用户既有规则 |

## 11. 测试与验收矩阵

### 11.1 单元测试

- profile/home 命令作用域；
- config/secret 分离与脱敏；
- manifest schema、哈希和 symlink 防护；
- transaction apply/rollback 每一步故障注入；
- uninstall 停服失败、Gateway 失败和配置漂移；
- purge dry-run、确认和根目录保护；
- Telegram `getMe`、菜单设置、API 错误脱敏；
- executable 绝对路径与 backend 选择。

### 11.2 临时环境集成

- 空临时 Hermes home 安装→status→默认卸载→重装；
- 命名 profile A/B 隔离，确认不修改 default；
- 旧 plugin/Hook/unit/config 存在时升级和回滚；
- 修改 owned 文件后卸载进入备份而非丢失；
- 无 manifest、损坏 manifest、并发 setup/uninstall；
- systemd user bus 不可用时前置失败且零副作用；
- 默认卸载保留 Registry，purge 删除 Registry 且保留原始文件；
- Wheel 安装后 plugin 资源存在。

### 11.3 隔离 Gateway E2E

- 目标 profile plugin enable/load；
- collector 与 service 使用同一配置和 state；
- Hermes 写文件后同一最终消息出现 Preview action；
- rollback 后 Hermes 普通回复不受影响；
- 错误路径不产生重复消息。

### 11.4 真实环境验收

必须单独获得项目负责人授权后执行：

1. `setup --plan` 审批；
2. 真实 profile setup；
3. `/healthz`、status、doctor；
4. Telegram 私聊、群组、Forum Topic；
5. 默认 uninstall 并确认数据保留；
6. 重装并验证恢复；
7. 使用专用测试状态目录执行 purge；
8. 回滚与紧急隔离演练。

真实凭据、Preview ID、内部域名和连接密钥均不得写入验收记录。

## 12. 发布门槛

只有满足以下条件才可以把 README 中的“一键安装/卸载”从原型改为正式能力：

- P0：profile 作用域修复；
- P0：service/plugin 共享配置；
- P0：setup transaction 与自动 rollback；
- P0：uninstall 停服和 Gateway 硬门槛；
- P1：manifest 所有权与修改文件备份；
- P1：Telegram `getMe` 在线验证；
- P1：`status`、`doctor`、`--plan`、`--dry-run`；
- systemd user bus 不可用场景有明确失败或受支持 backend；
- 打包、全量测试、安全扫描和文档链接检查通过；
- 真实环境安装、默认卸载、恢复和 purge 验收通过；
- 回滚演练证明不会破坏 Hermes 普通回复、其他 profile 或用户文件。

具体实施 TASK 和当前开发进度见 [`plan/03-lifecycle-setup-uninstall-rollout.md`](plan/03-lifecycle-setup-uninstall-rollout.md)。
