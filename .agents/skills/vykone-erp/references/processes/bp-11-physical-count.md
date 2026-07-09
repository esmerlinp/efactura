# BP-11: Conteo Físico de Inventario (Physical Count)

## Overview

Proceso de auditoría física del inventario donde el conteo real se compara
contra el stock en sistema, generando ajustes por diferencias (sobrantes o
faltantes) documentados y aprobados.

## Flow

```
1. Iniciar conteo(warehouse_id, item_ids[], cutoff_date)
   ├─ Validar warehouse existe y está activo
   ├─ "Freeze" del inventario en el warehouse a la fecha de corte
   │   ├─ Registrar stock teórico snapshot
   │   └─ Bloquear movimientos (opcional, configurable)
   ├─ Estado: "En Proceso"
   └─ Generar hojas de conteo por zona/sección

2. Registrar conteos (pueden ser múltiples por ítem)
   ├─ Cada conteo: item_id, zona, qty_contada, contado_por, timestamp
   ├─ Si hay múltiples conteos del mismo item → promedio o último válido
   └─ Validar qty_contada >= 0 (no negativos)

3. Finalizar conteo
   ├─ Comparar: stock_teórico vs stock_contado
   ├─ Generar reporte de diferencias:
   │   ├─ Sobrantes: stock_contado > stock_teórico
   │   └─ Faltantes: stock_contado < stock_teórico
   ├─ Calcular impacto financiero:
   │   ├─ Sobrantes → +costo_promedio × qty (otro ingreso)
   │   └─ Faltantes → -costo_promedio × qty (gasto)
   └─ Estado: "Pendiente de Revisión"

4. Revisión y Aprobación
   ├─ Supervisor revisa diferencias
   ├─ Investigación de diferencias significativas (> threshold $)
   ├─ Aprobación: genera ajustes de inventario
   │   ├─ Ajustes de entrada (sobrantes)
   │   ├─ Ajustes de salida (faltantes)
   │   └─ Asientos contables correspondientes:
   │       Sobrante: Débito Inventario / Crédito Otro Ingreso
   │       Faltante: Débito Gasto por Diferencia / Crédito Inventario
   └─ Estado: "Completado"
```

## Freeze Behavior

| Opción | Descripción |
|--------|------------|
| `soft_freeze` | Se permite seguir facturando pero los movimientos se registran como "post-cierre" |
| `hard_freeze` | Se bloquean todos los movimientos en el almacén durante el conteo |

## Adjustment Accounting

```
Sobrante (entrada):
  Debit:  Inventario (a costo promedio)
  Credit: Otro Ingreso por Ajuste de Inventario

Faltante (salida):
  Debit:  Gasto por Diferencia de Inventario
  Credit: Inventario (a costo promedio)
```

## Events

- `PhysicalCountStarted(owner_uid, count_id, warehouse_id, item_count, cutoff_date)`
- `PhysicalCountCompleted(owner_uid, count_id, differences[], total_impact)`
- Triggers: InventoryAdjusted (for each adjustment)

## Related Files
- `app/services/inventory_service.py` — PhysicalCount methods
- `app/services/accounting_service.py` — adjustment entries
- `app/models/pydantic/inventory.py` — PhysicalCount schemas
- `app/web/inventory.py` — count endpoints
- `app/events/domain_events.py` — PhysicalCountStarted, PhysicalCountCompleted
