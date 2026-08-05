---
name: hermes-peek-preview
description: Use when the user asks to send, show, or preview a file in the current Telegram conversation, including “发我看下”, “给我看文档”, and “预览文件”. Do not use for requests to modify, summarize, explain, locate, or paste file contents into chat.
version: 1.0.0
author: HermesPeek contributors
license: MIT
metadata:
  hermes:
    tags: [telegram, preview, files]
    related_skills: []
---

# HermesPeek Preview Delivery

## When to use

Use this skill for an explicit file-preview intent such as “把 README 发我看下”, “给我看文档”, or “预览文件”. Also use it for “给我看下” when the conversation is 上下文唯一 and identifies one file.

Do not trigger for near-misses such as “修改 README”, “总结 README”, “解释这个文档”, “README 在哪里”, or “把正文复制到聊天”. Handle those requests normally.

## Resolve the file

1. Validate an explicit absolute path read-only.
2. Resolve an explicit relative path within the current project context.
3. Use a filename only when it has one reasonable match.
4. Use a prior conversational file only when the context is unique.
5. For 多匹配, ask the user which file they mean.
6. For 无明确目标, ask the user to identify the file.

Do not ask again for a 唯一 target. 不要从 Git diff、修改时间或整个工作区猜测目标. Never infer a target from shell output.

## Deliver

Once the target is unique:

1. Supply absolute file paths in `files`; set `entry` to one member of `files`; give a short, non-empty `title`.
2. 只调用一次 `hermes_peek_send_preview`. Never pass credentials, routing identifiers, owner data, or a destination platform.
3. 成功时 output exactly `NO_REPLY` and nothing else.
4. 失败时 give a 简短、真实的 reason and do not output `NO_REPLY`.
5. If the dedicated tool is unavailable, ask the user to install or upgrade the HermesPeek integration. 不要自动改用 `terminal`、Shell、`publish --notify` or source a Secret file.

Read [the delivery contract](references/delivery-contract.md) only when detailed Tool, routing, or failure semantics are needed.
