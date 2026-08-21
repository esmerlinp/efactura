"""
Actualiza la fecha de vencimiento de las secuencias fiscales (e-NCF) en Firestore
a la exigida por la DGII para la certificación: 31/12/2028 (Informe Técnico §7).

La DGII exige que los comprobantes muestren como 'Fecha Vencimiento' la fecha de
vencimiento de la secuencia autorizada (31/12/2028), no la fecha comercial.

Uso:
  python scripts/update_sequence_expiration.py --dry-run
  python scripts/update_sequence_expiration.py
  python scripts/update_sequence_expiration.py --fecha 2028-12-31
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services.db_service import db_firestore, firebase_initialized


def main():
    parser = argparse.ArgumentParser(
        description="Actualizar fechaExpiracion de secuencias e-NCF a la fecha exigida por la DGII."
    )
    parser.add_argument("--fecha", default="2028-12-31", help="Fecha de vencimiento a aplicar (ISO).")
    parser.add_argument("--dry-run", action="store_true", help="Solo reportar, sin escribir.")
    args = parser.parse_args()

    create_app()

    if not firebase_initialized or db_firestore is None:
        print("❌ Firebase no está inicializado. Ejecuta desde el entorno del servidor.")
        sys.exit(1)

    fecha = args.fecha
    total = 0

    for coll in ("sandbox_sequences", "sequences"):
        for parent in ("companies", "users"):
            try:
                parents = db_firestore.collection(parent).get()
            except Exception as e:
                print(f"⚠️ No se pudo leer colección {parent}: {e}")
                continue
            for p in parents:
                ref = db_firestore.collection(parent).document(p.id).collection(coll)
                try:
                    docs = ref.get()
                except Exception as e:
                    print(f"⚠️ Error en {parent}/{p.id}/{coll}: {e}")
                    continue
                for doc in docs:
                    data = doc.to_dict()
                    if data.get("fechaExpiracion") == fecha:
                        continue
                    print(f"{parent}/{p.id}/{coll}/{doc.id}: {data.get('fechaExpiracion')} -> {fecha}")
                    if not args.dry_run:
                        try:
                            ref.document(doc.id).update({"fechaExpiracion": fecha})
                        except Exception as e:
                            print(f"  ❌ No se actualizó: {e}")
                            continue
                    total += 1

    print(f"\n✓ {total} secuencias {'verificadas' if args.dry_run else 'actualizadas'} a {fecha}")


if __name__ == "__main__":
    main()
