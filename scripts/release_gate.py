"""Offline release gate: reject unsafe configs and credential-bearing inputs."""
from __future__ import annotations

import re
import sys
from pathlib import Path

SECRET_PATTERNS = [
    re.compile(r"(?:BINANCE|TELEGRAM|GEMINI).*?(?:KEY|SECRET|HASH)\s*[:=]\s*['\"]?[A-Za-z0-9_+/@.-]{16,}"),
    re.compile(r"mode\s*:\s*LIVE", re.IGNORECASE),
    re.compile(r"live_trading_enabled\s*:\s*true", re.IGNORECASE),
]
EXCLUDED = {"node_modules", ".git", ".claude", "target", "dist", "__pycache__", ".pytest_cache", "audit_output"}
CONFIG_INPUTS = {"config.yaml", ".env", ".env.local", ".env.production"}


def scan(root: Path) -> list[str]:
    findings = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".yaml", ".yml", ".env", ".json", ".toml", ".ts", ".tsx", ".rs", ".bat"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text) and (path.name in CONFIG_INPUTS or path.name not in {"SettingsPage.tsx"}):
                findings.append(f"{path}: {pattern.pattern}")
    return findings


if __name__ == "__main__":
    findings = scan(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
    if findings:
        print("Release gate failed:")
        print("\n".join(findings))
        raise SystemExit(1)
    print("Release gate passed")
