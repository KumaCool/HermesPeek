# 00 HermesPeek 产品决策

更新日期：2026-08-04

## 已确认范围

1. **Telegram Bot**：复用当前 Hermes Bot，不创建独立 Bot。
2. **预览语义**：读取项目中的实时文件；刷新页面后显示磁盘上的最新内容，不制作完成时快照。
3. **文件选择**：采用默认规则——收集本轮由写文件工具产生或修改的文件，过滤敏感、缓存、依赖和不支持的文件；文件较多时使用一个“查看本次修改”入口。
4. **网络入口**：优先评估现有 WireGuard 网络；若无法满足 Telegram 客户端访问和 HTTPS 要求，则使用 Cloudflare Tunnel。
5. **访问控制**：启用 Telegram 身份授权。默认仅任务发起人可访问；可配置为授权当前聊天成员。
6. **首版格式**：Markdown、代码/文本、JSON/YAML/TOML、HTML、图片和 PDF。
7. **接入顺序**：先实现显式 `hermes-peek publish`，稳定后接 Hermes 插件自动收集并把按钮合并进最终回复。

## 网络判断

目标部署环境可能使用 WireGuard 或其他私有网络。具体接口名、私有地址、节点名和域名属于部署清单，不写入项目仓库。WireGuard 本身只提供私有网络连通性，不自动提供 Telegram Mini App 所需的受信任 HTTPS 站点。

WireGuard 方案仅在以下条件同时满足时可用：

- 打开 Telegram 的手机/桌面设备也加入同一个 WireGuard 网络；
- 设备能够路由到 HermesPeek 主机；
- 为预览地址配置受 Telegram WebView 信任的 HTTPS 证书和域名；
- BotFather/Mini App 配置接受该 HTTPS 地址。

因此首版架构保持入口可替换：应用仅监听本地端口，由外层入口提供 HTTPS。开发和受控设备测试可使用 WireGuard；需要任意 Telegram 客户端直接打开时，默认采用 Cloudflare Tunnel。

## 默认安全规则

- 不允许 URL 直接提交任意绝对路径；对外只暴露随机 Preview ID。
- Preview ID 绑定允许的文件列表、Telegram 用户、聊天与过期时间。
- 文件每次请求时重新读取，实现实时预览。
- `Path.resolve()` 后必须位于配置的允许根目录。
- 拒绝 `.env`、密钥、凭据、`.git`、缓存和依赖目录。
- HTML 在受限 sandbox iframe 中显示；Markdown 默认禁用或清洗原始 HTML。
- 页面只读，不提供写回项目文件的接口。

## 待实现里程碑

1. Preview Registry 与随机 Preview ID。
2. Markdown、代码、结构化文本、图片、PDF 和受限 HTML 渲染。
3. `hermes-peek publish` CLI。
4. Telegram `initData` 验证和用户授权。
5. WireGuard 开发入口验证；Cloudflare Tunnel 生产入口。
6. Hermes 插件：记录本轮文件、发布预览、发送按钮。
7. 私聊使用 `web_app`；群组和 Topic 使用 Mini App Direct Link。
