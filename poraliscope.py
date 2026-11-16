
"""The Poraliscope公式NEWSの「ライブ」カテゴリから公演を取得。"""
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Asia/Tokyo")
NEWS_URL = "https://poraliscope.bitfan.id/contents/menu/76258"

DATE = re.compile(
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
EXCLUDE = re.compile(
    r"トーク|配信|生放送|YouTube|インストア|特典会|"
    r"サイン会|握手会|撮影会|リリースイベント|ラジオ",
    re.I,
)
BAND = re.compile(r"The\s*Poraliscope|ポラリスコープ", re.I)
TIME = re.compile(
    r"(?:START|開演)\s*[:：]?\s*([01]?\d|2[0-3]):([0-5]\d)",
    re.I,
)
VENUE = re.compile(r"【会場】\s*([^\n]+)")
TITLE = re.compile(r"【(?:題名|タイトル)】\s*([^\n]+)")


def _lines(soup):
    for element in soup(["script", "style", "nav", "footer"]):
        element.decompose()

    return [
        re.sub(r"\s+", " ", x).strip()
        for x in soup.get_text("\n").splitlines()
        if x.strip()
    ]


def _first_match(pattern, text):
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _date_from(text, today):
    for match in DATE.finditer(text):
        try:
            value = date(*map(int, match.groups()))
        except ValueError:
            continue

        if value >= today:
            return value

    return None


def fetch_poraliscope(artist):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html",
    })

    today = datetime.now(TZ).date()

    # NEWSの「ライブ」タグから記事を取得
    article_links = {}

    for page in range(1, 21):
        response = session.get(
            NEWS_URL,
            params={"tag": "ライブ", "page": page},
            timeout=25,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        added = 0

        for a in soup.select('a[href*="/contents/"]'):
            url = urljoin(
                response.url,
                a.get("href", ""),
            ).split("?")[0]

            match = re.search(r"/contents/(\d+)/?$", url)

            if match and url not in article_links:
                article_links[url] = a.get_text(" ", strip=True)
                added += 1

        if added == 0:
            break

    events = []

    for url, listing_title in article_links.items():
        response = session.get(url, timeout=25)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        lines = _lines(soup)
        full_text = "\n".join(lines)

        heading = next(
            (
                x for x in lines
                if "【出演決定" in x or "【開催決定" in x
            ),
            listing_title,
        )

        title_text = heading.split(" | ")[0]

        if EXCLUDE.search(title_text):
            continue

        if not BAND.search(full_text):
            continue

        day = _date_from(title_text, today)

        if day is None:
            day = _date_from(full_text, today)

        if day is None:
            continue

        event_name = _first_match(TITLE, full_text)

        if not event_name:
            for i, line in enumerate(lines):
                if DATE.search(line) and i > 0:
                    previous = lines[i - 1]

                    if (
                        previous != title_text
                        and len(previous) < 130
                        and not DATE.search(previous)
                    ):
                        event_name = previous
                        break

        event_name = event_name or title_text or listing_title

        if EXCLUDE.search(event_name):
            continue

        venue = _first_match(VENUE, full_text)

        if not venue:
            for i, line in enumerate(lines):
                if DATE.search(line) and i + 1 < len(lines):
                    next_line = lines[i + 1]

                    if re.search(
                        r"LIVEHOLIC|ReG|FOWS|HALL|"
                        r"ホール|ライブハウス",
                        next_line,
                        re.I,
                    ):
                        venue = next_line
                        break

        if not venue:
            match = re.search(r"＠\s*([^\s]+)", title_text)

            if match:
                venue = match.group(1)
            else:
                match = re.search(
                    r"(渋谷FOWS|下北沢ReG|下北沢LIVEHOLIC)",
                    title_text,
                )

                if match:
                    venue = match.group(1)

        tm = TIME.search(full_text)

        if tm:
            start = datetime(
                day.year,
                day.month,
                day.day,
                int(tm.group(1)),
                int(tm.group(2)),
                tzinfo=TZ,
            )
            end = start + timedelta(hours=3)
        else:
            start = day
            end = day + timedelta(days=1)

        event_id = re.search(
            r"/contents/(\d+)",
            url,
        ).group(1)

        events.append({
            "uid": f"poraliscope-{event_id}@live-calendar",
            "title": f'【{artist["name"]}】{event_name}',
            "start": start,
            "end": end,
            "location": venue,
            "description": (
                f"公式情報: {url}\n"
                f'開演: {tm.group(0) if tm else "未掲載"}\n'
                "終了時刻は仮設定"
            ),
            "url": url,
        })

    return sorted(
        events,
        key=lambda event: str(event["start"]),
    )
