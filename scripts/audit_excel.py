import openpyxl, json
from collections import defaultdict

wb = openpyxl.load_workbook("Projection_Library_Spec_v1.1.xlsx", data_only=True)
print("Sheets:", wb.sheetnames)


def find_header_row(ws):
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 20)):
        non_empty = [c for c in row if c.value is not None and str(c.value).strip() != ""]
        if len(non_empty) >= 2:
            return row[0].row
    return 1


def count_data_rows(ws, header_row):
    n = 0
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if any(cell is not None and str(cell).strip() != "" for cell in row):
            n += 1
    return n


for name in wb.sheetnames:
    ws = wb[name]
    hdr = find_header_row(ws)
    data_rows = count_data_rows(ws, hdr)
    print(f"{name}: {ws.max_row} rows total, {ws.max_column} cols, header@row{hdr}, {data_rows} data rows")

ws = wb["02_voices"]
hdr_row = find_header_row(ws)
header = [cell.value for cell in ws[hdr_row]]
print(f"\n02_voices header (row {hdr_row}): {header}")


def unique_values(column_name):
    if column_name not in header:
        return None
    idx = header.index(column_name)
    values = []
    seen = set()
    for row in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
        val = row[idx]
        if val is None or str(val).strip() == "":
            continue
        if val not in seen:
            seen.add(val)
            values.append(val)
    return values


for col in ("nature", "calc_phase"):
    vals = unique_values(col)
    if vals is None:
        print(f"02_voices: column '{col}' not found.")
    else:
        print(f"02_voices unique '{col}' ({len(vals)}): {vals}")
