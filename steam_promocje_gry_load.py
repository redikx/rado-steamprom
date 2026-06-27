#!/usr/bin/env python3
"""
Lista WSZYSTKICH gier na Steam ze znizka >= MIN_DISCOUNT -> Google Sheets.

Zrodlo danych: endpoint wyszukiwarki sklepu (NIE newsy).
  https://store.steampowered.com/search/results/?specials=1&infinite=1...
Zwraca stronicowany HTML z wierszami gier; parsujemy znizke, cene, appid, link.
Nie wymaga przegladarki - tylko requests + BeautifulSoup.

WAZNE: endpoint oddaje JSON tylko dla zapytan AJAX, dlatego wysylamy naglowek
X-Requested-With. Bez niego Steam zwraca pelna strone HTML (i json() sie wywala).

Konfiguracja przez zmienne srodowiskowe:
  GOOGLE_CREDENTIALS - JSON konta serwisowego (ten sam co przy kampaniach)
  SHEET_ID           - ID tego samego arkusza
  MIN_DISCOUNT       - prog znizki w %, domyslnie 20
  CC                 - region cenowy, domyslnie DE
  TAGS               - opcjonalnie: ID tagow przez przecinek
  MAX_PRICE          - opcjonalnie: max cena (np. 20)

Tryb lokalny: bez GOOGLE_CREDENTIALS zapisuje steam_specials.csv.
"""

import os
import csv
import json
import re
import time
import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://store.steampowered.com/search/results/"
TAGS_URL = "https://store.steampowered.com/tagdata/populartags/english"
MIN_DISCOUNT = int(os.environ.get("MIN_DISCOUNT", "20"))
CC = os.environ.get("CC", "DE")
TAGS = os.environ.get("TAGS", "")
MAX_PRICE = os.environ.get("MAX_PRICE", "")
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "5000"))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://store.steampowered.com/search/?specials=1",
}


def fetch_tag_names():
    """Pobiera slownik {tag_id: nazwa} ze Steam API (jeden request)."""
    try:
        r = requests.get(TAGS_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return {str(t["tagid"]): t["name"] for t in r.json()}
    except Exception as e:
        print(f"[tagi] Nie udalo sie pobrac nazw tagow: {e}")
        return {}


def parse_review(tooltip):
    """Wyciaga (opis, procent) z tooltipa opinii."""
    if not tooltip:
        return "", ""
    # "Overwhelmingly Positive<br>99% of the 12,340 user reviews..."
    parts = tooltip.split("<br>")
    label = parts[0].strip() if parts else ""
    pct = ""
    if len(parts) > 1:
        m = re.search(r"(\d+)%", parts[1])
        if m:
            pct = int(m.group(1))
    return label, pct


def parse_rows(html, tag_map):
    """Wyciaga gry z fragmentu HTML wyszukiwarki, filtruje po znizce."""
    out = []
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a.search_result_row"):
        appid = a.get("data-ds-appid", "")
        name_el = a.select_one(".title")
        name = name_el.get_text(strip=True) if name_el else ""

        disc_block = a.select_one(".discount_block[data-discount]")
        try:
            discount = int(disc_block["data-discount"]) if disc_block else 0
        except (ValueError, TypeError):
            discount = 0
        if discount < MIN_DISCOUNT:
            continue

        final_el = a.select_one(".discount_final_price")
        final_price = final_el.get_text(strip=True) if final_el else ""
        orig_el = a.select_one(".discount_original_price")
        orig_price = orig_el.get_text(strip=True) if orig_el else ""
        link = a.get("href", "").split("?")[0]

        # tagi
        try:
            tag_ids = json.loads(a.get("data-ds-tagids", "[]"))
            tags_str = ", ".join(
                tag_map[str(tid)] for tid in tag_ids[:4] if str(tid) in tag_map
            )
        except (ValueError, TypeError):
            tags_str = ""

        # data wydania
        released_el = a.select_one(".search_released")
        release_date = ""
        if released_el:
            try:
                release_date = time.strftime("%d.%m.%Y",
                    time.strptime(released_el.get_text(strip=True), "%d %b, %Y"))
            except ValueError:
                release_date = released_el.get_text(strip=True)

        # opinie
        rev_el = a.select_one(".search_review_summary[data-tooltip-html]")
        review_label, review_pct = parse_review(
            rev_el.get("data-tooltip-html", "") if rev_el else ""
        )

        out.append([name, discount, final_price, orig_price, link, tags_str,
                    release_date, review_label, review_pct, appid])
    return out


def fetch_specials(tag_map):
    rows = []
    session = requests.Session()
    session.headers.update(HEADERS)
    start, count = 0, 100

    while True:
        params = {
            "query": "",
            "start": start,
            "count": count,
            "dynamic_data": "",
            "sort_by": "Reviews_DESC",
            "specials": 1,
            "category1": 998,
            "infinite": 1,
            "cc": CC,
            "l": "english",
        }
        if TAGS:
            params["tags"] = TAGS
        if MAX_PRICE:
            params["maxprice"] = MAX_PRICE

        for attempt in range(5):
            r = session.get(SEARCH_URL, params=params, timeout=30)
            if r.status_code in (429, 502, 503, 504):
                retry_after = r.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() \
                    else 10 * (2 ** attempt)
                print(f"[retry] {r.status_code}, czekam {wait}s (proba {attempt+1}/5)...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            break
        else:
            r.raise_for_status()

        try:
            data = r.json()
            total = data.get("total_count", 0)
            html = data.get("results_html", "")
            rows.extend(parse_rows(html, tag_map))
            start += count
            if start >= total or start >= MAX_RESULTS or not html.strip():
                break
            time.sleep(2)
        except ValueError:
            print(f"[diag] status={r.status_code}, brak JSON; "
                  f"poczatek odpowiedzi: {r.text[:120]!r}")
            rows.extend(parse_rows(r.text, tag_map))
            break

    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


def write_to_sheet(rows):
    import datetime as dt
    import gspread

    gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_CREDENTIALS"]))
    sh = gc.open_by_key(os.environ["SHEET_ID"])
    try:
        ws = sh.worksheet("Promocje gier")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Promocje gier", rows=2000, cols=11)

    cest = dt.timezone(dt.timedelta(hours=2))
    stamp = dt.datetime.now(tz=cest).strftime("%Y-%m-%d %H:%M CEST")
    header = ["Nazwa", "Znizka %", "Cena", "Base price", "Link",
              "Tagi", "Released", "Opinie", "% pozytywnych", "AppID"]
    sheet_rows = [
        [f"Ostatnia aktualizacja: {stamp} | prog: {MIN_DISCOUNT}% | region: {CC}",
         "", "", "", "", "", "", "", "", ""],
        header,
    ] + [[r[0], r[1], r[2], r[3], f'=HYPERLINK("{r[4]}";"Link")', r[5], r[6], r[7], r[8], r[9]]
         for r in rows]

    ws.clear()
    ws.update(values=sheet_rows, range_name="A1", value_input_option="USER_ENTERED")

    sh.batch_update({"requests": [
        {"updateSheetProperties": {
            "properties": {"sheetId": ws.id, "index": 0},
            "fields": "index",
        }},
        {"autoResizeDimensions": {"dimensions": {
            "sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1
        }}} if max((len(str(r[0])) for r in rows), default=0) <= 40 else
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 296},
            "fields": "pixelSize",
        }},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 2, "startColumnIndex": 1, "endColumnIndex": 5},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment",
        }},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 2, "startColumnIndex": 9, "endColumnIndex": 10},
            "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat.horizontalAlignment",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 9, "endIndex": 10},
            "properties": {"pixelSize": 104},
            "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 80},
            "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 4},
            "properties": {"pixelSize": 80},
            "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 5},
            "properties": {"pixelSize": 55},
            "fields": "pixelSize",
        }},
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 6, "endIndex": 7},
            "properties": {"pixelSize": 96},
            "fields": "pixelSize",
        }},
        {"autoResizeDimensions": {"dimensions": {
            "sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 5, "endIndex": 6
        }}} if max((len(str(r[5])) for r in rows), default=0) <= 55 else
        {"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS", "startIndex": 5, "endIndex": 6},
            "properties": {"pixelSize": 405},
            "fields": "pixelSize",
        }},
        {"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": 2},
            "cell": {"userEnteredFormat": {
                "horizontalAlignment": "CENTER",
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.678, "green": 0.847, "blue": 0.902},
                "borders": {"bottom": {
                    "style": "SOLID_THICK",
                    "color": {"red": 0.2, "green": 0.2, "blue": 0.2},
                }},
            }},
            "fields": "userEnteredFormat(horizontalAlignment,textFormat,backgroundColor,borders)",
        }},
        {"addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": ws.id, "startRowIndex": 2, "startColumnIndex": 0, "endColumnIndex": 10}],
                "booleanRule": {
                    "condition": {
                        "type": "CUSTOM_FORMULA",
                        "values": [{"userEnteredValue": "=$B3>89"}],
                    },
                    "format": {"backgroundColor": {"red": 1.0, "green": 0.6, "blue": 0.0}},
                },
            },
            "index": 0,
        }},
    ]})

    print(f"Zapisano {len(rows)} gier (>= {MIN_DISCOUNT}%) do zakladki 'Promocje gier'.")


def write_csv(rows):
    with open("steam_specials.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Nazwa", "Znizka %", "Cena", "Base price", "Link",
                    "Tagi", "Released", "Opinie", "% pozytywnych", "AppID"])
        w.writerows(rows)
    print(f"Tryb lokalny: zapisano {len(rows)} gier -> steam_specials.csv")


def main():
    print("Pobieranie nazw tagow Steam...")
    tag_map = fetch_tag_names()
    print(f"Zaladowano {len(tag_map)} tagow.")

    rows = fetch_specials(tag_map)
    print(f"Znaleziono {len(rows)} gier ze znizka >= {MIN_DISCOUNT}%.")
    if not rows:
        print("UWAGA: brak wynikow. Sprawdz diagnostyke wyzej lub parametry.")
    if os.environ.get("GOOGLE_CREDENTIALS") and os.environ.get("SHEET_ID"):
        write_to_sheet(rows)
    else:
        write_csv(rows)


if __name__ == "__main__":
    main()
