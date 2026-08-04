# HermesPeek

> Preview files produced by Hermes securely inside Telegram.

HermesPeek 是面向 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的轻量、只读产物预览服务。它把 Hermes 在任务中创建或修改的 Markdown、代码、结构化数据、图片、PDF 和受限 HTML 转换为受控 Preview，并通过 Telegram 打开。

> [!IMPORTANT]
> HermesPeek 的核心服务、Preview Registry、Telegram 身份认证、多格式预览、Hermes 自动收集和最终消息 action 已实现并通过离线测试。当前仓库的真实本机服务与私网 HTTPS 入口已有单独验收记录，但阶段 6 插件尚未安装到当前运行的 Hermes profile，也未重启 Gateway。未完成目标环境安全评审前，请勿直接暴露到公网。

## 为什么需要 HermesPeek

当 Hermes 生成文档或修改代码后，用户通常需要离开 Telegram，再通过终端、编辑器或文件管理器查看结果。HermesPeek 的目标是提供一条更短的只读查看链路：

```text
Hermes 创建或修改文件
        ↓
HermesPeek 发布受控 Preview
        ↓
Telegram 显示“预览”入口
        ↓
Mini App 读取磁盘上的最新文件
```

HermesPeek 预览的是磁盘当前内容，而不是任务结束时的静态快照；文件更新后，刷新页面即可看到最新版本。

## 当前实现

当前实现支持：

- `GET /healthz` 健康检查；
- `GET /` 项目介绍页；
- 不透明 Preview ID 和文件系统 Registry；
- `hermes-peek publish/inspect/revoke/serve`；
- Telegram `initData` 验证、owner 授权和短期会话；
- Markdown、代码/文本、JSON/YAML/TOML、图片、PDF 与受限 HTML；
- Hermes `post_tool_call` 精确收集成功的 `write_file`/`patch`；
- Hermes `final_message_actions` 在最终回复同一条消息附加 `Open preview` URL 按钮；
- 使用 `HERMES_PEEK_ALLOWED_ROOTS` 限制可读取目录；
- 拒绝敏感文件名、目录穿越、根目录外文件和超大文件；
- 每次读取重新执行路径和文件安全检查；
- HTML sandbox、CSP 和安全响应头；
- 本机回环 systemd user service 模板。

当前仍待完成或单独授权：

- 在当前真实 Hermes profile 安装/启用阶段 6 插件并重启 Gateway；
- 私聊、群组和 Topic 的真实单消息按钮验收；
- 未批准的公网入口（TASK 5.3 不执行）；
- 面向广泛公网使用的完整部署评审。

完整范围和 TASK 状态请查看[项目文档](#项目文档)。

## 快速开始

### 环境要求

- Python 3.11 或更高版本；
- [uv](https://docs.astral.sh/uv/)；
- Linux、macOS 或 Windows。

### 安装依赖

```bash
uv sync
```

### 启动本地开发服务

选择一个专门用于测试的目录，不要把整个主目录、系统根目录或包含凭据的目录设为允许根：

```bash
export HERMES_PEEK_ALLOWED_ROOTS="/path/to/safe/workspace"
uv run uvicorn hermes_peek.app:app --host 127.0.0.1 --port 8765
```

打开：

```text
http://127.0.0.1:8765/
http://127.0.0.1:8765/preview?path=/path/to/safe/workspace/README.md
```

多个允许根使用操作系统路径分隔符连接：Linux/macOS 使用 `:`，Windows 使用 `;`。

## 测试

```bash
uv run pytest
```

## 安全模型

HermesPeek 的设计目标是“只读、最小暴露、显式授权”：

- 对外只暴露随机 Preview ID，不暴露服务器绝对路径；
- 每次读取文件时重新解析路径并检查允许根；
- 默认拒绝 `.env`、密钥、凭据、Git 元数据、缓存和依赖目录；
- Preview 与 Telegram 用户、聊天和过期时间绑定；
- 密码、密钥、Token、Cookie 和连接字符串只能通过运行时 Secret 或环境变量注入；
- HTML 使用受限 sandbox；Markdown 原始 HTML 默认禁用或清洗；
- 不提供编辑、删除、执行或写回工作区的接口。

安全边界和实际部署状态以 [`docs/03-security.md`](docs/03-security.md)、[`docs/05-operations.md`](docs/05-operations.md) 和任务计划中的验收记录为准。Preview URL 不包含绝对路径，但随机 ID 也不替代 Telegram 身份认证。

如发现安全问题，请不要在公开 Issue 中粘贴漏洞利用细节、真实凭据、个人信息或部署地址。发布前应在仓库托管平台配置私密安全报告渠道，并在此处补充链接。

## 配置原则

项目仓库只保存无敏感值的配置说明或模板。以下内容不得提交：

- 个人主目录和机器专属路径；
- Telegram Bot Token、API Key、密码和会话凭据；
- 私钥、证书密钥、Cookie 和连接字符串；
- 真实用户 ID、聊天 ID、Topic ID、私有 IP 和内部域名；
- 包含上述数据的 `.env`、日志、截图和测试夹具。

提交前应同时检查工作区和 staged diff；`.gitignore` 不是敏感信息检查的替代品。

## 项目文档

- [00 产品决策](docs/00-product-decisions.md)
- [01 设计与开发方案](docs/01-design-development-plan.md)
- [02 系统架构](docs/02-architecture.md)
- [03 安全模型](docs/03-security.md)
- [04 Hermes 集成](docs/04-hermes-integration.md)
- [05 本机服务运维](docs/05-operations.md)
- [01 实施任务计划、TASK 状态与验收矩阵](docs/plan/01-implementation-task-plan.md)

## 路线图

1. 文件系统 Preview Registry 与随机 Preview ID；
2. 安全路径策略和显式 `hermes-peek publish` CLI；
3. Telegram 身份认证与多格式 Mini App；
4. Telegram 显式通知闭环；
5. Hermes Plugin 和 Gateway Hook 自动收集；
6. 经授权验证 HTTPS 与生产入口；
7. 通过 Hermes 通用 `final_message_actions` 扩展点，将预览按钮融合进最终回复（代码与离线集成已完成，真实 Gateway 验收待授权）。

路线图不代表相关能力已经实现，实时进度以任务计划中的 TASK 状态为准。

## 参与贡献

项目仍在建立基础架构。提交 Issue 或 Pull Request 前，请先阅读设计方案和任务计划，并遵守以下要求：

1. 一个 Pull Request 聚焦一个明确问题；
2. 行为变更必须包含测试；
3. 不绕过允许根、身份认证或只读边界；
4. 不提交个人信息、密码、密钥、Token、凭据或部署清单；
5. 不把规划能力描述为已经实现；
6. 对网络入口、认证和文件访问范围的变更必须附带安全分析。

## 许可证

本项目采用 [MIT License](LICENSE)。允许个人和商业使用、复制、修改、合并、发布、分发、再许可和销售，但须保留许可证中的版权及许可声明。

## 项目名称

`Peek` 表示快速、轻量地查看最新产出，也对应 Telegram Mini App 的浮窗使用体验。
