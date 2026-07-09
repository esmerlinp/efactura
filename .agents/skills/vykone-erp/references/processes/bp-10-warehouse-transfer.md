# BP-10: Transferencia entre Almacenes (Warehouse Transfer)

## Overview

Movimiento de inventario entre dos almacenes de la misma empresa. El proceso
valida disponibilidad de stock en el almacén origen, genera un documento de
transferencia, y actualiza el inventario en ambos almacenes de forma atómica.
No genera asiento contable (el costo sigue en la misma empresa) pero sí afecta
la valoración de inventario por ubicación.

## Flow

```
Crear transferencia(owner_uid, item_id, qty, warehouse_from_id, warehouse_to_id)
  │
  ├─ Validar: warehouse_from != warehouse_to
  ├─ Validar: item existe y está activo
  ├─ Validar: stock actual en warehouse_from >= qty_requested
  │   └─ Si no hay suficiente → error: "Stock insuficiente en origen: {disponible}"
  │
  ├─ Estado: "Pendiente"
  │   ├─ Opcional: requiere aprobación (si qty > threshold de empresa)
  │   │   ├─ Aprobación → estado "En Tránsito"
  │   │   └─ Rechazo → estado "Rechazado" (se libera el stock reservado)
  │   └─ Sin aprobación → avanza a "En Tránsito" automáticamente
  │
  ├─ "En Tránsito":
  │   ├─ Reservar stock en origen (disminuye stock_disponible)
  │   ├─ NO incrementa destino aún (hasta recepción)
  │   └─ EventBus: TransferInitiated
  │
  └─ Recepción en destino (manual/escaneo):
      ├─ Validar: qty_recibida == qty_enviada (o diferencia aceptable)
      ├─ Incrementar stock en destino
      ├─ Confirmar stock_sacado en origen
      ├─ Estado: "Completado"
      └─ EventBus: TransferCompleted
```

## Stock States During Transfer

```
Origen:  stock_disponible -= qty, stock_reservado += qty
Destino: sin cambio

Al completar:
Origen:  stock_reservado -= qty, stock_total -= qty
Destino: stock_disponible += qty, stock_total += qty
```

## Accounting Impact

No se genera asiento contable porque el costo del inventario reside en la
misma entidad legal. Solo se actualiza el costo promedio por almacén para
fines de valoración interna. Si la empresa usa centros de costo (departamentos),
la transferencia sí afecta la distribución de costo.

## Events

- `TransferInitiated(owner_uid, transfer_id, item_id, qty, from_warehouse, to_warehouse)`
- `TransferCompleted(owner_uid, transfer_id, received_by)`

## Related Files
- `app/services/warehouse_service.py` — WarehouseService, transfer_stock()
- `app/models/pydantic/warehouse.py` — WarehouseTransfer schemas
- `app/web/inventory.py` — transfer endpoints
- `app/events/domain_events.py` — TransferInitiated, TransferCompleted
