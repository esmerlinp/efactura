# Caja — Fase 4 (Entrega y conciliación de fondos): alcance definitivo

**Estado:** **FASE 4 COMPLETA Y CERRADA** (4.1 Arquitectura · 4.2 Entrega · 4.3 Conciliación ·
4.4 Reportes). Validación con Firestore Emulator pendiente como condición de despliegue.
Rama: `feature/cash-fase4-entrega-conciliacion` (derivada de `feature/cash-fase3-refunds`).

## 0. Verificación técnica previa — `CASH_DROP ↔ expectedCash` (la dependencia crítica)

Confirmado en código (`app/services/db_service.py`):

1. `CASH_TYPE_CASH_DROP = "CASH_DROP"` (línea 1156) y está en `CASH_OUTFLOW_TYPES` (línea 1174).
2. `close_cash_shift` (línea 6725) calcula `sign = -1` para tipos de salida y lo aplica a
   `expected_cash` (o `expected_usd`/`expected_card`/`expected_transfer` según canal).

**Conclusión:** cada movimiento `CASH_DROP` **ya reduce `expectedCash`** en el cierre (es
dinero que salió físicamente de la caja). El `declaredCash` al cierre es el conteo físico
del dinero que **queda** en la caja.

### Regla técnica obligatoria (anti-doble-substracción)

> `CashDelivery` **no debe crear un segundo movimiento `CASH_DROP`**. Si lo hiciera, el
> mismo efectivo se restaría dos veces de `expectedCash`.

Relación correcta (1:1): cada entrega parcial de efectivo corresponde a **un** movimiento
`CASH_DROP` existente y a **un** registro `CashDelivery` que lo enriquece con la
transferencia física:

```
CASH_DROP (movimiento, reduce expectedCash)  ←→  CashDelivery (físico: quién entrega/recibe, denominaciones)
                                                        │
                                                        ▼
                                            CashReconciliation (¿el receptor recibió lo esperado?)
```

- `CASH_DROP` = efecto financiero (ya contabilizado por F2/F3).
- `CashDelivery` = trazabilidad física de esa salida.
- `CashReconciliation` = verificación de recepción.

### Creación conjunta (decisión cerrada — sin ambigüedad)

`register_delivery` crea, en **una única transacción Firestore**:

1. **Uno o dos movimientos `CASH_DROP`** (uno por cada moneda presente: DOP y/o USD; efecto
   financiero: cada uno reduce `expectedCash`/`expectedUSD`).
2. **Su correspondiente `CashDelivery`**, cuyo `cashDropTransactionIds[]` referencia esos movimientos.

Reglas inequívocas:

- **Nunca** se crea un segundo `CASH_DROP` para una moneda ya registrada en la misma entrega.
- **No** depende de un `CASH_DROP` manual previo: el servicio los crea él mismo.
- **Reintentos**: recuperan el resultado anterior por idempotencia (no duplican movimientos ni entrega).

La confirmación del receptor (PIN) y la conciliación son pasos **posteriores e independientes**
de la creación de la entrega.

## 1. Decisiones definitivas (validadas)

| Decisión | Definición |
|---|---|
| ¿Qué fondos se entregan? | **Efectivo DOP y USD exclusivamente** (denominaciones por moneda). |
| ¿Entregas parciales? | **Sí**, durante el turno y al cierre (cash drops). |
| ¿Evidencia? | **UID autenticado + confirmación del receptor con PIN**. Evidencia fotográfica/documental opcional. |

### 1.1 Separación por canal
- **`CashDelivery`**: solo transferencia física de efectivo (DOP + USD). Tarjetas y
  transferencias **no** generan `CashDelivery`.
- **`CashReconciliation`**: cubre efectivo, tarjetas (lote de terminal/adquirente) y
  transferencias (depósitos/movimientos bancarios).

### 1.2 Entregas parciales y al cierre
Cada entrega tiene ID, estado e idempotencia independientes. El cierre del turno **no**
depende de que todas las entregas estén conciliadas, pero debe quedar marcado como
"pendiente de entrega/conciliación" cuando corresponda.

### 1.3 Evidencia y segregación de funciones
- **Cajero**: registra y confirma la entrega.
- **Receptor**: confirma la recepción con usuario autenticado + **PIN de recepción**
  (distinto del PIN de autorización de supervisor de F2).
- **Supervisor**: autoriza diferencias con la autorización single-use de F2.
- **Auditor**: consulta historial sin modificar.

## 2. Reglas arquitectónicas incorporadas (A–D)

**A. Una entrega no equivale a una conciliación.**
La entrega puede estar `RECEIVED` pero aún `PENDING_RECONCILIATION`. Estados independientes.

**B. No duplicar `CASH_DROP`.**
`CashDelivery` se vincula a 1..2 movimientos `CASH_DROP` (uno por moneda) vía
`cashDropTransactionIds[]`; no crea un segundo para una moneda ya registrada.
(Ver sección 0.)

**C. No conciliar el mismo importe dos veces.**
Las entregas parciales se acumulan por turno/moneda/responsable con IDs independientes;
la conciliación final detecta entregas faltantes o duplicadas.

**D. Una diferencia no se corrige modificando la entrega original.**
Se conservan importe declarado, recibido, diferencia, justificación, autorización e
historial. Inmutable para auditoría.

## 3. Modelo funcional definitivo

| Entidad | Responsabilidad | Estados |
|---|---|---|
| `CashDelivery` | Entrega física de efectivo DOP/USD | `PENDING_RECEIPT → RECEIVED → PENDING_RECONCILIATION → RECONCILED`; `UNDER_REVIEW` |
| `CashReconciliation` | Verificación de efectivo/tarjetas/transferencias | `OPEN → RECONCILED`; `UNDER_REVIEW` |
| Historial | Embebido e inmutable en cada registro (`history[]`) | — |

No se crean colecciones adicionales para historial (se usa `history[]` embebido), salvo
que volumen/consultas lo justifiquen después.

### `cash_deliveries` (CashDelivery)
```
id, companyId, shiftId, registerId, cashDropTransactionIds[] (1..2 → cash_transactions.id, uno por moneda),
deliveredBy{uid,email}, receivedBy{uid,email}, receivedAt, receivedPinVerified,
amounts{dop, usd, usdRate}, denominations{dop, usd}, declaredTotal, difference,
status, receiptEvidenceUrl (opcional), notes,
idempotencyKey, createdAt, updatedAt, history[]
```

### `cash_reconciliations` (CashReconciliation)
```
id, companyId, deliveryId, shiftId, channel (CASH_DOP|CASH_USD|CARD|TRANSFER),
expectedAmount, deliveredAmount, receivedAmount, difference,
status, reconciledAt, reconciledBy, approvedBy, approvalJustification,
reference (lote de tarjeta / depósito bancario), idempotencyKey, createdAt, updatedAt, history[]
```

**Qué se compara en cada canal (criterio de conciliación corregido):**

| Canal | Importe esperado para conciliar | Importe real |
|---|---|---|
| Efectivo DOP | Importe del `CASH_DROP` vinculado (DOP) | Efectivo recibido en DOP |
| Efectivo USD | Importe del `CASH_DROP` vinculado (USD) | Efectivo recibido en USD |
| Tarjeta | Total esperado del canal en el cierre | Total del lote del adquirente |
| Transferencia | Total esperado del canal en el cierre | Total acreditado/comprobado en banco |

**No** se compara `expectedCash` del cierre contra lo recibido: `expectedCash` es el efectivo
que **queda** en la caja tras las salidas, un concepto distinto al efectivo entregado. Para
efectivo, la referencia es el `CASH_DROP` vinculado (dinero que salió a entregar). En entregas
parciales, la conciliación suma los `CASH_DROP` vinculados **sin contar dos veces** una misma
transacción.

## 4. Criterios de aceptación (14)

1. La entrega es independiente del cierre: un turno cerrado puede tener entregas pendientes.
2. Cada entrega registra quién entrega y quién recibe, con denominaciones e idempotencia.
3. La conciliación compara, por canal, el importe correcto contra el **recibido** (no contra
   `expectedCash`): efectivo → `CASH_DROP` vinculado; tarjeta/transferencia → esperado del
   canal en el cierre vs lote/depósito bancario.
4. Una diferencia requiere justificación y aprobación de supervisor (PIN single-use, SoD).
5. Entregas parciales se acumulan sin duplicar; reintentos no crean entregas duplicadas.
6. Aislamiento por empresa/entorno y trazabilidad completa (AuditService).
7. No se recalcula el esperado: se consume el resultado de `close_cash_shift`.
8. Un receptor no puede confirmar una entrega que él mismo registró (SoD).
9. Una entrega física **no duplica ni altera** los movimientos `CASH_DROP` existentes.
10. La conciliación de tarjetas/transferencias no simula una entrega física de efectivo.
11. Una entrega recibida (`RECEIVED`) puede permanecer pendiente de conciliación.
12. Entregas parciales acumulables y conciliables individualmente y por turno.
13. Una diferencia aprobada no elimina ni modifica el registro original.
14. El cierre identifica fondos pendientes de entrega, recepción o conciliación.

## 5. Plan de implementación (sub-fases)

### 4.1 — Arquitectura y auditoría
- Documentar `shift → deliveries → reconciliations` e índices compuestos
  (`shiftId+status`, `deliveryId+channel`, `cashDropTransactionIds`).
- Definir permisos y PIN de recepción (nuevo) vs PIN de supervisor (F2).

### 4.2 — Entrega de fondos
- `CashDeliveryService.register_delivery` (transaccional, idempotente): crea **conjuntamente**
  el/los movimiento(s) `CASH_DROP` (uno por moneda DOP/USD) y el registro `CashDelivery`
  (vínculo vía `cashDropTransactionIds[]` en una transacción).
- Denominaciones DOP/USD, entregador/receptor, evidencia opcional.

### 4.3 — Conciliación
- `CashReconciliationService.reconcile` compara, **por canal**:
  - Efectivo DOP/USD → importe del `CASH_DROP` vinculado vs efectivo recibido.
  - Tarjeta → esperado del canal en el cierre vs lote del adquirente.
  - Transferencia → esperado del canal en el cierre vs acreditación/depósito bancario.
- Diferencias + justificación + aprobación supervisor.
- Entregas parciales acumulables sin contar dos veces una misma transacción.

### 4.4 — Reportes y controles
- Pendientes, conciliadas, con diferencias; historial; métricas por cajero/terminal/sucursal.

## 6. Riesgos / decisiones restantes (para validar al implementar)

- **Momento del `CASH_DROP`** — *decidido*: creación conjunta con `CashDelivery` en
  `register_delivery` (una transacción). No hay `CASH_DROP` huérfano ni entrega sin movimiento.
- **Recepción sin conciliación**: ¿el estado `RECEIVED` se alcanza con el PIN de recepción,
  y la conciliación es un paso posterior separado? (Sí, según regla A.)
- **Moneda**: la conciliación de efectivo debe separar DOP y USD (como ya hace el cierre).
- **Card/transfer sin `CashDelivery`**: la conciliación de estos canales se hace directamente
  contra el esperado del cierre, sin requerir una entrega física previa.

---

**Conclusión técnica:** la dependencia `CASH_DROP ↔ expectedCash` está verificada, el criterio
de conciliación de efectivo quedó corregido (se concilia contra el `CASH_DROP` vinculado, no
contra `expectedCash`), y la creación conjunta `CASH_DROP` + `CashDelivery` quedó decidida.
El alcance funcional de Fase 4 está **validado y listo para autorizar**; la implementación se
hará en una rama derivada de `feature/cash-fase3-refunds`, manteniendo F1–F3 intactas y sin
commits, merge ni despliegue.
