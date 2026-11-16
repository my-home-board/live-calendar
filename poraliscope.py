"""The Poraliscope Bitfan SCHEDULEのライブ公演を取得。"""
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo('Asia/Tokyo')
DATE = re.compile(r'(20\d{2})\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})')
TIME = re.compile(r'(?<!\d)([01]?\d|2[0-3]):([0-5]\d)')
EXCLUDE = re.compile(r'トーク|配信|生放送|YouTube|インストア|特典会|サイン会|握手会|ラジオ|ゲスト出演|撮影会|リリースイベント', re.I)
LIVE = re.compile(r'ライブ|LIVE|ワンマン|対バン|出演|OPEN|START|開場|開演|TIGET|チケット', re.I)


def _label(text, label):
    m = re.search(r'〖' + re.escape(label) + r'〗\s*([^\n]+)', text)
    return m.group(1).strip() if m else ''


def fetch_poraliscope(artist):
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    now = datetime.now(TZ).date()
    links = {}
    for page in range(1, 11):
        url = artist['url'] + ('?page=' + str(page) if page > 1 else '')
        resp = session.get(url, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        new = 0
        for a in soup.select('a[href*="/schedules/"]'):
            href = urljoin(url, a.get('href', '')).split('?')[0]
            if re.search(r'/schedules/\d+/?$', href) and href not in links:
                links[href] = a.get_text(' ', strip=True)
                new += 1
        if not new:
            break
    events = []
    for url, listing_title in links.items():
        resp = session.get(url, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        text = soup.get_text('\n', strip=True)
        title_tag = soup.find('h1')
        title = title_tag.get_text(' ', strip=True) if title_tag else listing_title
        if EXCLUDE.search(title):
            continue
        dm = DATE.search(_label(text, '日程') or text)
        if not dm:
            continue
        try:
            day = date(*map(int, dm.groups()))
        except ValueError:
            continue
        if day < now:
            continue
        location = _label(text, '会場')
        event_name = _label(text, '題名') or title
        time_text = _label(text, '時間')
        # ライブと確認できない予定は登録しない（会場名だけでは判定しない）。
        detail = event_name + ' ' + time_text + ' ' + text[:1200]
        if EXCLUDE.search(event_name) or not LIVE.search(detail):
            continue
        # バンドの出演が明示されない予定は安全側で保留。
        if not re.search(r'The\s+Poraliscope|ポラリスコープ', text, re.I):
            continue
        # 開場ではなく開演を優先。出演時刻が明示されている場合は未判定。
        start_match = re.search(r'(?:START|開演)\s*[:：]?\s*(\d{1,2}):([0-5]\d)', time_text, re.I)
        if start_match:
            hh, mm = int(start_match[1]), int(start_match[2])
            start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)
            end = start + timedelta(hours=3)
        else:
            # 開演時刻が未掲載なら終日予定として登録。開場時刻を誤用しない。
            start, end = day, day + timedelta(days=1)
        ident = re.search(r'/schedules/(\d+)', url).group(1)
        events.append({
            'uid': f'poraliscope-{ident}@live-calendar',
            'title': f'【{artist["name"]}】{event_name}',
            'start': start, 'end': end, 'location': location,
            'description': f'公式情報: {url}\n時間: {time_text or "未掲載"}\n終了時刻は仮設定',
            'url': url,
        })
    return events
