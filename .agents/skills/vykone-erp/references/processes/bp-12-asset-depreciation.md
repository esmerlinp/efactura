# BP-12: Depreciación de Activos (Asset Depreciation)

## Overview

Proceso mensual de cálculo de depreciación de activos fijos según tablas DGII
(ISR Reglamento Art. 31). El proceso recorre todos los activos activos,
calcula la depreciación del período por método de línea recta, y genera los
asientos contables de depreciación acumulada.

## Flow

```
ejecutar_depreciacion(owner_uid, period_start, period_end, dry_run=False)
  │
  ├─ Validar período abierto (no cerrado fiscalmente)
  │
  ├─ Para cada activo where is_active == True AND estado == "Activo":
  │   │
  │   ├─ Saltar si fully_depreciated
  │   ├─ Calcular depreciación del período:
  │   │   mes_depreciacion = (valor_adquisicion - valor_residual) / vida_util_meses
  │   │
  │   ├─ Validar: depreciación_acumulada + mes_depreciacion <= valor_adquisicion - valor_residual
  │   ├─ Actualizar: depreciacion_acumulada += mes_depreciacion
  │   ├─ Actualizar: valor_neto_libros = valor_adquisicion - depreciacion_acumulada
  │   ├─ Si valor_neto_libros <= valor_residual:
  │   │   └─ Marcar fully_depreciated = True
  │   └─ Acumular en batch contable
  │
  ├─ dry_run=True → Retorna resumen sin aplicar cambios
  └─ dry_run=False → Genera asiento contable + guarda en Firestore
      │
      └─ Asiento:
          Debit:  Gasto de Depreciación (por categoría)
          Credit: Depreciación Acumulada (contra-activo)
```

## DGII Depreciation Rates (ISR Reglamento Art. 31)

| Categoría | Vida útil (años) | Vida útil (meses) | Tasa anual |
|-----------|-----------------|-------------------|------------|
| `edificios` | 20 | 240 | 5% |
| `maquinaria` | 10 | 120 | 10% |
| `equipo_oficina` | 5 | 60 | 20% |
| `vehiculos` | 5 | 60 | 20% |
| `equipo_informatico` | 3 | 36 | 33.33% |
| `mobiliario` | 5 | 60 | 20% |
| `herramientas` | 3 | 36 | 33.33% |
| `software` | 3 | 36 | 33.33% |
| `mejoras_propiedad_arrendada` | 5 | 60 | 20% |
| `custom` | configurable | configurable | configurable |

## Asset Model

```
Asset:
  - asset_id
  - codigo_interno: str
  - descripcion: str
  - categoria: CategoriaActivo
  - valor_adquisicion: Decimal
  - valor_residual: Decimal (default: 0.01 del valor de adquisición)
  - fecha_adquisicion: Date
  - fecha_inicio_uso: Date (default: fecha_adquisicion)
  - vida_util_meses: int (auto from categoria or custom)
  - depreciacion_acumulada: Decimal
  - valor_neto_libros: Decimal
  - fully_depreciated: bool
  - estado: "Activo" | "Vendido" | "Dado de Baja" | "En Reparación"
  - metodo_depreciacion: "linea_recta" (only method supported)
  - cuenta_gasto: str (reference to chart of accounts)
  - cuenta_depreciacion_acumulada: str
```

## Accounting Entry per Category

```
Gasto de Depreciación - Edificios          xxx.xx
Gasto de Depreciación - Maquinaria         xxx.xx
Gasto de Depreciación - Vehículos          xxx.xx
Gasto de Depreciación - Equipo Oficina     xxx.xx
Gasto de Depreciación - Eq. Informático    xxx.xx
Gasto de Depreciación - Mobiliario         xxx.xx
  Depreciación Acumulada - Edificios               xxx.xx
  Depreciación Acumulada - Maquinaria              xxx.xx
  Depreciación Acumulada - Vehículos               xxx.xx
  Depreciación Acumulada - Equipo Oficina          xxx.xx
  Depreciación Acumulada - Eq. Informático         xxx.xx
  Depreciación Acumulada - Mobiliario              xxx.xx
```

## Events

- `DepreciationExecuted(owner_uid, period_start, period_end, asset_count, total_depreciation)`

## Related Files
- `app/services/depreciation_service.py` — execute_depreciation()
- `app/services/accounting_service.py` — generate_depreciation_entries()
- `app/models/pydantic/depreciation.py` — DepreciationRequest, DepreciationResponse
- `app/web/assets.py` — depreciation endpoints
- `app/events/domain_events.py` — DepreciationExecuted
