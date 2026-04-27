import openpyxl, json
from collections import defaultdict

wb = openpyxl.load_workbook("Projection_Library_Spec_v1.1.xlsx", data_only=True)
print("Sheets:", wb.sheetnames)
for name in wb.sheetnames:
    ws = wb[name]
    print(f"{name}: {ws.max_row} rows, {ws.max_column} cols")
