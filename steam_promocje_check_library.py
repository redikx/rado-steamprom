import os
import json
import gspread
from google.oauth2.service_account import Credentials

GOOGLE_CREDENTIALS = os.environ['GOOGLE_CREDENTIALS']
SHEET_ID_PROMOCJE = os.environ['SHEET_ID_PROMOCJE']
SHEET_ID_LIBRARY = os.environ['SHEET_ID_LIBRARY']

creds = Credentials.from_service_account_info(
    json.loads(GOOGLE_CREDENTIALS),
    scopes=['https://www.googleapis.com/auth/spreadsheets']
)
gc = gspread.authorize(creds)

# ── Biblioteka: zbierz AppID ────────────────────────────────────────────────
library_sheet = gc.open_by_key(SHEET_ID_LIBRARY).sheet1
library_data = library_sheet.get_all_values()
lib_header = library_data[0]
appid_lib_col = lib_header.index('AppID')

library_appids = set()
for row in library_data[1:]:
    if len(row) > appid_lib_col and row[appid_lib_col].strip():
        library_appids.add(row[appid_lib_col].strip())

print(f"Biblioteka: {len(library_appids)} gier z AppID.")

# ── Steam-promocje: znajdź nagłówek dynamicznie ────────────────────────────
promo_sheet = gc.open_by_key(SHEET_ID_PROMOCJE).sheet1
promo_data = promo_sheet.get_all_values()

header_row_idx = next(i for i, row in enumerate(promo_data) if 'AppID' in row)
promo_header = promo_data[header_row_idx]
data_rows = promo_data[header_row_idx + 1:]
data_start_row = header_row_idx + 2  # 1-indexed w arkuszu

appid_promo_col = promo_header.index('AppID')

# znajdź lub utwórz kolumnę IF_IN_LIBRARY
if 'IF_IN_LIBRARY' in promo_header:
    lib_col_idx = promo_header.index('IF_IN_LIBRARY') + 1  # 1-indexed
else:
    lib_col_idx = len(promo_header) + 1
    promo_sheet.update_cell(header_row_idx + 1, lib_col_idx, 'IF_IN_LIBRARY')

# ── Sprawdź każdy wiersz ────────────────────────────────────────────────────
batch_updates = []
y_count = 0
n_count = 0

for i, row in enumerate(data_rows):
    if not row or len(row) <= appid_promo_col:
        continue
    appid = row[appid_promo_col].strip()
    if not appid:
        continue

    value = 'Y' if appid in library_appids else 'N'
    batch_updates.append({
        'range': gspread.utils.rowcol_to_a1(data_start_row + i, lib_col_idx),
        'values': [[value]]
    })
    if value == 'Y':
        y_count += 1
    else:
        n_count += 1

if batch_updates:
    promo_sheet.batch_update(batch_updates)

print(f"Zaktualizowano {len(batch_updates)} wierszy: {y_count} w bibliotece (Y), {n_count} brak (N).")
