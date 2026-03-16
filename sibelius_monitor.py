import json
import os

import requests
from bs4 import BeautifulSoup

from discord_notify import send_discord

URL = os.getenv(
    "SIBELIUS_URL",
    "https://bachtrack.com/de_DE/search-events/composer=101;region=146",
)
DATA_FILE = os.getenv("SIBELIUS_DATA_FILE", "events.json")


def get_events() -> list[str]:
    html = requests.get(URL, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")

    events: list[str] = []
    for e in soup.select("h3"):
        text = e.get_text(strip=True)
        if text:
            events.append(text)

    return events


def load_previous() -> list[str]:
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_events(events: list[str]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f)


def main() -> None:
    current = get_events()
    previous = load_previous()

    new_events = [e for e in current if e not in previous]

    if new_events:
        for event in new_events:
            msg = f"🎻 Neuer Sibelius Event in NRW entdeckt:\n{event}\n{URL}"
            send_discord(msg)

    save_events(current)


if __name__ == "__main__":
    main()

