import requests
from bs4 import BeautifulSoup
import json
import os

URL = "https://bachtrack.com/de_DE/search-events/composer=101;region=146"
DATA_FILE = "events.json"

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")


def send_discord(message):
    if not DISCORD_WEBHOOK:
        return
    requests.post(DISCORD_WEBHOOK, json={"content": message})


def get_events():
    html = requests.get(URL, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")

    events = []
    for e in soup.select("h3"):
        text = e.get_text(strip=True)
        if text:
            events.append(text)

    return events


def load_previous():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE) as f:
        return json.load(f)


def save_events(events):
    with open(DATA_FILE, "w") as f:
        json.dump(events, f)


def main():
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