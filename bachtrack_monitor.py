import json
import os
import re
import datetime
from datetime import datetime
from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from discord_notify import send_discord

BACHTRACK_BASE_URL = "https://bachtrack.com"
STATE_FILE = os.getenv("BACHTRACK_STATE_FILE", "bachtrack_state.json")
DEBUG = os.getenv("BACHTRACK_DEBUG", "").strip().lower() in {"1", "true", "yes", "y", "on"}
USER_AGENT = os.getenv(
    "BACHTRACK_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
)


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
        name="rachmaninoff",
        url="https://bachtrack.com/de_DE/search-events/composer=85;region=146",
        emoji="🎹",
    ),
    Listener(
        name="dvorak",
        url="https://bachtrack.com/de_DE/search-events/composer=38;region=146",
        emoji="🎹",
    ),
    Listener(
        name="ray_chen",
        url="https://bachtrack.com/de_DE/search-events/performer=17568;region=146",
        emoji="🎻",
    ),
    Listener(
        name="hilary_hahn",
        url="https://bachtrack.com/de_DE/search-events/performer=102;region=146",
        emoji="🎻",
    ),
    Listener(
        name="holst_diePlaneten",
        url="https://bachtrack.com/de_DE/search-events/work=7161;region=146",
        emoji="🎹",
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


def _split_program_items(program: str) -> list[str]:
    """
    Try to split a flattened program string into readable items.
    Bachtrack listing snippets often look like: "Composer, Name Work ... Composer, Name Work ..."
    """
    program = (program or "").strip()
    if not program:
        return []

    # Split on likely composer tokens like "Surname, Firstname"
    token_re = re.compile(r"(?:^| )([A-ZÀ-ÖØ-Ý][^,\n]{1,60},\s+[^,\n]{1,60})")
    matches = list(token_re.finditer(program))
    if len(matches) < 2:
        return [program]

    starts = [m.start(1) for m in matches]
    starts.append(len(program))
    out: list[str] = []
    for i in range(len(starts) - 1):
        chunk = program[starts[i] : starts[i + 1]].strip(" ,;-")
        if chunk:
            out.append(chunk)
    return out or [program]


def _trim_for_discord(text: str, limit: int = 1800) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def fetch_program(event_url: str) -> str:
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
    title = (event.title or "").strip() or "(unbekannter Titel)"
    venue = (event.venue or "").strip() # Sicherstellen, dass es nicht None ist
    date = (event.date or "").strip()

    # Debug: Print direkt vor dem Zusammenbau der Nachricht
    print(f"DEBUG Discord Message: Venue is '{venue}'") 

    header = (
        f"{listener.emoji} *Neues Konzert* ({listener.name})\n"
        f"**{title}**\n"
        f"📅 {date if date else 'Datum unbekannt'}\n"
        f"📍 {venue if venue else 'Ort unbekannt'}\n"
        f"{event.url}"
    )
    # ... restlicher Code

    # Allow short alerts without the (often long) program block.
    # Set BACHTRACK_DISCORD_INCLUDE_PROGRAM=0 to disable.
    if not _env_truthy("BACHTRACK_DISCORD_INCLUDE_PROGRAM", default=True):
        return _trim_for_discord(header)

    detail_program = (program or "").strip()
    listing_program = (event.listing_program or "").strip()

    # Prefer detail program; fall back to listing program.
    primary = detail_program or listing_program
    secondary = listing_program if detail_program and listing_program and detail_program != listing_program else ""

    blocks: list[str] = [header]
    if primary:
        items = _split_program_items(primary)
        if len(items) > 12:
            items = items[:12] + ["(weitere Stücke gekürzt)"]
        pretty = "\n".join(f"- {it}" for it in items)
        blocks.append("**Programm**\n" + pretty)

    if secondary:
        items2 = _split_program_items(secondary)
        if len(items2) > 8:
            items2 = items2[:8] + ["(weitere Stücke gekürzt)"]
        pretty2 = "\n".join(f"- {it}" for it in items2)
        blocks.append("**Programm (Listing)**\n" + pretty2)

    return _trim_for_discord("\n\n".join(blocks))


def run_listener(listener: Listener, state: dict) -> None:
    all_events = fetch_search_events(listener.url)
    print(f"[{listener.name}] found {len(all_events)} events")
    if not all_events:
        print(f"[{listener.name}] no events parsed (skipping alerts/state update)")
        return

    listeners_state = state.setdefault("listeners", {})
    seen_for_listener = listeners_state.get(listener.name)

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
    #         program = str(last_info.get("program") or "")
    #         listing_program = str(last_info.get("listing_program") or "")
    #         venue = str(last_info.get("venue") or "")
    #         last_event = EventRef(
    #             title=title,
    #             url=last_url,
    #             listing_program=listing_program,
    #             venue=str(last_info.get("venue") or ""),
    #         )
    #         send_discord(_discord_message(listener, last_event, program))
    #     return

    for e in new:
        program = fetch_program(e.url)
        send_discord(_discord_message(listener, e, program))
        seen_for_listener[e.url] = {
            "title": e.title,
            "listing_program": e.listing_program,
            "program": program,
            "venue": e.venue,
            "date": e.date
        }
        print(f"seen_for_listener: {seen_for_listener}")


def main() -> None:
    state = _load_state()
    for listener in LISTENERS:
        run_listener(listener, state)
    _save_state(state)


if __name__ == "__main__":
    main()

