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

try:
    header_row_idx = next(i for i, row in enumerate(promo_data) if 'AppID' in row)
except StopIteration:
    print("BŁĄD: nie znaleziono nagłówka 'AppID' w arkuszu Steam-promocje.")
    exit(1)
promo_header = promo_data[header_row_idx]
data_rows = promo_data[header_row_idx + 1:]
data_start_row = header_row_idx + 2  # 1-indexed w arkuszu

if 'AppID' not in promo_header:
    print("BŁĄD: brak kolumny 'AppID' w nagłówku Steam-promocje.")
    exit(1)
appid_promo_col = promo_header.index('AppID')

# znajdź lub utwórz kolumnę HAVE
if 'HAVE' in promo_header:
    lib_col_idx = promo_header.index('HAVE') + 1  # 1-indexed
else:
    lib_col_idx = len(promo_header) + 1
    promo_sheet.resize(cols=lib_col_idx)
    promo_sheet.update_cell(header_row_idx + 1, lib_col_idx, 'HAVE')

# ── Sprawdź każdy wiersz ────────────────────────────────────────────────────
batch_updates = []
y_count = 0
n_count = 0

for i, row in enumerate(data_rows):
    if not row or len(row) <= appid_promo_col:
        continue
    appid_raw = row[appid_promo_col].strip()
    if not appid_raw:
        continue

    appids = [a.strip() for a in appid_raw.split(',')]
    value = 'Y' if any(a in library_appids for a in appids) else 'N'
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

col_idx_0 = lib_col_idx - 1  # 0-indexed
sheet_id = promo_sheet.id
promo_sheet.spreadsheet.batch_update({"requests": [
    {"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col_idx_0, "endIndex": col_idx_0 + 1},
        "properties": {"pixelSize": 6 * 7 + 20},
        "fields": "pixelSize"
    }},
    {"repeatCell": {
        "range": {"sheetId": sheet_id, "startColumnIndex": col_idx_0, "endColumnIndex": col_idx_0 + 1},
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.horizontalAlignment"
    }}
]})

print(f"Zaktualizowano {len(batch_updates)} wierszy: {y_count} w bibliotece (Y), {n_count} brak (N).")
