# 07 Telegram 会话预览 Skill 与单消息交付

## 1. 背景与问题

HermesPeek 已具备 Preview 服务、Telegram Mini App、路径安全、owner 授权、显式 `publish --notify` CLI，以及 `post_tool_call + final_message_actions` 自动产物预览。

但“把 README 发我看下”这类已有文件预览请求目前仍依赖 Agent 私有记忆和显式 Shell 兼容路径：

1. Agent 根据私人记忆理解口令；
2. 通过 `terminal` 加载 Secret 环境；
3. 执行 `hermes-peek publish --notify` 并手工传入路由；
4. HermesPeek 发送带 `Open preview` 按钮的消息；
5. Agent 再发送“已发送……”确认文本。

该行为不能随项目传播，并存在三个问题：

- 能力只存在于某个 Agent Profile 的记忆中，其他用户克隆项目后无法获得；
- Shell 调用暴露实现细节，并要求模型接触 Token、chat ID、thread ID 和 owner；
- Preview 消息已经表达成功，额外最终文本重复；错误路由还可能把 Topic 请求发到私聊。

## 2. 目标与非目标

### 2.1 目标

将会话预览能力作为项目正式能力交付：

1. 在仓库中维护 `hermes-peek-preview` Skill，由 Git、源码包和发布流程版本控制；
2. Skill 识别“发我看下 / 给我看文档 / 预览文件”等自然语言意图；
3. Skill 只调用一次 HermesPeek 专用 Plugin Tool；
4. Tool 从当前 Gateway Session Context 读取路由和 owner，不接受模型传入路由或凭据；
5. Preview 只发送到请求发生的同一私聊、群组或 Forum Topic；
6. 成功时 Agent 输出 `NO_REPLY`，Telegram 只保留一条带 `Open preview` 的 Preview 消息；
7. 失败、多匹配或上下文不足时返回可读说明，不静默、不伪成功；
8. setup、upgrade、rollback 和 uninstall 同时管理 Skill 与 Plugin Tool。

### 2.2 非目标

本阶段不做：

- 修改 Tailscale Serve、HTTPS、端口、防火墙、反向代理或外部访问范围；
- 修改 Hermes `config.yaml`、`hermes.json`、`exec-approvals.json` 或 Gateway 配置；
- 修改 Hermes core 工具或 `final_message_actions` 契约；
- 删除 `hermes-peek publish --notify` 兼容 CLI；
- 改变 Preview 路径策略、TTL、owner、Telegram `initData` 或授权规则；
- 将普通文件写入自动预览改为静默独立通知；
- 引入持久消息去重、数据库或新的后台服务。

## 3. 选定架构

```text
用户：把 README 发我看下
        │
        ▼
仓库随附 Skill：hermes-peek-preview
  - 判断预览意图
  - 定位唯一文件
  - 多匹配时澄清
  - 决定成功/失败结束语义
        │
        ▼
Plugin Tool：hermes_peek_send_preview
  - 读取当前 Session Context
  - 安全读取 HermesPeek Secret
  - 发布 owner-bound Preview
  - 原位发送 Telegram Preview
        │
        ▼
同一私聊 / 群组 / Topic：Open preview
        │
        ▼
Tool success → Agent 输出 NO_REPLY
```

### 3.1 职责边界

| 组件 | 权威职责 |
|---|---|
| `skills/hermes-peek-preview/SKILL.md` | 触发边界、文件定位、澄清、Tool 调用和结束语义 |
| `references/delivery-contract.md` | Tool 契约、路由、安全和错误语义的按需参考 |
| HermesPeek Plugin Tool | 当前会话路由、Secret 加载、Preview 发布和 Telegram 单消息发送 |
| HermesPeek Service | 路径安全、Registry、授权、渲染和生命周期 |
| Agent 私有记忆 | 不作为项目能力来源，不承担分发 |

Skill 不能单独替代 Tool：若只有 `SKILL.md`，正常路径仍只能指导 Agent 使用 Shell。Tool 也不能替代 Skill：Tool 不负责自然语言意图、文件歧义或 Agent 最终响应。因此二者是一个产品能力的入口和执行层。

### 3.2 为什么不用 `final_message_actions + NO_REPLY`

`final_message_actions` 给 Hermes 的正常最终文本附加按钮；Gateway 会对完整的 `NO_REPLY` / `[SILENT]` 做 intentional-silence 过滤，且静默响应不应依赖最终文本 action 生成用户可见消息。

本需求要求 HermesPeek Preview 消息成为唯一交付，因此由专用 Tool 直接发送 Preview，成功后再让 Gateway 抑制 Agent 的额外文本。既有 `final_message_actions` 继续服务“本轮写入产物随正常答复附加按钮”的不同场景。

### 3.3 为什么不用 Shell 包装

Shell alias 或脚本仍会：

- 暴露 `terminal` 工具进度；
- 要求显式加载 Secret；
- 让模型拼装 chat/thread/owner；
- 在路由缺失时诱发错误回退。

因此 Shell 仅保留为 CLI/排障兼容路径，不是 Skill 的正常执行路径。

## 4. 仓库与安装布局

### 4.1 仓库源码

```text
skills/
└── hermes-peek-preview/
    ├── SKILL.md
    └── references/
        └── delivery-contract.md

integrations/hermes/
├── plugin.yaml
├── __init__.py
├── preview_tool.py
├── collector.py
└── handler.py

src/hermes_peek/hermes_plugin/
└── 与 integrations/hermes/ 的可安装运行副本保持一致
```

Skill 源码位于仓库而非 `~/.hermes/skills/`，使其可审查、提交、打包和发布。`SKILL.md` 保留始终需要的行为；详细 Tool/路由契约放入 `references/`，避免常驻上下文膨胀。

### 4.2 目标 Profile

setup 安装到当前明确指定的 Profile：

```text
<HERMES_HOME>/skills/hermes-peek-preview/
<HERMES_HOME>/plugins/hermes-peek/
```

安装清单分别记录 Skill、Plugin、pointer、service 和 Secret 等 owned resources 的路径与哈希。upgrade、rollback 和 uninstall 复用现有 transaction/ownership 机制：

- upgrade 备份并原子替换安装器拥有的 Skill 与 Plugin；
- rollback 恢复旧副本；
- 默认 uninstall 删除未漂移的安装器拥有副本，保留 Preview 数据；
- 发现用户修改或哈希漂移时拒绝覆盖/删除并报告；
- 不跨 Profile 安装，也不修改 Hermes 主配置。

独立 Skill source/tap 可作为后续公开分发入口，但不是本阶段完整安装的替代：仅安装 Skill 而缺少 Plugin Tool/Service 时，Skill 必须提示安装 HermesPeek 集成，不得自动走 Shell。

## 5. Skill 契约

### 5.1 触发

应触发：

- `把 README 发我看下`
- `给我看 README 文档`
- `预览一下 docs/architecture.md`
- `看看刚才生成的方案`
- 上下文已唯一明确目标时的 `给我看下`

不应触发：

- `修改 README`
- `总结 README`
- `解释这个文档`
- `README 在哪里`
- `把正文复制到聊天里`

### 5.2 文件解析

1. 明确绝对路径：只读验证该路径；
2. 明确相对路径：在当前项目上下文定位；
3. 文件名存在唯一合理匹配：直接使用；
4. 会话上下文存在唯一明确文件：直接使用；
5. 多个合理匹配：询问用户；
6. 无明确目标：询问用户；
7. 不从 Git diff、mtime、整个工作区或 Shell 文本猜测目标。

### 5.3 执行和结束语义

- 正常路径只调用一次 `hermes_peek_send_preview`；
- Tool 成功：最终只输出 `NO_REPLY`；
- Tool 失败：简短说明真实错误，不输出 `NO_REPLY`；
- 专用 Tool 不可用：提示用户安装/升级 HermesPeek 集成；
- 不自动执行 `terminal source ... hermes-peek publish`；只有用户明确要求 CLI 兼容路径时才允许使用。

## 6. Plugin Tool 契约

### 6.1 Schema

工具名：

```text
hermes_peek_send_preview
```

模型可传：

```json
{
  "files": ["/absolute/path/README.md"],
  "entry": "/absolute/path/README.md",
  "title": "HermesPeek README"
}
```

输入约束：

- `files`：一个或多个绝对文件路径；
- `entry`：必须属于 `files`；
- `title`：非空并限制长度；
- 所有路径继续通过 `PathPolicy`；
- schema 不接受 Token、`chat_id`、`thread_id`、owner、Preview URL 或目标平台。

### 6.2 Session Context 与严格原位路由

Tool 通过 `gateway.session_context.get_session_env()` 读取：

- `HERMES_SESSION_PLATFORM`；
- `HERMES_SESSION_CHAT_ID`；
- `HERMES_SESSION_THREAD_ID`；
- `HERMES_SESSION_USER_ID`；
- 必要的 chat type/session metadata。

路由不变量：

- 私聊请求只发送到同一私聊；
- 普通群组请求只发送到同一群组；
- Forum Topic 请求同时保留原 chat ID 和 thread ID；
- owner 始终绑定当前请求用户；
- 路由只来自当前入站消息绑定的 ContextVar，不使用进程级历史值、Home channel 或记忆值；
- 平台不是 Telegram、chat/user 缺失、Topic thread 缺失或来源不确定时，零发送失败；
- 绝不回退到私人对话或其他聊天。

### 6.3 Secret 加载

安装器写入的 Plugin pointer 扩展为：

```json
{
  "config_file": "/.../config.json",
  "env_file": "/.../secrets.env"
}
```

Tool 只读取 `HERMES_PEEK_TELEGRAM_BOT_TOKEN`，并要求 Secret 路径：

- 是普通文件；
- 不是 symlink；
- group/other 无权限；
- 属于当前目标 Profile 的安装状态。

Token 不得进入 Tool schema、返回值、异常、日志、manifest、测试快照或 Git。

### 6.4 返回值

成功：

```json
{
  "success": true,
  "sent": true,
  "message_id": 123,
  "button_type": "mini_app"
}
```

失败：

```json
{
  "success": false,
  "sent": false,
  "error_code": "route_unavailable",
  "error": "current Telegram topic route is unavailable"
}
```

返回值不得包含 Preview URL、绝对路径、Token、owner ID、chat ID 或 thread ID。错误必须是稳定、可读、已脱敏的产品错误。

## 7. 单消息与失败语义

- 发布并发送成功：Tool 返回成功，Skill 输出 `NO_REPLY`；唯一用户可见交付是 Preview 消息；
- 路径拒绝或路由缺失：不创建通知，Skill 解释原因；
- Preview 已创建但 Telegram 发送失败：返回明确失败，不声称已发送；本阶段不自动多次重试；
- Tool 不创建 collector spool，不让下一轮 `final_message_actions` 重复附加按钮；
- 一次 Tool 调用最多发送一条消息；本阶段不增加持久 dedup key；
- 任何 Plugin 异常不得阻断 Hermes 后续正常会话。

## 8. 生命周期、打包与兼容

- `setup` 同时安装 Skill、Plugin 和扩展后的 pointer；
- `status`/`doctor` 区分 Skill installed/owned/drift 与 Plugin loaded 状态；
- upgrade/rollback 覆盖 Skill 和 Plugin；
- default uninstall 保留 Registry、Preview、collector、journal 和日志策略不变；
- wheel/sdist 必须包含 Skill 源码和 Plugin 运行副本；
- README 和中文 README 说明完整集成需要 Skill + Plugin Tool + Service；
- `publish --notify` 保留给 CLI、排障和非 Gateway 使用；
- 既有 `post_tool_call + final_message_actions` 保持不变；
- legacy `agent:end` 独立通知 Hook 不作为本能力安装路径，避免重复通知；
- Skill/Tool 在新 Session 或 Gateway 重启后生效，不尝试在当前会话中破坏 prompt/tool 缓存。

## 9. 验收标准

### 9.1 Skill 静态与触发检查

- `SKILL.md` frontmatter 合法，名称和 description 明确触发/非触发边界；
- 正向口令触发，修改/总结/解释类 near-miss 不触发；
- 唯一文件不追问，多匹配或无目标才澄清；
- 正常路径明确只调用专用 Tool；
- 成功 `NO_REPLY`，失败解释；
- Skill 和 reference 不含本机路径、路由、Token 或私人信息。

### 9.2 Tool 与生命周期离线测试

- Plugin 注册 `hermes_peek_send_preview`；
- schema 仅包含 `files`、`entry`、`title`；
- DM、群组和 Topic 严格使用当前 Session Context；
- Topic 缺 thread 时零发送失败，禁止回退私聊/Home；
- Secret symlink、非普通文件、宽权限和缺 Token 均拒绝；
- owner 绑定当前用户；
- 一次 handler 调用只发送一条消息；
- 返回值、日志和异常无敏感值；
- 现有 CLI notify、collector、final action、路径安全和 lifecycle 回归通过；
- 临时 Profile setup→upgrade→rollback→uninstall 验证 Skill/Plugin 所有权；
- wheel/sdist 包含 Skill 和 Plugin；
- 全量测试、compileall、build、链接和敏感信息检查通过。

### 9.3 真实 Telegram 验收

获得真实运行态授权后：

1. 更新当前 Profile 的 Skill 和 Plugin；
2. 从 Gateway 外重启 Gateway并创建新会话；
3. 在私聊输入短口令；
4. 在 Forum Topic 输入短口令；
5. 每个场景确认：
   - 只调用一个 HermesPeek 专用工具；
   - 不出现 `terminal source ...`；
   - 只收到一条带 `Open preview` 的 Preview 消息；
   - 没有“已发送……”追加回复；
   - 按钮可打开且 owner 校验通过；
   - Topic 回复位于请求发生的同一 Topic；
6. 人为构造缺失路由时确认失败且不改发私聊。

离线测试不得冒充真实 Telegram 单消息验收。

## 10. 安全与回滚

真实部署仍需单独明确批准，因为会更新当前 Profile 并重启 Gateway。若验收失败：

- 使用 lifecycle transaction rollback 恢复旧 Skill、Plugin 和 pointer；
- 从 Gateway 外重启；
- 验证普通 Hermes 回复和既有 `final_message_actions`；
- 保留 CLI `publish --notify` 兼容路径。

回滚不修改网络入口，不删除 Preview 数据或用户原始文件。
