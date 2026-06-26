import os
import re
import json
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from difflib import SequenceMatcher

STEAM_API_KEY = os.environ['STEAM_API_KEY']
STEAM_ID = os.environ['STEAM_ID']
GOOGLE_CREDENTIALS = os.environ['GOOGLE_CREDENTIALS']
SHEET_ID_LIBRARY = os.environ['SHEET_ID_LIBRARY']


def normalize(name):
    name = name.lower()
    name = re.sub(r'[®™©]', '', name)
    for pat in [
        r'\s*[-–]\s*complete edition', r'\s*complete edition',
        r'\s*[-–]\s*definitive edition', r'\s*definitive edition',
        r'\s*[-–]\s*deluxe edition', r'\s*deluxe edition',
        r'\s*[-–]\s*game of the year edition', r'\s*goty',
        r'\s*[-–]\s*standard edition', r'\s*standard edition',
        r'\s*\(.*?\)',
    ]:
        name = re.sub(pat, '', name, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', name).strip()


def similarity(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def get_owned_games():
    url = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
    params = {
        'key': STEAM_API_KEY,
        'steamid': STEAM_ID,
        'include_appinfo': 1,
        'include_played_free_games': 1,
        'format': 'json'
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    games = resp.json().get('response', {}).get('games', [])
    return {g['name']: g['appid'] for g in games}


def search_steam_store(name):
    url = "https://store.steampowered.com/api/storesearch/"
    try:
        resp = requests.get(url, params={'term': name, 'cc': 'PL', 'l': 'polish'}, timeout=15)
        resp.raise_for_status()
        items = resp.json().get('items', [])
        if items:
            return items[0]['id']
    except Exception:
        pass
    return None


creds = Credentials.from_service_account_info(
    json.loads(GOOGLE_CREDENTIALS),
    scopes=['https://www.googleapis.com/auth/spreadsheets']
)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID_LIBRARY).sheet1

data = sheet.get_all_values()
if not data:
    print("Arkusz jest pusty.")
    exit()

header = data[0]

if 'AppID' not in header:
    appid_col_idx = len(header) + 1
    sheet.update_cell(1, appid_col_idx, 'AppID')
    header.append('AppID')
else:
    appid_col_idx = header.index('AppID') + 1

NAME_COL = 1  # kolumna B (0-based)

print("Pobieranie listy gier ze Steam API...")
steam_games = get_owned_games()
print(f"Znaleziono {len(steam_games)} pozycji w bibliotece Steam.\n")

batch_updates = []
matched = []
unmatched = []

for row_idx, row in enumerate(data[1:], start=2):
    if not row or len(row) <= NAME_COL or not row[NAME_COL].strip():
        continue

    # pomiń jeśli AppID już wpisane
    if len(row) >= appid_col_idx and row[appid_col_idx - 1].strip():
        continue

    raw_name = row[NAME_COL].strip()

    # pomiń pakiety promocyjne — nie mają sensu jako AppID
    if 'free promotional package' in raw_name.lower():
        unmatched.append((row_idx, raw_name, 'POMINIĘTO — pakiet promocyjny'))
        continue

    # usuń artefakt "Usuń" z polskiego Steam
    clean_name = re.sub(r'^Usuń\s*', '', raw_name).strip()

    # 1. dokładne dopasowanie
    if clean_name in steam_games:
        appid = steam_games[clean_name]
        batch_updates.append((row_idx, appid_col_idx, appid))
        matched.append((raw_name, appid, 'EXACT'))
        continue

    # 2. fuzzy match
    best_name, best_appid, best_ratio = None, None, 0.0
    for sname, appid in steam_games.items():
        r = similarity(clean_name, sname)
        if r > best_ratio:
            best_ratio, best_name, best_appid = r, sname, appid

    if best_ratio >= 0.80:
        batch_updates.append((row_idx, appid_col_idx, best_appid))
        matched.append((raw_name, best_appid, f'FUZZY → "{best_name}" ({best_ratio:.0%})'))
        continue

    # 3. fallback: szukaj w Steam Store po polskiej nazwie
    time.sleep(0.5)
    appid = search_steam_store(clean_name)
    if appid:
        batch_updates.append((row_idx, appid_col_idx, appid))
        matched.append((raw_name, appid, 'STORE_SEARCH'))
        continue

    unmatched.append((row_idx, raw_name, f'BRAK DOPASOWANIA (best: "{best_name}", {best_ratio:.0%})'))

# zapis wsadowy do arkusza
if batch_updates:
    sheet.batch_update([{
        'range': gspread.utils.rowcol_to_a1(r, c),
        'values': [[v]]
    } for r, c, v in batch_updates])

# raport
print(f"{'='*60}")
print(f"RAPORT: {len(matched)} dopasowanych, {len(unmatched)} wymaga uwagi")
print(f"{'='*60}")

print(f"\n✓ DOPASOWANE ({len(matched)}):")
for name, appid, method in matched:
    print(f"  [{appid}] {name}  ({method})")

print(f"\n✗ WYMAGAJĄ RĘCZNEJ KOREKTY ({len(unmatched)}):")
for row_idx, name, reason in unmatched:
    print(f"  Wiersz {row_idx}: {name}")
    print(f"           → {reason}")
