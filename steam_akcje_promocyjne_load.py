#!/usr/bin/env python3
"""
Scraper kampanii wyprzedazowych Steam -> Google Sheets.

Co robi:
  1. Otwiera /news/collection/sales/ w prawdziwej przegladarce (Playwright)
     i przechwytuje odpowiedz JSON z wewnetrznego endpointu eventow Steama.
  2. Wyciaga: nazwa kampanii, czas zakonczenia, bezposredni link.
  3. Wpisuje wynik do arkusza Google (zakladka 'Steam Sales').

Uwierzytelnianie do Google:
  Przez konto serwisowe. JSON klucza podajemy w zmiennej srodowiskowej
  GOOGLE_CREDENTIALS (cala zawartosc pliku), a ID arkusza w SHEET_ID.
  (W GitHub Actions to sekrety repozytorium.)

Tryb lokalny (test):
  Jesli brak GOOGLE_CREDENTIALS, skrypt zapisze tylko steam_sales.csv lokalnie.
"""

import os
import csv
import json
import re
import datetime as dt
from playwright.sync_api import sync_playwright

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002300-\U000027BF\U0000FE00-\U0000FE0F\U0001F1E0-\U0001F1FF]+",
    flags=re.UNICODE
)

def strip_emoji(text):
    return re.sub(r"\s+", " ", EMOJI_RE.sub("", text)).strip()

URL = "https://store.steampowered.com/news/collection/sales/"

collected = []


def handle_response(resp):
    url = resp.url
    if "event" not in url.lower():
        return
    if "json" not in resp.headers.get("content-type", "").lower():
        return
    try:
        collected.append(resp.json())
    except Exception:
        pass


def walk(obj, out):
    if isinstance(obj, dict):
        has_name = "event_name" in obj or "announcement_body" in obj
        has_time = "rtime32_end_time" in obj or "rtime32_start_time" in obj
        if has_name and has_time:
            out.append(obj)
        for v in obj.values():
            walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, out)


def to_local_iso(ts):
    try:
        ts = int(ts)
        if ts <= 0:
            return ""
        cest = dt.timezone(dt.timedelta(hours=2))
        return (
            dt.datetime.fromtimestamp(ts, dt.timezone.utc)
            .astimezone(cest)
            .strftime("%Y-%m-%d %H:%M CEST")
        )
    except Exception:
        return ""


def build_link(e):
    body = e.get("announcement_body") or {}
    gid = str(e.get("gid") or body.get("gid") or "")
    appid = e.get("appid")
    appids = e.get("appids")
    if not appid and isinstance(appids, list) and appids:
        appid = appids[0]
    clan = e.get("clan_steamid") or e.get("clanid")
    if gid and appid:
        return f"https://store.steampowered.com/news/app/{appid}/view/{gid}"
    if gid and clan:
        return f"https://steamcommunity.com/gid/{clan}/announcements/detail/{gid}"
    if gid:
        return f"https://store.steampowered.com/news/posts/{gid}"
    return ""


def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="en-US")
        page = ctx.new_page()
        page.on("response", handle_response)
        page.goto(URL, wait_until="networkidle", timeout=60000)
        for _ in range(8):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)
        browser.close()

    events = []
    for blob in collected:
        walk(blob, events)

    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    rows, seen = [], set()
    for e in events:
        body = e.get("announcement_body") or {}
        name = strip_emoji(e.get("event_name") or body.get("headline") or "")
        end_unix = int(e.get("rtime32_end_time") or 0)
        # pomijamy promocje, ktore juz sie zakonczyly
        if 0 < end_unix < now:
            continue
        gid = str(e.get("gid") or body.get("gid") or "")
        key = (name, gid)
        if key in seen:
            continue
        seen.add(key)
        rows.append([name, to_local_iso(end_unix), end_unix, build_link(e)])

    rows.sort(key=lambda r: (r[2] == 0, r[2]))
    return [[r[0], r[1], f'=HYPERLINK("{r[3]}","Link")' if r[3] else ""] for r in rows]


def write_to_sheet(rows):
    import gspread

    creds = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    sheet_id = os.environ["SHEET_ID_SALES"]
    gc = gspread.service_account_from_dict(creds)
    sh = gc.open_by_key(sheet_id)

    try:
        ws = sh.worksheet("Steam Sales")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Steam Sales", rows=200, cols=6)

    cest = dt.timezone(dt.timedelta(hours=2))
    stamp = dt.datetime.now(tz=cest).strftime("%Y-%m-%d %H:%M CEST")
    header = ["Nazwa kampanii", "Czas zakonczenia", "Link"]
    data = [[f"Ostatnia aktualizacja: {stamp}", "", ""], header] + rows

    ws.clear()
    ws.update(values=data, range_name="A1", value_input_option="USER_ENTERED")

    max_len = max((len(r[0]) for r in rows if r), default=20)
    col_a_px = min(max_len, 50) * 7 + 20
    col_c_px = 8 * 7 + 20
    sh.batch_update({"requests": [
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": col_a_px},
            "fields": "pixelSize"
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
            "properties": {"pixelSize": col_c_px},
            "fields": "pixelSize"
        }},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startColumnIndex": 2, "endColumnIndex": 3},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment"
        }},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": 2},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True},
                "horizontalAlignment": "CENTER"
            }},
            "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.horizontalAlignment"
        }}
    ]})

    print(f"Zapisano {len(rows)} kampanii do arkusza (zakladka 'Steam Sales').")


def write_csv(rows):
    with open("steam_sales.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Nazwa kampanii", "Czas zakonczenia", "Link"])
        w.writerows(rows)
    print(f"Tryb lokalny: zapisano {len(rows)} kampanii -> steam_sales.csv")


def main():
    rows = scrape()
    if not rows:
        print("UWAGA: nie znaleziono zadnych kampanii. Sprawdz strukture odpowiedzi Steama.")
    if os.environ.get("GOOGLE_CREDENTIALS") and os.environ.get("SHEET_ID_SALES"):
        write_to_sheet(rows)
    else:
        write_csv(rows)


if __name__ == "__main__":
    main()
