"""
Actualiza la fecha de vencimiento que muestra el PDF de comprobantes ya generados
en Firestore (sandbox) a la fecha exigida por la DGII: 31/12/2028.

Facturas (E31/E32/E33/E34/E45...): viven en sandbox_invoices y el PDF usa
  invoice.fechaVencimientoSecuencia or invoice.dueDate (templates/invoices/pdf.html).

Gastos e-CF (E41/E43/E47): viven en sandbox_expenses y el PDF usa expense.dueDate
  (templates/expenses/pdf.html). Aquí se actualizan dueDate y fechaVencimientoSecuencia
  solo para gastos con e-NCF asignado (encf), no los gastos internos.

Uso:
  python scripts/update_invoice_due_date.py --dry-run
  python scripts/update_invoice_due_date.py
  python scripts/update_invoice_due_date.py --fecha 2028-12-31
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services.db_service import db_firestore, firebase_initialized


def _iter_docs(collection_name):
    """Yield (path, doc_ref, data) para todos los docs de la subcolección dada."""
    for parent in ("companies", "users"):
        try:
            parents = db_firestore.collection(parent).get()
        except Exception as e:
            print(f"⚠️ No se pudo leer colección {parent}: {e}")
            continue
        for p in parents:
            ref = db_firestore.collection(parent).document(p.id).collection(collection_name)
            try:
                docs = ref.get()
            except Exception as e:
                print(f"⚠️ Error en {parent}/{p.id}/{collection_name}: {e}")
                continue
            for doc in docs:
                yield f"{parent}/{p.id}/{collection_name}/{doc.id}", ref.document(doc.id), doc.to_dict()


def main():
    parser = argparse.ArgumentParser(
        description="Actualizar fecha de vencimiento (PDF) de comprobantes sandbox a la fecha exigida por la DGII."
    )
    parser.add_argument("--fecha", default="2028-12-31", help="Fecha a aplicar (ISO).")
    parser.add_argument("--dry-run", action="store_true", help="Solo reportar, sin escribir.")
    args = parser.parse_args()

    create_app()

    if not firebase_initialized or db_firestore is None:
        print("❌ Firebase no está inicializado. Ejecuta desde el entorno del servidor.")
        sys.exit(1)

    fecha = args.fecha
    total = 0
    updated = 0

    # 1) Facturas: el PDF usa fechaVencimientoSecuencia (fallback dueDate).
    for path, doc_ref, data in _iter_docs("sandbox_invoices"):
        if data.get("isDeleted") or data.get("isQuotation"):
            continue
        if data.get("fechaVencimientoSecuencia") == fecha:
            continue
        print(f"{path}: {data.get('fechaVencimientoSecuencia') or '(vacío)'} -> {fecha}")
        total += 1
        if not args.dry_run:
            try:
                doc_ref.update({"fechaVencimientoSecuencia": fecha})
                updated += 1
            except Exception as e:
                print(f"  ❌ No se actualizó: {e}")

    # 2) Gastos e-CF (E41/E43/E47): el PDF usa dueDate.
    for path, doc_ref, data in _iter_docs("sandbox_expenses"):
        if data.get("isDeleted") or not data.get("encf"):
            continue
        if data.get("dueDate", "")[:10] == fecha and data.get("fechaVencimientoSecuencia") == fecha:
            continue
        print(f"{path}: dueDate={str(data.get('dueDate', ''))[:10] or '(vacío)'} -> {fecha}")
        total += 1
        if not args.dry_run:
            try:
                doc_ref.update({
                    "dueDate": fecha,
                    "fechaVencimientoSecuencia": fecha,
                })
                updated += 1
            except Exception as e:
                print(f"  ❌ No se actualizó: {e}")

    if args.dry_run:
        print(f"\n✓ {total} comprobantes por actualizar a {fecha}")
    else:
        print(f"\n✓ {updated}/{total} comprobantes actualizados a {fecha}")


if __name__ == "__main__":
    main()
