from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import pytest

from hermes_peek.auth import TelegramAuthError, verify_telegram_init_data


def signed_init_data(
    bot_token: str,
    *,
    user_id: str = "123",
    auth_date: datetime,
    query_id: str = "query-1",
) -> str:
    values = {
        "auth_date": str(int(auth_date.timestamp())),
        "query_id": query_id,
        "user": json.dumps({"id": int(user_id), "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_valid_telegram_init_data_returns_verified_user() -> None:
    now = datetime(2026, 8, 4, 4, 0, tzinfo=UTC)
    payload = signed_init_data("test:token", auth_date=now)

    identity = verify_telegram_init_data(
        payload,
        bot_token="test:token",
        now=now,
        max_age_seconds=300,
    )

    assert identity.user_id == "123"
    assert identity.auth_date == now


@pytest.mark.parametrize("mutation", ["hash", "user", "query_id"])
def test_tampered_init_data_is_rejected(mutation: str) -> None:
    now = datetime(2026, 8, 4, 4, 0, tzinfo=UTC)
    values = dict(
        item.split("=", 1)
        for item in signed_init_data("test:token", auth_date=now).split("&")
    )
    values[mutation] = values[mutation] + "x"

    with pytest.raises(TelegramAuthError, match="invalid Telegram authentication"):
        verify_telegram_init_data(
            "&".join(f"{key}={value}" for key, value in values.items()),
            bot_token="test:token",
            now=now,
            max_age_seconds=300,
        )


def test_expired_or_future_init_data_is_rejected() -> None:
    now = datetime(2026, 8, 4, 4, 0, tzinfo=UTC)
    for auth_date in (now - timedelta(seconds=301), now + timedelta(seconds=31)):
        payload = signed_init_data("test:token", auth_date=auth_date)
        with pytest.raises(TelegramAuthError, match="expired Telegram authentication"):
            verify_telegram_init_data(
                payload,
                bot_token="test:token",
                now=now,
                max_age_seconds=300,
            )
