#!/usr/bin/env python3
"""
Dopasowanie tag enricher:
- Czyta zakładkę "Dopasowanie" z SHEET_ID_WISHLIST
- Dla gier bez AppID: szuka po nazwie w Steam search API
- Pobiera community tags ze strony gry
- Zapisuje: AppID -> kolumna B, Tagi -> kolumna C
- Pomija wiersze gdzie AppID już jest (nie nadpisuje)
"""

import os
import json
import time
import re
import requests
import gspread
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials

SHEET_ID_WISHLIST = os.environ["SHEET_ID_WISHLIST"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "birthtime=-568022400; lastagecheckage=1-January-1950; mature_content=1",
}

creds = Credentials.from_service_account_info(
    json.loads(os.environ["GOOGLE_CREDENTIALS"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
gc = gspread.authorize(creds)


def clean_name(name):
    """Usuwa znaki specjalne i sufiksy edycji dla lepszego wyszukiwania."""
    name = re.sub(r"[™®©]", "", name)
    name = re.sub(
        r"\s*[-–]\s*(Standard|Complete|Deluxe|Ultimate|GOTY|Game of the Year"
        r"|Early Access|Supporter Pack|DLC|Season Pass).*$",
        "", name, flags=re.IGNORECASE,
    )
    return name.strip()


def search_appid(name):
    clean = clean_name(name)
    r = requests.get(
        "https://store.steampowered.com/search/suggest",
        params={"term": clean, "f": "games", "cc": "DE", "l": "english"},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    clean_lower = clean.lower()

    for item in soup.select("a"):
        appid = item.get("data-ds-appid", "")
        title_el = item.select_one(".match_name")
        if not appid or not title_el:
            continue
        found = clean_name(title_el.get_text(strip=True)).lower()
        if found == clean_lower:
            return appid

    # fallback: pierwszy wynik
    first = soup.select_one("a[data-ds-appid]")
    if first:
        appid = first.get("data-ds-appid", "")
        title = first.select_one(".match_name")
        print(f"    [fallback] '{clean}' -> '{title.get_text(strip=True) if title else '?'}' ({appid})")
        return appid
    return ""


def get_tags(appid):
    r = requests.get(
        f"https://store.steampowered.com/app/{appid}/",
        headers=HEADERS,
        timeout=15,
    )
    soup = BeautifulSoup(r.text, "html.parser")
    tags = [t.get_text(strip=True) for t in soup.select("a.app_tag") if t.get_text(strip=True)]
    return ", ".join(tags[:10])


# ── Otwórz arkusz ──────────────────────────────────────────────────────────
wb = gc.open_by_key(SHEET_ID_WISHLIST)
ws = wb.worksheet("Dopasowanie")
data = ws.get_all_values()

if not data:
    print("Zakładka Dopasowanie jest pusta.")
    exit()

# Ustaw nagłówki jeśli brak
header = data[0] if data else []
if len(header) < 1 or header[0] != "Gra":
    ws.update_cell(1, 1, "Gra")
if len(header) < 2 or header[1] != "AppID":
    ws.update_cell(1, 2, "AppID")
if len(header) < 3 or header[2] != "Tagi":
    ws.update_cell(1, 3, "Tagi")

# ── Przetwarzaj gry ────────────────────────────────────────────────────────
appid_updates = []
tag_updates   = []

for i, row in enumerate(data[1:], start=2):
    name = row[0].strip() if row else ""
    if not name:
        continue

    appid = row[1].strip() if len(row) > 1 else ""

    if not appid:
        appid = search_appid(name)
        if appid:
            appid_updates.append({"range": f"B{i}", "values": [[appid]]})
            print(f"  [{i}] {name} -> AppID {appid}")
        else:
            print(f"  [{i}] {name} -> nie znaleziono AppID")
        time.sleep(1)
    else:
        print(f"  [{i}] {name}: AppID={appid} (już istnieje)")

    if appid:
        tags = get_tags(appid)
        tag_updates.append({"range": f"C{i}", "values": [[tags]]})
        print(f"       Tagi: {tags[:80]}{'...' if len(tags) > 80 else ''}")
        time.sleep(1)

if appid_updates:
    ws.batch_update(appid_updates)
if tag_updates:
    ws.batch_update(tag_updates)

print(f"\nGotowe: zaktualizowano {len(tag_updates)} gier w zakładce Dopasowanie.")
