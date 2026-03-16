import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from discord_notify import send_discord

BACHTRACK_BASE_URL = "https://bachtrack.com"
STATE_FILE = os.getenv("BACHTRACK_STATE_FILE", "bachtrack_state.json")


@dataclass(frozen=True)
class Listener:
    name: str
    url: str
    emoji: str = "🎻"


@dataclass(frozen=True)
class EventRef:
    title: str
    url: str


LISTENERS: list[Listener] = [
    Listener(
        name="sibelius_nrw",
        url="https://bachtrack.com/de_DE/search-events/composer=101;region=146",
        emoji="🎻",
    ),
    Listener(
        name="deutschland_neu",
        url="https://bachtrack.com/de_DE/search-events/medium=1/country=5",
        emoji="🇩🇪",
    ),
    Listener(
        name="UK",
        url="https://bachtrack.com/de_DE/search-events/country=1",
        emoji="🇬🇧",
    ),
    Listener(
        name="USA",
        url="https://bachtrack.com/de_DE/search-events/country=2",
        emoji="🇺🇸",
    ),
    Listener(
        name="Netherlands",
        url="https://bachtrack.com/de_DE/search-events/country=25",
        emoji="🇳🇱",
    ),
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
    # Heuristic: only keep likely event detail URLs.
    if re.search(r"/de_DE/(event|concert|search-events)/", abs_url):
        return abs_url
    return abs_url


def _extract_events_from_search(html: str, search_url: str) -> list[EventRef]:
    soup = BeautifulSoup(html, "html.parser")

    # Prefer anchors wrapping titles; fall back to scanning h3s.
    candidates: list[EventRef] = []
    seen: set[str] = set()

    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        if "/de_DE/" not in href:
            continue

        title_el = a.select_one("h3") or a.select_one("[class*='title']") or a
        title = title_el.get_text(" ", strip=True)
        if not title:
            continue

        url = _normalize_event_url(href) or urljoin(search_url, href)
        if url in seen:
            continue
        seen.add(url)
        candidates.append(EventRef(title=title, url=url))

    if candidates:
        return candidates

    # Last-resort: just use h3 text without links.
    for h3 in soup.select("h3"):
        title = h3.get_text(" ", strip=True)
        if not title:
            continue
        synthetic_url = search_url + "#title=" + requests.utils.quote(title)
        if synthetic_url in seen:
            continue
        seen.add(synthetic_url)
        candidates.append(EventRef(title=title, url=synthetic_url))

    return candidates


def fetch_search_events(search_url: str) -> list[EventRef]:
    html = requests.get(search_url, timeout=30).text
    return _extract_events_from_search(html, search_url=search_url)


def _soup_text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def fetch_program(event_url: str) -> str:
    try:
        html = requests.get(event_url, timeout=30).text
    except Exception:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Common-ish containers (Bachtrack markup can vary).
    selectors = [
        "#program",
        "#programme",
        "[id*='program']",
        "[class*='program']",
        "[class*='programme']",
        "[data-testid*='program']",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            text = _soup_text(el)
            if text and len(text) >= 20:
                return text

    # Heading-based fallback: find a header mentioning "Programm"/"Programme".
    for h in soup.select("h1, h2, h3, h4"):
        label = _soup_text(h).lower()
        if "programm" in label or "programme" in label:
            # Take the next meaningful block.
            nxt = h.find_next(["div", "section", "p", "ul", "ol"])
            if nxt:
                text = _soup_text(nxt)
                if text and len(text) >= 20:
                    return text

    return ""


def _discord_message(listener: Listener, event: EventRef, program: str) -> str:
    header = f"{listener.emoji} Neues Konzert entdeckt ({listener.name}):\n{event.title}\n{event.url}"
    program = (program or "").strip()
    if not program:
        return header
    return header + "\n\nProgramm:\n" + program


def run_listener(listener: Listener, state: dict) -> None:
    all_events = fetch_search_events(listener.url)

    listeners_state = state.setdefault("listeners", {})
    seen_for_listener = listeners_state.get(listener.name)

    # Same methodology as before: first run records state, no spam.
    if not isinstance(seen_for_listener, dict):
        listeners_state[listener.name] = {e.url: {"title": e.title} for e in all_events}
        return

    new = [e for e in all_events if e.url not in seen_for_listener]
    if not new:
        # Nothing new → sende das zuletzt bekannte Event.
        if seen_for_listener:
            try:
                last_url, last_info = next(reversed(seen_for_listener.items()))
            except StopIteration:
                return
            title = str(last_info.get("title") or "").strip() or "(unbekannter Titel)"
            program = str(last_info.get("program") or "")
            last_event = EventRef(title=title, url=last_url)
            send_discord(_discord_message(listener, last_event, program))
        return

    for e in new:
        program = fetch_program(e.url)
        send_discord(_discord_message(listener, e, program))
        seen_for_listener[e.url] = {"title": e.title, "program": program}


def main() -> None:
    state = _load_state()
    for listener in LISTENERS:
        run_listener(listener, state)
    _save_state(state)


if __name__ == "__main__":
    main()

