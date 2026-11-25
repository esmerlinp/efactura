# Precio por porcentaje e inventario inicial — Fase 1: Diseño técnico y decisiones

> Estado: propuesta aprobada para revisión. No se modifica código en esta fase.
> Fase actual: 1/10.

## 1. Objetivo de la fase

Convertir el análisis funcional en un diseño técnico concreto y ejecutable:
modelo de datos, contratos de servicio, claves de identificación, semántica de
markup y decisiones de negocio con valor por defecto recomendado.

## 2. Decisiones de negocio con recomendación

Cada decisión indica un **valor recomendado** (para avanzar sin bloquear) y
marca si requiere confirmación explícita (`[CONFIRMAR]`).

| # | Decisión | Recomendación | Confirmación |
|---|---|---|---|
| D1 | Semántica del porcentaje | Markup sobre costo (`precio = costo × (1 + pct/100)`), no margen | Aceptada en análisis |
| D2 | ¿Permitir vender bajo costo? | No. `pct >= 0`; `0` permitido; límite máx 1000% | [CONFIRMAR] límite |
| D3 | Cambio de costo posterior | No actualiza el precio automáticamente; se muestra advertencia | [CONFIRMAR] |
| D4 | ¿A qué precio aplica el markup? | Solo precio público (`price`) en v1. `wholesalePrice` queda manual | [CONFIRMAR] |
| D5 | Listas de precios con markup | No en v1. Siguen con precio absoluto | Aceptada |
| D6 | Clave de identificación (upsert) | `code` (SKU) como clave; `barcode` secundario; sin upsert automático en v1 de importación | [CONFIRMAR] |
| D7 | ¿Actualizar existentes en importación? | Sí, si `code` coincide y el usuario elige "actualizar" | [CONFIRMAR] |
| D8 | Almacén | Selección global en pantalla + columna `warehouse` opcional por fila | Aceptada |
| D9 | Costo inicial distinto de `costPrice` | Permitido vía columna `costo_inicial`; fallback a `costPrice` | Aceptada |
| D10 | Fecha efectiva inicial | Columna `fecha_inicial`; fallback a fecha de confirmación | [CONFIRMAR] |
| D11 | Producto con movimientos previos | Bloquear saldo inicial si ya tiene movimientos en ese almacén | [CONFIRMAR] |
| D12 | Lotes en v1 | Incluir: columna `lote` y `fecha_vencimiento` cuando `trackLots` | Aceptada |
| D13 | Números de serie en v1 | Excluir (sin flujo de importación consolidado) | Aceptada |
| D14 | Confirmación parcial | Permitir: filas con error se omiten; el resto se confirma | [CONFIRMAR] |
| D15 | Formato de archivo | CSV (estado actual). `.xlsx` como mejora posterior | Aceptada |
| D16 | Aprobación adicional para movimientos | `canManageInventory` (o `canInventoryAdjustments`) además de `canManageCatalog` | [CONFIRMAR] |

## 3. Modelo de datos

### 3.1. Producto (`items` / `sandbox_items`)

Campos nuevos (opcionales, sin migración obligatoria):

```text
pricingMode          : "amount" | "markup"    # default "amount"
markupPercentage     : Decimal | null         # solo cuando pricingMode == "markup"
priceSource          : "manual" | "markup" | "import" | "list"
priceCalculationBase : "costPrice" | null     # base usada en el último cálculo
priceUpdatedAt       : Timestamp | null
```

Reglas:

- `price` se mantiene como el precio final absoluto (fuente de verdad para
  ventas/POS). `save_item()` sigue normalizándolo a `float`.
- `pricingMode`/`markupPercentage` se persisten para auditar y recalcular.
- La ausencia de `pricingMode` se interpreta como `"amount"` → compatibilidad
  total con productos existentes.
- `save_item()` (db_service.py:3193) agrega la normalización de estos campos.

### 3.2. Lote de importación (colección nueva)

```text
companies/{companyId}/product_import_batches           (prod)
companies/{companyId}/sandbox_product_import_batches   (sandbox)
```

```text
id, companyId, environment, status, filename, fileHash,
createdBy, createdAt, confirmedBy, confirmedAt,
totalRows, validRows, errorRows, warningRows,
newProducts, updatedProducts, inventoryMovements,
totalUnits, totalInventoryValue
```

Estados: `DRAFT → VALIDATED → CONFIRMED` (y `FAILED` transitorio).

### 3.3. Resultado por fila (colección nueva)

```text
.../product_import_rows  (misma partición sandbox/prod)
```

```text
batchId, rowNumber, sourceKey, productId, warehouseId, action,
pricingMode, calculatedPrice, initialQuantity, initialUnitCost,
inventoryTransactionId, status, errors, warnings
```

### 3.4. Movimiento de inventario (esquema existente + metadatos)

Reutilizar `inventory_transactions`. Agregar al `tx_dict`:

```text
reason        : "SALDO_INICIAL"      # nueva constante
referenceType : "PRODUCT_IMPORT"
referenceId   : {batchId}:{rowKey}
idempotencyKey: {companyId}|PRODUCT_IMPORT|{batchId}:{rowKey}|ENTRADA
```

Se agrega `REASON_SALDO_INICIAL = "SALDO_INICIAL"` en
`InventoryTransactionService` (inventory_transaction_service.py:66-76).

## 4. Contratos de servicio

### 4.1. Servicio de cálculo de precio (nuevo, único)

```text
app/services/pricing_service.py
```

```python
class PricingService:
    PRICING_MODE_AMOUNT = "amount"
    PRICING_MODE_MARKUP = "markup"

    @staticmethod
    def compute_price(cost: Decimal, mode: str,
                      markup_percentage: Decimal | None = None,
                      explicit_price: Decimal | None = None) -> Decimal:
        # mode == amount  -> explicit_price (>= 0)
        # mode == markup  -> cost * (1 + markup_percentage/100)
        # redondeo monetario ROUND_HALF_UP a 2 decimales
```

- Usa `Decimal` y `quantize` (coherente con `quantize_value` de
  `inventory_valuation_service.py`).
- Único punto de cálculo para: formulario de producto, API, importador.

### 4.2. `save_item()` — normalización

Ampliar `save_item()` para persistir `pricingMode` (default `"amount"`),
`markupPercentage`, `priceSource`, `priceCalculationBase`, `priceUpdatedAt`.
No se altera la semántica de `price` ni `costPrice`.

### 4.3. Registro de existencia inicial (reutiliza motor existente)

```python
InventoryTransactionService.execute_transaction(
    owner_uid, company_id, tx_dict, sandbox=sandbox, dry_run=dry_run
)
```

`tx_dict`:

```python
{
  "itemId": product_id,
  "type": "ENTRADA",
  "quantity": initial_qty,
  "destinationWarehouseId": warehouse_id,
  "unitCost": initial_unit_cost,
  "reason": "SALDO_INICIAL",
  "referenceType": "PRODUCT_IMPORT",
  "referenceId": f"{batch_id}:{row_key}",
  "idempotencyKey": idem_key,
  "performedBy": user_email,
  "date": effective_date_iso,   # fecha efectiva (económica)
  "notes": "Inventario inicial por importación"
}
```

- `dry_run=True` para la previsualización (ya soportado, línea 104/127).
- Idempotencia ya cubierta por la clave (línea 79-94): repetir la misma fila
  devuelve la transacción existente sin duplicar stock.

### 4.4. Integración contable

`inventory_accounting_service.py` mapea `type+reason` a cuentas
(líneas 97-217). Se debe añadir el mapeo `ENTRADA + SALDO_INICIAL` (cuenta de
inventario contra apertura/patrimonio, según plan de cuentas). Sin este mapeo,
el movimiento físico existiría pero quedaría sin asiento.

## 5. Claves de identificación y upsert

- Clave primaria de producto para importación: `code` (SKU). Si `code` está
  vacío, se genera (comportamiento actual, línea 340 de items_import.py).
- Detección de duplicados **dentro** del archivo antes de persistir.
- El lote define `action` por fila: `new` | `update` | `skip`.

## 6. Compatibilidad e impacto

- Productos existentes sin `pricingMode` siguen funcionando (default `amount`).
- Plantillas antiguas sin columnas nuevas: `price` se interpreta como monto.
- `items.totalStock` nunca se escribe directamente; solo vía `execute_transaction`.
- Costo histórico en líneas (`originalCost`/`unitCost`) no se ve afectado.

## 7. Riesgos técnicos (vigentes tras diseño)

1. **Atomicidad producto+movimiento**: `save_item()` y `execute_transaction()`
   son escrituras Firestore separadas. Mitigación: estado por fila + reintento
   idempotente (Fase 8).
2. **Importador no transaccional**: escribe fila por fila. Mitigación: lote
   persistente con reanudación (Fases 5/6/8).
3. **Sin mapeo contable para `SALDO_INICIAL`**: requerido en Fase 7.
4. **POS vs facturación (listas)**: el markup v1 solo toca `price` de catálogo;
   no altera la resolución de listas.

## 8. Entregables de esta fase

- [x] Decisiones D1–D16 con valor por defecto recomendado.
- [x] Modelo de datos (producto, lote, fila, movimiento).
- [x] Contratos de servicio (`PricingService`, `save_item`, `execute_transaction`).
- [ ] Aprobación de las decisiones marcadas `[CONFIRMAR]`.

## 9. Criterios de salida

La Fase 1 se considera completa cuando las decisiones `[CONFIRMAR]` (D2, D3, D4,
D6, D7, D10, D11, D14, D16) estén aprobadas o se acepten los valores por defecto.
