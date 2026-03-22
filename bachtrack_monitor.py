import json
import os
import re
from datetime import datetime
from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.parse import urlparse
from difflib import SequenceMatcher
import re

import requests
from bs4 import BeautifulSoup

from discord_notify import send_discord
from gmail_monitor import DISCORD_WEBHOOK

BACHTRACK_BASE_URL = "https://bachtrack.com"
STATE_FILE = os.getenv("BACHTRACK_STATE_FILE", "bachtrack_state.json")
DEBUG = os.getenv("BACHTRACK_DEBUG", "").strip().lower() in {"1", "true", "yes", "y", "on"}
USER_AGENT = os.getenv(
    "BACHTRACK_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
)
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_BACHTRACK")

def load_favourites(path="favourites.txt") -> list[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []

def normalize(text: str) -> str:
    text = text.lower()

    # Sonderzeichen entfernen
    text = re.sub(r"[^\w\s]", " ", text)

    # Wörter sortieren → Reihenfolge egal
    words = text.split()
    words.sort()

    return " ".join(words)

FAVOURITES = load_favourites()
FAVOURITES_NORM = [normalize(f) for f in FAVOURITES]

def _env_truthy(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Listener:
    name: str
    url: str
    emoji: str = "🎻"


@dataclass(frozen=True)
class EventRef:
    title: str
    url: str
    listing_program: str = ""
    venue: str = ""
    date: str = ""


LISTENERS: list[Listener] = [
# -------
# REGION
# -------
# ---------
# COMPOSERS
# ---------
    Listener(
        name="Jean Sibelius",
        url="https://bachtrack.com/de_DE/search-events/composer=101;region=146",
        emoji="🎻",
    ),
    Listener(
        name="Sergeij Rachmaninoff",
        url="https://bachtrack.com/de_DE/search-events/composer=85;region=146",
        emoji="🎹",
    ),
    Listener(
        name="Antonin Dvorak",
        url="https://bachtrack.com/de_DE/search-events/composer=38;region=146",
        emoji="🎹",
    ),
# ----------
# PERFORMERS
# ----------
    Listener(
        name="Ray Chen",
        url="https://bachtrack.com/de_DE/search-events/performer=17568;region=146",
        emoji="🎻",
    ),
    Listener(
        name="Hilary Hahn",
        url="https://bachtrack.com/de_DE/search-events/performer=102;region=146",
        emoji="🎻",
    ),
    Listener(
        name="Augustin Hadelich",
        url="https://bachtrack.com/de_DE/search-events/performer=7009;region=146",
        emoji="🎻",
    ),
    Listener(
        name="Martha Argerich",
        url="https://bachtrack.com/de_DE/search-events/performer=1208;region=146",
        emoji="🎹",
    ),
    Listener(
        name="Yunchan Lim",
        url="https://bachtrack.com/de_DE/search-events/performer=108981;region=146",
        emoji="🎹",
    ),
#--------
# PIECES
#--------
    Listener(
        name="Holst - Die Planeten",
        url="https://bachtrack.com/de_DE/search-events/work=7161;region=146",
        emoji="🎹",
    ),
    Listener(
        name="Sibelius - Symphonie Nr. 2",
        url="https://bachtrack.com/de_DE/search-events/work=8559;region=146",
        emoji="🎼",
    )
    # Example for adding more:
    # Listener(name="bruckner_nrw", url="https://bachtrack.com/de_DE/search-events/composer=85;region=146"),
]


def _load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass


def _normalize_event_url(href: str) -> str | None:
    if not href:
        return None
    abs_url = urljoin(BACHTRACK_BASE_URL, href)
    return abs_url


def _extract_events_from_search(html: str, search_url: str) -> list[EventRef]:
    soup = BeautifulSoup(html, "html.parser")

    # Preferred: search XHR returns `.listing-shortform` blocks.
    candidates: list[EventRef] = []
    seen: set[str] = set()

    def add_candidate(
        title: str,
        href: str,
        listing_program: str = "",
        venue: str = "",
        date: str = "",
    ) -> None:
        title = (title or "").strip()
        if not title:
            return
        url = _normalize_event_url(href) or urljoin(search_url, href)
        if not url:
            return
        if url in seen:
            return
        seen.add(url)
        candidates.append(
            EventRef(
                title=title,
                url=url,
                listing_program=(listing_program or "").strip(),
                venue=(venue or "").strip(),
                date=(date or "").strip(),
            )
        )

    for card in soup.select(".listing-shortform"):
        title_el = card.select_one(".li-shortform-title")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)

        date_el = card.select_one(".listing-shortform-dates")
        date_text = date_el.get_text(strip=True) if date_el else ""

        listing_right = card.select_one(".listing-shortform-right")
        listing_program = listing_right.get_text(" ", strip=True) if listing_right else ""

        venue_el = card.select_one("div.li-shortform-venue > h2")
        venue_text = venue_el.get_text(strip=True) if venue_el else ""

        link = card.select_one("a[href*='-event/']")
        if not link:
            continue

        add_candidate(
            title,
            link.get("href") or "",
            listing_program=listing_program,
            venue=venue_text,
            date=date_text
        )

    if candidates:
        return candidates

    # Pass 1: Strong heuristic: `/de_DE/event/` links
    for a in soup.select("a[href*='/de_DE/event/']"):
        href = a.get("href") or ""
        h3 = a.select_one("h3")
        if h3:
            add_candidate(h3.get_text(" ", strip=True), href)

    if candidates:
        return candidates

    # Pass 2: Any anchor that wraps an h3 (often the card title)
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        h3 = a.select_one("h3")
        if not h3:
            continue
        if "/de_DE/" not in href:
            continue
        add_candidate(h3.get_text(" ", strip=True), href)

    if candidates:
        return candidates

    # No event links found → don't invent synthetic "events" (this causes misleading fixed counts like 50).
    return []


def fetch_search_events(search_url: str) -> list[EventRef]:
    """
    Bachtrack search pages load results via XHR.
    We replicate that by calling `json/search/get-results/...` and parsing the returned HTML fragment.
    """

    parsed = urlparse(search_url)
    # IMPORTANT: bachtrack search criteria often uses semicolons in the URL path
    # (e.g. ".../composer=101;region=146"). Python's urlparse splits everything
    # after the first ';' into `params`, so we must stitch it back.
    path = (parsed.path or "") + ((";" + parsed.params) if getattr(parsed, "params", "") else "")

    # Extract the criteria chunk after `/search-.../`
    # Example: `/de_DE/search-events/composer=101;region=146`
    crit = ""
    if "/search-" in path:
        crit = path.split("/search-", 1)[1]  # e.g. "events/composer=101;region=146"
        crit = crit.split("/", 1)[1] if "/" in crit else ""
    crit = crit or "none"

    json_url = f"{BACHTRACK_BASE_URL}/json/search/get-results/1200/listing/{crit}"
    try:
        resp = requests.get(
            json_url,
            timeout=30,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                "Accept": "application/json,text/json;q=0.9,*/*;q=0.8",
                "Referer": search_url,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        j = resp.json()
        if j.get("result") == "OK":
            frag = (j.get("data") or {}).get("text") or ""
            return _extract_events_from_search(frag, search_url=search_url)
        if DEBUG:
            data = j.get("data") or {}
            print(
                f"[debug] XHR returned result={j.get('result')} count={data.get('count')} total={data.get('total')} url={json_url}"
            )
    except Exception as e:
        if DEBUG:
            try:
                status = locals().get("resp").status_code  # type: ignore[name-defined]
                ct = locals().get("resp").headers.get("content-type")  # type: ignore[name-defined]
                head = (locals().get("resp").text or "")[:200].replace("\n", " ")  # type: ignore[name-defined]
                print(f"[debug] XHR failed ({status} {ct}): {e} head={head}")
            except Exception:
                print(f"[debug] XHR failed: {e}")

    # Fallback: fetch raw HTML (may not contain results without JS).
    html = requests.get(
        search_url,
        timeout=30,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://bachtrack.com/de_DE/",
        },
    ).text
    return _extract_events_from_search(html, search_url=search_url)


def _soup_text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def is_favourite(item: str) -> bool:
    norm_item = normalize(item)
    return any(is_similar(norm_item, fav) for fav in FAVOURITES_NORM)


def is_similar(a: str, b: str, threshold: float = 0.6) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= threshold


def _trim_for_discord(text: str, limit: int = 1800) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def fetch_program(event_url: str) -> list[str]:
    try:
        html = requests.get(
            event_url,
            timeout=30,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
            },
        ).text
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")

    # --- HIER FEHLTE ES ---
    rows = soup.select("#tbody_listing-programme tr")
    if DEBUG:
        print(f"[fetch_program] found {len(rows)} rows in tbody_listing-programme")

    program_items = []

    for row in rows:
        cols = row.select("td")
        if len(cols) < 2:
            continue

        composer = cols[0].get_text(" ", strip=True)
        work = cols[1].get_text(" ", strip=True)

        if composer and work:
            item = f"{composer} – {work}"

            if is_favourite(item):
                item = "❗ " + item

            program_items.append(item)

    if DEBUG:
        print(f"[fetch_program] parsed items: {program_items}")

    return program_items


def _discord_message(listener: Listener, event: EventRef, program: list[str]) -> str:
    title = (event.title or "").strip() or "(unbekannter Titel)"
    venue = (event.venue or "").strip() # Sicherstellen, dass es nicht None ist
    date = (event.date or "").strip()

    header = (
        f"{listener.emoji} *Neues Konzert* ({listener.name})\n"
        f"**{title}**\n"
        f"📅 {date if date else 'Datum unbekannt'}\n"
        f"📍 {venue if venue else 'Ort unbekannt'}\n"
        f"{event.url}"
    )
    
    if not _env_truthy("BACHTRACK_DISCORD_INCLUDE_PROGRAM", default=True):
        return _trim_for_discord(header)

    blocks: list[str] = [header]

    if program:
        items = program[:5]
        if len(program) > 5:
            items.append("(weitere Stücke gekürzt)")

        pretty_lines = []
        for it in items:
            if it.startswith("❗ "):
                it = it[2:]  # ❗ entfernen, wenn nötig
                fav_prefix = "❗ "
            else:
                fav_prefix = ""

            if "–" in it:
                composer, work = map(str.strip, it.split("–", 1))
                pretty_lines.append(f"- {fav_prefix}**{composer}**\n    {work}")
            else:
                pretty_lines.append(f"- {fav_prefix}{it}")

        blocks.append("**Programm**\n" + "\n".join(pretty_lines))

    return _trim_for_discord("\n\n".join(blocks))


def run_listener(listener: Listener, state: dict) -> None:
    all_events = fetch_search_events(listener.url)
    print(f"[{listener.name}] found {len(all_events)} events")
    if not all_events:
        print(f"[{listener.name}] no events parsed (skipping alerts/state update)")
        return

    listeners_state = state.setdefault("listeners", {})
    seen_for_listener = listeners_state.get(listener.name, {})

    for e in all_events:
        program = fetch_program(e.url)  # <-- hier kommt jetzt immer dein Debug-Print
        seen_for_listener[e.url] = {
            "title": e.title,
            "listing_program": e.listing_program,
            "program": program,
            "venue": e.venue,
            "date": e.date,
        }

    # State speichern
    listeners_state[listener.name] = seen_for_listener

    # Same methodology as before: first run records state, no spam.
    # Treat missing or empty state as first run to avoid spamming.
    if (
        not isinstance(seen_for_listener, dict)
        or not seen_for_listener
        or not any("-event/" in str(k) or "/event/" in str(k) for k in seen_for_listener.keys())
    ):
        listeners_state[listener.name] = {
            e.url: {
                "title": e.title,
                "listing_program": e.listing_program,
                "venue": e.venue,
            }
            for e in all_events
        }
        print(f"[{listener.name}] initialized state with {len(all_events)} events (no alerts on first run)")
        return

    new = [e for e in all_events if e.url not in seen_for_listener]
    print(f"[{listener.name}] new events: {len(new)}")

    # if not new:
    #     # Nothing new → sende das zuletzt bekannte Event.
    #     if seen_for_listener:
    #         try:
    #             last_url, last_info = next(reversed(seen_for_listener.items()))
    #         except StopIteration:
    #             return
    #         if "-event/" not in str(last_url):
    #             print(
    #                 f"[{listener.name}] last known url doesn't look like an *-event url, skipping test alert: {last_url}"
    #             )
    #             return
    #         title = str(last_info.get("title") or "").strip() or "(unbekannter Titel)"
    #         program = last_info.get("program") or []
    #         if isinstance(program, str):
    #             program = [program]
    #         listing_program = str(last_info.get("listing_program") or "")
    #         venue = str(last_info.get("venue") or "")
    #         last_event = EventRef(
    #             title=title,
    #             url=last_url,
    #             listing_program=listing_program,
    #             venue=str(last_info.get("venue") or ""),
    #         )
    #     return None

    for e in new:
        program = fetch_program(e.url)
        send_discord(_discord_message(listener, e, program), DISCORD_WEBHOOK)
        seen_for_listener[e.url] = {
            "title": e.title,
            "listing_program": e.listing_program,
            "program": program,
            "venue": e.venue,
            "date": e.date
        }
        print(f"seen_for_listener: {seen_for_listener}")


def send_all_from_state():
    """Liest den kompletten State und sendet jedes gespeicherte Event an Discord."""
    state = _load_state()
    listeners_state = state.get("listeners", {})

    if not listeners_state:
        print("Der State ist leer oder konnte nicht geladen werden.")
        return

    for listener_name, events_dict in listeners_state.items():
        # Wir suchen das passende Listener-Objekt für das Emoji
        listener_obj = next((l for l in LISTENERS if l.name == listener_name), None)
        if not listener_obj:
            # Fallback, falls der Listener aus der Liste gelöscht wurde
            listener_obj = Listener(name=listener_name, url="", emoji="🎶")

        print(f"Sende Events für Listener: {listener_name} ({len(events_dict)} Events)")

        for url, data in events_dict.items():
            # Wir bauen ein temporäres EventRef Objekt aus den JSON-Daten
            event = EventRef(
                title=data.get("title", ""),
                url=url,
                listing_program=data.get("listing_program", ""),
                venue=data.get("venue", ""),
                date=data.get("date", "")
            )
            program = data.get("program", "") or[]
            if isinstance(program, str):
                program = [program]
            
            # Nachricht generieren und senden
            msg = _discord_message(listener_obj , event, program)
            send_discord(msg, DISCORD_WEBHOOK)
            
            # Kurze Pause, um Discord Rate-Limits zu vermeiden
            import time
            time.sleep(0.5)

    print("Fertig! Alle Events wurden gesendet.")


def main() -> None:
    state = _load_state()
    for listener in LISTENERS:
        run_listener(listener, state)
    _save_state(state)


if __name__ == "__main__":
    # Option A: Normaler Monitor-Betrieb
    main()

    now = datetime.now().hour 
    # Option B: Einmalig alles aus dem Speicher senden
    if  15 <= now <= 16:
        send_all_from_state()