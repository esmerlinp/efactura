# Caja — Fase 3 (Devoluciones, anulaciones y notas de crédito desde POS): alcance

**Estado:** propuesta de alcance, pendiente de autorización de implementación.

## Objetivo
Permitir devoluciones (totales/parciales) de ventas POS con generación de Nota de
Crédito (E34), reingreso de inventario, reversión de movimientos de caja (REFUND),
y trazabilidad/idempotencia, sin romper la integridad de Fase 1 y Fase 2.

## Distinción de conceptos (crítico)

| Operación | Naturaleza | Documento | Efecto |
|---|---|---|---|
| **Devolución** (comercial) | El cliente devuelve mercancía/dinero | Nota de Crédito (E34) | Reingresa inventario, emite NC, registra `REFUND` en caja |
| **Anulación técnica** | Error de emisión / comprobante inválido | Cancelación DGII (anulación e-CF) | Revierte la factura ya emitida (sin devolución comercial) |

No deben mezclarse: la devolución es un flujo de negocio (con NC + reembolso); la
anulación técnica ya existe (`void_invoice_route`) y se mantiene separada.

## Alcance funcional

1. **Búsqueda de la factura original** desde el POS (por e-NCF o número interno),
   con sus partidas y cantidades vendidas.
2. **Devolución parcial o total**:
   - Seleccionar productos y cantidades a devolver.
   - **Validar cantidades previamente devueltas** (no exceder lo vendido ni lo ya
     devuelto). Se mantiene un acumulado `returnedQty` por línea de la factura.
3. **Referencia obligatoria** a la factura original (`originalInvoiceId`,
   `originalEncNcf`, `originalLineId`).
4. **Nota de Crédito (E34)** vía `EcfEmissionService` + `CreditNoteInventoryService`
   (reingreso físico de inventario). Reglas DGII: NC referencia el e-CF original.
5. **Reversión de movimientos de caja**:
   - Se registra un movimiento `REFUND` (taxonomía Fase 2) con autorización de
     supervisor (PIN, `CashAuthorizationService`).
   - El reembolso puede ser **efectivo**, **tarjeta** o **transferencia** (según el
     medio de pago original); el `REFUND` respeta el lock ACTIVE y la conciliación
     por canal (`expectedCash`/`expectedCard`/`expectedTransfer`).
6. **Idempotencia y trazabilidad**: clave de idempotencia por devolución; cada
   devolución guarda `performedBy`, `authorizedBy`, `authorizedAt`, `reason`,
   referencia a la NC y a la factura original; auditado con `AuditService`.
7. **Comportamiento en caja cerrada**: la devolución de una venta de un turno ya
   cerrado se registra de forma consistente (ajuste documentado, sin reabrir el turno).

## Reglas DGII aplicables (resumen)
- E34 (Nota de Crédito) para consumidor final / crédito fiscal, según el comprobante original.
- La NC debe referenciar el e-CF original y, cuando aplique, el motivo de devolución.
- La anulación de una NC ya emitida revierte el reingreso de inventario
  (`CreditNoteInventoryService.revert_credit_note_stock_reentry`).

## Reutilización de componentes existentes
- `CreditNoteInventoryService` — reingreso y reversión de inventario para E34.
- `EcfEmissionService` — emisión de NC.
- `CashAuthorizationService` / `register_cash_transaction` (tipo `REFUND`) — Fase 2.
- `void_invoice_route` — anulación técnica (no se modifica; se aísla del flujo de devolución).

## Fuera de alcance
- Entrega/conciliación de fondos (`CashDelivery`/`CashReconciliation`) → Fase 4.
- Reapertura automática de turnos cerrados.

## Criterios de aceptación (testables)
1. Devolución total genera NC E34 + reingreso de inventario + `REFUND` por el total.
2. Devolución parcial genera NC por las cantidades devueltas y no excede lo vendido ni lo ya devuelto.
3. La NC referencia obligatoriamente la factura original (se rechaza si falta).
4. El reingreso de inventario ocurre exactamente una vez (idempotente).
5. El `REFUND` requiere autorización de supervisor y respeta el lock ACTIVE.
6. El reembolso por tarjeta/transferencia no incrementa el efectivo (`expectedCash`); solo `REFUND` en efectivo lo reduce.
7. Un reintento con la misma clave de idempotencia no duplica la NC, el inventario ni el `REFUND`.
8. La anulación técnica de una factura emitida no dispara el flujo de devolución comercial (y viceversa).
9. Se impide devolver más cantidad de la vendida o de la ya devuelta (validación backend).
10. Todo queda auditado (`performedBy`/`authorizedBy`/referencias).

## Archivos objetivo
- `app/web/pos.py` — rutas de búsqueda de factura y de devolución desde POS.
- `app/services/cash_refund_service.py` *(nuevo)* — orquestación devolución + NC + REFUND.
- `app/services/credit_note_inventory_service.py` — reuso (posibles ajustes menores).
- `templates/pos/` — UI de devolución.
- `tests/test_cash_refunds.py` *(nuevo)*.
