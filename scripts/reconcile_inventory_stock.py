#!/usr/bin/env python3
"""
CLI Tool: Reconciliación de Stock de Inventario
===============================================
Audita y reconcilia la vista materializada `items.totalStock` con la
fuente de verdad física `inventory_stock` por almacén.

Uso:
  # Auditoría previa sin modificar (dry-run):
  python scripts/reconcile_inventory_stock.py --company COMP_ID --dry-run
  
  # Aplicar correcciones a una empresa en sandbox:
  python scripts/reconcile_inventory_stock.py --company COMP_ID --apply --sandbox
  
  # Aplicar correcciones a una empresa en producción:
  python scripts/reconcile_inventory_stock.py --company COMP_ID --apply --prod

  # Auditar todas las empresas:
  python scripts/reconcile_inventory_stock.py --all --dry-run
"""

import sys
import os
import argparse
import json

# Asegurar que el directorio raíz del proyecto esté en el PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.inventory_reconciliation_service import InventoryReconciliationService


def main():
    parser = argparse.ArgumentParser(description="Reconciliación de Stock de Inventario (VykOne ERP)")
    parser.add_argument("--company", help="ID de la compañía a auditar o reconciliar")
    parser.add_argument("--all", action="store_true", help="Procesar todas las compañías")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Solo reportar inconsistencias sin modificar datos")
    parser.add_argument("--apply", action="store_true", default=False, help="Aplicar correcciones a items.totalStock")
    parser.add_argument("--sandbox", action="store_true", default=True, help="Modo Sandbox (por defecto)")
    parser.add_argument("--prod", action="store_true", default=False, help="Modo Producción")

    args = parser.parse_args()

    if not args.company and not args.all:
        parser.print_help()
        print("\n❌ Error: Debe especificar --company <ID> o --all")
        sys.exit(1)

    if not args.dry_run and not args.apply:
        print("ℹ️ No se especificó --dry-run ni --apply. Se ejecutará en modo --dry-run por seguridad.")
        args.dry_run = True

    sandbox = not args.prod if args.prod else args.sandbox

    print("=" * 70)
    print(" 🛠️  HERRAMIENTA DE RECONCILIACIÓN DE INVENTARIO - VYKONE ERP")
    print("=" * 70)
    print(f" Entorno: {'SANDBOX' if sandbox else 'PRODUCCIÓN'}")
    print(f" Modo:    {'DRY-RUN (Solo Auditoría)' if args.dry_run else 'APLICAR CAMBIOS'}")
    print("=" * 70)

    if args.company:
        if args.dry_run:
            report = InventoryReconciliationService.audit_company_stock(
                company_id=args.company,
                sandbox=sandbox
            )
        else:
            report = InventoryReconciliationService.reconcile_company_stock(
                company_id=args.company,
                sandbox=sandbox,
                dry_run=False
            )
        
        print_report(report)

    elif args.all:
        reports = InventoryReconciliationService.reconcile_all_companies(
            sandbox=sandbox,
            dry_run=args.dry_run
        )
        for rep in reports:
            print_report(rep)


def print_report(report: dict):
    comp_id = report.get("companyId", "N/A")
    status = report.get("status", "N/A")
    total_audited = report.get("totalItemsAudited", 0)
    discrepancies_count = report.get("discrepanciesCount", len(report.get("discrepancies", [])))
    
    print(f"\n🏢 Empresa: {comp_id}")
    print(f"   Estado: {status}")
    print(f"   Artículos Auditados: {total_audited}")
    print(f"   Discrepancias Detectadas: {discrepancies_count}")

    discrepancies = report.get("discrepancies", [])
    if discrepancies:
        print("\n   Detalle de discrepancias:")
        for d in discrepancies:
            print(f"   • [{d.get('code') or d.get('itemId')}] {d.get('name')}")
            print(f"     totalStock materializado: {d.get('materializedTotalStock')}")
            print(f"     SUM(inventory_stock):     {d.get('physicalSumStock')}")
            print(f"     Diferencia:               {d.get('discrepancy')}")
            whs = d.get("warehouses", [])
            if whs:
                wh_str = ", ".join([f"{w.get('warehouseName')}: {w.get('quantity')}" for w in whs])
                print(f"     Por Almacén:              {wh_str}")
            else:
                print("     Por Almacén:              Sin existencias en ningún almacén (0.0)")

    if report.get("applied"):
        print(f"\n   ✅ {report.get('message')}")
        for r in report.get("reconciledItems", []):
            print(f"      - {r.get('name')}: {r.get('oldStock')} -> {r.get('newStock')} (Ajuste: {r.get('adjustment')})")
    elif report.get("message"):
        print(f"\n   ℹ️ {report.get('message')}")
    print("-" * 70)


if __name__ == "__main__":
    main()
