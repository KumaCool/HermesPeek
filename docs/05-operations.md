# 05 HermesPeek 本机服务运维

## 1. 边界

本阶段提供一个最小 systemd user service 模板，但不会自动安装、启用或启动服务。应用强制 `serve` 只接受回环地址 `127.0.0.1` 或 `::1`，不能直接监听公网地址。

阶段 5.2/5.3 的 WireGuard、HTTPS 和 Tunnel 配置不在本文件的自动执行范围；它们需要具体目标环境与单独明确授权。

## 2. 本机安装前检查

```bash
cd /path/to/HermesPeek
uv sync --dev
uv run pytest tests/integration/test_local_service.py -q
systemd-analyze verify deploy/systemd/hermes-peek.service
```

将项目安装到一个稳定、可升级且能提供 `hermes-peek` 可执行文件的位置。不要让 systemd 依赖临时 checkout 或临时虚拟环境。

## 3. 环境文件

复制示例并限制读取权限：

```bash
install -d -m 0700 ~/.config/hermes-peek
install -m 0600 deploy/systemd/hermes-peek.env.example \
  ~/.config/hermes-peek/hermes-peek.env
```

然后手动替换示例值。特别注意：

- `HERMES_PEEK_ALLOWED_ROOTS` 只能列出明确批准的只读工作目录；
- `HERMES_PEEK_STATE_DIR` 应与 unit 的 `ReadWritePaths` 一致，默认使用用户的 `~/.local/state/hermes-peek`；
- `HERMES_PEEK_EXTERNAL_BASE_URL` 必须是后续经批准入口的 HTTPS URL；
- Bot Token（仅显式通知 CLI 或旧独立通知兼容路径需要）只能存在权限为 `0600` 的环境文件或等价 secret store；阶段 6 `final_message_actions` 路径不需要 Bot Token；
- 生产环境保持 `HERMES_PEEK_DEVELOPMENT=false`。

systemd 的 EnvironmentFile 值不应依赖 shell 展开；将示例中的路径占位符改成目标用户的实际绝对路径。

## 4. 手动安装 unit

以下操作会改变真实 systemd user 配置，执行前需要项目负责人明确批准：

```bash
install -d ~/.config/systemd/user
install -m 0644 deploy/systemd/hermes-peek.service \
  ~/.config/systemd/user/hermes-peek.service
systemctl --user daemon-reload
systemctl --user enable --now hermes-peek.service
```

模板使用：

- 回环监听 `127.0.0.1:8765`；
- `Restart=on-failure`；
- `NoNewPrivileges`、`PrivateTmp`、`PrivateDevices`；
- 只读系统和 Home；
- 仅允许写入 HermesPeek 状态目录；
- 关闭 Uvicorn access log，避免 URL 和 Preview ID 进入常规访问日志。

若 `hermes-peek` 不在 systemd manager 的 PATH 中，应把 `ExecStart` 改为稳定虚拟环境中的绝对可执行文件，然后重新运行 `systemd-analyze verify`。不要指向临时 `.venv`。

## 5. 健康检查与现场验收

```bash
systemctl --user status hermes-peek.service
curl --fail --silent --show-error http://127.0.0.1:8765/healthz
ss -ltn | grep '127.0.0.1:8765'
```

期望健康响应：

```json
{"status":"ok","service":"hermes-peek"}
```

必须确认没有 `0.0.0.0:8765` 或 `[::]:8765` 监听。服务重启后再次执行健康检查。

## 6. 日志和轮转

服务日志进入 systemd journal：

```bash
journalctl --user -u hermes-peek.service --since today
```

由 journald 执行集中轮转。日志不得包含 Bot Token、Cookie、原始 Telegram `initData`、文件内容或绝对文件路径。默认关闭 HTTP access log。

## 7. 停止与卸载

生命周期 CLI 的目标是按安全顺序禁用准确 profile 的 Hermes 插件、重启 Gateway、确认服务退出，再删除 manifest 证明属于 HermesPeek 的资源。当前仓库命令仍是开发原型，尚缺事务回滚、停服硬门槛与所有权保护，**不得在真实 profile 上直接采用以下命令**：

```bash
hermes-peek uninstall
```

```bash
hermes-peek status --json
hermes-peek doctor
hermes-peek service restart
hermes-peek rollback <TRANSACTION_ID>
```

默认保留状态目录。先预览再明确确认 purge：

```bash
hermes-peek uninstall --purge --dry-run
hermes-peek uninstall --purge --yes
```

离线实现和临时 profile 验收已完成，但真实 profile/systemd/Gateway 验收仍待授权。完整方案与实施状态见 [`06-installation-uninstallation.md`](06-installation-uninstallation.md) 和 [`plan/03-lifecycle-setup-uninstall-rollout.md`](plan/03-lifecycle-setup-uninstall-rollout.md)。以下手工命令也只作为经批准维护窗口中的故障恢复参考，不应由普通用户盲目执行：

```bash
systemctl --user disable --now hermes-peek.service
rm ~/.config/systemd/user/hermes-peek.service
systemctl --user daemon-reload
```

环境文件和状态目录默认保留，以防误删凭据或 Preview Registry。确认不再需要后再单独安全清理。

## 8. 当前验收状态

离线验收覆盖 unit 静态加固、`systemd-analyze verify`、真实临时 Uvicorn 进程、回环 HTTP 健康检查以及进程终止。后续已按任务计划单独完成真实 user service、本机健康检查和 Tailscale/WireGuard 私网 HTTPS 入口验收；TASK 5.3 公网入口未获批准、不执行。阶段 6 Hermes 插件安装与 Gateway 重启仍待单独授权，详见 [`04-hermes-integration.md`](04-hermes-integration.md)。
