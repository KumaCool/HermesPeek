# 04 HermesPeek 与 Hermes 集成

## 1. 集成目标与当前状态

Hermes 自动集成会精确记录一次 Agent turn 中成功写入的文件，在最终回复阶段通过 HermesPeek 发布这些文件，并把 `Open preview` URL action 附加到 Hermes 的**同一条最终消息**。

代码与离线集成已经完成；当前真实 Hermes profile 尚未安装这版插件、启用配置或重启 Gateway。因此本文区分：

- **已实现并离线验证**：collector、`final_message_actions`、Preview 发布、Telegram send/edit action 渲染和失败降级；
- **尚待授权的真实验收**：在当前 profile 安装、启用、重启 Gateway，并在私聊、群组和 Topic 验证单消息按钮。

显式 `hermes-peek publish` 与旧 `agent:end` 独立通知 handler 仍作为兼容路径保留，但阶段 6 的首选自动集成不再直接调用 Telegram Bot API。

## 2. Hermes 扩展能力

Hermes 与 HermesPeek 的协作边界如下：

- General Plugin 的 `post_tool_call` 提供工具名、参数、结果和 task/session 上下文，用于精确收集 `write_file`、`patch` 的成功产物；
- General Plugin 的 `final_message_actions` 在最终发送阶段收集平台中立 action；
- action schema 当前支持经过验证的 HTTPS URL：

  ```json
  {"type":"url","label":"Open preview","url":"https://<host>/p/<preview_id>"}
  ```

- Hermes Gateway 负责验证、去重、限制 action 数量，并将 action 与文本分离；
- Telegram adapter 将 action 渲染成 InlineKeyboard：非流式回复在发送时附加，已流式发送的回复通过编辑原消息附加；
- 无 action、非法输出、插件异常或不支持 action 的平台都保持原有文本回复，不产生第二条消息；
- `agent:end` 仍是观察者，`transform_llm_output` 仍只处理文本；二者不是阶段 6 action 的实现入口。

## 3. 自动集成数据流

```text
post_tool_call Plugin
    │ successful write_file/patch
    ▼
collector spool keyed by session/task
    │
    ▼
final_message_actions Plugin Hook
    ├─ no files / non-Telegram → no action
    ├─ publish files through PreviewService
    ├─ return platform-neutral HTTPS URL action
    └─ consume spool after action creation
    │
    ▼
Hermes final delivery
    ├─ non-streaming → send final text + InlineKeyboard
    ├─ streaming → edit the already-sent final message
    └─ failure/unsupported platform → plain final text
```

集成文件：

```text
integrations/hermes/
├── plugin.yaml       # post_tool_call + final_message_actions
├── __init__.py       # hooks 与失败隔离
├── collector.py      # session/task collector
├── handler.py        # Preview 发布；兼容旧 agent:end handler
└── HOOK.yaml         # 旧独立通知兼容路径，阶段 6 不要求安装
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

## 5. 最终消息 Action 规则

`final_message_actions` 从 Hermes 传入的上下文读取 `platform`、`user_id`、`session_id` 和最终文本：

1. 非 Telegram、无最终文本、缺少 user/session：返回 `None`；
2. 查找与当前 session 精确匹配的 collector spool；
3. 通过 `PreviewService` 发布本轮文件，owner 绑定任务发起人的 Telegram user ID；
4. 构造 `Open preview` HTTPS URL action；
5. 成功创建 action 后消费 spool；
6. 任一步骤失败都返回 `None`，不能阻断 Hermes 的最终文本答复。

HermesPeek 插件在该路径中不读取 `HERMES_PEEK_TELEGRAM_BOT_TOKEN`，也不直接调用 Bot API。消息 ID、chat/thread 路由、流式消息编辑和 Telegram `reply_markup` 均由 Hermes Gateway 与 adapter 负责。

## 6. Telegram 与跨平台行为

- Telegram 私聊、群组和 Topic 使用同一种平台中立 HTTPS URL action；
- Telegram adapter 把它转换为 URL InlineKeyboardButton；
- Topic 路由沿用 Hermes 已有 metadata，不由 HermesPeek 手工拼接 `message_thread_id`；
- 分片回复只在最后一片附加 action；
- 流式回复在原消息上 finalize/edit，不额外发送按钮消息；
- 其他平台可以忽略 action 或实现自己的渲染器，不影响文本发送。

Preview 页面仍执行 Telegram `initData` 和 owner 授权。Preview URL 本身只定位记录，不替代身份认证。

## 7. 运行配置

目标 Hermes Gateway 进程需要获得：

- `HERMES_PEEK_ALLOWED_ROOTS`：明确批准的工作目录列表；
- `HERMES_PEEK_STATE_DIR`：HermesPeek 状态目录，必须与服务使用同一目录；
- `HERMES_PEEK_EXTERNAL_BASE_URL`：Telegram 可访问的 HTTPS 根地址。

阶段 6 最终消息 action **不需要** `HERMES_PEEK_TELEGRAM_BOT_TOKEN`。该变量仅供显式通知 CLI 或旧 `agent:end` 独立通知兼容路径使用。

配置中不得写入真实用户 ID、聊天 ID、Topic ID、内部地址或其他凭据。环境文件权限与服务加固见 [`05-operations.md`](05-operations.md)。

## 8. 安装与启用边界

安装器或复制步骤只能：

- 将 `plugin.yaml`、`__init__.py`、`collector.py` 和 `handler.py` 复制到目标 profile 的 `plugins/hermes-peek/`；
- 检查依赖和文件结构；
- 输出人工启用步骤；
- 支持移除自身文件。

阶段 6 首选路径不需要安装 `HOOK.yaml`。只有明确保留旧独立通知行为时，才把 `HOOK.yaml` 和 `handler.py` 安装到 `hooks/hermes-peek/`，且必须避免同时启用两条通知路径造成重复 Preview 或消息。

自动流程不得修改：

- `~/.hermes/config.yaml`；
- `hermes.json`；
- `exec-approvals.json`；
- Gateway 配置；
- 当前 profile 之外的 Hermes profile。

插件启用和 Gateway 重启必须由项目负责人明确授权。测试首先使用临时 `HERMES_HOME`，不得拿真实配置做测试夹具。

## 9. 安装、升级与卸载

> 以下命令是操作模板，不代表已对当前 profile 执行。先将 `<HERMES_HOME>` 和 `/path/to/HermesPeek` 替换为批准的实际路径。

### 9.1 前置检查

```bash
cd /path/to/HermesPeek
uv sync --locked
uv run pytest tests/integration/test_hermes_collector.py \
  tests/integration/test_gateway_hook.py \
  tests/integration/test_hermes_install.py -q
```

同时确认目标 Hermes 源码/版本包含 `final_message_actions` 扩展点及 Telegram send/edit action 支持。

### 9.2 安装阶段 6 插件文件（不启用）

```bash
mkdir -p <HERMES_HOME>/plugins/hermes-peek
cp integrations/hermes/plugin.yaml integrations/hermes/__init__.py \
   integrations/hermes/collector.py integrations/hermes/handler.py \
   <HERMES_HOME>/plugins/hermes-peek/
```

上述操作不修改 `config.yaml`。获得明确授权后再执行：

```bash
HERMES_HOME=<HERMES_HOME> hermes plugins list
HERMES_HOME=<HERMES_HOME> hermes plugins enable hermes-peek
HERMES_HOME=<HERMES_HOME> hermes gateway restart
```

`plugins enable` 会修改目标 profile 配置，Gateway 重启会影响当前会话，均不得由安装脚本擅自执行。

### 9.3 升级

先确认 Gateway 的维护窗口；保留 profile 配置、状态目录、collector spool 与 Preview Registry，重新复制插件文件，运行离线测试后再经授权重启。若目标 Hermes 不具备扩展点，应停止升级或保留旧兼容路径，不能声称支持同消息按钮。

### 9.4 卸载

```bash
HERMES_HOME=<HERMES_HOME> hermes plugins disable hermes-peek
HERMES_HOME=<HERMES_HOME> hermes gateway restart
rm -rf <HERMES_HOME>/plugins/hermes-peek
```

卸载不删除 Preview Registry 或 collector spool；确认不再需要后另行按运维策略清理。

## 10. 故障隔离与排查

- `hermes plugins list` 未显示：检查 profile、目录名和 `plugin.yaml`；
- collector 无记录：确认插件已启用、工具成功、工具属于 `write_file`/`patch`、路径处于允许根；
- 最终回复无按钮：确认目标 Hermes 支持并注册了 `final_message_actions`，Gateway 已重启，当前 platform 为 Telegram，session spool 存在，外部 URL 使用 HTTPS；
- 出现第二条消息：检查是否仍安装/启用了旧 `agent:end` Hook；阶段 6 首选路径只应由 Hermes 最终发送链路投递；
- action 创建后按钮未出现：检查 Hermes Gateway/Telegram adapter 日志中的脱敏错误；不得打印 Preview URL 中的私有部署信息、Token 或文件内容；
- Preview 打开后未授权：确认 Telegram `initData`、owner 和服务状态目录一致；
- 任何异常均不应阻断 Hermes 正常答复。若发生阻断，先禁用插件并经授权重启 Gateway。

## 11. 验收层次

### 已完成的离线验收

- 成功 write/patch 精确收集，失败调用忽略；
- 去重、安全过滤和 session 隔离；
- 无文件/非 Telegram 返回空 action；
- action 发布后消费当前 spool；
- 插件不读取 Bot Token、不调用 Bot API；
- Telegram 非流式发送和流式 edit 在同一消息渲染 URL action；
- 无 action 与异常路径保持纯文本回复；
- Hermes 相关目标回归 `58 passed`；HermesPeek 全量回归 `77 passed`。

### 尚待授权的真实验收

1. 在当前 profile 安装阶段 6 插件文件，但不自动修改其他配置；
2. 项目负责人启用插件并重启 Gateway；
3. 分别在私聊、群组和 Forum Topic 让 Hermes 写入一个明确测试文件；
4. 每个场景只出现一条最终完成消息，且同一消息带 `Open preview` 按钮；
5. 按钮对应本轮文件，不读取旧 collector；
6. Preview owner 授权和 Topic 路由正确；
7. 模拟 action 失败后，最终纯文本仍正常发送且没有重复消息。

未执行这些真实步骤前，只能声明“阶段 6 代码与离线集成完成”，不能声明当前运行 Gateway 的 Telegram 单消息闭环已经通过。
