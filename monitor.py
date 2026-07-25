"""
幕張ベイパーク 共用施設(ビューラウンジ&ゲスト)空き状況監視スクリプト
--------------------------------------------------------------------
毎週土日の空き状況をチェックし、「予約不可/予約済み」から「予約可能」に
変化した日をメールで通知します。
セレクタはChrome経由でログイン状態を実際に確認して取得したものです。

■ 使い方
1. pip install -r requirements.txt
2. playwright install chromium
3. 環境変数を設定(README参照)
4. 一度 HEADLESS=false で実行して動作確認
5. 問題なければ GitHub Actions か cron/タスクスケジューラで定期実行

■ この施設の予約システムの仕様(確認済み)
- カレンダーは月表示で、日付ごとにCSSクラス(available系/reserved/unavailable)
  で状態が分かる。個別の日付をクリックする必要はない。
- 「次月へ」ボタン(id="after_month")を押しても、予約枠が開放されていない
  先の月には進まない(この施設は直近2ヶ月分のみ開放される仕様だった)。
  そのため予約枠が開いている範囲は自動的に巡回し尽くす形になっている。
"""

import os
import json
import smtplib
import datetime
from email.mime.text import MIMEText
from pathlib import Path

from playwright.sync_api import sync_playwright

# ============ 設定 ============
LOGIN_URL = "https://makuhari.mwps.jp/login"
FACILITY_URL = "https://makuhari.mwps.jp/reserve/register/12698"

USER_ID = os.environ["MWPS_USER_ID"]
PASSWORD = os.environ["MWPS_PASSWORD"]

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]          # 送信元Gmailアドレス
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]  # Googleアプリパスワード(通常のパスワード不可)
NOTIFY_TO = os.environ.get("NOTIFY_TO_EMAIL", GMAIL_ADDRESS)  # 通知先(未指定なら自分宛)

WEEKS_AHEAD = int(os.environ.get("WEEKS_AHEAD", "10"))  # 何週間先まで見るか
HEADLESS = os.environ.get("HEADLESS", "true").lower() != "false"

STATE_FILE = Path(__file__).parent / "state.json"

# 空き状況を示すCSSクラス(施設ページの凡例より)。
# 「予約可能」系のいずれかがあれば空きありと判定する。
AVAILABLE_CLASSES = ["available", "available-lottery", "available-busy"]
UNAVAILABLE_CLASSES = ["reserved", "unavailable"]


def get_target_dates():
    """今日から WEEKS_AHEAD 週間分の、直近の土曜・日曜日リストを返す"""
    today = datetime.date.today()
    dates = []
    d = today
    end = today + datetime.timedelta(weeks=WEEKS_AHEAD)
    while d <= end:
        if d.weekday() in (5, 6):  # 5=土, 6=日
            dates.append(d)
        d += datetime.timedelta(days=1)
    return dates


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def send_email(newly_available: list[str]):
    if not newly_available:
        return
    body_lines = ["以下の日程で空きが出ました:\n"]
    body_lines += [f"・{d}" for d in newly_available]
    body_lines.append(f"\n予約ページ: {FACILITY_URL}")
    body = "\n".join(body_lines)

    msg = MIMEText(body)
    msg["Subject"] = f"【空き通知】ビューラウンジ&ゲスト 空きあり ({len(newly_available)}件)"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = NOTIFY_TO

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [NOTIFY_TO], msg.as_string())
    print(f"通知メール送信: {len(newly_available)}件")


def login(page):
    page.goto(LOGIN_URL)
    page.fill('input[name="email"]', USER_ID)
    page.fill('input[name="password"]', PASSWORD)
    page.get_by_role("button", name="ログイン").click()
    page.wait_for_load_state("networkidle")


def read_month_grid(page) -> tuple[str, dict[int, str]]:
    """
    現在#calendar_areaに表示されている月のヘッダー("YYYY-M")と、
    日付->状態("available"/"unavailable"/"reserved"等) の辞書を返す。
    """
    header = page.locator("#calendar_area span").first.inner_text()
    cells = page.locator("#calendar_area td")
    count = cells.count()
    day_status = {}
    for i in range(count):
        cell = cells.nth(i)
        text = cell.inner_text().strip()
        if not text or not text.isdigit():
            continue  # 前後月の空白セル
        cls = (cell.get_attribute("class") or "").strip()
        day_status[int(text)] = cls
    return header, day_status


def classify(cls: str) -> str:
    tokens = cls.split()
    for c in AVAILABLE_CLASSES:
        if c in tokens:
            return "available"
    for c in UNAVAILABLE_CLASSES:
        if c in tokens:
            return "unavailable"
    return "unknown"


def collect_all_status(page) -> dict[str, str]:
    """
    施設ページを開き、「次月へ」を押しながら開放されている全ての月を巡回し、
    date(ISO文字列) -> "available"/"unavailable"/"unknown" の辞書を返す。
    予約枠が開放されていない先の月に到達すると自動的に停止する。
    """
    page.goto(FACILITY_URL)
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#calendar_area td")

    result = {}
    seen_headers = set()

    while True:
        header, day_status = read_month_grid(page)
        if header in seen_headers:
            # 「次月へ」を押しても月が変わらない = これ以上先は開放されていない
            break
        seen_headers.add(header)

        year_str, month_str = header.split("-")
        year, month = int(year_str), int(month_str)

        for day, cls in day_status.items():
            try:
                d = datetime.date(year, month, day)
            except ValueError:
                continue
            result[d.isoformat()] = classify(cls)

        # 十分先まで見たら終了(念のための上限)
        if len(seen_headers) >= 6:
            break

        page.click("#after_month")
        page.wait_for_timeout(1000)

    return result


def main():
    state = load_state()
    newly_available = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        login(page)
        all_status = collect_all_status(page)
        browser.close()

    target_dates = {d.isoformat() for d in get_target_dates()}  # 土日のみ

    for date_key, status in all_status.items():
        if date_key not in target_dates:
            continue  # 平日は対象外

        prev_status = state.get(date_key)
        print(f"{date_key}: {status} (前回: {prev_status})")

        if status == "available" and prev_status != "available":
            newly_available.append(date_key)

        state[date_key] = status

    save_state(state)
    send_email(newly_available)


if __name__ == "__main__":
    main()
