# Caja POS — Fase 4.1: Arquitectura y auditoría

**Rama:** `feature/cash-fase4-entrega-conciliacion` (derivada de `feature/cash-fase3-refunds`).
**Estado:** **CERRADA / APROBADA**. Auditoría y documentación completadas. Sin implementación de servicios/rutas.

---

## 1. Auditoría técnica de arquitectura e integración (F1–F3)

### 1.1 Colecciones y entidades existentes

| Colección | Responsabilidad | Puntos de integración con F4 |
|---|---|---|
| `cash_registers` / `cash_register_locks` | Caja física + lock de ocupación | `registerId` en cada entrega |
| `cash_shifts` | Turno (apertura→cierre→arqueo) | `shiftId`; produce `expected*`/`difference*` (insumo de conciliación) |
| `cash_transactions` | Movimientos financieros | `CASH_DROP` = movimiento que reduce `expectedCash`; vínculo 1:1 con `CashDelivery` |
| `cash_authorizations` | Autorizaciones de supervisor (F2) | Reutilizable para aprobar diferencias |
| `cash_refunds` | Devoluciones (F3) | No interfiere; patrón de estados/idempotencia reutilizable |
| `idempotency_keys` | Idempotencia | Reutilizable para entrega/conciliación |

### 1.2 Capacidades reutilizables (verificadas)

| Capacidad | Origen | Uso en F4 |
|---|---|---|
| Transacción Firestore + lock (`_run_in_transaction`, `_company_coll`) | F1 | Creación conjunta `CASH_DROP` + `CashDelivery` |
| Idempotencia (`reserve_idempotency_key`: lease + owner + PENDING/COMPLETED/FAILED) | F1/F2 | Idempotencia de entrega y conciliación |
| `Decimal` / `_money` / `_qty` (2 y 3 decimales) | F1/F3 | Importes y denominaciones |
| Autorización single-use de supervisor (`CashAuthorizationService`) | F2 | Aprobación de diferencias |
| Conciliación por canal en `close_cash_shift` (`expectedCash/Card/Transfer/USD`) | F2/F3 | Insumo de conciliación de tarjeta/transferencia |
| Config por empresa (`get/save_pos_*`) | F2 | Política de entrega/umbrales |
| Auditoría (`AuditService.log_from_request`) + `history[]` embebido | global | Historial inmutable |

### 1.3 Hallazgos clave

1. **`CASH_DROP` ya reduce `expectedCash`** (`CASH_OUTFLOW_TYPES`, `close_cash_shift` sign=−1).
   → F4 debe **vincular** (no re-crear) el `CASH_DROP` para no restar dos veces.
2. **No existe PIN de recepción.** Solo `posSupervisorPin` (perfil de usuario). → F4 introduce un
   nuevo campo `receptionPin`, separado del PIN de supervisor.
3. **No existe rol "receptor".** La recepción es cualquier usuario autenticado con `receptionPin`.
   Roles existentes: `canManagePOS` (operar), `isPosSupervisor` (supervisar), `canViewAuditLog` (auditar).
4. **`close_cash_shift` ya produce** `expectedCash/Card/Transfer/USD`, `difference*`, denominaciones
   y `cardLoteNumber` → no recalcular en F4.
5. **Un `CASH_DROP` es de una sola moneda** (verificado: `cash_transactions` tiene `currency` y
   `amount` únicos). Una entrega con DOP **y** USD se representa como **dos** movimientos `CASH_DROP`
   (uno por moneda), ambos vinculados a la **misma** `CashDelivery` vía `cashDropTransactionIds[]`.

---

## 2. Modelo de datos definitivo

### 2.1 `cash_deliveries` (CashDelivery)

```
id                          string  (derivado de idempotencyKey o uuid)
companyId, ownerUID         string
shiftId, registerId         string
cashDropTransactionIds[]    array   (1..2 → cash_transactions.id, uno por moneda)
deliveredBy{uid,email}      object
receivedBy{uid,email}       object
receivedAt                  timestamp
receivedPinVerified         bool
amounts{dop, usd}           object  (float, 2 decimales; al menos uno presente)
usdRate                     float
denominations{dop, usd}     object  (desglose por denominación)
declaredTotal               float   (total declarado por el cajero)
difference                  float   (declarado - recibido; se calcula en conciliación)
status                      enum
receiptEvidenceUrl          string  (opcional)
notes                       string
idempotencyKey              string
createdAt, updatedAt        timestamp
history[]                   array   (inmutable)
```

Estados (corregidos — sin contradicción DELIVERED/RECEIVED):
```
PENDING_RECEIPT ──(creación conjunta CASH_DROP + CashDelivery)──► (inicio)
PENDING_RECEIPT ──(PIN del receptor)──► RECEIVED
RECEIVED ──(inicia conciliación)──► PENDING_RECONCILIATION ──► RECONCILED
cualquier estado ──(diferencia)──► UNDER_REVIEW ──(aprobación supervisor)──► RECONCILED
```

Nota: `PENDING_RECEIPT` es el estado en que queda el registro tras la creación conjunta; la
confirmación del receptor y la conciliación son pasos **posteriores e independientes**.

### 2.2 `cash_reconciliations` (CashReconciliation)

```
id                          string
companyId, ownerUID         string
deliveryId                  string  (null para tarjeta/transferencia)
shiftId                     string
channel                     enum    (CASH_DOP | CASH_USD | CARD | TRANSFER)
expectedAmount              float   ← ver tabla de conciliación (sección 2.3)
deliveredAmount             float
receivedAmount              float
difference                  float
status                      enum    (OPEN | RECONCILED | UNDER_REVIEW)
reconciledAt, reconciledBy  timestamp/string
approvedBy, approvalJustification
reference                   string  (lote de tarjeta / depósito bancario)
idempotencyKey              string
createdAt, updatedAt        timestamp
history[]                   array   (inmutable)
```

Estados: `OPEN → RECONCILED`; `OPEN → UNDER_REVIEW → RECONCILED`.

### 2.3 Criterio de conciliación (definitivo)

| Canal | `expectedAmount` | `receivedAmount` |
|---|---|---|
| `CASH_DOP` | Importe del `CASH_DROP` vinculado (DOP) | Efectivo recibido DOP |
| `CASH_USD` | Importe del `CASH_DROP` vinculado (USD) | Efectivo recibido USD |
| `CARD` | `expectedCard` del cierre | Lote del adquirente |
| `TRANSFER` | `expectedTransfer` del cierre | Acreditación/depósito bancario |

**Regla:** nunca usar `expectedCash` como importe esperado de entrega física. En entregas
parciales, la conciliación de efectivo suma los `CASH_DROP` vinculados (vía
`cashDropTransactionIds[]`) **sin contar dos veces** una misma transacción.

---

## 3. Matriz de permisos y segregación de funciones

| Rol | Permiso | Acciones |
|---|---|---|
| Cajero | `canManagePOS` | Registra la entrega (`register_delivery`), declara importe/denominaciones |
| Receptor | usuario autenticado + `receptionPin` | Confirma recepción (PIN) |
| Supervisor | `isPosSupervisor` (o owner) + `posSupervisorPin` | Aprueba diferencias (autorización single-use F2) |
| Auditor | `canViewAuditLog` | Consulta historial (solo lectura) |

### Segregación de funciones (SoD)

- **El receptor no puede confirmar una entrega que él mismo registró** (`receivedBy.uid ≠ deliveredBy.uid`).
- **PIN de recepción ≠ PIN de supervisor**: dos campos distintos (`receptionPin` vs `posSupervisorPin`)
  y dos operaciones distintas (confirmar recepción vs autorizar diferencia).
- Una diferencia aprobada **no modifica** el registro original; se conserva `declaredTotal`,
  `receivedAmount`, `difference`, `approvedBy` e `history[]`.

### Ciclo de vida del PIN de recepción (decisión cerrada)

- Campo nuevo `receptionPin` **hasheado** en el perfil de usuario (junto a `posSupervisorPin`),
  **sin reutilizar** `posSupervisorPin`.
- **Single-use**: cada confirmación consume una autorización de recepción de forma **atómica**,
  vinculada a una **entrega específica** (análogo a `cash_authorizations` de F2, con lease).
- Validación separada: `validate_reception_pin` (no confundir con `validate_pos_supervisor_pin`).

---

## 4. Índices Firestore requeridos y justificación

| Índice | Colección | Justificación |
|---|---|---|
| `shiftId ASC, status ASC` | `cash_deliveries` | Listar entregas pendientes/por turno (reporte 4.4) |
| `deliveryId ASC, channel ASC` | `cash_reconciliations` | Obtener conciliaciones de una entrega por canal |
| `cashDropTransactionIds` (array, `array_contains`) | `cash_deliveries` | Resolver el vínculo con `CASH_DROP` (evitar duplicados) |
| `shiftId ASC, channel ASC` | `cash_reconciliations` | Resumen de conciliación por turno/canal |

Nota: Firestore exige índices compuestos para consultas con múltiples `where`. El patrón ya se
usa en F1 (`get_open_shift`: `openedByUserId + status in [...]`). Los índices se crean como
**configuración de despliegue** (no en código) y no se aplican en esta sub-fase.

---

## 5. Diagrama de estados y flujos

```
  Cajero                          Receptor                    Supervisor
     │                                │                            │
     ▼                                │                            │
 register_delivery ───────────────────┤                            │
  └─ transacción: crea CASH_DROP(s)   │                            │
     (reduce expectedCash/expectedUSD)│                            │
     + CashDelivery (PENDING_RECEIPT) │                            │
     │                                │                            │
     ▼                                │                            │
  (RECEIVED)                          │                            │
     │                                ▼                            │
     │                    confirma recepción (PIN)                 │
     │                    └─ receivedBy, receivedAt,               │
     │                       receivedPinVerified                   │
     │                       → status RECEIVED                    │
     │                                │                            │
     ▼                                ▼                            │
  CashReconciliation (por canal)      │                            │
   ├─ CASH_DOP/USD: expectedAmount =  │                            │
   │    CASH_DROP vinculado           │                            │
   ├─ CARD: expectedCard              │                            │
   └─ TRANSFER: expectedTransfer      │                            │
     │                                │                            │
     ├─ sin diferencia ──► RECONCILED  │                            │
     └─ con diferencia ──► UNDER_REVIEW ──(aprueba)──► RECONCILED   │
                            │            │                            │
                            └──► justificación + approvedBy (single-use)
```

`close_cash_shift` (F1) permanece intacto: produce `expected*` y `difference*`, pero **no** crea
entregas ni conciliaciones. El cierre debe marcar el turno como "pendiente de entrega/conciliación"
cuando existan `cash_deliveries` en `PENDING_RECEIPT`/`RECEIVED` o conciliaciones `OPEN`.

---

## 6. Riesgos, dependencias y decisiones pendientes

### Riesgos
- **Doble substracción de `CASH_DROP`**: mitigado con creación conjunta + `cashDropTransactionIds[]` (1..2, uno por moneda).
- **Doble conciliación de un mismo `CASH_DROP`**: mitigado agrupando por `cashDropTransactionIds[]` + idempotencia.
- **PIN de recepción débil**: sin bloqueo por intentos (heredado de F2); endurecimiento futuro.
- **Concurrencia real**: pendiente Firestore Emulator (heredado de F1–F3).

### Dependencias
- Campos nuevos en perfil de usuario (`receptionPin`) y método `validate_reception_pin`.
- Índices Firestore (configuración de despliegue, no código).

### Decisiones pendientes (para 4.2)
- **PIN de recepción** — *decidido*: single-use, vinculado a una entrega específica, consumo
  atómico, no reutiliza `posSupervisorPin`.
- **Multi-moneda** — *decidido*: una entrega puede generar 1..2 `CASH_DROP` (uno por moneda DOP/USD).
- ¿La conciliación de tarjeta/transferencia se dispara manualmente o tras el cierre del turno?
  (Recomendado: manual, contra lote/depósito bancario.)
- Formato del `reference` de lote/depósito (numérico, archivo, URL).

---

## 6bis. Controles de seguridad (verificación previa a 4.2)

### C1. PIN de recepción
- **Almacenamiento seguro**: `receptionPin` se guarda **hasheado** (no en texto plano), igual
  que debe endurecerse `posSupervisorPin` (hoy se compara en texto plano; ver riesgo en F2).
- **Verificación sin exponer el PIN**: comparación contra el hash, nunca devolver el valor.
- **Limitación de intentos / anti-fuerza bruta**: contador de intentos fallidos + bloqueo
  temporal por usuario (pendiente de definir umbral exacto en 4.2).
- **Single-use por confirmación**: análogo a `cash_authorizations` (consume atómico con lease).

### C2. Segregación de funciones
- `receivedBy.uid ≠ deliveredBy.uid` (el receptor no confirma su propia entrega).
- La aprobación de diferencias usa **exclusivamente** el mecanismo single-use de supervisor de
  F2 (`CashAuthorizationService.consume`), no el PIN de recepción.

### C3. Idempotencia y concurrencia (atomicidad precisa)
- `register_delivery` usa `reserve_idempotency_key` (lease + owner) + `_run_in_transaction`.
- **Una clave de idempotencia no puede generar más de una entrega**; un reintento devuelve el
  resultado original (no duplica ni entrega ni movimientos).
- **Orden de lecturas/escrituras Firestore** (todas las lecturas antes de escribir):
  1. Leer idempotencia (reserva atómica).
  2. Leer lock de la caja (debe estar ACTIVE y apuntar al `shiftId`).
  3. Leer (si aplica) autorización de recepción/supervisor.
  4. Escribir el/los `CASH_DROP` (uno por moneda).
  5. Escribir `CashDelivery` (con `cashDropTransactionIds[]`).
  6. Tocar el lock (`updatedAt`) para forzar conflicto de escritura con un cierre concurrente.
- Dos solicitudes simultáneas **no** generan dos entregas ni dos `CASH_DROP` (conflicto de
  escritura + idempotencia por clave).

### C4. Conciliación sin doble suma
- Cada `CASH_DROP` queda asociado inequívocamente a `shiftId`, `currency` (DOP/USD) y a la
  `CashDelivery` (vía `cashDropTransactionIds[]`).
- La conciliación agrupa por `cashDropTransactionIds[]` para no sumar dos veces el mismo importe
  parcial (cada id se cuenta exactamente una vez, por su moneda).

---

## 7. Referencia

- Alcance definitivo: `docs/caja_fase4_alcance.md`.
- Fases previas: `docs/caja_fase1_cierre.md`, `docs/caja_fase2_implementacion.md`,
  `docs/caja_fase3_implementacion.md`.

**Conclusión:** la arquitectura de F1–F3 aporta atomicidad, idempotencia, autorización y
conciliación por canal. F4 introduce dos entidades nuevas (`cash_deliveries`, `cash_reconciliations`),
un campo de PIN de recepción y una relación 1:1 con `CASH_DROP`, sin modificar `close_cash_shift`
ni recalcular el esperado.
