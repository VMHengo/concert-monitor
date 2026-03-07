import email
import imaplib
import json
import os

import requests
from bs4 import BeautifulSoup
from email.header import decode_header, make_header

URL = "https://bachtrack.com/de_DE/search-events/composer=101;region=146"
DATA_FILE = "events.json"

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
GMAIL_SUBJECT_KEYWORD = os.getenv("GMAIL_SUBJECT_KEYWORD", "Ananas")


def send_discord(message):
    if not DISCORD_WEBHOOK:
        return
    requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=20)


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


def _decode_subject(raw_subject: str) -> str:
    try:
        return str(make_header(decode_header(raw_subject or "")))
    except Exception:
        return raw_subject or ""


def check_gmail_for_keyword(keyword: str):
    if not GMAIL_USER or not GMAIL_PASSWORD:
        return []

    matches = []
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(GMAIL_USER, GMAIL_PASSWORD)
        mail.select("INBOX")

        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            return []

        ids = data[0].split()

        for msg_id in ids:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data:
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode_subject(msg.get("Subject", ""))

            if keyword.lower() in subject.lower():
                matches.append(subject)
                mail.store(msg_id, "+FLAGS", "\\Seen")
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    return matches


def main():
    current = get_events()
    previous = load_previous()

    new_events = [e for e in current if e not in previous]

    if new_events:
        for event in new_events:
            msg = f"🎻 Neuer Sibelius Event in NRW entdeckt:\n{event}\n{URL}"
            send_discord(msg)

    save_events(current)

    subjects = check_gmail_for_keyword(GMAIL_SUBJECT_KEYWORD)
    for subject in subjects:
        msg = f"📧 Neue E-Mail mit passendem Betreff erhalten:\n'{subject}' (Keyword: '{GMAIL_SUBJECT_KEYWORD}')"
        send_discord(msg)


if __name__ == "__main__":
    main()