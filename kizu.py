
"""キズ公式SCHEDULEからバンド出演ライブを取得。"""
import hashlib
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("Asia/Tokyo")
DATE = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日")
TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)")
EXCLUDE = re.compile(
    r"インストア|特典会|サイン会|握手会|トーク|"
    r"配信|生放送|ラジオ|クリニック|撮影会|"
    r"リリースイベント",
    re.I,
)


def fetch_kizu(artist):
    url = artist["url"]
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=25,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    lines = [
        re.sub(r"\s+", " ", s).strip()
        for s in soup.get_text(
            "\n", strip=True
        ).splitlines()
    ]
    lines = [s for s in lines if s]

    today = datetime.now(TZ).date()
    events = []

    for i, line in enumerate(lines):
        dm = DATE.search(line)

        if not dm or i == 0:
            continue

        try:
            day = date(*map(int, dm.groups()))
        except ValueError:
            continue

        if day < today:
            continue

        title = lines[i - 1]

        if (
            not title
            or DATE.search(title)
            or EXCLUDE.search(title)
        ):
            continue

        block = lines[i + 1:i + 25]
        first = " ".join(block[:12])

        if EXCLUDE.search(
            title + " " + first[:100]
        ):
            continue

        is_band = (
            "キズ" in title
            or re.search(
                r"^キズ$",
                "\n".join(block[:12]),
                re.M,
            )
        )

        if not is_band:
            continue

        open_idx = next(
            (
                j
                for j, value in enumerate(block[:10])
                if "開場" in value
                and "開演" in value
            ),
            None,
        )

        if open_idx is None:
            start = day
            end = day + timedelta(days=1)
            hours = "未掲載"
        else:
            hours = " ".join(
                block[open_idx + 1:open_idx + 3]
            )
            times = TIME.findall(hours)

            if not times:
                start = day
                end = day + timedelta(days=1)
            else:
                start = datetime(
                    day.year,
                    day.month,
                    day.day,
                    int(times[0][0]),
                    int(times[0][1]),
                    tzinfo=TZ,
                )
                end = start + timedelta(hours=3)

        # 日付の後ろに付く曜日を除去
        location = line[dm.end():].strip(" 　-/")
        location = re.sub(
            r"^\s*[（(][月火水木金土日][）)]\s*",
            "",
            location,
        ).strip()

        key = hashlib.sha256(
            f"{day}|{title}|{location}".encode()
        ).hexdigest()[:20]

        events.append({
            "uid": f"kizu-{key}@live-calendar",
            "title": f'【{artist["name"]}】{title}',
            "start": start,
            "end": end,
            "location": location,
            "description": (
                f"公式情報: {url}\n"
                f"開場/開演: {hours}\n"
                "終了時刻は未発表の場合仮設定"
            ),
            "url": url,
        })

    return events
