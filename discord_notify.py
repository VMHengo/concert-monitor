import os

import requests


def send_discord(message: str) -> None:
    webhook = os.getenv("DISCORD_WEBHOOK")
    if not webhook:
        return
    requests.post(webhook, json={"content": message}, timeout=20)

