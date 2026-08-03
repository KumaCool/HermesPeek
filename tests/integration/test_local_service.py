from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "deploy" / "systemd" / "hermes-peek.service"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_systemd_unit_is_hardened_and_local_only() -> None:
    text = UNIT.read_text(encoding="utf-8")
    assert "EnvironmentFile=%h/.config/hermes-peek/hermes-peek.env" in text
    assert "ExecStart=/usr/bin/env hermes-peek serve --host 127.0.0.1" in text
    assert "NoNewPrivileges=true" in text
    assert "PrivateTmp=true" in text
    assert "ProtectSystem=strict" in text
    assert "ProtectHome=read-only" in text
    assert "Restart=on-failure" in text
    assert "0.0.0.0" not in text


def test_serve_binds_loopback_and_health_check_passes(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    state = tmp_path / "state"
    port = free_port()
    env = os.environ.copy()
    env.update({
        "HERMES_PEEK_ALLOWED_ROOTS": str(root),
        "HERMES_PEEK_STATE_DIR": str(state),
        "HERMES_PEEK_DEVELOPMENT": "true",
    })
    process = subprocess.Popen(
        [sys.executable, "-m", "hermes_peek.cli", "serve", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        response = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(f"service exited early: {stdout} {stderr}")
            try:
                response = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=0.5)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        assert response is not None
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "hermes-peek"}
    finally:
        process.terminate()
        process.wait(timeout=5)
    assert process.returncode is not None
