#!/usr/bin/env python3
"""
Liczy score dopasowania dla każdej gry w steam-promocje
na podstawie tagów z Stats_tagi (preferencje użytkownika).

Score = suma count z Stats_tagi dla każdego tagu gry.
Wynik trafia do kolumny Score w arkuszu Promocje gier.
"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials

creds = Credentials.from_service_account_info(
    json.loads(os.environ["GOOGLE_CREDENTIALS"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
gc = gspread.authorize(creds)

# ── Wczytaj preferencje z Stats_tagi ──────────────────────────────────────
wish_wb = gc.open_by_key(os.environ["SHEET_ID_WISHLIST"])
stats_ws = wish_wb.worksheet("Stats_tagi")
stats_data = stats_ws.get_all_values()

tag_scores = {}
for row in stats_data[1:]:
    if len(row) >= 2 and row[0].strip() and row[1].strip():
        try:
            tag_scores[row[0].strip().lower()] = int(row[1].strip())
        except ValueError:
            pass

print(f"Załadowano {len(tag_scores)} tagów z preferencjami.")
if not tag_scores:
    print("BŁĄD: Stats_tagi jest pusty — najpierw uruchom steam_stats_tagi.py")
    exit(1)

# ── Wczytaj steam-promocje ─────────────────────────────────────────────────
promo_wb = gc.open_by_key(os.environ["SHEET_ID_PROMOCJE"])
promo_ws = promo_wb.sheet1
promo_data = promo_ws.get_all_values()

try:
    header_row_idx = next(i for i, row in enumerate(promo_data) if "Tagi" in row)
except StopIteration:
    print("BŁĄD: nie znaleziono nagłówka 'Tagi' w arkuszu steam-promocje.")
    exit(1)

header = promo_data[header_row_idx]
data_rows = promo_data[header_row_idx + 1:]
data_start = header_row_idx + 2  # 1-indexed

if "Tagi" not in header:
    print("BŁĄD: brak kolumny 'Tagi' w nagłówku steam-promocje.")
    exit(1)
tagi_col = header.index("Tagi")

# Znajdź lub utwórz kolumnę Score
if "Score" in header:
    score_col_1 = header.index("Score") + 1
else:
    score_col_1 = len(header) + 1
    promo_ws.update_cell(header_row_idx + 1, score_col_1, "Score")

# ── Oblicz score wiersz po wierszu ────────────────────────────────────────
score_updates = []
bold_rows = []   # indeksy wierszy (0-based) z score > 0
nonbold_rows = []
scored = 0

for i, row in enumerate(data_rows):
    if not row or len(row) <= tagi_col:
        continue
    tags_raw = row[tagi_col].strip()
    score = 0
    if tags_raw:
        score = sum(
            tag_scores.get(t.strip().lower(), 0)
            for t in tags_raw.split(",")
            if t.strip()
        )
    score_updates.append({
        "range": gspread.utils.rowcol_to_a1(data_start + i, score_col_1),
        "values": [[score]],
    })
    if score > 1:
        bold_rows.append(header_row_idx + 1 + i)  # 0-indexed sheet row
        scored += 1
    else:
        nonbold_rows.append(header_row_idx + 1 + i)

if score_updates:
    promo_ws.batch_update(score_updates)

# ── Formatowanie kolumny Score + bold/normal dla wierszy ──────────────────
col_0 = score_col_1 - 1
format_requests = [
    {"updateDimensionProperties": {
        "range": {"sheetId": promo_ws.id, "dimension": "COLUMNS",
                  "startIndex": col_0, "endIndex": col_0 + 1},
        "properties": {"pixelSize": 70},
        "fields": "pixelSize",
    }},
    {"repeatCell": {
        "range": {"sheetId": promo_ws.id,
                  "startColumnIndex": col_0, "endColumnIndex": col_0 + 1},
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat(horizontalAlignment)",
    }},
]

# Bold dla wierszy z score > 0
for row_0 in bold_rows:
    format_requests.append({"repeatCell": {
        "range": {"sheetId": promo_ws.id,
                  "startRowIndex": row_0, "endRowIndex": row_0 + 1,
                  "startColumnIndex": 0, "endColumnIndex": score_col_1},
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
        "fields": "userEnteredFormat(textFormat)",
    }})

# Usuń bold dla wierszy bez dopasowania (reset po poprzednim runie)
for row_0 in nonbold_rows:
    format_requests.append({"repeatCell": {
        "range": {"sheetId": promo_ws.id,
                  "startRowIndex": row_0, "endRowIndex": row_0 + 1,
                  "startColumnIndex": 0, "endColumnIndex": score_col_1},
        "cell": {"userEnteredFormat": {"textFormat": {"bold": False}}},
        "fields": "userEnteredFormat(textFormat)",
    }})

promo_wb.batch_update({"requests": format_requests})

print(f"Score zapisane: {scored} gier z dopasowaniem > 0 (łącznie {len(updates)} wierszy).")
