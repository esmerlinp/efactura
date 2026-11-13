#!/usr/bin/env python3
"""Backfill de valoración de inventario (costo promedio / último costo de compra).

Reconstruye el estado de valoración por producto+almacén y lo materializa
para reportería, de forma idempotente y segura:

  * `inventory_stock/{itemId}_{warehouseId}` → `totalValue`, `unitCost`, `lastPurchaseCost`
  * `items` → `avgCost`, `lastPurchaseCost`

Fuentes de verdad según el método de valoración del ítem:
  * FIFO (legacy): `inventory_cost_ledger` (Σ balanceQty × unitCost) por almacén.
  * Promedio móvil: estado ya persistido en `inventory_stock` por el motor
    transaccional (se respeta; solo se re-materializa si falta).

Uso:
    python scripts/backfill_inventory_valuation.py --company <company_id> [--dry-run]
    python scripts/backfill_inventory_valuation.py --all [--dry-run] [--prod]
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.db_service import db_firestore, firebase_initialized, _company_coll


def _read_coll(company_id, coll_name, sandbox):
    docs = []
    try:
        snap = _company_coll(company_id=company_id, coll_name=coll_name).get()
        for d in snap:
            data = d.to_dict() or {}
            data["__doc_id__"] = d.id
            docs.append(data)
    except Exception as e:
        print(f"    ⚠️ Error leyendo {coll_name}: {e}")
    return docs


def _cmp_tx_date(tx):
    return str(tx.get("date") or tx.get("createdAt") or "")


def _is_compra_entrada(tx):
    if str(tx.get("type", "")).upper() != "ENTRADA":
        return False
    reason = str(tx.get("reason", "")).upper()
    ref_type = str(tx.get("referenceType", "")).upper()
    return (
        reason in ("COMPRA", "RECEPCION", "ORDEN_COMPRA", "GOODS_RECEIPT")
        or ref_type in ("GOODS_RECEIPT", "PURCHASE", "PURCHASE_ORDER")
    )


def _last_purchase_cost(transactions, item_id):
    """Último costo de compra: unitCost efectivo de la última ENTRADA de compra confirmada."""
    candidates = [t for t in transactions if t.get("itemId") == item_id and _is_compra_entrada(t)]
    if not candidates:
        return 0.0
    candidates.sort(key=_cmp_tx_date)
    return round(float(candidates[-1].get("unitCost", 0.0) or 0.0), 4)


def _ledger_value(ledger_docs, item_id, warehouse_id):
    """Valor FIFO remanente por almacén: Σ(balanceQty × unitCost)."""
    total_value = 0.0
    total_qty = 0.0
    for ld in ledger_docs:
        if ld.get("itemId") != item_id:
            continue
        if warehouse_id and ld.get("warehouseId") != warehouse_id:
            continue
        bal = float(ld.get("balanceQty", 0.0) or 0.0)
        if bal <= 0:
            continue
        total_value += bal * float(ld.get("unitCost", 0.0) or 0.0)
        total_qty += bal
    return round(total_value, 2), round(total_qty, 4)


def backfill_company(company_id, sandbox=True, dry_run=False):
    items = _read_coll(company_id, "sandbox_items" if sandbox else "items", sandbox)
    stocks = _read_coll(company_id, "sandbox_inventory_stock" if sandbox else "inventory_stock", sandbox)
    txs = _read_coll(company_id, "sandbox_inventory_transactions" if sandbox else "inventory_transactions", sandbox)
    ledger = _read_coll(company_id, "sandbox_inventory_cost_ledger" if sandbox else "inventory_cost_ledger", sandbox)

    items_map = {it.get("id") or it.get("__doc_id__"): it for it in items}

    per_item = {}  # item_id -> {qty, total_value}
    stock_updates = 0
    item_updates = 0

    for st in stocks:
        item_id = st.get("itemId")
        wh_id = st.get("warehouseId")
        doc_id = st.get("__doc_id__") or f"{item_id}_{wh_id}"
        if not item_id:
            continue
        item = items_map.get(item_id, {})
        if item.get("type", "Bien") != "Bien" and item.get("type") not in (None, "", "Bien"):
            continue

        qty = round(float(st.get("quantity", 0.0) or 0.0), 4)
        existing_total = round(float(st.get("totalValue", 0.0) or 0.0), 2)
        existing_unit = round(float(st.get("unitCost", 0.0) or 0.0), 4)
        existing_last = round(float(st.get("lastPurchaseCost", 0.0) or 0.0), 4)

        method = str(item.get("valuationMethod", "") or "").lower()

        if method == "promedio" and existing_total > 0 and existing_unit > 0:
            # Estado de promedio móvil ya persistido por el motor: respetarlo.
            total_value = existing_total
            unit_cost = existing_unit
        else:
            # FIFO legacy (o promedio sin estado): reconstruir desde el ledger.
            total_value, ledger_qty = _ledger_value(ledger, item_id, wh_id)
            unit_cost = round(total_value / qty, 4) if qty > 0 else 0.0

        last_purchase = _last_purchase_cost(txs, item_id)
        if last_purchase <= 0:
            last_purchase = existing_last

        # ¿Cambios a escribir en inventory_stock?
        needs_stock = (
            abs(total_value - existing_total) > 0.005
            or abs(unit_cost - existing_unit) > 0.0001
            or abs(last_purchase - existing_last) > 0.0001
        )
        if needs_stock:
            stock_updates += 1
            if not dry_run:
                payload = {
                    "id": doc_id,
                    "itemId": item_id,
                    "warehouseId": wh_id,
                    "quantity": qty,
                    "totalValue": total_value,
                    "unitCost": unit_cost,
                    "lastPurchaseCost": last_purchase,
                }
                try:
                    _company_coll(
                        company_id=company_id,
                        coll_name="sandbox_inventory_stock" if sandbox else "inventory_stock",
                    ).document(doc_id).set(payload, merge=True)
                except Exception as e:
                    print(f"    ❌ Error escribiendo stock {doc_id}: {e}")
            print(f"    {'[dry-run] ' if dry_run else ''}📦 {item_id}/{wh_id}: "
                  f"qty={qty} totalValue={total_value} unitCost={unit_cost} lastPurchase={last_purchase}")

        per_item.setdefault(item_id, {"qty": 0.0, "total_value": 0.0, "last": last_purchase})
        per_item[item_id]["qty"] = round(per_item[item_id]["qty"] + qty, 4)
        per_item[item_id]["total_value"] = round(per_item[item_id]["total_value"] + total_value, 2)
        if last_purchase > 0:
            per_item[item_id]["last"] = last_purchase

    # Materializar avgCost / lastPurchaseCost en items
    for item_id, agg in per_item.items():
        item = items_map.get(item_id)
        if not item:
            continue
        avg_cost = round(agg["total_value"] / agg["qty"], 4) if agg["qty"] > 0 else 0.0
        last_purchase = agg["last"]
        cur_avg = round(float(item.get("avgCost", 0.0) or 0.0), 4)
        cur_last = round(float(item.get("lastPurchaseCost", 0.0) or 0.0), 4)
        if abs(avg_cost - cur_avg) <= 0.0001 and abs(last_purchase - cur_last) <= 0.0001:
            continue
        item_updates += 1
        if not dry_run:
            try:
                item_doc_id = item.get("__doc_id__") or item_id
                _company_coll(
                    company_id=company_id,
                    coll_name="sandbox_items" if sandbox else "items",
                ).document(item_doc_id).update({
                    "avgCost": avg_cost,
                    "lastPurchaseCost": last_purchase,
                })
            except Exception as e:
                print(f"    ❌ Error actualizando item {item_id}: {e}")
        print(f"    {'[dry-run] ' if dry_run else ''}🏷️  {item_id}: avgCost={avg_cost} lastPurchaseCost={last_purchase}")

    return {"stock_updates": stock_updates, "item_updates": item_updates}


def main():
    parser = argparse.ArgumentParser(description="Backfill de valoración de inventario")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--company", help="ID de la empresa (companies/{id})")
    group.add_argument("--all", action="store_true", help="Todas las empresas")
    parser.add_argument("--dry-run", action="store_true", help="Solo previsualizar sin escribir")
    parser.add_argument("--sandbox", action="store_true", default=True, help="Entorno sandbox (por defecto)")
    parser.add_argument("--prod", action="store_true", help="Entorno producción")
    args = parser.parse_args()

    if not firebase_initialized or db_firestore is None:
        print("❌ Firebase no inicializado")
        sys.exit(1)

    sandbox = not args.prod

    company_ids = []
    if args.all:
        try:
            company_ids = [d.id for d in db_firestore.collection("companies").get()]
        except Exception as e:
            print(f"❌ Error listando empresas: {e}")
            sys.exit(1)
    else:
        company_ids = [args.company]

    print("=" * 70)
    print(" 🛠️  BACKFILL DE VALORACIÓN DE INVENTARIO - VYKONE ERP")
    print(f" Entorno: {'SANDBOX' if sandbox else 'PRODUCCIÓN'}")
    print(f" Modo:    {'DRY-RUN' if args.dry_run else 'APLICAR'}")
    print("=" * 70)

    total_stock = 0
    total_items = 0
    for company_id in company_ids:
        print(f"\n🔍 Empresa {company_id}...")
        s = backfill_company(company_id, sandbox=sandbox, dry_run=args.dry_run)
        total_stock += s["stock_updates"]
        total_items += s["item_updates"]

    print("\n📊 Resumen:")
    print(f"  stock actualizados: {total_stock}")
    print(f"  items materializados: {total_items}")
    if args.dry_run:
        print("  (dry-run: no se escribió nada)")


if __name__ == "__main__":
    main()
