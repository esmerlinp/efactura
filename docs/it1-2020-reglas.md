# IT-1 2020: catálogo histórico y control de habilitación

La fuente histórica es `docs/IT-1-2020.xls`. El archivo original no debe
modificarse, reemplazarse ni utilizarse como archivo de salida.

## Estado

- Versión: `IT-1-2020`
- Estado: histórica
- No habilitada para períodos 2026 o posteriores.
- Requiere aprobación fiscal para cualquier activación productiva.

## Anexo A

- Casillas 1–11: NCF y total de operaciones.
- Casillas 12–19: formas de venta y total.
- Casillas 20–26: tipos de ingreso y total.
- Casillas 27–33: pagos computables y total.
- Casillas 34–38: constructoras.
- Casillas 39–42: comisionistas.
- Casillas 43–44: informativas.
- Casillas 45–56: ITBIS pagado.

Fórmulas críticas:

```text
11 = 1 + 2 + 3 - 4 + 5 + 6 + 7 + 8 + 9 - 10
48 = 45 + 46 + 47
52 = 49 + 50 + 51
55 = 53 × 54 / 100
56 = 52 + 55
```

## IT-1

- Casillas 1–15: ingresos por operaciones.
- Casillas 16–34: liquidación.
- Casillas 35–37: penalidades.
- Casilla 38: total a pagar.
- Casillas 39–60: ITBIS retenido y percibido.
- Casillas 61–63: liquidación de retenciones.

Las fórmulas individuales están catalogadas en
`app/fiscal_forms/it1_rules.py`, incluyendo las casillas 28–34 y 39–63.

## Proporcionalidad

```text
Coeficiente = ((IT-1.2 + IT-1.5 + IT-1.10) / IT-1.1) × 100
Admitido = Anexo A.53 × Coeficiente / 100
```

No se aplica automáticamente a gastos. Requiere clasificación explícita o
decisión manual respaldada.

## Verificación

Con `xlrd` instalado:

```bash
python scripts/verify_it1_official_template.py
```

Este comando solo lee la plantilla, verifica las hojas oficiales y confirma
que permanece intacta. La activación productiva requiere además comparación
de fórmulas, casos DGII y aprobación fiscal.
