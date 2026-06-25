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
  CC                 - region cenowy, domyslnie PL
  TAGS               - opcjonalnie: ID tagow przez przecinek
  MAX_PRICE          - opcjonalnie: max cena (np. 20)

Tryb lokalny: bez GOOGLE_CREDENTIALS zapisuje steam_specials.csv.
"""

import os
import csv
import time
import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://store.steampowered.com/search/results/"
MIN_DISCOUNT = int(os.environ.get("MIN_DISCOUNT", "20"))
CC = os.environ.get("CC", "PL")
TAGS = os.environ.get("TAGS", "")
MAX_PRICE = os.environ.get("MAX_PRICE", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://store.steampowered.com/search/?specials=1",
}


def parse_rows(html):
    """Wyciaga gry z fragmentu HTML wyszukiwarki, filtruje po znizce."""
    out = []
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("a.search_result_row"):
        appid = a.get("data-ds-appid", "")
        name_el = a.select_one(".title")
        name = name_el.get_text(strip=True) if name_el else ""

        disc_el = a.select_one(".search_discount span")
        disc_txt = disc_el.get_text(strip=True) if disc_el else ""  # np. "-50%"
        try:
            discount = int(disc_txt.replace("-", "").replace("%", ""))
        except ValueError:
            discount = 0
        if discount < MIN_DISCOUNT:
            continue

        final_el = a.select_one(".discount_final_price")
        final_price = final_el.get_text(strip=True) if final_el else ""
        orig_el = a.select_one(".discount_original_price")
        orig_price = orig_el.get_text(strip=True) if orig_el else ""
        link = a.get("href", "").split("?")[0]

        out.append([name, discount, final_price, orig_price, appid, link])
    return out


def fetch_specials():
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
            "category1": 998,   # tylko gry; usun, jesli chcesz tez DLC/soundtracki
            "infinite": 1,
            "cc": CC,
            "l": "english",
        }
        if TAGS:
            params["tags"] = TAGS
        if MAX_PRICE:
            params["maxprice"] = MAX_PRICE

        r = session.get(SEARCH_URL, params=params, timeout=30)
        r.raise_for_status()

        # Probujemy JSON (poprawna sciezka). Jak sie nie uda - fallback na HTML.
        try:
            data = r.json()
            total = data.get("total_count", 0)
            html = data.get("results_html", "")
            rows.extend(parse_rows(html))
            start += count
            if start >= total or not html.strip():
                break
            time.sleep(0.5)
        except ValueError:
            print(f"[diag] status={r.status_code}, brak JSON; "
                  f"poczatek odpowiedzi: {r.text[:120]!r}")
            rows.extend(parse_rows(r.text))
            break

    rows.sort(key=lambda r: r[1], reverse=True)
    return rows


def write_to_sheet(rows):
    import json
    import datetime as dt
    import gspread

    gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_CREDENTIALS"]))
    sh = gc.open_by_key(os.environ["SHEET_ID"])
    try:
        ws = sh.worksheet("Promocje gier")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Promocje gier", rows=2000, cols=8)

    stamp = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    header = ["Nazwa", "Znizka %", "Cena", "Cena pierwotna", "AppID", "Link"]
    data = [
        [f"Ostatnia aktualizacja: {stamp} | prog: {MIN_DISCOUNT}% | region: {CC}", "", "", "", "", ""],
        header,
    ] + rows

    ws.clear()
    ws.update(values=data, range_name="A1")
    print(f"Zapisano {len(rows)} gier (>= {MIN_DISCOUNT}%) do zakladki 'Promocje gier'.")


def write_csv(rows):
    with open("steam_specials.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Nazwa", "Znizka %", "Cena", "Cena pierwotna", "AppID", "Link"])
        w.writerows(rows)
    print(f"Tryb lokalny: zapisano {len(rows)} gier -> steam_specials.csv")


def main():
    rows = fetch_specials()
    print(f"Znaleziono {len(rows)} gier ze znizka >= {MIN_DISCOUNT}%.")
    if not rows:
        print("UWAGA: brak wynikow. Sprawdz diagnostyke wyzej lub parametry.")
    if os.environ.get("GOOGLE_CREDENTIALS") and os.environ.get("SHEET_ID"):
        write_to_sheet(rows)
    else:
        write_csv(rows)


if __name__ == "__main__":
    main()