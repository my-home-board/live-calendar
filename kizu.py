"""キズ公式SCHEDULEからバンド出演ライブを取得。"""
import hashlib
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo('Asia/Tokyo')
DATE = re.compile(r'(20\d{2})年(\d{1,2})月(\d{1,2})日')
TIME = re.compile(r'(?<!\d)([01]?\d|2[0-3]):([0-5]\d)')
EXCLUDE = re.compile(r'インストア|特典会|サイン会|握手会|トーク|配信|生放送|ラジオ|クリニック|撮影会|リリースイベント', re.I)


def fetch_kizu(artist):
    url = artist['url']
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    # 公式ページは各公演のタイトル→公演日→[開場 / 開演]の順で表示される。
    # HTMLの見出し構造に依存せず、テキストの順序で切り分ける。
    lines = [re.sub(r'\s+', ' ', s).strip() for s in soup.get_text('\n', strip=True).splitlines()]
    lines = [s for s in lines if s]
    now = datetime.now(TZ).date()
    events = []
    for i, line in enumerate(lines):
        dm = DATE.search(line)
        if not dm or i == 0:
            continue
        try:
            day = date(*map(int, dm.groups()))
        except ValueError:
            continue
        if day < now:
            continue
        # 日付直前の見出しをタイトルとして扱う。
        title = lines[i-1]
        if not title or DATE.search(title) or EXCLUDE.search(title):
            continue
        # 次の公演日までの範囲（ただしチケット販売の日付は区切りにしない）。
        # 最初の出演・開場情報の周辺のみを検査する。
        block = lines[i+1:i+25]
        first = ' '.join(block[:12])
        # 個人出演・トーク等を除外。キズ本体のライブかどうか慎重に判定。
        if EXCLUDE.search(title + ' ' + first[:100]):
            continue
        is_band = ('キズ' in title or re.search(r'^キズ$', '\n'.join(block[:12]), re.M))
        if not is_band:
            continue
        open_idx = next((j for j, v in enumerate(block[:10]) if '開場' in v and '開演' in v), None)
        if open_idx is None:
            # 時間未掲載の公演は終日予定で記録
            start, end = day, day + timedelta(days=1)
            hours = '未掲載'
        else:
            hours = ' '.join(block[open_idx+1:open_idx+3])
            times = TIME.findall(hours)
            if not times:
                start, end = day, day + timedelta(days=1)
            else:
                # 開場時刻を起点とし、3時間の仮枠
                start = datetime(day.year, day.month, day.day, int(times[0][0]), int(times[0][1]), tzinfo=TZ)
                end = start + timedelta(hours=3)
        location = line[dm.end():].strip(' 　-/')
        key = hashlib.sha256(f'{day}|{title}|{location}'.encode()).hexdigest()[:20]
        events.append({
            'uid': f'kizu-{key}@live-calendar',
            'title': f'【{artist["name"]}】{title}',
            'start': start, 'end': end, 'location': location,
            'description': f'公式情報: {url}\n開場/開演: {hours}\n終了時刻は未発表の場合仮設定',
            'url': url,
        })
    return events
