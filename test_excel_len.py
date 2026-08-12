import pandas as pd
import json

df = pd.read_excel('evidencia_fase2/Set de Pruebas e-CF.xlsx', sheet_name='Casos')
for idx, row in df.iterrows():
    encf = str(row.get('e-NCF', '')).strip()
    if encf and str(encf).startswith('E'):
        if len(encf) != 13:
            print(f"INVALID LENGTH: {encf} (len {len(encf)}) at row {idx}")
        else:
            print(f"Valid: {encf}")
