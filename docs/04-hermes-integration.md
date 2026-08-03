# 04 HermesPeek 与 Hermes 集成

## 1. 集成目标

Hermes 自动集成的目标是：精确记录一次 Agent 任务中成功写入的文件，在任务结束时通过 HermesPeek 发布这些文件，并发送一条独立的 Telegram 预览通知。

首个可用版本先实现显式 `hermes-peek publish`。只有文件安全、身份认证、Mini App 和通知闭环稳定后，才启用自动集成。

## 2. 已确认的 Hermes 能力

依据 Hermes 官方 Hooks/Plugins 文档和当前源码：

- General Plugin 的 `post_tool_call` 可取得工具名、参数、结果以及 task/session 上下文；
- Gateway Event Hook 的 `agent:end` 可取得 platform、user、chat、thread、chat type 和 session 等路由上下文；
- Plugin 与 Gateway Hook 的异常不应阻断 Agent 主流程；
- `agent:end` 在最终普通消息发送前触发，但它是观察者，不能修改随后最终消息的发送参数；
- `transform_llm_output` 只能变换文本，不能安全地注入 Telegram `reply_markup`。

因此，当前可实现的是**第二条独立预览通知**，不能把“最终答复自带按钮”描述为已经支持。

## 3. 自动集成组件

```text
post_tool_call Plugin
    │ successful write_file/patch
    ▼
collector spool keyed by session/task
    │
agent:end Gateway Hook
    ├─ no files / non-Telegram → silent
    ├─ publish files through HermesPeek service
    ├─ send separate Telegram notification
    └─ consume spool after successful completion
```

建议文件：

```text
integrations/hermes/
├── plugin.yaml
├── __init__.py
├── collector.py
├── HOOK.yaml
└── handler.py
```

## 4. 文件收集规则

只收集具有明确路径参数且工具结果确认成功的文件写操作，例如 `write_file` 和 `patch`。

必须遵循：

- 失败或被拒绝的工具调用不计入；
- 同一文件在同一任务内去重；
- 路径在收集或发布阶段经过 HermesPeek 安全策略；
- 不从 `terminal` 命令文本猜测文件；
- 不从 Agent 最终答复、Git 工作区全部 diff、mtime 或 inotify 猜测“本轮产物”；
- session/task 缺失时安全跳过，不把文件错误归到其他会话；
- spool 写入使用原子替换，避免并发覆盖。

## 5. agent:end 处理规则

Hook 从上下文读取 Telegram user/chat/thread/chat type/session，并读取本轮 collector：

1. 非 Telegram 平台：静默；
2. 无本轮文件：静默；
3. 执行发布，owner 使用任务发起人的 Telegram user ID；
4. 构造私聊或群组/Topic 对应按钮；
5. 发送独立通知并保留 `message_thread_id`；
6. 成功后消费 collector；
7. 失败时保留可重试状态，记录脱敏错误，但不影响 Hermes 正常答复。

处理必须幂等。同一 session/event 重放不能重复发布或重复发送通知。

## 6. Telegram 路由

- 私聊：按钮使用 `web_app`，URL 指向 HermesPeek HTTPS Preview 页面。
- 群组/Topic：按钮使用 Mini App Direct Link 和 `mode=compact`。
- Forum Topic：发送 payload 携带整数 `message_thread_id`。
- Bot Token 仅从 secret env 获取，不进入 Hook YAML、普通配置、日志或 URL。

真实 Bot API 调用与当前 Topic 测试必须另行获得明确授权；默认测试使用 MockTransport。

## 7. 安装与启用边界

后续安装器只能：

- 将集成文件复制或链接到指定的临时/目标 profile 目录；
- 检查依赖和文件结构；
- 输出需要人工执行的启用步骤；
- 支持卸载自身文件。

安装器不得自动修改：

- `~/.hermes/config.yaml`；
- `hermes.json`；
- `exec-approvals.json`；
- Gateway 配置；
- 当前 profile 之外的 Hermes profile。

插件启用和 Gateway 重启由项目负责人明确授权并手动执行，或在单独授权后执行。测试首先使用临时 `HERMES_HOME`，不得拿真实配置做测试夹具。

## 8. 故障隔离与可观测性

集成属于 best-effort 边缘能力：

- collector 失败不能改变工具原始成功/失败结果；
- Hook 失败不能阻断 Hermes 最终文本答复；
- 通知失败时 Preview 可保留供重试；
- 日志不记录文件内容、绝对路径、Bot Token、Cookie 或原始 Telegram `initData`；
- 错误以稳定分类呈现，如 `COLLECTOR_WRITE_FAILED`、`PUBLISH_REJECTED`、`TELEGRAM_SEND_FAILED`。

## 9. 验收层次

### 离线集成测试

- 成功 write/patch 精确收集；
- 失败调用忽略；
- 去重、安全过滤和 session 隔离；
- 无文件/非 Telegram 静默；
- Topic 路由、幂等和异常隔离；
- 临时 `HERMES_HOME` 安装/卸载；
- Mock Bot API payload。

### 真实验收（需授权）

1. 在当前 profile 安装集成但不自动修改配置；
2. 由项目负责人启用插件并重启 Gateway；
3. 让 Hermes 修改一个明确测试文件；
4. 正常文本答复仍发送；
5. 随后收到独立预览消息；
6. 按钮对应本轮文件，不是旧 collector 记录；
7. Topic 路由和 owner 授权正确。

未执行真实步骤时，只能声称离线集成测试通过，不能声称 Hermes/Telegram 自动闭环完成。

## 10. 最终回复按钮融合

独立通知稳定后，可以向 Hermes 上游设计平台无关的 final-message actions/attachments 扩展点。该扩展点必须默认无行为，并保护非 Telegram 平台、流式输出、消息拆分、缓存和失败降级。

只有当前运行的 Hermes 真实具备并通过该扩展点测试后，HermesPeek 才能移除第二条通知并把按钮附加到最终回复。未经明确许可，不修改当前运行 Hermes 源码或配置。
