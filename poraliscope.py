
"""The Poraliscope公式NEWSからライブ公演を取得。"""

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
TIME = re.compile(
    r"(?:START|開演)\s*[:：]?\s*"
    r"([01]?\d|2[0-3]):([0-5]\d)",
    re.I,
)
EXCLUDE = re.compile(
    r"トーク|配信|生放送|YouTube|インストア|"
    r"特典会|サイン会|握手会|撮影会|"
    r"リリースイベント|ラジオ",
    re.I,
)

SKIP_TITLES = {
    "ログイン", "フォロー", "NEWS", "ライブ",
    "新しい記事", "過去の記事", "イベント",
    "【タイトル】", "【題名】", "【日程】",
    "【会場】", "【時間】", "【出演者】",
}


def get_lines(soup):
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    return [
        re.sub(r"\s+", " ", line).strip()
        for line in soup.get_text("\n").splitlines()
        if line.strip()
    ]


def extract_date(text, today):
    for match in DATE.finditer(text):
        try:
            day = date(*map(int, match.groups()))
        except ValueError:
            continue

        if day >= today:
            return day

    return None


def extract_title(lines, heading):
    # 【題名】【タイトル】の直後を優先
    for i, line in enumerate(lines):
        for label in ("【題名】", "【タイトル】"):
            if label in line:
                value = line.split(label, 1)[1].strip()

                if value and value not in SKIP_TITLES:
                    return value

                if i + 1 < len(lines):
                    value = lines[i + 1].strip()
                    if value and value not in SKIP_TITLES:
                        return value

    # 公演日の直前にある公演名を取得
    # サイトのログイン・ナビゲーションは除外
    for i, line in enumerate(lines):
        if not DATE.search(line):
            continue

        if i == 0:
            continue

        previous = lines[i - 1].strip()

        if (
            previous
            and previous not in SKIP_TITLES
            and not DATE.search(previous)
            and not previous.startswith("【出演決定")
            and not previous.startswith("【開催決定")
            and not previous.startswith("The Poraliscope")
            and not re.match(r"^\d{4}/\d{1,2}/\d{1,2}", previous)
            and len(previous) <= 150
        ):
            return previous

    return heading


def extract_venue(lines, heading):
    for i, line in enumerate(lines):
        if "【会場】" in line:
            value = line.split("【会場】", 1)[1].strip()

            if value:
                return value

            if i + 1 < len(lines):
                return lines[i + 1].strip()

    known_venues = (
        "渋谷FOWS",
        "下北沢ReG",
        "下北沢LIVEHOLIC",
    )

    for venue in known_venues:
        if venue in heading:
            return venue

    # 日付の直後に会場が書かれている形式
    for i, line in enumerate(lines):
        if DATE.search(line):
            remainder = DATE.sub("", line).strip()

            remainder = re.sub(
                r"^[（(][月火水木金土日][）)]",
                "",
                remainder,
            ).strip()

            if remainder and len(remainder) < 80:
                return remainder

            if i + 1 < len(lines):
                candidate = lines[i + 1].strip()

                if (
                    candidate
                    and candidate not in SKIP_TITLES
                    and len(candidate) < 80
                    and not TIME.search(candidate)
                ):
                    return candidate

    return ""


def fetch_poraliscope(artist):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html",
    })

    today = datetime.now(TZ).date()
    article_links = {}

    # ライブカテゴリのNEWS記事を取得
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

            if not re.search(r"/contents/\d+/?$", url):
                continue

            if url not in article_links:
                article_links[url] = a.get_text(
                    " ", strip=True
                )
                added += 1

        if added == 0:
            break

    events = []

    for url, listing_title in article_links.items():
        response = session.get(url, timeout=25)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        lines = get_lines(soup)
        text = "\n".join(lines)

        # 記事の見出し
        heading = listing_title.split(" NEW ")[0].strip()

        if not heading:
            heading = next(
                (
                    line.split(" | ")[0]
                    for line in lines
                    if "【出演決定" in line
                    or "【開催決定" in line
                ),
                "",
            )

        if EXCLUDE.search(heading):
            continue

        # 日付は記事タイトルを優先
        day = extract_date(heading, today)

        if day is None:
            day = extract_date(text, today)

        if day is None:
            continue

        title = extract_title(lines, heading)

        if EXCLUDE.search(title):
            continue

        if title in SKIP_TITLES:
            title = heading

        venue = extract_venue(lines, heading)

        match = TIME.search(text)

        if match:
            start = datetime(
                day.year,
                day.month,
                day.day,
                int(match.group(1)),
                int(match.group(2)),
                tzinfo=TZ,
            )
            end = start + timedelta(hours=3)
        else:
            start = day
            end = day + timedelta(days=1)

        article_id = re.search(
            r"/contents/(\d+)", url
        ).group(1)

        events.append({
            "uid": (
                f"poraliscope-{article_id}"
                "@live-calendar"
            ),
            "title": (
                f'【{artist["name"]}】{title}'
            ),
            "start": start,
            "end": end,
            "location": venue,
            "description": (
                f"公式情報: {url}\n"
                f"開演: "
                f'{match.group(0) if match else "未掲載"}\n'
                "終了時刻は仮設定"
            ),
            "url": url,
        })

    return sorted(
        events,
        key=lambda event: str(event["start"]),
    )
