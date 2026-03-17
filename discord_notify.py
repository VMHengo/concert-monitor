import os
import sys

import requests


def _ensure_utf8_stdio() -> None:
    # On Windows, stdout is often cp1252 and can't print emojis.
    # Ensure our debug/fallback printing never crashes the monitor.
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        safe = (text or "").encode("utf-8", errors="backslashreplace").decode("utf-8", errors="ignore")
        print(safe)


_ensure_utf8_stdio()


def send_discord(message: str, webhook) -> None:
    # Support a few common env var names to avoid "it is set" confusion.
    # Precedence: monitor-specific -> generic -> url-suffixed variants.
    try:
        resp = requests.post(webhook, json={"content": message}, timeout=20)
        if not (200 <= resp.status_code < 300):
            _safe_print(f"[discord] webhook returned {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        _safe_print(f"[discord] webhook post failed: {e}")

