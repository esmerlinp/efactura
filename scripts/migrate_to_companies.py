"""
Script de Migración One-Time: Multi-Company para VykOne ERP.

Este script migra los datos existentes de la estructura legacy
  users/{ownerUID}/...
a la nueva estructura
  companies/{companyId}/...

Ejecutar SOLO UNA VEZ después de desplegar el código multi-company.

Uso:
    cd /path/to/e-FacturaWeb
    python scripts/migrate_to_companies.py
"""

import os
import sys
import uuid
from datetime import datetime, timezone

# Agregar directorio raíz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.services.db_service import (
        db_firestore, firebase_initialized, DatabaseService,
        _cached_company_profile
    )
    from app.services.hr_data_service import _hr_company_path, _catalog_coll_path
except ImportError as e:
    print(f"❌ Error al importar módulos: {e}")
    print("Asegúrate de ejecutar desde la raíz del proyecto con 'python scripts/migrate_to_companies.py'")
    sys.exit(1)


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def log(msg: str):
    print(f"[{datetime.now().isoformat()}] {msg}")


def get_all_users():
    """Obtiene todos los UIDs de usuarios desde la colección users."""
    users = []
    try:
        docs = db_firestore.collection("users").limit(500).get()
        for doc in docs:
            users.append(doc.id)
    except Exception as e:
        log(f"⚠️ Error al listar users: {e}")
    return users


# ────────────────────────────────────────────────────────────
# Migración
# ────────────────────────────────────────────────────────────

def migrate():
    log("=== Iniciando migración multi-company ===")

    if not firebase_initialized:
        log("❌ Firebase no está inicializado. Verifica firebase-adminsdk.json")
        return

    all_uids = get_all_users()
    log(f"📊 Usuarios encontrados: {len(all_uids)}")

    stats = {
        "companies_created": 0,
        "memberships_created": 0,
        "branches_copied": 0,
        "team_copied": 0,
        "hr_collections_copied": 0,
        "business_docs_copied": 0,
        "extra_docs_copied": 0,
        "errors": 0,
    }

    HR_COLLECTIONS = [
        "employees", "attendance", "vacations", "leaves",
        "payroll_groups", "employment_contracts", "payroll",
        "salary_history", "employee_documents", "employee_dependents",
        "employment_history", "checklist_onboarding", "checklist_offboarding",
        "dgt_suspensions", "dgt_reinstatements", "liquidaciones",
        "mass_actions", "payroll_policies", "payroll_rules",
        "payroll_rule_log", "legal_parameters", "payroll_transactions",
        "variable_movements", "garnishments", "overtime_types",
        "overtime_records", "overtime_payroll_links", "work_certificates",
        "payroll_concepts",
    ]

    # Colecciones de negocio adicionales (con sandbox)
    BUSINESS_COLLECTIONS = [
        "clients", "expenses", "items", "sequences", "invoices",
        "suppliers", "goods_receipts", "purchase_orders",
        "supplier_invoices", "purchase_credit_notes",
        "ncf_traditional", "inventory_cost_ledger", "physical_counts",
        "inventory_lots", "crm_opportunities", "crm_activities",
        "projects", "price_lists", "categories", "cancellations",
        "bank_accounts", "bank_reconciliations", "bank_transfers",
        "accounting_entries", "cash_registers", "cash_shifts",
        "cash_transactions", "client_advances", "contracts",
        "cost_centers", "fixed_assets", "idempotency_keys",
        "inventory_stock", "inventory_transactions", "notes",
        "payment_promises", "rui_summaries", "sequence_logs",
        "warehouses", "warehouse_transfers",
    ]

    # Colecciones sin sandbox (solo producción)
    STANDARD_COLLECTIONS = [
        "audit_logs", "webhooks", "webhooks_dlq", "webhook_deliveries",
        "approval_rules", "approval_requests", "sod_actions",
    ]

    # Colecciones HR adicionales (sin prefijo hr_)
    HR_EXTRA_COLLECTIONS = [
        "hr_config", "hr_tax_rates_history", "hr_payroll_concepts",
        "hr_payroll_jobs", "hr_audit_log", "hr_ytd_accumulations",
        "hr_recurring_movements", "hr_recurring_exceptions",
        "hr_recurring_applications", "hr_legal_parameters",
    ]

    # Config documents to migrate (users/{owner_uid}/config/{doc_name})
    CONFIG_DOCUMENTS = [
        "commission_settings", "tax_rules", "sales_goals",
    ]

    # Documentos anidados bajo config
    NESTED_CONFIG = [
        ("chart_of_accounts", "accounts"),
        ("entry_types", "types"),
    ]

    for uid in all_uids:
        try:
            log(f"\n--- Procesando usuario: {uid} ---")

            # Obtener perfil
            profile = DatabaseService.get_user_profile(uid)
            if not profile:
                log(f"  ⏭️  Sin perfil, saltando")
                continue

            can_manage = profile.get("canManageOwnCompany", False)
            owner_uid = profile.get("ownerUID", uid)

            # Solo procesar si el usuario es owner de su propia compañía
            if not can_manage:
                log(f"  ⏭️  No es owner (canManageOwnCompany=false), saltando")
                continue

            # Obtener perfil de compañía legacy
            company_profile = DatabaseService.get_company_profile(owner_uid)
            if not company_profile:
                log(f"  ⏭️  Sin perfil de compañía, saltando")
                continue

            # Verificar si ya tiene company_id
            existing_companies = DatabaseService.get_companies_by_owner(owner_uid)
            if existing_companies:
                company_id = existing_companies[0]["id"]
                log(f"  ℹ️  Compañía ya existe: {company_id} — {existing_companies[0].get('name', '')}")
            else:
                # Crear compañía
                company_id = DatabaseService.create_company(owner_uid, company_profile)
                if not company_id:
                    log(f"  ❌ Error al crear compañía para {owner_uid}")
                    stats["errors"] += 1
                    continue
                stats["companies_created"] += 1
                log(f"  ✅ Compañía creada: {company_id}")

            # Crear membresía del owner
            existing_membership = DatabaseService.get_membership(uid, company_id)
            if not existing_membership:
                mem_id = DatabaseService.create_membership(
                    uid=uid,
                    company_id=company_id,
                    role=profile.get("role", "owner"),
                    permissions=profile.get("permissions", {}),
                    invited_by=""
                )
                if mem_id:
                    stats["memberships_created"] += 1
                    log(f"  ✅ Membresía creada para owner {uid}")
            else:
                log(f"  ℹ️  Membresía del owner ya existe")

            # Actualizar default_company_id en perfil del usuario
            if not profile.get("default_company_id"):
                try:
                    from app.services.db_service import db_firestore as db
                    db.collection("users").document(uid).collection("config").document("user_profile").update({
                        "default_company_id": company_id
                    })
                    log(f"  ✅ default_company_id actualizado")
                except Exception as e:
                    log(f"  ⚠️ Error al actualizar default_company_id: {e}")

            # ── Copiar branches ──
            for sandbox in [False, True]:
                coll_name = "sandbox_branches" if sandbox else "branches"
                try:
                    legacy_docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                    new_coll = db_firestore.collection("companies").document(company_id).collection(coll_name)
                    for doc in legacy_docs:
                        new_coll.document(doc.id).set(doc.to_dict())
                        stats["branches_copied"] += 1
                    if legacy_docs:
                        log(f"  ✅ Branches ({coll_name}): {len(list(legacy_docs))} copiadas")
                except Exception as e:
                    log(f"  ⚠️ Error copiando branches ({coll_name}): {e}")

            # ── Copiar Team ──
            for sandbox in [False, True]:
                try:
                    legacy_team = db_firestore.collection("users").document(owner_uid).collection("team").get()
                    new_team = db_firestore.collection("companies").document(company_id).collection("team")
                    for doc in legacy_team:
                        new_team.document(doc.id).set(doc.to_dict())
                        stats["team_copied"] += 1
                    if legacy_team:
                        log(f"  ✅ Team: {len(list(legacy_team))} miembros copiados")

                    # Crear membresías para los miembros del team
                    for doc in legacy_team:
                        team_data = doc.to_dict()
                        mem_uid = doc.id
                        mem_exists = DatabaseService.get_membership(mem_uid, company_id)
                        if not mem_exists:
                            DatabaseService.create_membership(
                                uid=mem_uid,
                                company_id=company_id,
                                role=team_data.get("role", "employee"),
                                permissions=team_data.get("permissions", {}),
                                invited_by=owner_uid
                            )
                            stats["memberships_created"] += 1
                except Exception as e:
                    log(f"  ⚠️ Error copiando team: {e}")

            # ── Copiar HR collections ──
            for sandbox in [False, True]:
                for coll_name in HR_COLLECTIONS:
                    try:
                        prefix = "sandbox_hr_" if sandbox else "hr_"
                        legacy_path = f"users/{owner_uid}/{prefix}{coll_name}"
                        new_path = f"companies/{company_id}/{prefix}{coll_name}"
                        legacy_docs = db_firestore.collection(legacy_path).get()
                        if not legacy_docs:
                            continue
                        new_ref = db_firestore.collection(new_path)
                        count = 0
                        for doc in legacy_docs:
                            new_ref.document(doc.id).set(doc.to_dict())
                            count += 1
                        stats["hr_collections_copied"] += count
                        log(f"  ✅ hr_{coll_name}: {count} copiados")
                    except Exception as e:
                        log(f"  ⚠️ Error copiando hr_{coll_name}: {e}")

            # ── Copiar catálogos (departments, positions) ──
            for sandbox in [False, True]:
                for cat_name in ["departments", "positions"]:
                    try:
                        prefix = "sandbox_" if sandbox else ""
                        legacy_path = f"users/{owner_uid}/{prefix}hr_catalog_{cat_name}"
                        new_path = f"companies/{company_id}/{prefix}hr_catalog_{cat_name}"
                        legacy_docs = db_firestore.collection(legacy_path).get()
                        if not legacy_docs:
                            continue
                        new_ref = db_firestore.collection(new_path)
                        count = 0
                        for doc in legacy_docs:
                            new_ref.document(doc.id).set(doc.to_dict())
                            count += 1
                        log(f"  ✅ catalog_{cat_name}: {count} copiados")
                    except Exception as e:
                        log(f"  ⚠️ Error copiando catalog_{cat_name}: {e}")

            # ── Copiar Business Collections (con sandbox) ──
            for sandbox in [False, True]:
                for coll in BUSINESS_COLLECTIONS:
                    try:
                        coll_name = f"sandbox_{coll}" if sandbox else coll
                        legacy_docs = db_firestore.collection("users").document(owner_uid).collection(coll_name).get()
                        if not legacy_docs:
                            continue
                        new_ref = db_firestore.collection("companies").document(company_id).collection(coll_name)
                        count = 0
                        for doc in legacy_docs:
                            new_ref.document(doc.id).set(doc.to_dict())
                            count += 1
                        stats["business_docs_copied"] += count
                        log(f"  ✅ {coll_name}: {count} copiados")
                    except Exception as e:
                        log(f"  ⚠️ Error copiando {coll_name}: {e}")

            # ── Copiar Standard Collections (sin sandbox) ──
            for coll in STANDARD_COLLECTIONS:
                try:
                    legacy_docs = db_firestore.collection("users").document(owner_uid).collection(coll).get()
                    if not legacy_docs:
                        continue
                    new_ref = db_firestore.collection("companies").document(company_id).collection(coll)
                    count = 0
                    for doc in legacy_docs:
                        new_ref.document(doc.id).set(doc.to_dict())
                        count += 1
                    log(f"  ✅ {coll}: {count} copiados")
                except Exception as e:
                    log(f"  ⚠️ Error copiando {coll}: {e}")

            # ── Copiar HR Extra Collections (hr_config, etc.) ──
            for sandbox in [False, True]:
                for coll in HR_EXTRA_COLLECTIONS:
                    try:
                        prefix = "sandbox_" if sandbox else ""
                        legacy_path = f"users/{owner_uid}/{prefix}{coll}"
                        new_path = f"companies/{company_id}/{prefix}{coll}"
                        legacy_docs = db_firestore.collection(legacy_path).get()
                        if not legacy_docs:
                            continue
                        new_ref = db_firestore.collection(new_path)
                        count = 0
                        for doc in legacy_docs:
                            new_ref.document(doc.id).set(doc.to_dict())
                            count += 1
                        log(f"  ✅ {prefix}{coll}: {count} copiados")
                    except Exception as e:
                        log(f"  ⚠️ Error copiando {prefix}{coll}: {e}")

            # ── Copiar Config Documents ──
            for doc_name in CONFIG_DOCUMENTS:
                try:
                    doc = db_firestore.collection("users").document(owner_uid).collection("config").document(doc_name).get()
                    if not doc.exists:
                        continue
                    new_ref = db_firestore.collection("companies").document(company_id).collection("config").document(doc_name)
                    new_ref.set(doc.to_dict())
                    log(f"  ✅ config/{doc_name}: copiado")
                except Exception as e:
                    log(f"  ⚠️ Error copiando config/{doc_name}: {e}")

            # ── Copiar Config Documents anidados (chart_of_accounts/accounts, etc.) ──
            for parent_doc, sub_coll in NESTED_CONFIG:
                try:
                    legacy_docs = db_firestore.collection("users").document(owner_uid).collection("config").document(parent_doc).collection(sub_coll).get()
                    if not legacy_docs:
                        continue
                    new_ref = db_firestore.collection("companies").document(company_id).collection("config").document(parent_doc).collection(sub_coll)
                    count = 0
                    for doc in legacy_docs:
                        new_ref.document(doc.id).set(doc.to_dict())
                        count += 1
                    log(f"  ✅ config/{parent_doc}/{sub_coll}: {count} copiados")
                except Exception as e:
                    log(f"  ⚠️ Error copiando config/{parent_doc}/{sub_coll}: {e}")

            # ── Copiar entry_counter y otros documentos sueltos en config ──
            for doc_name in ["entry_counter", "supplier_invoice_counter", "purchase_credit_note_counter"]:
                try:
                    doc = db_firestore.collection("users").document(owner_uid).collection("config").document(doc_name).get()
                    if not doc.exists:
                        continue
                    new_ref = db_firestore.collection("companies").document(company_id).collection("config").document(doc_name)
                    new_ref.set(doc.to_dict())
                    log(f"  ✅ config/{doc_name}: copiado")
                except Exception as e:
                    log(f"  ⚠️ Error copiando config/{doc_name}: {e}")

            # ── Copiar budgets ──
            try:
                legacy_docs = db_firestore.collection("users").document(owner_uid).collection("budgets").get()
                if legacy_docs:
                    new_ref = db_firestore.collection("companies").document(company_id).collection("budgets")
                    count = 0
                    for doc in legacy_docs:
                        new_ref.document(doc.id).set(doc.to_dict())
                        count += 1
                    log(f"  ✅ budgets: {count} copiados")
            except Exception as e:
                log(f"  ⚠️ Error copiando budgets: {e}")

            # ── Copiar fiscal_periods ──
            try:
                legacy_docs = db_firestore.collection("users").document(owner_uid).collection("fiscal_periods").get()
                if legacy_docs:
                    new_ref = db_firestore.collection("companies").document(company_id).collection("fiscal_periods")
                    count = 0
                    for doc in legacy_docs:
                        new_ref.document(doc.id).set(doc.to_dict())
                        count += 1
                    log(f"  ✅ fiscal_periods: {count} copiados")
            except Exception as e:
                log(f"  ⚠️ Error copiando fiscal_periods: {e}")

            # ── Copiar monthly_summaries ──
            try:
                legacy_docs = db_firestore.collection("users").document(owner_uid).collection("monthly_summaries").get()
                if legacy_docs:
                    new_ref = db_firestore.collection("companies").document(company_id).collection("monthly_summaries")
                    count = 0
                    for doc in legacy_docs:
                        new_ref.document(doc.id).set(doc.to_dict())
                        count += 1
                    log(f"  ✅ monthly_summaries: {count} copiados")
            except Exception as e:
                log(f"  ⚠️ Error copiando monthly_summaries: {e}")

            # ── Copiar closing_checklists ──
            try:
                legacy_docs = db_firestore.collection("users").document(owner_uid).collection("closing_checklists").get()
                if legacy_docs:
                    new_ref = db_firestore.collection("companies").document(company_id).collection("closing_checklists")
                    count = 0
                    for doc in legacy_docs:
                        new_ref.document(doc.id).set(doc.to_dict())
                        count += 1
                    log(f"  ✅ closing_checklists: {count} copiados")
            except Exception as e:
                log(f"  ⚠️ Error copiando closing_checklists: {e}")

            # ── Copiar journal_entry_audit ──
            try:
                legacy_docs = db_firestore.collection("users").document(owner_uid).collection("journal_entry_audit").get()
                if legacy_docs:
                    new_ref = db_firestore.collection("companies").document(company_id).collection("journal_entry_audit")
                    count = 0
                    for doc in legacy_docs:
                        new_ref.document(doc.id).set(doc.to_dict())
                        count += 1
                    log(f"  ✅ journal_entry_audit: {count} copiados")
            except Exception as e:
                log(f"  ⚠️ Error copiando journal_entry_audit: {e}")

        except Exception as e:
            log(f"❌ Error procesando {uid}: {e}")
            import traceback
            traceback.print_exc()
            stats["errors"] += 1

    # ── Resumen ──
    log("\n" + "=" * 60)
    log("=== RESUMEN DE MIGRACIÓN ===")
    log(f"  Compañías creadas:       {stats['companies_created']}")
    log(f"  Membresías creadas:      {stats['memberships_created']}")
    log(f"  Branches copiados:       {stats['branches_copied']}")
    log(f"  Team copiados:           {stats['team_copied']}")
    log(f"  HR documentos copiados:  {stats['hr_collections_copied']}")
    log(f"  Errores:                 {stats['errors']}")
    log("=" * 60)

    if stats["errors"]:
        log("⚠️  Hubieron errores. Revisa los logs arriba.")
    else:
        log("✅ Migración completada exitosamente.")


if __name__ == "__main__":
    migrate()
