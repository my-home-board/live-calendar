
import calendar
import hashlib
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from nightmare import fetch_nightmare
from kizu import fetch_kizu
from poraliscope import fetch_poraliscope


ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Tokyo")
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; PersonalCalendarBot/1.0)"
})


def soup_for(url):
    r = SESSION.get(url, timeout=25)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def field(text, label, next_labels):
    pattern = (
        re.escape(label)
        + r"\s*(.*?)\s*(?="
        + "|".join(map(re.escape, next_labels))
        + r"|$)"
    )
    m = re.search(pattern, text, flags=re.S)
    return clean(m.group(1)) if m else ""


def fetch_fanpla(artist):
    now = datetime.now(TZ).date()
    events = []

    for offset in range(13):
        y = now.year + (now.month - 1 + offset) // 12
        m = (now.month - 1 + offset) % 12 + 1

        listing = soup_for(
            artist["url"]
            + f"?year={y}&month={m}&viewMode=default"
        )

        links = []
        for a in listing.select(
            'a[href*="/live_information/detail/"]'
        ):
            url = urljoin(
                artist["url"], a.get("href", "")
            )
            if url not in links:
                links.append(url)

        for url in links:
            detail = soup_for(url)
            text = detail.get_text("\n", strip=True)

            match = re.search(
                r"公演日\s*(\d{4})\.(\d{1,2})\.(\d{1,2})",
                text,
            )
            if not match:
                raise ValueError(
                    f"Date not found in {url}"
                )

            day = date(*map(int, match.groups()))
            if day < now:
                continue

            title_tag = detail.find(["h1", "h2"])
            before = text.split("公演日")[0].splitlines()
            title = clean(before[-1]) if before else ""

            if not title or title in ("SCHEDULE", "MAMA."):
                title = (
                    clean(title_tag.get_text(" ", strip=True))
                    if title_tag
                    else "LIVE"
                )

            location = field(
                text,
                "開催場所・会場",
                [
                    "OPEN/START",
                    "出演",
                    "チケット",
                    "INFO",
                    "BACK",
                ],
            )

            hours = field(
                text,
                "OPEN/START",
                [
                    "出演",
                    "チケット",
                    "INFO",
                    "BACK",
                ],
            )

            times = re.findall(
                r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)",
                hours,
            )

            start = datetime.combine(
                day, datetime.min.time(), TZ
            )

            if times:
                start = start.replace(
                    hour=int(times[0][0]),
                    minute=int(times[0][1]),
                )
                end = start + timedelta(hours=3)
            else:
                start = day
                end = day + timedelta(days=1)

            desc = (
                f"公式情報: {url}\n"
                f'開場/開演: {hours or "未掲載"}'
            )

            events.append({
                "uid": (
                    f'{artist["id"]}-'
                    f'{url.rstrip("/").split("/")[-1]}'
                    "@live-calendar"
                ),
                "title": f'【{artist["name"]}】{title}',
                "start": start,
                "end": end,
                "location": location,
                "description": desc,
                "url": url,
            })

    return events


def esc(s):
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def dtline(name, value):
    if isinstance(value, datetime):
        return (
            f"{name};TZID=Asia/Tokyo:"
            f"{value:%Y%m%dT%H%M%S}"
        )
    return f"{name};VALUE=DATE:{value:%Y%m%d}"


def fold(line):
    out, part, count = [], "", 0

    for ch in line:
        n = len(ch.encode("utf-8"))

        if count + n > 75:
            out.append(part)
            part, count = " ", 1

        part += ch
        count += n

    out.append(part)
    return "\r\n".join(out)


def write_calendar(events, calendar_name, dest):
    stamp = datetime.now(
        ZoneInfo("UTC")
    ).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Personal Live Calendar//JP",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(calendar_name)}",
        "X-WR-TIMEZONE:Asia/Tokyo",
    ]

    for e in sorted(
        events, key=lambda e: str(e["start"])
    ):
        lines += [
            "BEGIN:VEVENT",
            f'UID:{e["uid"]}',
            f"DTSTAMP:{stamp}",
            dtline("DTSTART", e["start"]),
            dtline("DTEND", e["end"]),
            f'SUMMARY:{esc(e["title"])}',
            f'LOCATION:{esc(e["location"])}',
            f'DESCRIPTION:{esc(e["description"])}',
            f'URL:{e["url"]}',
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")

    dest.parent.mkdir(
        parents=True, exist_ok=True
    )
    dest.write_bytes(
        (
            "\r\n".join(
                fold(line) for line in lines
            ) + "\r\n"
        ).encode("utf-8")
    )

    print(
        f"Generated {len(events)} events: {dest}"
    )


def write_artist_calendar(
    events, artist_id, artist_name
):
    write_calendar(
        events,
        artist_name,
        ROOT / "docs" / f"{artist_id}.ics",
    )


def read_event_blocks(path):
    text = path.read_bytes().decode("utf-8")
    blocks = []

    for m in re.finditer(
        r"BEGIN:VEVENT\r?\n(?:.*\r?\n)*?END:VEVENT",
        text,
    ):
        block = (
            m.group(0)
            .replace("\r\n", "\n")
            .replace("\n", "\r\n")
        )
        dt = re.search(
            r"DTSTART[^:\r\n]*:(\d{8}(?:T\d{6})?)",
            block,
        )
        blocks.append(
            (dt.group(1) if dt else "", block)
        )

    return blocks


def write_combined_calendar(artists):
    blocks = []

    for artist in artists:
        if not artist.get("enabled", True):
            continue

        path = ROOT / "docs" / f'{artist["id"]}.ics'

        if path.exists():
            blocks.extend(read_event_blocks(path))

    blocks.sort(key=lambda b: b[0])

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Personal Live Calendar//JP",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc('LIVE SCHEDULE')}",
        "X-WR-TIMEZONE:Asia/Tokyo",
    ]

    body = "\r\n".join(lines) + "\r\n"
    body += "".join(
        block + "\r\n" for _, block in blocks
    )
    body += "END:VCALENDAR\r\n"

    dest = ROOT / "docs" / "live.ics"
    dest.write_bytes(body.encode("utf-8"))

    print(
        f"Generated {len(blocks)} events: {dest}"
    )


def main():
    artists = json.loads(
        (ROOT / "artists.json").read_text(
            encoding="utf-8"
        )
    )

    fetchers = {
        "fanpla_schedule": fetch_fanpla,
        "nightmare_schedule": fetch_nightmare,
        "kizu_schedule": fetch_kizu,
        "poraliscope_news": fetch_poraliscope,
    }

    succeeded = 0
    failed = []

    for artist in artists:
        if not artist.get("enabled", True):
            continue

        source = artist["source"]
        fetch = fetchers.get(source)

        if fetch is None:
            raise ValueError(
                f'Unsupported source for '
                f'{artist["id"]}: {source}'
            )

        try:
            artist_events = fetch(artist)
        except Exception as e:
            print(
                f'WARNING: {artist["name"]} '
                f'の取得に失敗したため、'
                f'前回のデータを維持します: {e}'
            )
            failed.append(artist["name"])
            continue

        succeeded += 1

        write_artist_calendar(
            artist_events,
            artist["id"],
            artist["name"],
        )

    if succeeded == 0 and failed:
        raise SystemExit(
            "ERROR: 全アーティストの取得に失敗しました"
        )

    write_combined_calendar(artists)

    if failed:
        print(
            "WARNING: 取得できなかったアーティスト: "
            + ", ".join(failed)
        )


if __name__ == "__main__":
    main()
