import email
import imaplib
import json
import os

import requests
from bs4 import BeautifulSoup
from email.header import decode_header, make_header

URL = "https://bachtrack.com/de_DE/search-events/composer=101;region=146"
DATA_FILE = "events.json"
GMAIL_STATE_FILE = "gmail_state.json"

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


def load_last_gmail_uid():
    if not os.path.exists(GMAIL_STATE_FILE):
        return None
    try:
        with open(GMAIL_STATE_FILE) as f:
            data = json.load(f)
        return data.get("last_uid")
    except Exception:
        return None


def save_last_gmail_uid(uid: int):
    try:
        with open(GMAIL_STATE_FILE, "w") as f:
            json.dump({"last_uid": uid}, f)
    except Exception:
        pass


def _decode_subject(raw_subject: str) -> str:
    try:
        return str(make_header(decode_header(raw_subject or "")))
    except Exception:
        return raw_subject or ""


def check_gmail_for_keyword(keyword: str):
    if not GMAIL_USER or not GMAIL_PASSWORD:
        return []

    matches = []
    last_uid = load_last_gmail_uid()

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        mail.login(GMAIL_USER, GMAIL_PASSWORD)
        mail.select("INBOX")

        # Alle Nachrichten-UIDs im Posteingang holen
        status, data = mail.uid("search", None, "ALL")
        if status != "OK":
            return []

        raw_uids = data[0].split()
        if not raw_uids:
            return []

        uids = sorted(int(x) for x in raw_uids)
        max_uid = uids[-1]

        # Beim allerersten Lauf nur den aktuellen Stand merken,
        # aber keine alten Mails melden.
        if last_uid is None:
            save_last_gmail_uid(max_uid)
            return []

        new_uids = [uid for uid in uids if uid > last_uid]
        if not new_uids:
            return []

        for uid in new_uids:
            status, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
            if status != "OK" or not msg_data:
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode_subject(msg.get("Subject", ""))

            if keyword.lower() in subject.lower():
                matches.append(subject)
                mail.store(str(uid), "+FLAGS", "\\Seen")
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    if matches and max_uid > (last_uid or 0):
        save_last_gmail_uid(max_uid)

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