"""
Consolidación de proveedores: contactos como fuente de verdad.

Por cada empresa/entorno:
1. Legacy `suppliers` sin contacto con ese doc id → crea contacto con el MISMO id
   (preserva referencias supplierId en gastos/OC/facturas) y types=['proveedor'].
2. Legacy con id ya presente en contacts (o fusionado por RNC) → backfill de
   campos de proveedor faltantes en el contacto.
3. Contacto con 'proveedor' → regenera el espejo legacy vía ContactService.save_contact.
4. Duplicados por RNC en legacy → reporta conflicto (no borra nada).

Idempotente y aditivo: solo crea/fusiona/backfillea, nunca borra.
`--dry-run` es el comportamiento por defecto.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

from app.services.db_service import db_firestore, firebase_initialized, _resolve_owner_uid
from app.services.contact_service import ContactService, CONTACT_DEFAULTS, _coll_name


def _serialize(val):
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%dT%H:%M:%S")
    return str(val)


def _supplier_contact_dict(s, contact=None):
    """Construye/actualiza un contacto con datos de proveedor legacy."""
    d = dict(contact) if contact else dict(CONTACT_DEFAULTS)
    d.setdefault("types", [])
    if "proveedor" not in d["types"]:
        d["types"] = list(d["types"]) + ["proveedor"]

    # Campos de contacto (solo rellenar vacíos si el contacto ya existía)
    mapping_fill = {
        "rnc": "".join(filter(str.isdigit, str(s.get("rnc", "")))),
        "razonSocial": s.get("name", ""),
        "email": s.get("email", ""),
        "telefono": s.get("phone", ""),
        "direccion": s.get("address", ""),
        "municipio": s.get("city", ""),
        "pais": s.get("country", "República Dominicana"),
        "notes": s.get("notes", ""),
        "createdAt": _serialize(s.get("createdAt", datetime.now(timezone.utc))),
    }
    for k, v in mapping_fill.items():
        if not d.get(k) and v:
            d[k] = v

    # Campos de proveedor (siempre desde legacy, es la fuente histórica)
    d.update({
        "tipoPersona": s.get("tipoPersona", d.get("tipoPersona", "fisica")),
        "code": s.get("code", d.get("code", "")),
        "estado": s.get("estado", d.get("estado", "Activo")),
        "contactPerson": s.get("contactPerson", d.get("contactPerson", "")),
        "supplierType": s.get("supplierType", d.get("supplierType", "formal")),
        "currency": s.get("currency", d.get("currency", "DOP")),
        "creditDays": s.get("creditDays", d.get("creditDays", 0)),
        "creditLimit": s.get("creditLimit", d.get("creditLimit", 0.0)),
        "paymentMethod": s.get("paymentMethod", d.get("paymentMethod", "Efectivo")),
        "ecfTypeEmits": s.get("ecfTypeEmits", d.get("ecfTypeEmits", "E31")),
        "itbisWithholding": s.get("itbisWithholding", d.get("itbisWithholding", False)),
        "isrWithholding": s.get("isrWithholding", d.get("isrWithholding", False)),
        "tipoGastoDGII": s.get("tipoGastoDGII", d.get("tipoGastoDGII", "02")),
        "attachments": s.get("attachments", d.get("attachments", [])),
        "firebaseAttachmentURLs": s.get("firebaseAttachmentURLs", d.get("firebaseAttachmentURLs", [])),
        "branchId": s.get("branchId", d.get("branchId", "default-sucursal-principal")),
        "projectId": s.get("projectId", d.get("projectId")),
    })
    return d


def consolidate_company(company_id, sandbox=True, dry_run=True):
    if not firebase_initialized or db_firestore is None:
        print("❌ Firebase no está inicializado.")
        return {"created": 0, "merged": 0, "mirrored": 0, "conflicts": 0}

    sup_coll = "sandbox_suppliers" if sandbox else "suppliers"
    con_coll = _coll_name(sandbox)
    sup_ref = db_firestore.collection("companies").document(company_id).collection(sup_coll)
    con_ref = db_firestore.collection("companies").document(company_id).collection(con_coll)

    supplier_docs = [d for d in sup_ref.get() if d.to_dict()]
    contact_docs = {d.id: d.to_dict() for d in con_ref.get() if d.to_dict()}

    # Índice de contactos por RNC (dentro de la misma colección)
    contacts_by_rnc = {}
    for cid, cdata in contact_docs.items():
        rc = "".join(filter(str.isdigit, str(cdata.get("rnc", ""))))
        if rc:
            contacts_by_rnc.setdefault(rc, []).append(cid)

    owner_uid = _resolve_owner_uid(company_id)
    env = "sandbox" if sandbox else "produccion"
    print(f"\n📋 Empresa {company_id} ({env}) — {len(supplier_docs)} proveedores legacy, {len(contact_docs)} contactos")

    created = merged = mirrored = 0
    conflicts = []

    # Conflicto: >1 proveedor legacy con el mismo RNC (elige el más antiguo como canónico)
    by_rnc = {}
    for d in supplier_docs:
        s = d.to_dict()
        rc = "".join(filter(str.isdigit, str(s.get("rnc", ""))))
        if rc:
            by_rnc.setdefault(rc, []).append((d.id, s))
    for rc, entries in by_rnc.items():
        if len(entries) > 1:
            entries.sort(key=lambda e: str(e[1].get("createdAt", "")))
            winner_id = entries[0][0]
            for sid, s in entries[1:]:
                conflicts.append({"rnc": rc, "canonical": winner_id, "duplicate": sid,
                                  "name": s.get("name", "")})
            print(f"   ⚠️ Conflicto RNC {rc}: {len(entries)} proveedores legacy; canónico={winner_id}")

    for d in supplier_docs:
        s = d.to_dict()
        sid = d.id
        rc = "".join(filter(str.isdigit, str(s.get("rnc", ""))))

        # ¿Existe contacto con este id?
        existing = contact_docs.get(sid)

        # Si no, fusionar por RNC
        if not existing and rc and rc in contacts_by_rnc:
            existing = contact_docs[contacts_by_rnc[rc][0]]
            sid = existing["id"]  # fusionar en el contacto existente

        if existing:
            before = len(existing.get("types", []))
            merged_dict = _supplier_contact_dict(s, existing)
            if merged_dict != existing:
                if not dry_run:
                    ContactService.save_contact(owner_uid=owner_uid, contact_id=merged_dict["id"],
                                                contact_dict=merged_dict, sandbox=sandbox, company_id=company_id)
                merged += 1
        else:
            # Crear contacto con el MISMO id del legacy (preserva referencias)
            new_dict = _supplier_contact_dict(s, None)
            new_dict["id"] = sid
            if not dry_run:
                ContactService.save_contact(owner_uid=owner_uid, contact_id=sid,
                                            contact_dict=new_dict, sandbox=sandbox, company_id=company_id)
            contact_docs[sid] = new_dict
            if rc:
                contacts_by_rnc.setdefault(rc, []).append(sid)
            created += 1

    # Contactos con tipo proveedor → regenerar espejo legacy (sin importar si venían de legacy)
    for cid, cdata in list(contact_docs.items()):
        if "proveedor" not in cdata.get("types", []):
            continue
        legacy = None
        try:
            doc = sup_ref.document(cid).get()
            legacy = doc.to_dict() if doc.exists else None
        except Exception:
            legacy = None
        if legacy is None:
            # regenerar espejo pasando por save_contact (el sync lo escribe)
            if not dry_run:
                ContactService.save_contact(owner_uid=owner_uid, contact_id=cid,
                                            contact_dict=cdata, sandbox=sandbox, company_id=company_id)
            mirrored += 1

    print(f"   {'🔍 (dry-run) ' if dry_run else ''}Creados: {created} | Fusionados/backfill: {merged} | Espejos regenerados: {mirrored} | Conflictos: {len(conflicts)}")
    return {"created": created, "merged": merged, "mirrored": mirrored, "conflicts": len(conflicts),
            "conflict_detail": conflicts}


def get_all_company_ids():
    if not firebase_initialized or db_firestore is None:
        return []
    try:
        return [d.id for d in db_firestore.collection("companies").get()]
    except Exception as e:
        print(f"⚠️ Error al obtener empresas: {e}")
        return []


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Consolidar proveedores legacy → contactos (fuente de verdad)")
    parser.add_argument("--company", help="company_id específico (opcional, sino todas)")
    parser.add_argument("--sandbox", action="store_true", default=True, help="Colecciones sandbox (por defecto)")
    parser.add_argument("--production", action="store_true", help="Colecciones de producción")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Solo simular (por defecto)")
    parser.add_argument("--apply", action="store_true", help="Escribir cambios (desactiva dry-run)")
    args = parser.parse_args()

    sandbox = not args.production
    dry_run = not args.apply

    print("🚀 Consolidación de proveedores → contactos (fuente de verdad)")
    print(f"   Entorno: {'sandbox' if sandbox else 'produccion'} | Dry run: {dry_run}")

    if not firebase_initialized:
        print("❌ Firebase no está inicializado.")
        sys.exit(1)

    if args.company:
        company_ids = [args.company]
    else:
        company_ids = get_all_company_ids()
        print(f"\n🏢 Empresas encontradas: {len(company_ids)}")

    totals = {"created": 0, "merged": 0, "mirrored": 0, "conflicts": 0}
    all_conflicts = []
    for cid in company_ids:
        r = consolidate_company(cid, sandbox=sandbox, dry_run=dry_run)
        for k in totals:
            totals[k] += r.get(k, 0)
        all_conflicts.extend(r.get("conflict_detail", []))

    print(f"\n{'='*50}")
    print(f"🏁 CONSOLIDACIÓN {'SIMULADA' if dry_run else 'APlicada'} COMPLETADA")
    print(f"   Contactos creados:   {totals['created']}")
    print(f"   Fusionados/backfill: {totals['merged']}")
    print(f"   Espejos regenerados: {totals['mirrored']}")
    print(f"   Conflictos RNC:      {totals['conflicts']}")
    if all_conflicts:
        print("\n   ⚠️ Conflictos (duplicados por RNC en legacy):")
        for c in all_conflicts:
            print(f"      RNC {c['rnc']}: canónico={c['canonical']} | duplicado={c['duplicate']} ({c['name']})")
    print(f"{'='*50}")
