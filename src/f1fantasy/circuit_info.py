"""Seasonal official circuit metadata. Images remain remote browser resources."""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

import requests

from . import public_history
from .data import DataError

BASE = "https://www.formula1.com"
VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def nodes(self, tag):
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    yield child
                yield from child.nodes(tag)

    def text(self):
        return " ".join(
            child.text() if isinstance(child, Node) else child
            for child in self.children
        ).strip()


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def calendar(html, season):
    """Discover published round URLs, including new venues and reordered calendars."""
    result = {}
    for anchor in Page(html).root.nodes("a"):
        href = anchor.attrs.get("href", "")
        if not re.fullmatch(rf"/en/racing/{season}/[a-z0-9-]+", href):
            continue
        number = re.search(r"\bROUND\s+(\d+)", anchor.text(), re.I)
        if number:
            key = int(number[1])
            source = urljoin(BASE, href)
            if key in result and result[key] != source:
                raise DataError("Official circuit calendar has ambiguous round links")
            result[key] = source
    if not result:
        raise DataError("Official circuit calendar contains no round links")
    return result


def image_url(value):
    parsed = urlsplit(value)
    return (
        value
        if parsed.scheme == "https"
        and parsed.netloc == "media.formula1.com"
        and parsed.path.startswith("/image/upload/")
        else None
    )


def parse(html, *, season, number, event, source, checked_at):
    page = Page(html).root
    sport = None
    for script in page.nodes("script"):
        if script.attrs.get("type") == "application/ld+json":
            value = json.loads(script.text())
            if isinstance(value, dict) and value.get("@type") == "SportsEvent":
                sport = value
                break
    if sport is None or f"/en/racing/{season}/" not in sport.get("@id", ""):
        raise DataError("Circuit page does not identify the requested official season")
    start, end = (public_history.date(sport[key]) for key in ("startDate", "endDate"))
    race = public_history.date(event["race_start"])
    if start.year != season or not start - timedelta(days=1) <= race <= end + timedelta(
        days=1
    ):
        raise DataError("Circuit page dates do not match the archived race")

    def place(value):
        return "".join(
            c for c in unicodedata.normalize("NFKD", value.casefold()) if c.isalnum()
        )

    if place(sport["location"]["name"]) != place(event["Location"]):
        raise DataError("Circuit page location does not match the archived venue")

    fields, notes = {}, {}
    for dl in page.nodes("dl"):
        for group in dl.nodes("div"):
            labels, values = list(group.nodes("dt")), list(group.nodes("dd"))
            if len(labels) == len(values) == 1:
                label = labels[0].text()
                fields[label] = values[0].text()
                notes[label] = " ".join(n.text() for n in group.nodes("span")).strip()
    length = float(fields["Circuit Length"].removesuffix("km").strip())
    laps = int(fields["Number of Laps"])
    distance = float(fields["Race Distance"].removesuffix("km").strip())
    if not (0 < length < 30 and 0 < laps < 200 and 0 < distance < 1000):
        raise DataError("Official circuit specifications are incomplete or invalid")
    maps, photos = [], []
    for image in page.nodes("img"):
        url = image_url(image.attrs.get("src", ""))
        if url and "/track/" in url and "detailed" in url:
            maps.append(url)
        elif url and "racehub" in url.lower():
            photos.append(url)
    maps = list(dict.fromkeys(maps))
    if len(maps) != 1:
        raise DataError("No unique official detailed circuit map")
    description = ""
    for details in page.nodes("details"):
        summary = next(details.nodes("summary"), None)
        if summary and "circuit like?" in summary.text().lower():
            description = " ".join(
                p.text()
                for p in details.nodes("p")
                if "circuit like?" not in p.text().lower()
            )
            break
    return {
        "season": season,
        "round": number,
        "event_name": event["EventName"],
        "race_start": event["race_start"],
        "location": sport["location"]["name"],
        "source": source,
        "checked_at": checked_at.isoformat(),
        "spec": {"length_km": length, "race_laps": laps, "race_distance_km": distance},
        "map_asset": maps[0],
        "photo_asset": photos[0] if photos else None,
        "description": description,
        "first_gp": int(fields["First Grand Prix"])
        if fields.get("First Grand Prix", "").isdigit()
        else None,
        "lap_record": fields.get("Fastest lap time"),
        "record_driver": notes.get("Fastest lap time", ""),
    }


def _html(url):
    response = requests.get(url, timeout=25)
    response.raise_for_status()
    return response.text


def refresh(document, season, now):
    """Refresh metadata daily. Failure preserves its original check time and source."""
    rows = document.setdefault("circuits", {})
    events = {
        key: value
        for key, value in document["events"].items()
        if key.startswith(f"{season}/")
    }
    for key in list(rows):
        if key.startswith(f"{season}/") and key not in events:
            del rows[key]
    try:
        links = calendar(_html(f"{BASE}/en/racing/{season}"), season)
    except (requests.RequestException, DataError, ValueError) as exc:
        print(f"Circuit calendar unavailable: {exc}", flush=True)
        return
    for key, event in events.items():
        number = int(key.split("/")[1])
        source = links.get(number)
        if source is None:
            continue
        old = rows.get(key)
        if (
            old
            and old["source"] == source
            and old["race_start"] == event["race_start"]
            and old["event_name"] == event["EventName"]
            and old["location"] == event["Location"]
            and public_history.date(old["checked_at"]).date() == now.date()
        ):
            continue
        try:
            rows[key] = parse(
                _html(source),
                season=season,
                number=number,
                event=event,
                source=source,
                checked_at=now,
            )
        except (
            requests.RequestException,
            DataError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            print(f"Circuit metadata unavailable for {key}: {exc}", flush=True)


def lookup(weekend):
    document = (public_history.current() or {}).get("document", {})
    row = document.get("circuits", {}).get(f"{weekend.season}/{weekend.round}")
    event = document.get("events", {}).get(f"{weekend.season}/{weekend.round}")
    return (
        row
        if row
        and event
        and row["race_start"] == event["race_start"]
        and row["event_name"] == event["EventName"]
        and row["location"] == event["Location"]
        else None
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--history", type=Path, default=public_history.DEFAULT)
    args = parser.parse_args(argv)
    with public_history.repository(args.history, update=True) as document:
        refresh(document, args.season, datetime.now(timezone.utc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
