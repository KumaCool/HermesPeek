---
name: hermes-peek-preview
description: Use when the user explicitly asks to send, show, open, or preview a file in the current Telegram conversation, such as “send me the README”, “show me the document”, “preview this file”, “发我看下”, “给我看文档”, or “预览文件”. Do not use for requests to modify, summarize, explain, locate, or paste file contents into chat.
version: 1.1.0
author: HermesPeek contributors
license: MIT
metadata:
  hermes:
    tags: [telegram, preview, files]
    related_skills: []
---

# HermesPeek Preview Delivery

## When to use

Trigger by **intent, not by one language or an exact keyword**. Use this skill when the user explicitly wants a file delivered as a Preview in the current Telegram conversation.

Positive examples include:

- English: “send me the README”, “show me the document”, “preview this file”, “open the report”, or “let me see it” when the conversation uniquely identifies one file.
- Chinese: “把 README 发我看下”, “给我看文档”, “预览文件”, “打开报告”, or “给我看下” when the conversation uniquely identifies one file.
- Equivalent requests in any other language when their meaning is the same.

Do not trigger for near-misses that ask to modify, summarize, explain, locate, or paste the file into chat. Examples include:

- English: “edit the README”, “summarize the README”, “explain this document”, “where is the README?”, or “paste the contents here”.
- Chinese: “修改 README”, “总结 README”, “解释这个文档”, “README 在哪里”, or “把正文复制到聊天”.

Handle those near-miss requests normally.

## Resolve the file

1. Validate an explicit absolute path read-only.
2. Resolve an explicit relative path within the current project context.
3. Use a filename only when it has one reasonable match.
4. Use a prior conversational file only when the context is unique.
5. For multiple matches（多匹配）, ask the user which file they mean.
6. If there is no clear target（无明确目标）, ask the user to identify the file.

Do not ask again when the target is unique（唯一）. Do not guess the target from Git diff, modification time, the entire workspace, or shell output（不要从 Git diff、修改时间或整个工作区猜测目标）.

## Deliver

Once the target is unique:

1. Supply absolute file paths in `files`; set `entry` to one member of `files`; give a short, non-empty `title`.
2. Call `hermes_peek_send_preview` exactly once（只调用一次）. Never pass credentials, routing identifiers, owner data, or a destination platform.
3. On success（成功）, output exactly `NO_REPLY` and nothing else.
4. On failure（失败）, give a brief and truthful reason（简短、真实的原因）and do not output `NO_REPLY`.
5. If the dedicated tool is unavailable, ask the user to install or upgrade the HermesPeek integration. Do not automatically fall back to `terminal`, Shell, `publish --notify`, or sourcing a Secret file（不要自动改用 `terminal`）.

Read [the delivery contract](references/delivery-contract.md) only when detailed Tool, routing, or failure semantics are needed.
