import os
import json
import time
import requests
import gspread
from google.oauth2.service_account import Credentials

GOOGLE_CREDENTIALS = os.environ['GOOGLE_CREDENTIALS']
SHEET_ID_PROMOCJE  = os.environ['SHEET_ID_PROMOCJE']
SHEET_ID_WISHLIST  = os.environ['SHEET_ID_WISHLIST']
MIN_DISCOUNT = 85

DECK_MAP = {0: 'U', 1: 'N', 2: 'P', 3: 'V'}

# cookie omija age-gate Steama
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Cookie": "birthtime=-568022400; lastagecheckage=1-January-1950; mature_content=1"
}

creds = Credentials.from_service_account_info(
    json.loads(GOOGLE_CREDENTIALS),
    scopes=['https://www.googleapis.com/auth/spreadsheets']
)
gc = gspread.authorize(creds)


_debug_done = False

def get_deck(appid):
    global _debug_done
    try:
        r = requests.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "l": "english"},
            headers=HEADERS,
            timeout=15
        )
        r.raise_for_status()
        app = r.json().get(str(appid), {})
        if not app.get('success'):
            return 'U'
        data = app.get('data') or {}
        if not isinstance(data, dict):
            return 'U'
        deck = data.get('steam_deck_compatibility') or {}
        if isinstance(deck, list):
            deck = deck[0] if deck else {}
        if not isinstance(deck, dict):
            return 'U'
        if not _debug_done:
            print(f"  DEBUG deck fields: {deck}")
            _debug_done = True
        category = deck.get('category', 0)
        return DECK_MAP.get(category, 'U')
    except Exception as e:
        print(f"  Błąd API dla {appid}: {e}")
        return 'U'


# ── Wishlist: Szukane ──────────────────────────────────────────────────────
wish_wb = gc.open_by_key(SHEET_ID_WISHLIST)
wish_ws = wish_wb.sheet1
wish_data = wish_ws.get_all_values()

szukane_header = wish_data[0]
appid_wish_col_0 = szukane_header.index('AppID')  # 0-indexed
deck_wish_col_1  = appid_wish_col_0 + 2            # 1-indexed (następna kolumna)

# Szukane = wiersze do pierwszego pustego wiersza po nagłówku
wish_rows = []
for i, row in enumerate(wish_data[1:], start=2):
    if not any(cell.strip() for cell in row):
        break
    appid = row[appid_wish_col_0].strip() if len(row) > appid_wish_col_0 else ''
    if appid:
        wish_rows.append((i, appid))

print(f"Wishlist Szukane: {len(wish_rows)} gier z AppID.")

deck_header_exists = (
    len(szukane_header) > appid_wish_col_0 + 1 and
    szukane_header[appid_wish_col_0 + 1] == 'DECK'
)
if not deck_header_exists:
    wish_ws.update_cell(1, deck_wish_col_1, 'DECK')


# ── Steam-promocje ─────────────────────────────────────────────────────────
promo_wb = gc.open_by_key(SHEET_ID_PROMOCJE)
promo_ws = promo_wb.sheet1
promo_data = promo_ws.get_all_values()

header_row_idx = next(i for i, row in enumerate(promo_data) if 'AppID' in row)
promo_header   = promo_data[header_row_idx]
data_rows      = promo_data[header_row_idx + 1:]
data_start_row = header_row_idx + 2  # 1-indexed

appid_col  = promo_header.index('AppID')
znizka_col = promo_header.index('Znizka %')
have_col   = promo_header.index('HAVE')

if 'DECK' in promo_header:
    deck_promo_col_1 = promo_header.index('DECK') + 1
else:
    deck_promo_col_1 = len(promo_header) + 1
    promo_ws.resize(cols=deck_promo_col_1)
    promo_ws.update_cell(header_row_idx + 1, deck_promo_col_1, 'DECK')

# Filtruj: HAVE=N, Znizka >= MIN_DISCOUNT
promo_candidates = []
for i, row in enumerate(data_rows):
    if not row or len(row) <= have_col:
        continue
    have = row[have_col].strip() if len(row) > have_col else ''
    if have != 'N':
        continue
    try:
        znizka = int(row[znizka_col].strip()) if len(row) > znizka_col else 0
    except ValueError:
        continue
    if znizka < MIN_DISCOUNT:
        continue
    appid_raw = row[appid_col].strip() if len(row) > appid_col else ''
    if not appid_raw:
        continue
    appid = appid_raw.split(',')[0].strip()  # dla bundli: pierwszy AppID
    promo_candidates.append((data_start_row + i, appid))

print(f"Steam-promocje: {len(promo_candidates)} gier (HAVE=N, ≥{MIN_DISCOUNT}% zniżki).")


# ── Sprawdź Deck compatibility ─────────────────────────────────────────────
wish_updates = []
print(f"\nWishlist ({len(wish_rows)} gier):")
for row_idx, appid in wish_rows:
    result = get_deck(appid)
    wish_updates.append({
        'range': gspread.utils.rowcol_to_a1(row_idx, deck_wish_col_1),
        'values': [[result]]
    })
    print(f"  [{appid}] → {result}")
    time.sleep(0.5)

if wish_updates:
    wish_ws.batch_update(wish_updates)

promo_updates = []
print(f"\nSteam-promocje ({len(promo_candidates)} gier):")
for row_idx, appid in promo_candidates:
    result = get_deck(appid)
    promo_updates.append({
        'range': gspread.utils.rowcol_to_a1(row_idx, deck_promo_col_1),
        'values': [[result]]
    })
    print(f"  [{appid}] → {result}")
    time.sleep(0.5)

if promo_updates:
    promo_ws.batch_update(promo_updates)


# ── Formatowanie DECK w Steam-promocje ─────────────────────────────────────
col_0 = deck_promo_col_1 - 1
promo_ws.spreadsheet.batch_update({"requests": [
    {"updateDimensionProperties": {
        "range": {"sheetId": promo_ws.id, "dimension": "COLUMNS",
                  "startIndex": col_0, "endIndex": col_0 + 1},
        "properties": {"pixelSize": 6 * 7 + 20},
        "fields": "pixelSize"
    }},
    {"repeatCell": {
        "range": {"sheetId": promo_ws.id,
                  "startColumnIndex": col_0, "endColumnIndex": col_0 + 1},
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.horizontalAlignment"
    }}
]})

counts = {}
for u in promo_updates:
    v = u['values'][0][0]
    counts[v] = counts.get(v, 0) + 1
print(f"\nRaport Steam-promocje: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
