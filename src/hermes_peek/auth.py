from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    user_id: str
    auth_date: datetime


def verify_telegram_init_data(
    init_data: str,
    *,
    bot_token: str,
    now: datetime | None = None,
    max_age_seconds: int = 300,
    future_skew_seconds: int = 30,
) -> TelegramIdentity:
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        values = dict(pairs)
        supplied_hash = values.pop("hash")
        if len(pairs) != len(set(key for key, _ in pairs)):
            raise ValueError
        check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
        secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        expected_hash = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied_hash, expected_hash):
            raise TelegramAuthError("invalid Telegram authentication")
        auth_date = datetime.fromtimestamp(int(values["auth_date"]), tz=UTC)
        user = json.loads(values["user"])
        user_id = str(user["id"])
    except TelegramAuthError:
        raise
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise TelegramAuthError("invalid Telegram authentication") from exc

    current = now or datetime.now(UTC)
    age = (current - auth_date).total_seconds()
    if age > max_age_seconds or age < -future_skew_seconds:
        raise TelegramAuthError("expired Telegram authentication")
    return TelegramIdentity(user_id=user_id, auth_date=auth_date)
