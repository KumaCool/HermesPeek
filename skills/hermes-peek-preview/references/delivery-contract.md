# Preview delivery contract

## Tool input

Call `hermes_peek_send_preview` with exactly these model-controlled fields:

- `files`: one or more absolute file paths;
- `entry`: an absolute path that is also in `files`;
- `title`: a short non-empty display title.

The model must not provide credentials, destination platform, route, owner, Preview URL, or any chat, user, or thread identifier.

## Routing and ownership

The Tool obtains the current Telegram route from the request-scoped Gateway session context. A direct message stays in that direct message, a group stays in that group, and a forum request stays in the same topic. The current requester becomes the Preview owner. Missing or uncertain context is a failure; there is no fallback to a home channel, remembered route, or private conversation.

## Completion

A successful Tool result means the Preview message was sent. Return exactly `NO_REPLY` so that it remains the only user-visible delivery. A failed result means it was not confirmed sent: explain the safe product error briefly and never claim success.

One invocation may send at most one Telegram message. Do not retry automatically, create collector spool data, invoke the CLI compatibility path, or expose absolute paths, URLs, credentials, owner data, or route values in the final response.
