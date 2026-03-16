import email
import json
import os

import imaplib
from email.header import decode_header, make_header

from discord_notify import send_discord

GMAIL_STATE_FILE = os.getenv("GMAIL_STATE_FILE", "gmail_state.json")

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
GMAIL_SUBJECT_KEYWORD = os.getenv("GMAIL_SUBJECT_KEYWORD", "Ananas")


def load_last_gmail_uid() -> int | None:
    if not os.path.exists(GMAIL_STATE_FILE):
        return None
    try:
        with open(GMAIL_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        last_uid = data.get("last_uid")
        return int(last_uid) if last_uid is not None else None
    except Exception:
        return None


def save_last_gmail_uid(uid: int) -> None:
    try:
        with open(GMAIL_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_uid": uid}, f)
    except Exception:
        pass


def _decode_subject(raw_subject: str) -> str:
    try:
        return str(make_header(decode_header(raw_subject or "")))
    except Exception:
        return raw_subject or ""


def check_gmail_for_keyword(keyword: str) -> list[str]:
    if not GMAIL_USER or not GMAIL_PASSWORD:
        return []

    matches: list[str] = []
    last_uid = load_last_gmail_uid()

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    max_uid: int | None = None
    try:
        mail.login(GMAIL_USER, GMAIL_PASSWORD)
        mail.select("INBOX")

        status, data = mail.uid("search", None, "ALL")
        if status != "OK":
            return []

        raw_uids = data[0].split()
        if not raw_uids:
            return []

        uids = sorted(int(x) for x in raw_uids)
        max_uid = uids[-1]

        # First run: remember current max UID, don't alert on older emails.
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

    if matches and max_uid is not None and max_uid > (last_uid or 0):
        save_last_gmail_uid(max_uid)

    return matches


def main() -> None:
    subjects = check_gmail_for_keyword(GMAIL_SUBJECT_KEYWORD)
    for subject in subjects:
        msg = (
            "📧 Neue E-Mail mit passendem Betreff erhalten:\n"
            f"'{subject}' (Keyword: '{GMAIL_SUBJECT_KEYWORD}')"
        )
        send_discord(msg)


if __name__ == "__main__":
    main()

