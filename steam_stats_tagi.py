#!/usr/bin/env python3
"""
Agreguje tagi z zakładki Dopasowanie i zapisuje statystyki do Stats_tagi.
Każde uruchomienie czyści Stats_tagi i liczy od nowa.
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

wb = gc.open_by_key(os.environ["SHEET_ID_WISHLIST"])
src = wb.worksheet("Dopasowanie")
dst = wb.worksheet("Stats_tagi")

data = src.get_all_values()
if not data or len(data) < 2:
    print("Zakładka Dopasowanie jest pusta lub ma tylko nagłówek.")
    exit()

# Zliczaj tagi wiersz po wierszu
counts = {}
processed = 0
for row in data[1:]:
    name = row[0].strip() if row else ""
    if not name:
        continue
    tags_raw = row[2].strip() if len(row) > 2 else ""
    if not tags_raw:
        continue
    for tag in (t.strip() for t in tags_raw.split(",") if t.strip()):
        counts[tag] = counts.get(tag, 0) + 1
    processed += 1
    print(f"  [{processed}] {name}: {tags_raw[:60]}")

print(f"\nZliczono {len(counts)} unikalnych tagów z {processed} gier.")

# Posortuj malejąco po count
rows_out = sorted(counts.items(), key=lambda x: x[1], reverse=True)

# Wyczyść Stats_tagi i zapisz od nowa
dst.clear()
dst.update(
    values=[["Gatunek", "Count"]] + [[tag, cnt] for tag, cnt in rows_out],
    range_name="A1",
    value_input_option="RAW",
)

# Formatowanie nagłówka: bold + centrowanie
wb.batch_update({"requests": [
    {"repeatCell": {
        "range": {"sheetId": dst.id, "startRowIndex": 0, "endRowIndex": 1},
        "cell": {"userEnteredFormat": {
            "textFormat": {"bold": True},
            "horizontalAlignment": "CENTER",
        }},
        "fields": "userEnteredFormat(textFormat,horizontalAlignment)",
    }},
    {"repeatCell": {
        "range": {"sheetId": dst.id, "startRowIndex": 1,
                  "startColumnIndex": 1, "endColumnIndex": 2},
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat(horizontalAlignment)",
    }},
    {"updateDimensionProperties": {
        "range": {"sheetId": dst.id, "dimension": "COLUMNS",
                  "startIndex": 1, "endIndex": 2},
        "properties": {"pixelSize": 80},
        "fields": "pixelSize",
    }},
]})

print(f"Stats_tagi zaktualizowane: {len(rows_out)} tagów.")
