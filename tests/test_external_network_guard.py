import os
import socket
import urllib.request

import pytest


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    original_connect = socket.socket.connect

    def blocked_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise AssertionError(f"external network blocked in tests: {address}")
        return original_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("urllib network blocked in tests")))
    for key in ("TELEGRAM_REMOTE_CHANNELS_URL", "BINANCE_LIVE_API_KEY", "BINANCE_LIVE_API_SECRET", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
